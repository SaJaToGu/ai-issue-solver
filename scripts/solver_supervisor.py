#!/usr/bin/env python3
"""Solver process supervisor for monitoring and targeted cancellation.

Provides status monitoring for active solver runs and targeted stop commands
with graceful termination, worktree preservation, and cancellation notes.

Features:
- Read-only status from existing run reports and health files
- Targeted stop commands (--run-id, --issue, --repo, --pid)
- Dry-run mode showing exact process tree before sending signals
- Graceful termination (SIGTERM) with configurable escalation (SIGKILL)
- Worktree preservation before terminating unhealthy jobs
- Structured cancellation notes in run reports
- Unrelated-process safety checks
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable

sys.path.insert(0, str(Path(__file__).parent))
from solver_reporting import RUN_REPORTS_ROOT, preserve_worker_worktree  # noqa: E402
from status_dashboard import parse_created_at, parse_datetime_value, parse_summary  # noqa: E402
from utils import print_banner, print_ok, print_step, print_warn  # noqa: E402


RUNNING_STATUSES = {"started", "running", "queued"}
TERMINAL_STATUSES = {
    "archived",
    "cleanup_noop",
    "cleanup_successful",
    "clone_failed",
    "failed",
    "no_changes",
    "nonzero_without_changes",
    "pr_created",
    "pr_created_from_existing_branch",
    "pr_created_with_warning",
    "pr_failed",
    "push_failed",
    "rate_limit_deferred",
    "skip_existing_pr",
    "skip_merged_pr",
    "validation_failed",
    "worker_validation_failed",
}
DEFAULT_STALE_SECONDS = 15 * 60
DEFAULT_GRACEFUL_TIMEOUT_SECONDS = 10
DEFAULT_KILL_TIMEOUT_SECONDS = 5
SAFE_SIGNALS = {"SIGTERM", "SIGKILL"}
GRACEFUL_SIGNAL = signal.SIGTERM
KILL_SIGNAL = signal.SIGKILL
PROTECTED_PID_1 = 1
PROTECTED_PIDS = {PROTECTED_PID_1, os.getpid()}


@dataclass(frozen=True)
class SupervisorRun:
    run_id: str
    run_dir: Path
    repo: str
    issue: str
    branch: str
    model: str
    status: str
    phase: str
    runner_pid: str
    parent_pid: str
    worker_pid: str
    last_activity_at: datetime | None
    last_report_update_at: datetime | None
    health_status: str
    health_reason: str
    output_tail: str
    cancelled_at: datetime | None = None
    cancellation_reason: str | None = None
    cancellation_signal: str | None = None

    @property
    def is_active(self) -> bool:
        return self.status in RUNNING_STATUSES or self.health_status in {"healthy", "stale"}

    @property
    def is_cancelled(self) -> bool:
        return self.cancelled_at is not None


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _summary_fields(run_dir: Path) -> dict[str, str]:
    summary_path = run_dir / "summary.txt"
    if not summary_path.exists():
        return {}
    try:
        return parse_summary(summary_path)
    except OSError:
        return {}


def _string_value(data: dict, key: str) -> str:
    value = data.get(key, "")
    return "" if value is None else str(value)


def _latest_datetime(*values: datetime | None) -> datetime | None:
    parsed = [value for value in values if value is not None]
    return max(parsed) if parsed else None


def classify_run_health(
    status: str,
    phase: str,
    last_seen: datetime | None,
    now: datetime,
    stale_seconds: int,
) -> tuple[str, str]:
    if status in TERMINAL_STATUSES:
        return "finished", "terminal status"
    if last_seen is None:
        return "unknown", "no health timestamp"

    age_seconds = int((now - last_seen).total_seconds())
    if age_seconds > stale_seconds:
        return "stale", f"no update for {age_seconds}s"
    if phase:
        return "healthy", f"phase {phase}"
    return "healthy", "recent update"


def read_supervisor_runs(
    runs_dir: Path = RUN_REPORTS_ROOT,
    now: datetime | None = None,
    stale_seconds: int = DEFAULT_STALE_SECONDS,
) -> list[SupervisorRun]:
    now = now or datetime.now()
    if not runs_dir.exists():
        return []

    runs: list[SupervisorRun] = []
    for run_dir in sorted((path for path in runs_dir.iterdir() if path.is_dir()), reverse=True):
        summary = _summary_fields(run_dir)
        metadata = _read_json(run_dir / "metadata.json")
        health = _read_json(run_dir / "health.json")

        status = _string_value(metadata, "status") or summary.get("status", "")
        phase = _string_value(health, "phase")
        health_status = _string_value(health, "status")
        if health_status and health_status not in RUNNING_STATUSES and not status:
            status = health_status

        last_activity = parse_datetime_value(
            _string_value(health, "last_activity_at")
            or _string_value(metadata, "last_activity_at")
            or summary.get("last_activity_at", "")
        )
        last_report_update = parse_datetime_value(
            _string_value(health, "last_report_update_at")
            or _string_value(metadata, "last_report_update_at")
            or summary.get("last_report_update_at", "")
        )
        last_seen = _latest_datetime(last_activity, last_report_update, parse_created_at(run_dir.name))
        run_health, reason = classify_run_health(status, phase, last_seen, now, stale_seconds)

        cancelled_at, cancellation_reason, cancellation_signal = read_cancellation_info(run_dir)

        runs.append(
            SupervisorRun(
                run_id=run_dir.name,
                run_dir=run_dir,
                repo=_string_value(metadata, "repo") or summary.get("repo", ""),
                issue=_string_value(metadata, "issue_number")
                or _string_value(metadata, "issue")
                or summary.get("issue", ""),
                branch=_string_value(metadata, "branch") or summary.get("branch", ""),
                model=_string_value(metadata, "model") or summary.get("model", ""),
                status=status,
                phase=phase,
                runner_pid=_string_value(
                    health.get("process", {}) if isinstance(health.get("process"), dict) else {},
                    "runner_pid",
                ),
                parent_pid=_string_value(
                    health.get("process", {}) if isinstance(health.get("process"), dict) else {},
                    "parent_pid",
                ),
                worker_pid=_string_value(
                    health.get("process", {}) if isinstance(health.get("process"), dict) else {},
                    "worker_pid",
                ),
                last_activity_at=last_activity,
                last_report_update_at=last_report_update,
                health_status=run_health,
                health_reason=reason,
                output_tail=_string_value(health, "output_tail"),
                cancelled_at=cancelled_at,
                cancellation_reason=cancellation_reason,
                cancellation_signal=cancellation_signal,
            )
        )
    return runs


def filter_active_runs(runs: Iterable[SupervisorRun]) -> list[SupervisorRun]:
    return [run for run in runs if run.is_active]


def _pid_from_text(value: str) -> int | None:
    try:
        pid = int(value)
    except (TypeError, ValueError):
        return None
    return pid if pid > 0 else None


def direct_child_pids(pid: int) -> list[int]:
    try:
        result = subprocess.run(
            ["pgrep", "-P", str(pid)],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return []
    if result.returncode not in {0, 1}:
        return []
    children = []
    for line in result.stdout.splitlines():
        child_pid = _pid_from_text(line.strip())
        if child_pid is not None:
            children.append(child_pid)
    return children


def process_tree(root_pids: Iterable[int]) -> list[int]:
    seen: set[int] = set()
    pending = [pid for pid in root_pids if pid > 0]
    while pending:
        pid = pending.pop(0)
        if pid in seen:
            continue
        seen.add(pid)
        pending.extend(child for child in direct_child_pids(pid) if child not in seen)
    return sorted(seen)


def is_process_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def send_signal_to_process(pid: int, sig: signal.Signals) -> bool:
    try:
        os.kill(pid, sig)
        return True
    except OSError:
        return False


def terminate_process_tree(
    pids: list[int],
    graceful_timeout: float = DEFAULT_GRACEFUL_TIMEOUT_SECONDS,
    kill_timeout: float = DEFAULT_KILL_TIMEOUT_SECONDS,
    progress_callback=None,
) -> tuple[list[int], list[int], list[int]]:
    terminated = []
    killed = []
    failed = []
    handled = set()

    for pid in pids:
        if pid in PROTECTED_PIDS:
            failed.append(pid)
            handled.add(pid)
            continue
        if not is_process_alive(pid):
            continue

        if progress_callback:
            progress_callback(pid, "SIGTERM")
        sent = send_signal_to_process(pid, GRACEFUL_SIGNAL)
        if not sent:
            failed.append(pid)
            handled.add(pid)
            continue

    if pids:
        time.sleep(graceful_timeout)

    for pid in pids:
        if pid in handled:
            continue
        if pid in PROTECTED_PIDS or pid in terminated:
            continue
        if not is_process_alive(pid):
            terminated.append(pid)
            continue

        if progress_callback:
            progress_callback(pid, "SIGKILL")
        sent = send_signal_to_process(pid, KILL_SIGNAL)
        if not sent:
            failed.append(pid)
            continue

        time.sleep(kill_timeout / len(pids) if pids else 0.1)

        if is_process_alive(pid):
            failed.append(pid)
        else:
            killed.append(pid)

    return terminated, killed, failed


def check_unrelated_processes(pids: list[int]) -> tuple[bool, list[int]]:
    safe_pids = []
    unsafe_pids = []

    for pid in pids:
        if pid in PROTECTED_PIDS:
            unsafe_pids.append(pid)
            continue
        try:
            proc_path = Path(f"/proc/{pid}")
            if not proc_path.exists():
                continue
            cmdline = (proc_path / "cmdline").read_text(encoding="utf-8", errors="replace")
            cmdline_lower = cmdline.lower()
            if any(
                protected in cmdline_lower
                for protected in [
                    "dashboard",
                    "terminal",
                    "bash",
                    "zsh",
                    "ssh",
                    "login",
                    "windowserver",
                    "codesign",
                ]
            ):
                unsafe_pids.append(pid)
            else:
                safe_pids.append(pid)
        except (OSError, PermissionError):
            continue

    return len(unsafe_pids) == 0, unsafe_pids


def read_cancellation_info(run_dir: Path) -> tuple[datetime | None, str | None, str | None]:
    summary = _summary_fields(run_dir)
    cancelled_at = None
    cancellation_reason = None
    cancellation_signal = None

    cancelled_at_str = summary.get("cancelled_at", "")
    if cancelled_at_str:
        cancelled_at = parse_datetime_value(cancelled_at_str)

    cancellation_reason = summary.get("cancellation_reason") or None
    cancellation_signal = summary.get("cancellation_signal") or None

    return cancelled_at, cancellation_reason, cancellation_signal


def extend_supervisor_run(run: SupervisorRun) -> SupervisorRun:
    cancelled_at, cancellation_reason, cancellation_signal = read_cancellation_info(run.run_dir)
    return SupervisorRun(
        run_id=run.run_id,
        run_dir=run.run_dir,
        repo=run.repo,
        issue=run.issue,
        branch=run.branch,
        model=run.model,
        status=run.status,
        phase=run.phase,
        runner_pid=run.runner_pid,
        parent_pid=run.parent_pid,
        worker_pid=run.worker_pid,
        last_activity_at=run.last_activity_at,
        last_report_update_at=run.last_report_update_at,
        health_status=run.health_status,
        health_reason=run.health_reason,
        output_tail=run.output_tail,
        cancelled_at=cancelled_at,
        cancellation_reason=cancellation_reason,
        cancellation_signal=cancellation_signal,
    )


def run_root_pids(run: SupervisorRun) -> list[int]:
    pids = []
    for value in (run.worker_pid, run.runner_pid):
        pid = _pid_from_text(value)
        if pid is not None and pid not in pids:
            pids.append(pid)
    return pids


def select_runs(
    runs: Iterable[SupervisorRun],
    run_id: str | None = None,
    repo: str | None = None,
    issue: str | None = None,
    worker_pid: str | None = None,
) -> list[SupervisorRun]:
    selected = []
    for run in runs:
        if run_id and run.run_id != run_id:
            continue
        if repo and run.repo != repo:
            continue
        if issue and run.issue != issue:
            continue
        if worker_pid and run.worker_pid != worker_pid:
            continue
        selected.append(run)
    return selected


def format_dry_run_stop(run: SupervisorRun) -> list[str]:
    root_pids = run_root_pids(run)
    tree = process_tree(root_pids)
    issue = f"#{run.issue}" if run.issue else "-"
    lines = [
        f"DRY-RUN stop target: {run.run_id}",
        f"  repo: {run.repo or '-'}",
        f"  issue: {issue}",
        f"  phase: {run.phase or '-'}",
        f"  status: {run.status or '-'}",
        f"  worker_pid: {run.worker_pid or '-'}",
        f"  runner_pid: {run.runner_pid or '-'}",
        f"  process_tree: {', '.join(str(pid) for pid in tree) if tree else '(none known)'}",
        "  action: no signal sent",
    ]
    return lines


def format_stop_result(
    run: SupervisorRun,
    terminated: list[int],
    killed: list[int],
    failed: list[int],
    preserved_worktree: Path | None,
    cancellation_reason: str,
) -> list[str]:
    issue = f"#{run.issue}" if run.issue else "-"
    lines = [
        f"STOP completed for: {run.run_id}",
        f"  repo: {run.repo or '-'}",
        f"  issue: {issue}",
        f"  phase: {run.phase or '-'}",
        f"  status: {run.status or '-'}",
        f"  worker_pid: {run.worker_pid or '-'}",
        f"  runner_pid: {run.runner_pid or '-'}",
        f"  graceful_terminated: {', '.join(str(p) for p in terminated) if terminated else '(none)'}",
        f"  force_killed: {', '.join(str(p) for p in killed) if killed else '(none)'}",
        f"  failed: {', '.join(str(p) for p in failed) if failed else '(none)'}",
        f"  cancellation_reason: {cancellation_reason}",
    ]
    if preserved_worktree:
        lines.append(f"  preserved_worktree: {preserved_worktree}")
    return lines


def worktree_has_local_changes(run: SupervisorRun) -> bool:
    summary = _summary_fields(run.run_dir)
    git_diff_stat = summary.get("git_diff_stat", "")
    output_tail = summary.get("output_tail", "")
    if git_diff_stat and "no changes" not in git_diff_stat.lower():
        return True
    if output_tail and "no changes" not in output_tail.lower():
        return True
    return False


def preserve_run_worktree(run: SupervisorRun) -> Path | None:
    if not worktree_has_local_changes(run):
        return None

    try:
        metadata = _read_json(run.run_dir / "metadata.json")
        owner = ""
        base_branch = metadata.get("base_branch", "main")
    except (OSError, json.JSONDecodeError):
        owner = ""
        base_branch = "main"

    if not run.branch:
        return None

    try:
        report = type("RunReport", (), {
            "path": run.run_dir,
            "repo": run.repo,
            "issue_number": int(run.issue) if run.issue and run.issue.isdigit() else 0,
            "branch": run.branch,
            "model": run.model,
        })()
        return preserve_worker_worktree(
            repo_dir="",
            report=report,
            owner=owner,
            repo=run.repo,
            issue_number=int(run.issue) if run.issue and run.issue.isdigit() else 0,
            branch=run.branch,
            status="supervisor_stop",
            base_branch=base_branch,
        )
    except (ValueError, OSError):
        return None


def write_cancellation_note(
    run: SupervisorRun,
    reason: str,
    signal_sent: str,
    preserved_worktree: Path | None = None,
) -> None:
    summary_path = run.run_dir / "summary.txt"
    lines = []
    if summary_path.exists():
        lines = summary_path.read_text(encoding="utf-8").splitlines()

    cancelled_at = datetime.now().isoformat(timespec="seconds")
    insert_at = 0
    status_line_index = None
    output_tail_index = None

    for index, line in enumerate(lines):
        key, separator, _value = line.partition(":")
        key = key.strip()
        if separator and key == "status":
            status_line_index = index
        if separator and key == "output_tail":
            output_tail_index = index

    new_lines = [
        f"status: cancelled",
        f"cancelled_at: {cancelled_at}",
        f"cancellation_reason: {reason}",
        f"cancellation_signal: {signal_sent}",
    ]
    if preserved_worktree:
        new_lines.append(f"preserved_worktree: {preserved_worktree}")

    if status_line_index is not None:
        lines[status_line_index] = "status: cancelled"
        insert_at = status_line_index + 1
    else:
        insert_at = 0

    if output_tail_index is not None and output_tail_index > insert_at:
        insert_at = output_tail_index

    for i, new_line in enumerate(new_lines):
        lines.insert(insert_at + i, new_line)

    lines.insert(insert_at + len(new_lines), "")

    try:
        summary_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    except OSError:
        pass

    metadata_path = run.run_dir / "metadata.json"
    if metadata_path.exists():
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            metadata["status"] = "cancelled"
            metadata["cancelled_at"] = cancelled_at
            metadata["cancellation_reason"] = reason
            metadata["cancellation_signal"] = signal_sent
            if preserved_worktree:
                metadata["preserved_worktree"] = str(preserved_worktree)
            metadata_path.write_text(json.dumps(metadata, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        except (OSError, json.JSONDecodeError):
            pass


def stop_run(
    run: SupervisorRun,
    args: argparse.Namespace,
) -> tuple[list[int], list[int], list[int], Path | None]:
    root_pids = run_root_pids(run)
    tree = process_tree(root_pids)

    safe, unsafe_pids = check_unrelated_processes(tree)
    if not safe:
        print_warn(
            f"Unsafe PIDs detected (protected processes): {unsafe_pids}. "
            "Refusing to stop to prevent system damage."
        )
        return [], [], tree, None

    preserved_worktree = None
    if args.preserve_worktree and worktree_has_local_changes(run):
        preserved_worktree = preserve_run_worktree(run)
        if preserved_worktree:
            print_warn(f"Worktree preserved: {preserved_worktree}")

    def progress_callback(pid: int, signal_name: str):
        print(f"  Sending {signal_name} to PID {pid}")

    terminated, killed, failed = terminate_process_tree(
        tree,
        graceful_timeout=args.graceful_timeout,
        kill_timeout=args.kill_timeout,
        progress_callback=progress_callback if args.verbose else None,
    )

    return terminated, killed, failed, preserved_worktree


def format_run_line(run: SupervisorRun) -> str:
    issue = f"#{run.issue}" if run.issue else "-"
    return (
        f"{run.health_status:<8} {run.repo or '-':<22} {issue:<8} "
        f"{run.phase or '-':<18} {run.status or '-':<18} {run.model or '-':<24} "
        f"{run.worker_pid or '-':<8} {run.run_id}"
    )


def print_status(runs: list[SupervisorRun], active_only: bool) -> None:
    selected = filter_active_runs(runs) if active_only else runs
    if not selected:
        print_ok("No matching solver runs found.")
        return

    print("Health   Repo                   Issue    Phase              Status             Model                    Worker   Run")
    print("-" * 128)
    for run in selected:
        print(format_run_line(run))
        if run.health_status in {"stale", "unknown"}:
            print(f"         reason: {run.health_reason}; report: {run.run_dir}")
        if run.is_cancelled:
            print(f"         cancelled: {run.cancellation_reason or 'unknown'} at {run.cancelled_at}")
    print()
    print(f"{len(selected)} run(s) shown.")


def run_stop_dry_run(args: argparse.Namespace) -> int:
    runs = read_supervisor_runs(Path(args.runs_dir), stale_seconds=args.stale_seconds)
    selected = select_runs(
        runs,
        run_id=args.run_id,
        repo=args.repo,
        issue=str(args.issue) if args.issue is not None else None,
        worker_pid=str(args.worker_pid) if args.worker_pid is not None else None,
    )
    if not selected:
        print_warn("No matching solver run found.")
        return 1
    if len(selected) > 1:
        print_warn(f"{len(selected)} matching runs found; add --run-id or --worker-pid.")
        for run in selected:
            print(format_run_line(run))
        return 1

    run = selected[0]

    if args.dry_run:
        for line in format_dry_run_stop(run):
            print(line)
        return 0

    cancelled_reason = args.reason or "manual_supervisor_stop"
    terminated, killed, failed, preserved_worktree = stop_run(run, args)

    for line in format_stop_result(run, terminated, killed, failed, preserved_worktree, cancelled_reason):
        print(line)

    write_cancellation_note(
        run,
        reason=cancelled_reason,
        signal_sent="SIGTERM/SIGKILL" if killed else "SIGTERM",
        preserved_worktree=preserved_worktree,
    )

    if failed:
        print_warn(f"Some processes could not be terminated: {failed}")
        return 1

    print_ok("Run stopped successfully.")
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Solver process supervisor for monitoring and targeted cancellation")
    subparsers = parser.add_subparsers(dest="command", required=True)

    status_parser = subparsers.add_parser("status", help="Show solver run status")
    status_parser.add_argument("--runs-dir", default=str(RUN_REPORTS_ROOT), help="Run report directory")
    status_parser.add_argument(
        "--stale-seconds",
        type=int,
        default=DEFAULT_STALE_SECONDS,
        help=f"Seconds without health updates before a run is stale (default: {DEFAULT_STALE_SECONDS})",
    )
    status_parser.add_argument("--all", action="store_true", help="Show terminal runs too")

    stop_parser = subparsers.add_parser("stop", help="Targeted stop of solver runs")
    stop_parser.add_argument("--runs-dir", default=str(RUN_REPORTS_ROOT), help="Run report directory")
    stop_parser.add_argument("--run-id", help="Exact run report directory name")
    stop_parser.add_argument("--repo", help="Repository name")
    stop_parser.add_argument("--issue", type=int, help="Issue number")
    stop_parser.add_argument("--worker-pid", type=int, help="Worker process id from health.json")
    stop_parser.add_argument("--dry-run", action="store_true", help="Preview target process tree only")
    stop_parser.add_argument(
        "--stale-seconds",
        type=int,
        default=DEFAULT_STALE_SECONDS,
        help=f"Seconds without health updates before a run is stale (default: {DEFAULT_STALE_SECONDS})",
    )
    stop_parser.add_argument(
        "--graceful-timeout",
        type=float,
        default=DEFAULT_GRACEFUL_TIMEOUT_SECONDS,
        help=f"Seconds to wait for graceful SIGTERM termination (default: {DEFAULT_GRACEFUL_TIMEOUT_SECONDS})",
    )
    stop_parser.add_argument(
        "--kill-timeout",
        type=float,
        default=DEFAULT_KILL_TIMEOUT_SECONDS,
        help=f"Seconds to wait after SIGKILL before giving up (default: {DEFAULT_KILL_TIMEOUT_SECONDS})",
    )
    stop_parser.add_argument(
        "--preserve-worktree",
        action="store_true",
        help="Preserve worktree with local changes before stopping",
    )
    stop_parser.add_argument(
        "--reason",
        help="Reason for cancellation (written to run report)",
    )
    stop_parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Show signal sending progress",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    print_banner("SOLVER SUPERVISOR")
    if args.command == "stop":
        return run_stop_dry_run(args)

    print_step(1, f"Reading runs from {args.runs_dir}")
    runs = read_supervisor_runs(Path(args.runs_dir), stale_seconds=args.stale_seconds)
    print_status(runs, active_only=not args.all)
    if any(run.health_status == "stale" for run in filter_active_runs(runs)):
        print_warn("Stale runs detected. Use 'python scripts/solver_supervisor.py stop --dry-run --run-id <id>' to preview stop.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
