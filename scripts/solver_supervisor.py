#!/usr/bin/env python3
"""Read-only supervisor status for solver run reports.

This first supervisor slice intentionally does not inspect or stop OS
processes. It reports active-looking solver runs from existing report files so
operators can see stale jobs without manual tail/ps work.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable

sys.path.insert(0, str(Path(__file__).parent))
from solver_reporting import RUN_REPORTS_ROOT  # noqa: E402
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
    if not args.dry_run:
        print_warn("Stop is not implemented in this read-only slice. Re-run with --dry-run.")
        return 2
    for line in format_dry_run_stop(selected[0]):
        print(line)
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Read-only solver supervisor status")
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

    stop_parser = subparsers.add_parser("stop", help="Preview targeted stop selection")
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
        print_warn("Stale runs detected. This read-only command does not stop processes yet.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
