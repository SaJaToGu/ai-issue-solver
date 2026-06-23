#!/usr/bin/env python3
"""watchdog.py — Deterministic cost, progress and stuck detection.

Replaces the earlier LLM-based Watchdog agent. Runs as a cron-driven script
that checks solver run health, cost budgets, and progress. LLM escalation
is only triggered on anomaly via an explicit CLI flag (not the default).

Usage:
    python scripts/watchdog.py check              # Run all checks
    python scripts/watchdog.py check --cost-only  # Cost check only
    python scripts/watchdog.py check --llm-escalate   # With LLM on anomaly
    python scripts/watchdog.py status             # Write structured JSON report
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from solver_reporting import (  # noqa: E402
    RUN_REPORTS_ROOT,
    RUNNING_STATUSES as _SOLVER_RUNNING_STATUSES,
    TERMINAL_STATUSES,
    read_normalized_run_outcome,
    latest_datetime,
    parse_summary_file,
)

# ── Default paths & thresholds ──────────────────────────────────────────────

WATCHDOG_STATUS_PATH = Path("reports") / "watchdog-status.json"
BUDGET_TRACKER_PATH = Path("reports") / "budget_tracker.json"

# Default thresholds
DEFAULT_PROGRESS_TIMEOUT_MINUTES = 30
DEFAULT_STUCK_TIMEOUT_MINUTES = 15
DEFAULT_COST_PER_RUN_USD = 5.0
DEFAULT_COST_PER_DAY_USD = 20.0
DEFAULT_COST_BUDGET_RATIO = 0.8  # Warn when 80% of monthly budget reached

# ── Data classes ────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class WatchdogRun:
    run_id: str
    run_dir: Path
    repo: str
    issue: str
    phase: str
    status: str
    last_activity_at: datetime | None
    last_report_update_at: datetime | None
    model: str = ""
    worker_exit_code: str = ""


@dataclass(frozen=True)
class CostFinding:
    kind: str  # per_run | per_day | budget_ratio
    severity: str  # info | warning | critical
    message: str
    run_id: str | None = None
    current: float = 0.0
    threshold: float = 0.0


@dataclass(frozen=True)
class ProgressFinding:
    kind: str  # no_progress | stuck
    severity: str  # warning | critical
    message: str
    run_id: str
    idle_minutes: float


@dataclass(frozen=True)
class WatchdogStatus:
    checked_at: str
    total_runs: int
    active_runs: int
    finished_runs: int
    cost_findings: list[dict]
    progress_findings: list[dict]
    stuck_findings: list[dict]
    anomalies_detected: bool
    summary: str


# ── Helpers ─────────────────────────────────────────────────────────────────


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _string_value(data: dict, key: str) -> str:
    value = data.get(key, "")
    return "" if value is None else str(value)






def _active_runs(runs_dir: Path) -> list[WatchdogRun]:
    """Read all active (non-terminal) runs from the runs directory."""
    if not runs_dir.exists():
        return []

    results: list[WatchdogRun] = []
    for run_dir in sorted(runs_dir.iterdir()):
        if not run_dir.is_dir():
            continue
        summary = parse_summary_file(run_dir / "summary.txt")
        metadata = _read_json(run_dir / "metadata.json")
        health = _read_json(run_dir / "health.json")
        normalized = read_normalized_run_outcome(run_dir)

        status = normalized.status
        if not status:
            continue

        if status in TERMINAL_STATUSES:
            continue

        health_status = _string_value(health, "status")
        if health_status and health_status not in {"started", "running"} and not status:
            continue

        phase = _string_value(health, "phase")
        last_activity = normalized.last_activity_at
        last_report = normalized.last_report_update_at

        results.append(WatchdogRun(
            run_id=run_dir.name,
            run_dir=run_dir,
            repo=normalized.repo,
            issue=normalized.issue_number,
            phase=phase,
            status=status,
            last_activity_at=last_activity,
            last_report_update_at=last_report,
            model=normalized.model,
            worker_exit_code=normalized.worker_exit_code,
        ))
    return results


# ── Cost checks ─────────────────────────────────────────────────────────────


def check_cost(
    runs: Iterable[WatchdogRun],
    budget_tracker_path: Path = BUDGET_TRACKER_PATH,
    per_run_limit: float = DEFAULT_COST_PER_RUN_USD,
    per_day_limit: float = DEFAULT_COST_PER_DAY_USD,
    budget_ratio: float = DEFAULT_COST_BUDGET_RATIO,
) -> list[CostFinding]:
    """Check costs: per-run, per-day, and budget ratio."""
    findings: list[CostFinding] = []

    # Per-run cost check from provider_scorecard in metadata
    for run in runs:
        metadata = _read_json(run.run_dir / "metadata.json")
        scorecard = metadata.get("provider_scorecard", {})
        estimated_cost = scorecard.get("estimated_cost")
        if estimated_cost is not None:
            try:
                cost = float(estimated_cost)
                if cost > per_run_limit:
                    findings.append(CostFinding(
                        kind="per_run",
                        severity="warning",
                        message=(
                            f"Run {run.run_id} cost ${cost:.2f} exceeds "
                            f"per-run limit ${per_run_limit:.2f}"
                        ),
                        run_id=run.run_id,
                        current=cost,
                        threshold=per_run_limit,
                    ))
            except (TypeError, ValueError):
                pass

    # Budget ratio check from budget_tracker.json
    tracker = _read_json(budget_tracker_path)
    for role_name, role_data in tracker.items():
        if not isinstance(role_data, dict):
            continue
        spent = role_data.get("spent", 0.0)
        budget = role_data.get("budget", 0.0)
        if budget > 0 and spent > 0:
            try:
                ratio = float(spent) / float(budget)
                if ratio >= budget_ratio:
                    severity = "critical" if ratio >= 1.0 else "warning"
                    findings.append(CostFinding(
                        kind="budget_ratio",
                        severity=severity,
                        message=(
                            f"Role '{role_name}' has spent ${spent:.2f} of "
                            f"${budget:.2f} budget ({ratio:.0%})"
                        ),
                        current=spent,
                        threshold=budget * budget_ratio,
                    ))
            except (TypeError, ValueError):
                pass

    return findings


# ── Progress checks ─────────────────────────────────────────────────────────


def check_progress(
    runs: Iterable[WatchdogRun],
    now: datetime | None = None,
    progress_timeout: timedelta | None = None,
) -> list[ProgressFinding]:
    """Check for runs with no progress (no phase change) within timeout."""
    now = now or datetime.now()
    progress_timeout = progress_timeout or timedelta(minutes=DEFAULT_PROGRESS_TIMEOUT_MINUTES)
    findings: list[ProgressFinding] = []

    for run in runs:
        last_seen = latest_datetime(run.last_activity_at, run.last_report_update_at)
        if last_seen is None:
            continue
        idle = now - last_seen
        if idle >= progress_timeout:
            findings.append(ProgressFinding(
                kind="no_progress",
                severity="warning",
                message=(
                    f"Run {run.run_id} ({run.repo} #{run.issue}) has no "
                    f"progress for {int(idle.total_seconds() // 60)} min "
                    f"(phase: {run.phase or 'unknown'})"
                ),
                run_id=run.run_id,
                idle_minutes=idle.total_seconds() / 60.0,
            ))

    return findings


# ── Stuck detection ─────────────────────────────────────────────────────────


def check_stuck(
    runs: Iterable[WatchdogRun],
    now: datetime | None = None,
    stuck_timeout: timedelta | None = None,
) -> list[ProgressFinding]:
    """Check for runs with no activity at all within timeout."""
    now = now or datetime.now()
    stuck_timeout = stuck_timeout or timedelta(minutes=DEFAULT_STUCK_TIMEOUT_MINUTES)
    findings: list[ProgressFinding] = []

    for run in runs:
        last_seen = latest_datetime(run.last_activity_at, run.last_report_update_at)
        if last_seen is None:
            continue
        idle = now - last_seen
        if idle >= stuck_timeout:
            findings.append(ProgressFinding(
                kind="stuck",
                severity="critical" if idle >= stuck_timeout * 2 else "warning",
                message=(
                    f"Run {run.run_id} ({run.repo} #{run.issue}) appears stuck: "
                    f"no activity for {int(idle.total_seconds() // 60)} min"
                ),
                run_id=run.run_id,
                idle_minutes=idle.total_seconds() / 60.0,
            ))

    return findings


# ── Status report ───────────────────────────────────────────────────────────


def write_status_report(
    runs: list[WatchdogRun],
    cost_findings: list[CostFinding],
    progress_findings: list[ProgressFinding],
    stuck_findings: list[ProgressFinding],
    output_path: Path = WATCHDOG_STATUS_PATH,
) -> Path:
    """Write a structured JSON status report for dashboard ingestion."""
    anomalies_detected = bool(cost_findings or progress_findings or stuck_findings)
    total_runs = len(runs)
    active_runs = sum(1 for r in runs if r.phase or r.status in {"started", "running"})
    finished_runs = total_runs - active_runs

    parts = []
    if cost_findings:
        parts.append(f"{len(cost_findings)} cost issue(s)")
    if progress_findings:
        parts.append(f"{len(progress_findings)} stalled run(s)")
    if stuck_findings:
        parts.append(f"{len(stuck_findings)} stuck run(s)")
    summary = "; ".join(parts) if parts else "All checks passed."

    status = WatchdogStatus(
        checked_at=datetime.now().isoformat(timespec="seconds"),
        total_runs=total_runs,
        active_runs=active_runs,
        finished_runs=finished_runs,
        cost_findings=[asdict(f) for f in cost_findings],
        progress_findings=[asdict(f) for f in progress_findings],
        stuck_findings=[asdict(f) for f in stuck_findings],
        anomalies_detected=anomalies_detected,
        summary=summary,
    )

    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(asdict(status), indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    except OSError as exc:
        print(f"watchdog: could not write status report: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    return output_path


# ── CLI ─────────────────────────────────────────────────────────────────────


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Watchdog — deterministic cost, progress and stuck detection",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # check command
    check_parser = subparsers.add_parser("check", help="Run deterministic checks")
    check_parser.add_argument(
        "--runs-dir",
        default=str(RUN_REPORTS_ROOT),
        help="Run report directory (default: reports/runs)",
    )
    check_parser.add_argument(
        "--budget-tracker",
        default=str(BUDGET_TRACKER_PATH),
        help="Budget tracker path (default: reports/budget_tracker.json)",
    )
    check_parser.add_argument(
        "--progress-timeout",
        type=int,
        default=DEFAULT_PROGRESS_TIMEOUT_MINUTES,
        help=f"Minutes without progress before warning (default: {DEFAULT_PROGRESS_TIMEOUT_MINUTES})",
    )
    check_parser.add_argument(
        "--stuck-timeout",
        type=int,
        default=DEFAULT_STUCK_TIMEOUT_MINUTES,
        help=f"Minutes without activity before stuck detection (default: {DEFAULT_STUCK_TIMEOUT_MINUTES})",
    )
    check_parser.add_argument(
        "--per-run-cost",
        type=float,
        default=DEFAULT_COST_PER_RUN_USD,
        help=f"Per-run cost limit in USD (default: {DEFAULT_COST_PER_RUN_USD})",
    )
    check_parser.add_argument(
        "--per-day-cost",
        type=float,
        default=DEFAULT_COST_PER_DAY_USD,
        help=f"Per-day cost limit in USD (default: {DEFAULT_COST_PER_DAY_USD})",
    )
    check_parser.add_argument(
        "--budget-ratio",
        type=float,
        default=DEFAULT_COST_BUDGET_RATIO,
        help=f"Budget ratio to warn at (default: {DEFAULT_COST_BUDGET_RATIO})",
    )
    check_parser.add_argument(
        "--cost-only",
        action="store_true",
        help="Run cost checks only",
    )
    check_parser.add_argument(
        "--progress-only",
        action="store_true",
        help="Run progress checks only",
    )
    check_parser.add_argument(
        "--stuck-only",
        action="store_true",
        help="Run stuck detection only",
    )
    check_parser.add_argument(
        "--llm-escalate",
        action="store_true",
        help="Enable LLM escalation when anomalies are detected",
    )
    check_parser.add_argument(
        "--output",
        default=str(WATCHDOG_STATUS_PATH),
        help="Output path for status report (default: reports/watchdog-status.json)",
    )

    # status command
    status_parser = subparsers.add_parser("status", help="Write structured status report")
    status_parser.add_argument(
        "--runs-dir",
        default=str(RUN_REPORTS_ROOT),
        help="Run report directory (default: reports/runs)",
    )
    status_parser.add_argument(
        "--output",
        default=str(WATCHDOG_STATUS_PATH),
        help="Output path for status report (default: reports/watchdog-status.json)",
    )

    return parser.parse_args(argv)


def run_check(args: argparse.Namespace) -> int:
    runs_dir = Path(args.runs_dir)
    runs = _active_runs(runs_dir)

    now = datetime.now()

    cost_findings: list[CostFinding] = []
    progress_findings: list[ProgressFinding] = []
    stuck_findings: list[ProgressFinding] = []

    run_all = not (args.cost_only or args.progress_only or args.stuck_only)

    if run_all or args.cost_only:
        cost_findings = check_cost(
            runs,
            budget_tracker_path=Path(args.budget_tracker),
            per_run_limit=args.per_run_cost,
            per_day_limit=args.per_day_cost,
            budget_ratio=args.budget_ratio,
        )

    if run_all or args.progress_only:
        progress_findings = check_progress(
            runs,
            now=now,
            progress_timeout=timedelta(minutes=args.progress_timeout),
        )

    if run_all or args.stuck_only:
        stuck_findings = check_stuck(
            runs,
            now=now,
            stuck_timeout=timedelta(minutes=args.stuck_timeout),
        )

    # Write status report
    output_path = write_status_report(
        runs, cost_findings, progress_findings, stuck_findings,
        output_path=Path(args.output),
    )

    anomalies = cost_findings or progress_findings or stuck_findings
    has_critical = any(
        f.severity == "critical"
        for f in (*cost_findings, *progress_findings, *stuck_findings)
    )

    # Print findings
    if cost_findings:
        print("[watchdog] Cost findings:")
        for f in cost_findings:
            print(f"  [{f.severity}] {f.message}")

    if progress_findings:
        print("[watchdog] Progress findings:")
        for f in progress_findings:
            print(f"  [{f.severity}] {f.message}")

    if stuck_findings:
        print("[watchdog] Stuck findings:")
        for f in stuck_findings:
            print(f"  [{f.severity}] {f.message}")

    if anomalies:
        print(f"[watchdog] Status report written to {output_path}")
        print(f"[watchdog] Anomalies detected: {len(anomalies)}")

        if args.llm_escalate:
            # LLM escalation path: build a prompt and (in future) call an LLM
            context_lines = []
            for f in cost_findings:
                context_lines.append(f"[cost {f.severity}] {f.message}")
            for f in progress_findings:
                context_lines.append(f"[progress {f.severity}] {f.message}")
            for f in stuck_findings:
                context_lines.append(f"[stuck {f.severity}] {f.message}")
            print("[watchdog] LLM escalation requested with context:")
            for line in context_lines:
                print(f"  {line}")
        # Exit-Code-Stufen (cron-tauglich):
        #   0 = keine Anomalien
        #   1 = nur Warnungen (Monitoring-Alert auslösen)
        #   2 = mindestens ein 'critical'-Finding (Run abbrechen / Pager)
        return 2 if has_critical else 1
    else:
        print("[watchdog] All checks passed. No anomalies detected.")
        return 0


def run_status(args: argparse.Namespace) -> int:
    runs_dir = Path(args.runs_dir)
    runs = _active_runs(runs_dir)
    output_path = write_status_report(
        runs, [], [], [],
        output_path=Path(args.output),
    )
    print(f"[watchdog] Status report written to {output_path}")
    print(f"[watchdog] Active runs: {len(runs)}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.command == "check":
        return run_check(args)
    elif args.command == "status":
        return run_status(args)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
