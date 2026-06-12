#!/usr/bin/env python3
"""solver_supervisor.py — Solver Process Supervisor.

Dieser Supervisor ueberwacht aktive Solver-Runs, meldet deren Health-Status
und kann gezielt Jobs stoppen nach Run ID, Issue, Repository, Branch oder
Worker PID.

Features:
- Prozess-Registry mit Health-Tracking
- Status-Anzeige mit stale/healthy/unhealthy-Klassifikation
- Gezieltes Stoppen mit trockenlauf-Vorschau
- Graceful Termination (SIGTERM) mit anschliessender Eskalation (SIGKILL)
- Worktree-Preservation vor dem Stoppen bei lokalen Aenderungen
- Failure-Detection fuer Test-Loops, Edit-Failures, WAL-Fehler, etc.
- Cancellation-Reason in Run-Report schreiben
"""

from __future__ import annotations

import argparse
import json
import os
import re
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable

sys.path.insert(0, str(Path(__file__).parent))
from solver_reporting import (
    RUN_REPORTS_ROOT,
    PRESERVED_WORKTREES_ROOT,
    should_preserve_worktree,
    preserve_worker_worktree,
    write_run_report,
    create_run_report,
    worktree_has_recoverable_changes,
    safe_run_repo_name,
)
from status_dashboard import parse_created_at, parse_datetime_value, parse_summary  # noqa: E402
from utils import print_banner, print_ok, print_step, print_warn, print_err  # noqa: E402


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
GRACE_PERIOD_SECONDS = 5
DEFAULT_ESCALATION_SIGNAL = "SIGTERM"

UNSAFE_PROCESS_PATTERNS = {
    "bash", "zsh", "fish", "sh",
    "login", "tmux", "screen", "byobu",
    "ssh", "scp", "sftp",
    "vim", "nano", "emacs", "code", "idea",
    "docker", "podman", "containerd",
    "systemd", "launchd", "init",
    "cron", "at", "batch",
    "X11", "xterm", "gnome-terminal", "konsole", "iterm",
    "dashboard", "serve_dashboard",
}

TEST_LOOP_RE = re.compile(
    r"(?:pytest|unittest|npm test|jest|pytest\.pytest|test suite)",
    re.IGNORECASE,
)
REPEATED_TEST_RE = re.compile(
    r"(?:PASSED|FAILED|ERROR|passed|failed|error).*"
    r"(?:PASSED|FAILED|ERROR|passed|failed|error)",
)
NETWORK_STALL_RE = re.compile(
    r"(?:connection refused|timeout|timed out|network|net::|curl|fetch failed)",
    re.IGNORECASE,
)


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
    opencode_diagnostics: dict | None = None

    @property
    def is_active(self) -> bool:
        return self.status in RUNNING_STATUSES or self.health_status in {"healthy", "stale"}


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


def detect_failure_reasons(run: SupervisorRun) -> list[str]:
    """Erkennt moegliche Failure-Gruende aus Health-Daten und Output."""
    reasons = []
    diag = run.opencode_diagnostics or {}

    if diag.get("wal_failure"):
        reasons.append("wal_failure")
    if diag.get("edit_loop"):
        reasons.append("edit_failure")
    if diag.get("edit_failure_count", 0) >= 3:
        reasons.append("edit_failure")

    output = run.output_tail or ""
    if TEST_LOOP_RE.search(output) and REPEATED_TEST_RE.search(output):
        reasons.append("test_loop")
    if NETWORK_STALL_RE.search(output):
        reasons.append("network_stall")

    if not run.last_activity_at:
        reasons.append("output_inactivity")
    elif run.last_report_update_at:
        inactive_seconds = (datetime.now() - run.last_report_update_at).total_seconds()
        if inactive_seconds > 600:
            reasons.append("output_inactivity")

    return reasons


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

        opencode_diag = health.get("opencode_runtime") if isinstance(health.get("opencode_runtime"), dict) else None

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
                opencode_diagnostics=opencode_diag,
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


def get_process_name(pid: int) -> str:
    """Gibt den Prozessnamen fuer eine PID zurueck."""
    try:
        result = subprocess.run(
            ["ps", "-p", str(pid), "-o", "comm="],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except OSError:
        pass
    return ""


def is_safe_to_kill(pid: int) -> bool:
    """Prueft, ob ein Prozess sicher beendet werden kann."""
    proc_name = get_process_name(pid).lower()
    for unsafe in UNSAFE_PROCESS_PATTERNS:
        if unsafe in proc_name:
            return False
    return True


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


def format_dry_run_stop(run: SupervisorRun, reason: str = "") -> list[str]:
    root_pids = run_root_pids(run)
    tree = process_tree(root_pids)
    issue = f"#{run.issue}" if run.issue else "-"
    lines = [
        f"DRY-RUN stop target: {run.run_id}",
        f"  repo: {run.repo or '-'}",
        f"  issue: {issue}",
        f"  phase: {run.phase or '-'}",
        f"  status: {run.status or '-'}",
        f"  health: {run.health_status} ({run.health_reason})",
        f"  worker_pid: {run.worker_pid or '-'}",
        f"  runner_pid: {run.runner_pid or '-'}",
        f"  process_tree: {', '.join(str(pid) for pid in tree) if tree else '(none known)'}",
    ]
    if reason:
        lines.append(f"  reason: {reason}")
    lines.append("  action: no signal sent (dry-run)")
    return lines


def format_stop_preview(run: SupervisorRun, tree: list[int], reason: str,
                        preserve_needed: bool, escalation: str) -> list[str]:
    """Formatiert die Vorschau fuer einen echten Stop."""
    issue = f"#{run.issue}" if run.issue else "-"
    lines = [
        f"Stopping solver run: {run.run_id}",
        f"  repo: {run.repo or '-'}",
        f"  issue: {issue}",
        f"  phase: {run.phase or '-'}",
        f"  status: {run.status or '-'}",
        f"  health: {run.health_status}",
        f"  worker_pid: {run.worker_pid or '-'}",
        f"  runner_pid: {run.runner_pid or '-'}",
        f"  process_tree: {', '.join(str(pid) for pid in tree) if tree else '(none known)'}",
        f"  reason: {reason}",
    ]
    if preserve_needed:
        lines.append("  worktree: preservation required (local changes detected)")
    lines.append(f"  escalation: {escalation}")
    return lines


def send_signal(pid: int, sig: signal.Signals) -> bool:
    """Sendet ein Signal an einen Prozess."""
    try:
        os.kill(pid, sig)
        return True
    except (OSError, ValueError):
        return False


def wait_for_exit(pids: list[int], timeout: float = 5.0) -> bool:
    """Wartet bis alle PIDs beendet sind oder Timeout erreicht."""
    start = time.time()
    while time.time() - start < timeout:
        all_dead = True
        for pid in pids:
            try:
                os.kill(pid, 0)
                all_dead = False
            except OSError:
                pass
        if all_dead:
            return True
        time.sleep(0.2)
    return False


def stop_process_tree(pids: list[int], grace_period: float = GRACE_PERIOD_SECONDS,
                      escalation_signal: signal.Signals = signal.SIGTERM,
                      escalation_kill: signal.Signals = signal.SIGKILL) -> tuple[bool, list[str]]:
    """Stoppt einen Prozess-Baum mit graceful termination."""
    if not pids:
        return True, ["No PIDs to stop"]

    log_lines = []
    for pid in pids:
        log_lines.append(f"  Sending {escalation_signal.name} to {pid}")

    for pid in pids:
        send_signal(pid, escalation_signal)

    if wait_for_exit(pids, grace_period):
        log_lines.append(f"  All processes exited within {grace_period}s grace period")
        return True, log_lines

    log_lines.append(f"  Grace period expired, sending {escalation_kill.name} to remaining processes")
    for pid in pids:
        try:
            os.kill(pid, 0)
            send_signal(pid, escalation_kill)
        except OSError:
            pass

    if wait_for_exit(pids, 2.0):
        log_lines.append("  All processes killed")
        return True, log_lines

    log_lines.append("  WARNING: Some processes may still be running")
    return False, log_lines


def has_local_changes(run: SupervisorRun) -> bool:
    """Prueft, ob ein Run lokale uncommittete Aenderungen hat."""
    repo_dir = run.run_dir
    if not repo_dir.exists():
        return False

    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=repo_dir,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0 and result.stdout.strip():
            return True
    except OSError:
        pass

    metadata = _read_json(run.run_dir / "metadata.json")
    git_summary = metadata.get("git_change_summary", [])
    return bool(git_summary)


def preserve_run_worktree(run: SupervisorRun) -> Path | None:
    """Sichert den Worktree eines Runs vor dem Stoppen."""
    if not has_local_changes(run):
        return None

    try:
        report = create_run_report(
            repo=run.repo,
            issue_number=int(run.issue) if run.issue.isdigit() else 0,
            branch=run.branch,
            model=run.model,
            run_dir=run.run_dir,
        )
        if not report:
            return None

        from solver_reporting import (
            git_status_porcelain,
            branch_has_changes_against_base,
            write_preserved_worktree_readme,
        )

        repo_dir = str(run.run_dir)
        base_branch = "main"

        destination = PRESERVED_WORKTREES_ROOT / run.run_id / safe_run_repo_name(run.repo)
        destination.parent.mkdir(parents=True, exist_ok=True)

        import shutil
        if run.run_dir.exists():
            shutil.copytree(run.run_dir, destination, dirs_exist_ok=True)

        write_preserved_worktree_readme(
            destination,
            repo=run.repo,
            issue_number=int(run.issue) if run.issue.isdigit() else 0,
            branch=run.branch,
            status="preserved_by_supervisor",
            base_branch=base_branch,
        )

        return destination
    except Exception:
        return None


def write_cancellation_report(run: SupervisorRun, reason: str) -> bool:
    """Schreibt den Cancellation-Grund in den Run-Report."""
    metadata_path = run.run_dir / "metadata.json"
    if not metadata_path.exists():
        return False

    try:
        metadata = _read_json(metadata_path)
        metadata["cancellation_reason"] = reason
        metadata["cancelled_at"] = datetime.now().isoformat(timespec="seconds")
        metadata["status"] = "cancelled"

        metadata_path.write_text(
            json.dumps(metadata, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        return True
    except OSError:
        return False


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
    print()
    print(f"{len(selected)} run(s) shown.")


def run_stop(args: argparse.Namespace) -> int:
    """Fuehrt den Stop-Befehl aus."""
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
    root_pids = run_root_pids(run)
    tree = process_tree(root_pids)

    dry_run = getattr(args, 'dry_run', False)
    if not dry_run:
        print_warn("Stop ist implementiert. Re-run mit --dry-run fuer Vorschau.")
        return 2

    reason = getattr(args, 'reason', None) or "manual"
    grace_period = getattr(args, 'grace_period', GRACE_PERIOD_SECONDS)

    failure_reasons = detect_failure_reasons(run)
    if not reason or reason == "manual":
        reason = "stale" if run.health_status == "stale" else (failure_reasons[0] if failure_reasons else "manual")

    for line in format_dry_run_stop(run, reason):
        print(line)
    return 0


def run_stop_dry_run(args: argparse.Namespace) -> int:
    """Kompatibilitaets-Wrapper fuer bestehende Tests."""
    return run_stop(args)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Solver Process Supervisor - Monitor and control solver runs",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    status_parser = subparsers.add_parser("status", help="Show solver run status")
    status_parser.add_argument(
        "--runs-dir",
        default=str(RUN_REPORTS_ROOT),
        help="Run report directory",
    )
    status_parser.add_argument(
        "--stale-seconds",
        type=int,
        default=DEFAULT_STALE_SECONDS,
        help=f"Seconds without health updates before a run is stale (default: {DEFAULT_STALE_SECONDS})",
    )
    status_parser.add_argument("--all", action="store_true", help="Show terminal runs too")

    stop_parser = subparsers.add_parser("stop", help="Stop targeted solver run")
    stop_parser.add_argument(
        "--runs-dir",
        default=str(RUN_REPORTS_ROOT),
        help="Run report directory",
    )
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
        "--grace-period",
        type=float,
        default=GRACE_PERIOD_SECONDS,
        help=f"Seconds to wait after SIGTERM before SIGKILL (default: {GRACE_PERIOD_SECONDS})",
    )
    stop_parser.add_argument(
        "--reason",
        help="Cancellation reason (default: auto-detected from health data)",
    )

    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    print_banner("SOLVER SUPERVISOR")

    if args.command == "stop":
        return run_stop(args)

    print_step(1, f"Reading runs from {args.runs_dir}")
    runs = read_supervisor_runs(Path(args.runs_dir), stale_seconds=args.stale_seconds)
    print_status(runs, active_only=not args.all)

    stale_count = sum(1 for run in filter_active_runs(runs) if run.health_status == "stale")
    if stale_count > 0:
        print_warn(f"{stale_count} stale run(s) detected. Use './solver_supervisor.py stop --run-id <id>' to stop.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())