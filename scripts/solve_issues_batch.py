#!/usr/bin/env python3
"""
solve_issues_batch.py — mehrere Issues parallel mit begrenzter Worker-Zahl lösen.

Der Batch-Runner startet pro Issue einen eigenen solve_issues.py-Prozess. Dadurch
bleiben Arbeitsverzeichnisse, Branch-Recovery und Worker-Logs voneinander
getrennt; die Ausgabe wird pro Job gesammelt und erst nach Job-Ende gedruckt.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, replace
from datetime import datetime
import heapq
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time

sys.path.insert(0, str(Path(__file__).parent))
from solve_issues import (  # noqa: E402
    GitHubClient,
    MODEL_CONFIGS,
    RUN_REPORTS_ROOT,
    detect_codex_rate_limit,
    format_worker_output_tail,
    requests,
    safe_run_repo_name,
    should_surface_worker_line,
)
from solver_reporting import (  # noqa: E402
    format_heartbeat,
)
from solver_commands import (  # noqa: E402
    add_budget_flags,
    add_solver_core_flags,
)
from workers.opencode_diagnostics import (  # noqa: E402
    check_opencode_state_guard,
    find_opencode_executable,
)
from utils import (  # noqa: E402
    is_placeholder_value,
    load_env,
    print_banner,
    print_err,
    print_step,
    print_warn,
    require_config_value,
)


DEFAULT_WORKERS = 2
DEFAULT_WORKER_HEALTH_TIMEOUT_MINUTES = 60
SUPPORTED_MODEL_HELP = ", ".join(MODEL_CONFIGS.keys())


@dataclass(frozen=True)
class IssueJob:
    repo: str
    issue_number: int

    @property
    def label(self) -> str:
        return f"{self.repo}#{self.issue_number}"


@dataclass(frozen=True)
class IssueJobResult:
    job: IssueJob
    returncode: int
    output: str
    duration_seconds: float
    rate_limited: bool = False
    delayed_until: datetime | None = None
    delayed_reset_text: str | None = None
    unhealthy: bool = False
    unhealthy_reason: str | None = None
    requested_model: str | None = None
    actual_model: str | None = None
    fallback_from: str | None = None

    @property
    def ok(self) -> bool:
        # Check if the run resulted in no changes
        no_changes = "no_changes" in self.output.lower() or "nonzero_without_changes" in self.output.lower()
        return self.returncode == 0 and not self.delayed and not self.unhealthy and not no_changes

    @property
    def delayed(self) -> bool:
        return self.rate_limited


def get_result_priority(result: IssueJobResult) -> int:
    """
    Prioritaets-Funktion fuer die Sortierung von Job-Ergebnissen in Summaries.
    
    Rueckgabewert:
        0 = hohe Prioritaet (erfolgreich, clean, exit_code = 0)
        1 = mittlere Prioritaet (Rate-Limit verzögert oder warnings)
        2 = niedrige Prioritaet (fehlgeschlagen, unhealthy oder exit_code != 0)
    
    Sortierreihenfolge: clean runs zuerst, dann delayed/warnings, dann failed.
    """
    if result.ok:
        return 0  # Erfolgreich: exit_code 0, kein delay, nicht unhealthy
    if result.delayed or result.returncode == 0:
        return 1  # Verzögert oder exit_code 0 aber mit Warnings (z.B. turn-limit)
    return 2  # Fehlerhaft: exit_code != 0 oder unhealthy


def get_result_badge(result: IssueJobResult) -> str:
    """
    Erzeugt ein Status-Badge fuer ein Job-Ergebnis.
    
    Badges:
        [OK]         - Erfolgreich (exit_code = 0, kein delay, nicht unhealthy)
        [DELAYED]    - Rate-Limit verzögert
        [WARNING]    - Exit code 0 aber mit Potenzialen Problemen (z.B. turn-limit)
        [FAIL]       - Fehlerhaft (exit_code != 0)
        [UNHEALTHY]  - Worker unhealthy
        [FALLBACK]   - Fallback wurde verwendet
    """
    if result.fallback_from:
        return "[FALLBACK]"
    if result.unhealthy:
        return "[UNHEALTHY]"
    if result.delayed:
        return "[DELAYED]"
    if result.returncode == 0:
        # Pruefe ob es Warnungen wie turn-limit oder no_changes in der Ausgabe gibt
        output_lower = result.output.lower()
        if "turn limit" in output_lower or "turn-limit" in output_lower or "no_changes" in output_lower or "nonzero_without_changes" in output_lower:
            return "[WARNING]"
        return "[OK]"
    # Check for special cases that should be warnings even with non-zero return code
    if "nonzero_without_changes" in result.output.lower():
        return "[WARNING]"
    return "[FAIL]"
    return "[FAIL]"


@dataclass(frozen=True)
class QueuedRunReport:
    job: IssueJob
    path: Path
    model: str
    base_branch: str
    queued_at: datetime


def positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("muss mindestens 1 sein")
    return parsed


def dedupe_issue_jobs(jobs: list[IssueJob]) -> list[IssueJob]:
    """Verhindert doppelte Branch-/Worker-Starts innerhalb desselben Batch-Laufs."""
    deduped = []
    seen = set()
    for job in jobs:
        key = (job.repo, job.issue_number)
        if key in seen:
            continue
        deduped.append(job)
        seen.add(key)
    return deduped


def discover_issue_jobs(client: GitHubClient, repos: list[str],
                        issue_numbers: list[int] | None,
                        label: str) -> list[IssueJob]:
    jobs = []
    for repo in repos:
        if issue_numbers:
            for issue_number in issue_numbers:
                issue = client.get_single_issue(repo, issue_number)
                if issue and "pull_request" not in issue:
                    jobs.append(IssueJob(repo, issue_number))
            continue

        for issue in client.get_open_issues(repo, label=label):
            if "pull_request" in issue:
                continue
            jobs.append(IssueJob(repo, int(issue["number"])))

    return dedupe_issue_jobs(jobs)


def build_worker_command(args: argparse.Namespace, job: IssueJob,
                         solve_script: Path,
                         run_report_dir: Path | None = None,
                         model: str | None = None,
                         model_name: str | None = None) -> list[str]:
    selected_model = model or args.model
    selected_model_name = args.model_name if model_name is None else model_name
    cmd = [sys.executable, str(solve_script)]
    add_solver_core_flags(
        cmd, args,
        model=selected_model,
        model_name=selected_model_name,
        verbosity=getattr(args, "verbosity", "quiet"),
    )
    cmd.extend(["--repo", job.repo, "--issue", str(job.issue_number)])

    if selected_model == "codex":
        cmd.append("--defer-codex-rate-limit")
    if run_report_dir:
        cmd.extend(["--run-report-dir", str(run_report_dir)])
    if selected_model == "opencode" and getattr(args, "allow_opencode_state_conflict", False):
        cmd.append("--allow-opencode-state-conflict")
    add_budget_flags(cmd, args)
    return cmd


def create_queued_run_report(job: IssueJob, model: str,
                             base_branch: str | None = None,
                             now_fn=datetime.now,
                             reports_root: Path = RUN_REPORTS_ROOT) -> QueuedRunReport | None:
    queued_at = now_fn()
    run_name = f"{queued_at.strftime('%Y%m%d-%H%M%S-%f')}-{safe_run_repo_name(job.repo)}-issue-{job.issue_number}"
    run_dir = reports_root / run_name
    suffix = 2
    while run_dir.exists():
        run_dir = reports_root / f"{run_name}-{suffix}"
        suffix += 1
    base_value = base_branch or ""
    try:
        run_dir.mkdir(parents=True, exist_ok=False)
        metadata = {
            "status": "queued",
            "selected_repo": job.repo,
            "repo": job.repo,
            "issue_number": job.issue_number,
            "issue": job.issue_number,
            "branch": "",
            "base_branch": base_value,
            "model": model,
            "worker_exit_code": "",
            "pr_url": "",
            "queued_at": queued_at.isoformat(timespec="seconds"),
            "note": "Batch-Job wartet auf einen freien Worker-Slot.",
            "preserved_worktree": "",
        }
        (run_dir / "metadata.json").write_text(
            json.dumps(metadata, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        summary_lines = [
            "status: queued",
            f"selected_repo: {job.repo}",
            f"repo: {job.repo}",
            f"issue_number: {job.issue_number}",
            f"issue: {job.issue_number}",
            "branch: ",
            f"base_branch: {base_value}",
            f"model: {model}",
            "worker_exit_code: ",
            "pr_url: ",
            f"queued_at: {queued_at.isoformat(timespec='seconds')}",
            "preserved_worktree: ",
            "",
            "note: Batch-Job wartet auf einen freien Worker-Slot.",
        ]
        (run_dir / "summary.txt").write_text(
            "\n".join(summary_lines) + "\n",
            encoding="utf-8",
        )
    except OSError as exc:
        print_warn(f"Queue-Report konnte nicht angelegt werden: {exc}")
        return None
    return QueuedRunReport(job, run_dir, model, base_value, queued_at)


def queued_report_status(report: QueuedRunReport) -> str:
    summary_path = report.path / "summary.txt"
    if not summary_path.exists():
        return ""
    for line in summary_path.read_text(encoding="utf-8").splitlines():
        key, separator, value = line.partition(":")
        if separator and key.strip() == "status":
            return value.strip()
    return ""


def _determine_report_status(result: IssueJobResult) -> str:
    """Ermittelt den Status für den Report basierend auf dem Ergebnis."""
    return "rate_limit_deferred" if result.delayed else "worker_finished"


def _build_metadata_for_finished_job(
    report: QueuedRunReport,
    result: IssueJobResult,
    status: str,
) -> dict:
    """Erstellt die Metadata für einen abgeschlossenen Job."""
    return {
        "status": status,
        "selected_repo": report.job.repo,
        "repo": report.job.repo,
        "issue_number": report.job.issue_number,
        "issue": report.job.issue_number,
        "branch": "",
        "base_branch": report.base_branch,
        "model": report.model,
        "worker_exit_code": str(result.returncode),
        "pr_url": "",
        "queued_at": report.queued_at.isoformat(timespec="seconds"),
        "note": "Worker endete, bevor solve_issues.py einen normalen Run-Report geschrieben hat.",
        "preserved_worktree": "",
    }


def _build_summary_lines_for_finished_job(
    report: QueuedRunReport,
    result: IssueJobResult,
    status: str,
    output_tail: str | None = None,
) -> list[str]:
    """Erstellt die Zusammenfassungszeilen für einen abgeschlossenen Job."""
    lines = [
        f"status: {status}",
        f"selected_repo: {report.job.repo}",
        f"repo: {report.job.repo}",
        f"issue_number: {report.job.issue_number}",
        f"issue: {report.job.issue_number}",
        "branch: ",
        f"base_branch: {report.base_branch}",
        f"model: {report.model}",
        f"worker_exit_code: {result.returncode}",
        "pr_url: ",
        f"queued_at: {report.queued_at.isoformat(timespec='seconds')}",
        "preserved_worktree: ",
        "",
        "note: Worker endete, bevor solve_issues.py einen normalen Run-Report geschrieben hat.",
    ]
    if output_tail:
        lines.extend(["", "output_tail:", output_tail])
    return lines


def _write_report_files(
    report_path: Path,
    result: IssueJobResult,
    metadata: dict,
    summary_lines: list[str],
) -> bool:
    """Schreibt die Report-Dateien und gibt Erfolg zurück."""
    try:
        if result.output:
            (report_path / "worker-output.log").write_text(result.output, encoding="utf-8")

        output_tail = format_worker_output_tail(result.output)
        if output_tail:
            (report_path / "output-tail.log").write_text(output_tail + "\n", encoding="utf-8")

        (report_path / "metadata.json").write_text(
            json.dumps(metadata, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        (report_path / "summary.txt").write_text(
            "\n".join(summary_lines) + "\n",
            encoding="utf-8",
        )
        return True
    except OSError as exc:
        print_warn(f"Queue-Report konnte nicht finalisiert werden: {exc}")
        return False


def finalize_unclaimed_queued_report(report: QueuedRunReport,
                                     result: IssueJobResult) -> Path | None:
    """Finalisiert einen Queue-Report, der nicht vom Worker beansprucht wurde."""
    if queued_report_status(report) != "queued":
        return None

    status = _determine_report_status(result)
    metadata = _build_metadata_for_finished_job(report, result, status)
    output_tail = format_worker_output_tail(result.output)
    summary_lines = _build_summary_lines_for_finished_job(
        report, result, status, output_tail
    )

    if _write_report_files(report.path, result, metadata, summary_lines):
        return report.path
    return None


def annotate_fallback_run_report(run_dir: Path, requested_model: str, actual_model: str) -> None:
    note = f"Fallback verwendet: {requested_model} -> {actual_model}"
    summary_path = run_dir / "summary.txt"
    metadata_path = run_dir / "metadata.json"
    try:
        if metadata_path.exists():
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            metadata["requested_model"] = requested_model
            metadata["actual_model"] = actual_model
            metadata["fallback_from"] = requested_model
            existing_note = str(metadata.get("note") or "")
            metadata["note"] = f"{existing_note} {note}".strip()
            metadata_path.write_text(
                json.dumps(metadata, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
        if summary_path.exists():
            summary = summary_path.read_text(encoding="utf-8")
            additions = [
                f"requested_model: {requested_model}",
                f"actual_model: {actual_model}",
                f"fallback_from: {requested_model}",
                f"note: {note}",
            ]
            for line in additions:
                if line not in summary:
                    summary += line + "\n"
            summary_path.write_text(summary, encoding="utf-8")
    except (OSError, json.JSONDecodeError) as exc:
        print_warn(f"Fallback-Info konnte nicht im Run-Report vermerkt werden: {exc}")


def resolve_batch_base_branches(client: GitHubClient, repos: list[str],
                                requested_base: str | None) -> dict[str, str]:
    base_branches: dict[str, str] = {}
    for repo in repos:
        base_branch = client.resolve_base_branch(repo, requested_base)
        if base_branch:
            base_branches[repo] = base_branch
    return base_branches


def run_issue_job(job: IssueJob, cmd: list[str], project_root: Path,
                  env: dict[str, str],
                  health_timeout_seconds: float | None = None,
                  unhealthy_action: str = "warn",
                  detect_rate_limit_fn=detect_codex_rate_limit,
                  now_fn=datetime.now,
                  heartbeat_interval_seconds: float | None = None,
                  heartbeat_job_label: str | None = None) -> IssueJobResult:
    started_at = time.monotonic()
    try:
        process = subprocess.Popen(
            cmd,
            cwd=project_root,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
    except OSError as exc:
        output = f"Worker konnte nicht gestartet werden: {exc}\n"
        return IssueJobResult(
            job=job,
            returncode=127,
            output=output,
            duration_seconds=time.monotonic() - started_at,
            unhealthy=True,
            unhealthy_reason="Worker-Prozess konnte nicht gestartet werden",
        )

    output_parts: list[str] = []
    line_queue: queue.Queue[str | None] = queue.Queue()
    last_activity = time.monotonic()
    unhealthy_reason = None
    unhealthy_seen = False
    last_heartbeat_at = started_at

    def read_output() -> None:
        try:
            assert process.stdout is not None
            for line in process.stdout:
                line_queue.put(line)
        finally:
            line_queue.put(None)

    reader = threading.Thread(target=read_output, daemon=True)
    reader.start()

    while True:
        try:
            line = line_queue.get(timeout=0.2)
        except queue.Empty:
            line = ""

        if line is None:
            break
        if line:
            output_parts.append(line)
            if should_surface_worker_line(line):
                last_activity = time.monotonic()

        if process.poll() is not None and line_queue.empty():
            break

        if (
            health_timeout_seconds
            and health_timeout_seconds > 0
            and not unhealthy_seen
            and time.monotonic() - last_activity > health_timeout_seconds
            and not worker_is_known_waiting("".join(output_parts), detect_rate_limit_fn, now_fn)
        ):
            unhealthy_seen = True
            unhealthy_reason = (
                f"keine Worker-Ausgabe seit {health_timeout_seconds:.0f}s"
            )
            output_parts.append(f"\n[batch-health] Unhealthy: {unhealthy_reason}\n")
            if unhealthy_action in {"stop", "retry"}:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
                break

        if heartbeat_interval_seconds and heartbeat_interval_seconds > 0:
            elapsed = time.monotonic() - last_heartbeat_at
            if elapsed >= heartbeat_interval_seconds:
                heartbeat_line = format_heartbeat(
                    job.issue_number,
                    time.monotonic() - started_at,
                    job_label=heartbeat_job_label,
                )
                print(heartbeat_line)
                last_heartbeat_at = time.monotonic()

    if process.stdout:
        process.stdout.close()
    reader.join(timeout=1)
    returncode = process.wait()
    output = "".join(output_parts)
    if unhealthy_seen and unhealthy_action == "warn":
        unhealthy_reason = None

    return IssueJobResult(
        job=job,
        returncode=returncode,
        output=output,
        duration_seconds=time.monotonic() - started_at,
        unhealthy=unhealthy_seen and unhealthy_action in {"stop", "retry"},
        unhealthy_reason=unhealthy_reason,
    )


def _is_successful_result(result: IssueJobResult) -> bool:
    """Prueft, ob ein Ergebnis erfolgreich war (kein Fehler, nicht verzögert, nicht unhealthy)."""
    return result.returncode == 0


def _has_fallback_already(result: IssueJobResult) -> bool:
    """Prueft, ob bereits ein Fallback versucht wurde."""
    return result.fallback_from is not None


def mark_rate_limited_result(result: IssueJobResult, detect_rate_limit_fn) -> IssueJobResult:
    """Markiert ein Ergebnis als rate-limitiert, falls die Ausgabe ein Rate-Limit anzeigt."""
    if _is_successful_result(result) or _has_fallback_already(result):
        return result

    rate_limit = detect_rate_limit_fn(result.output)
    if not rate_limit:
        return result
    return replace(
        result,
        rate_limited=True,
        delayed_until=rate_limit.reset_at,
        delayed_reset_text=rate_limit.reset_text,
    )


def worker_is_known_waiting(output: str, detect_rate_limit_fn, now_fn=datetime.now) -> bool:
    """Prueft, ob der Worker auf ein Rate-Limit wartet."""
    rate_limit = detect_rate_limit_fn(output)
    return bool(rate_limit and rate_limit.reset_at and rate_limit.reset_at > now_fn())


def _should_run_fallback(
    args: argparse.Namespace,
    primary_result: IssueJobResult,
    detect_rate_limit_fn,
) -> bool:
    """Prueft, ob ein Fallback-Lauf notwendig ist."""
    if not args.fallback_model:
        return False
    if primary_result.returncode == 0:
        return False
    rate_limit = detect_rate_limit_fn(primary_result.output)
    return rate_limit is not None


def _build_fallback_command(
    args: argparse.Namespace,
    job: IssueJob,
    solve_script: Path,
    queued_report: QueuedRunReport | None,
) -> list[str]:
    """Erstellt den Befehl für den Fallback-Lauf."""
    return build_worker_command(
        args,
        job,
        solve_script,
        run_report_dir=queued_report.path if queued_report else None,
        model=args.fallback_model,
        model_name=args.fallback_model_name or "",
    )


def _build_primary_command(
    args: argparse.Namespace,
    job: IssueJob,
    solve_script: Path,
    queued_report: QueuedRunReport | None,
) -> list[str]:
    """Erstellt den Befehl für den primären Lauf."""
    return build_worker_command(
        args,
        job,
        solve_script,
        run_report_dir=queued_report.path if queued_report else None,
    )


def _combine_fallback_output(
    primary_result: IssueJobResult,
    fallback_result: IssueJobResult,
    fallback_model: str,
) -> str:
    """Kombiniert die Ausgabe von primärem und Fallback-Lauf."""
    return (
        primary_result.output.rstrip()
        + "\n\n[batch-fallback] Codex-Rate-Limit erkannt; "
        + f"Fallback mit {fallback_model} gestartet.\n"
        + fallback_result.output
    )


def run_issue_job_with_optional_fallback(
    job: IssueJob,
    args: argparse.Namespace,
    solve_script: Path,
    project_root: Path,
    env: dict[str, str],
    queued_report: QueuedRunReport | None,
    *,
    health_timeout_seconds: float | None,
    unhealthy_action: str,
    detect_rate_limit_fn,
    run_issue_job_fn=run_issue_job,
    heartbeat_interval_seconds: float | None = None,
    heartbeat_job_label: str | None = None,
) -> IssueJobResult:
    """Fuehrt einen Issue-Job aus und startet bei Rate-Limit optional einen Fallback."""
    primary_cmd = _build_primary_command(args, job, solve_script, queued_report)
    primary_result = run_issue_job_fn(
        job,
        primary_cmd,
        project_root,
        env,
        health_timeout_seconds=health_timeout_seconds,
        unhealthy_action=unhealthy_action,
        detect_rate_limit_fn=detect_rate_limit_fn,
        heartbeat_interval_seconds=heartbeat_interval_seconds,
        heartbeat_job_label=heartbeat_job_label,
    )
    primary_result = replace(
        primary_result,
        requested_model=args.model,
        actual_model=args.model,
    )

    if not _should_run_fallback(args, primary_result, detect_rate_limit_fn):
        return primary_result

    fallback_cmd = _build_fallback_command(args, job, solve_script, queued_report)
    fallback_result = run_issue_job_fn(
        job,
        fallback_cmd,
        project_root,
        env,
        health_timeout_seconds=health_timeout_seconds,
        unhealthy_action=unhealthy_action,
        detect_rate_limit_fn=lambda output: None,
        heartbeat_interval_seconds=heartbeat_interval_seconds,
        heartbeat_job_label=heartbeat_job_label,
    )
    combined_output = _combine_fallback_output(
        primary_result, fallback_result, args.fallback_model
    )
    if queued_report:
        annotate_fallback_run_report(
            queued_report.path, args.model, f"{args.fallback_model}/{args.fallback_model_name}" if args.fallback_model_name else args.fallback_model
        )
    return replace(
        fallback_result,
        output=combined_output,
        duration_seconds=primary_result.duration_seconds + fallback_result.duration_seconds,
        requested_model=args.model,
        actual_model=args.fallback_model,
        fallback_from=args.model,
    )


def _can_requeue_rate_limited(
    result: IssueJobResult,
    requeue_delayed: bool,
    attempts: dict[IssueJob, int],
    job: IssueJob,
    max_rate_limit_requeues: int,
) -> bool:
    """Prueft, ob ein rate-limitierter Job erneut eingereiht werden soll."""
    return (
        result.delayed
        and requeue_delayed
        and result.delayed_until is not None
        and attempts.get(job, 0) <= max_rate_limit_requeues
    )


def _can_requeue_unhealthy(
    result: IssueJobResult,
    requeue_unhealthy: bool,
    attempts: dict[IssueJob, int],
    job: IssueJob,
    max_unhealthy_requeues: int,
) -> bool:
    """Prueft, ob ein unhealthy Job erneut eingereiht werden soll."""
    return (
        result.unhealthy
        and requeue_unhealthy
        and attempts.get(job, 0) <= max_unhealthy_requeues
    )


def _handle_completed_job(
    result: IssueJobResult,
    job: IssueJob,
    requeue_delayed: bool,
    requeue_unhealthy: bool,
    max_rate_limit_requeues: int,
    max_unhealthy_requeues: int,
    attempts: dict[IssueJob, int],
    delayed_jobs: list[tuple[datetime, int, IssueJob]],
    sequence: int,
    on_delay,
    on_result,
    results: list[IssueJobResult],
    total_jobs: int,
    pending: list[IssueJob],
) -> tuple[int, list[IssueJobResult], list[tuple[datetime, int, IssueJob]], list[IssueJob]]:
    """Behandelt das Ergebnis eines abgeschlossenen Jobs und gibt den neuen Zustand zurueck.

    Return: (neuer_sequence, results, delayed_jobs, pending)
    """
    if _can_requeue_rate_limited(
        result, requeue_delayed, attempts, job, max_rate_limit_requeues
    ):
        sequence += 1
        heapq.heappush(delayed_jobs, (result.delayed_until, sequence, job))
        if on_delay:
            on_delay(result)
    elif _can_requeue_unhealthy(
        result, requeue_unhealthy, attempts, job, max_unhealthy_requeues
    ):
        # Job wird neu gestartet, Ergebnis wird nicht gespeichert
        pending.append(job)
        if on_delay:
            on_delay(result)
    else:
        results.append(result)
        if on_result:
            on_result(result, len(results), total_jobs)

    return sequence, results, delayed_jobs, pending


def run_issue_jobs(jobs: list[IssueJob],
                   workers: int,
                   run_job_fn,
                   *,
                   requeue_delayed: bool = False,
                   max_rate_limit_requeues: int = 1,
                   detect_rate_limit_fn=detect_codex_rate_limit,
                   sleep_fn=time.sleep,
                   now_fn=datetime.now,
                   requeue_unhealthy: bool = False,
                   max_unhealthy_requeues: int = 1,
                   on_result=None,
                   on_delay=None) -> list[IssueJobResult]:
    results: list[IssueJobResult] = []
    pending = list(jobs)
    delayed_jobs: list[tuple[datetime, int, IssueJob]] = []
    attempts = {job: 0 for job in jobs}
    sequence = 0

    with ThreadPoolExecutor(max_workers=workers) as executor:
        future_to_job = {}

        def promote_ready_delayed_jobs() -> None:
            """Foerdert Jobs, deren Wartezeit abgelaufen ist, zurueck in die pending-Liste."""
            now = now_fn()
            while delayed_jobs and delayed_jobs[0][0] <= now:
                _, _, ready_job = heapq.heappop(delayed_jobs)
                pending.append(ready_job)

        def submit_ready_jobs() -> None:
            """Reicht bereitstehende Jobs an den ThreadPool ein."""
            promote_ready_delayed_jobs()
            while pending and len(future_to_job) < workers:
                job = pending.pop(0)
                attempts[job] += 1
                future_to_job[executor.submit(run_job_fn, job)] = job

        submit_ready_jobs()
        while future_to_job or pending or delayed_jobs:
            if not future_to_job:
                # Alle Worker sind frei, aber es gibt verzögerte Jobs
                delayed_until, _, delayed_job = heapq.heappop(delayed_jobs)
                wait_seconds = max(0.0, (delayed_until - now_fn()).total_seconds())
                if wait_seconds > 0:
                    sleep_fn(wait_seconds)
                pending.append(delayed_job)
                submit_ready_jobs()
                continue

            for future in as_completed(list(future_to_job), timeout=None):
                job = future_to_job.pop(future)
                try:
                    result = future.result()
                except Exception as exc:  # pragma: no cover - defensiver Schutz fuer Batch-Laeufe
                    result = IssueJobResult(
                        job=job,
                        returncode=1,
                        output=f"Unerwarteter Worker-Fehler: {exc}\n",
                        duration_seconds=0.0,
                    )

                result = mark_rate_limited_result(result, detect_rate_limit_fn)

                sequence, results, delayed_jobs, pending = _handle_completed_job(
                    result,
                    job,
                    requeue_delayed,
                    requeue_unhealthy,
                    max_rate_limit_requeues,
                    max_unhealthy_requeues,
                    attempts,
                    delayed_jobs,
                    sequence,
                    on_delay,
                    on_result,
                    results,
                    len(jobs),
                    pending,
                )

                submit_ready_jobs()
                break
    return results


def _get_result_status_label(result: IssueJobResult) -> str:
    """Ermittelt das Status-Label für ein Ergebnis."""
    if result.unhealthy:
        return "UNHEALTHY"
    if result.delayed:
        return "VERZÖGERT"
    if result.ok:
        return "OK"
    return "FEHLER"


def _format_reset_time(result: IssueJobResult) -> str:
    """Formatiert die Reset-Zeit für die Anzeige."""
    if result.delayed_until:
        return result.delayed_until.strftime("%Y-%m-%d %H:%M")
    return result.delayed_reset_text or "zum naechsten Reset"


def _print_result_header(result: IssueJobResult, completed: int, total: int) -> None:
    """Druckt den Header für ein Job-Ergebnis."""
    badge = get_result_badge(result)
    status = _get_result_status_label(result)
    print("\n" + "─" * 60)
    print(
        f"[{completed}/{total}] {result.job.label} {badge} — {status} "
        f"({result.duration_seconds:.1f}s, Exit {result.returncode})"
    )


def _print_result_details(result: IssueJobResult) -> None:
    """Druckt die Details eines Job-Ergebnisses."""
    if result.delayed:
        reset = _format_reset_time(result)
        print(
            "Codex-Rate-Limit erkannt; "
            f"Job bleibt bis {reset} verzögert."
        )
    if result.fallback_from:
        print(f"Fallback verwendet: {result.fallback_from} -> {result.actual_model}")
    if result.unhealthy:
        print(f"Worker-Health: {result.unhealthy_reason or 'unhealthy'}")


def _print_result_output(result: IssueJobResult) -> None:
    """Druckt die Ausgabe eines Job-Ergebnisses."""
    print("─" * 60)
    if result.output.strip():
        print(result.output.rstrip())
    else:
        print("(keine Worker-Ausgabe)")


def print_job_result(result: IssueJobResult, completed: int, total: int) -> None:
    """Druckt das Ergebnis eines Jobs."""
    _print_result_header(result, completed, total)
    _print_result_details(result)
    _print_result_output(result)


def print_job_delay(result: IssueJobResult) -> None:
    """Druckt eine Meldung für verzögerte oder unhealthy Jobs."""
    if result.unhealthy:
        print_warn(
            f"{result.job.label}: Worker unhealthy; "
            f"Requeue ({result.unhealthy_reason or 'keine Details'})."
        )
        return
    reset = _format_reset_time(result)
    print_warn(
        f"{result.job.label}: Codex-Rate-Limit erkannt; "
        f"Requeue nach {reset}."
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="GitHub Issues parallel mit begrenzter Worker-Zahl lösen"
    )
    parser.add_argument(
        "--model", required=True, choices=list(MODEL_CONFIGS.keys()),
        help=f"KI-Modell / Provider: {SUPPORTED_MODEL_HELP}",
    )
    parser.add_argument(
        "--model-name",
        help=(
            "Spezifisches Modell (für Codex optional, für Mistral z.B. "
            "'magistral-small-2509', für Ollama z.B. 'deepseek-coder:6.7b')"
        ),
    )
    parser.add_argument(
        "--fallback-model",
        choices=list(MODEL_CONFIGS.keys()),
        help="Optionaler Fallback-Provider fuer erkannte Codex-Rate-Limits",
    )
    parser.add_argument(
        "--fallback-model-name",
        help="Optionaler Modellname fuer --fallback-model",
    )
    parser.add_argument("--repo", help="Nur dieses Repo bearbeiten")
    parser.add_argument(
        "--issue",
        type=int,
        action="append",
        help="Nur diese Issue-Nummer lösen; kann mehrfach angegeben werden",
    )
    parser.add_argument("--dry-run", action="store_true", help="Nur anzeigen, nichts ändern")
    parser.add_argument("--label", default="ai-generated", help="Welche Issues holen (Label)")
    parser.add_argument(
        "--base-branch",
        help="Zielbranch für Klon und PR; ohne Angabe nutzt solve_issues.py den Default-Branch",
    )
    parser.add_argument(
        "--close-issues",
        action="store_true",
        help="Issues nach PR-Erstellung direkt schließen",
    )
    parser.add_argument(
        "--workers",
        type=positive_int,
        default=DEFAULT_WORKERS,
        help=f"Maximale parallele Worker, Standard: {DEFAULT_WORKERS}",
    )
    parser.add_argument(
        "--requeue-rate-limited",
        action="store_true",
        help="Codex-Jobs nach erkannter Reset-Zeit erneut einplanen statt nur als verzögert zu melden",
    )
    parser.add_argument(
        "--rate-limit-retries",
        type=positive_int,
        default=1,
        help="Maximale Requeue-Versuche pro rate-limitiertem Codex-Job, Standard: 1",
    )
    parser.add_argument(
        "--worker-health-timeout-minutes",
        type=positive_int,
        default=DEFAULT_WORKER_HEALTH_TIMEOUT_MINUTES,
        help=(
            "Minuten ohne Worker-Ausgabe bis zur Health-Warnung, "
            f"Standard: {DEFAULT_WORKER_HEALTH_TIMEOUT_MINUTES}"
        ),
    )
    parser.add_argument(
        "--unhealthy-action",
        choices=("warn", "stop", "retry"),
        default="warn",
        help="Aktion bei unhealthy Worker: warn, stop oder retry; Standard: warn",
    )
    parser.add_argument(
        "--unhealthy-retries",
        type=positive_int,
        default=1,
        help="Maximale Retry-Versuche fuer unhealthy Jobs bei --unhealthy-action retry, Standard: 1",
    )
    parser.add_argument(
        "--verbosity",
        choices=("quiet", "normal", "verbose"),
        default="quiet",
        help="Worker-Ausgabe: quiet=keine Live-Ausgabe (Standard), normal=gefiltert, verbose=alles",
    )
    parser.add_argument(
        "--allow-opencode-state-conflict",
        action="store_true",
        help=(
            "OpenCode trotz laufendem Versions-/State-Mix starten und an Worker weiterreichen. "
            "Nur bewusst verwenden; Standard ist blockieren."
        ),
    )
    parser.add_argument(
        "--heartbeat-interval",
        type=int,
        default=None,
        help="Heartbeat-Ausgabeintervall in Sekunden (z.B. 60 fuer 1-Minuten-Heartbeat). "
        "Ohne Angabe kein Heartbeat.",
    )
    # OpenCode Budget-Limits (nur fuer --model opencode)
    parser.add_argument(
        "--max-run-cost-usd",
        type=float,
        default=None,
        help="Maximale Kosten in USD fuer einen einzelnen OpenCode-Run",
    )
    parser.add_argument(
        "--max-run-input-tokens",
        type=int,
        default=None,
        help="Maximale Input-Tokens fuer einen einzelnen OpenCode-Run",
    )
    parser.add_argument(
        "--max-run-output-tokens",
        type=int,
        default=None,
        help="Maximale Output-Tokens fuer einen einzelnen OpenCode-Run",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    print_banner("ISSUES PARALLEL MIT KI LÖSEN")
    args = parse_args(argv)

    if args.fallback_model and args.model != "codex":
        print_err("--fallback-model ist nur fuer --model codex erlaubt")
        return 1
    if args.fallback_model == "codex":
        print_err("--fallback-model darf nicht erneut codex sein")
        return 1
    if args.fallback_model_name and not args.fallback_model:
        print_err("--fallback-model-name braucht auch --fallback-model")
        return 1

    if requests is None:
        print_err("Python-Abhängigkeit fehlt: requests")
        print("   → Installieren mit: pip install -r requirements.txt")
        return 1

    cfg = load_env()
    token = require_config_value(cfg, "GITHUB_TOKEN", "GitHub Token")
    user = require_config_value(cfg, "GITHUB_USER", "GitHub User")

    if args.model == "opencode" and not args.dry_run:
        opencode_exe = find_opencode_executable()
        if not opencode_exe:
            print_err("OpenCode CLI wurde nicht gefunden!")
            print("   → Installieren: https://opencode.ai/docs/installation")
            print("   → Danach `opencode` im PATH verfügbar machen")
            return 1
        if not check_opencode_state_guard(
            opencode_exe,
            allow_conflict=args.allow_opencode_state_conflict,
        ):
            return 1

    model_config = MODEL_CONFIGS[args.model]
    env_key = model_config.get("env_key")
    if env_key and args.dry_run and is_placeholder_value(cfg.get(env_key)):
        print_warn(f"{env_key} fehlt oder ist noch ein Platzhalter")
    elif env_key:
        require_config_value(cfg, env_key)
    if args.fallback_model:
        fallback_config = MODEL_CONFIGS[args.fallback_model]
        fallback_env_key = fallback_config.get("env_key")
        if fallback_env_key and args.dry_run and is_placeholder_value(cfg.get(fallback_env_key)):
            print_warn(f"{fallback_env_key} fehlt oder ist noch ein Platzhalter")
        elif fallback_env_key:
            require_config_value(cfg, fallback_env_key)

    client = GitHubClient(token, user)
    repos = [args.repo] if args.repo else [
        repo["name"] for repo in client.get_repos() if not repo.get("archived")
    ]

    print_step(1, f"Suche Jobs in {len(repos)} Repo(s)")
    jobs = discover_issue_jobs(client, repos, args.issue, args.label)
    if not jobs:
        print_warn("Keine passenden Issues gefunden")
        return 0

    queued_reports = {}
    if args.dry_run:
        print_step(2, "Queue-Reports im Dry-run uebersprungen")
    else:
        print_step(2, "Schreibe Queue-Reports")
        base_branches = resolve_batch_base_branches(
            client,
            sorted({job.repo for job in jobs}),
            args.base_branch,
        )
        queued_reports = {
            report.job: report
            for report in (
                create_queued_run_report(
                    job,
                    args.model,
                    base_branch=base_branches.get(job.repo),
                )
                for job in jobs
            )
            if report is not None
        }
        print(f"   Queue-Reports: {len(queued_reports)}/{len(jobs)}")

    print_step(3, f"Starte {len(jobs)} Job(s) mit maximal {args.workers} Worker(n)")
    for job in jobs:
        print(f"   - {job.label}")

    project_root = Path(__file__).resolve().parents[1]
    solve_script = Path(__file__).with_name("solve_issues.py")
    env = os.environ.copy()

    def run(job: IssueJob) -> IssueJobResult:
        queued_report = queued_reports.get(job)
        heartbeat_interval = args.heartbeat_interval if args.heartbeat_interval else None
        heartbeat_label = f"{args.model}" if heartbeat_interval else None
        return run_issue_job_with_optional_fallback(
            job,
            args,
            solve_script,
            project_root,
            env,
            queued_report,
            health_timeout_seconds=args.worker_health_timeout_minutes * 60,
            unhealthy_action=args.unhealthy_action,
            detect_rate_limit_fn=detect_rate_limit_fn,
            heartbeat_interval_seconds=heartbeat_interval,
            heartbeat_job_label=heartbeat_label,
        )

    def handle_result(result: IssueJobResult, completed: int, total: int) -> None:
        queued_report = queued_reports.get(result.job)
        if queued_report:
            finalize_unclaimed_queued_report(queued_report, result)
        print_job_result(result, completed, total)

    requeue_delayed = args.model == "codex" and args.requeue_rate_limited
    detect_rate_limit_fn = (
        detect_codex_rate_limit if args.model == "codex" else (lambda output: None)
    )
    results = run_issue_jobs(
        jobs,
        workers=args.workers,
        run_job_fn=run,
        requeue_delayed=requeue_delayed,
        max_rate_limit_requeues=args.rate_limit_retries,
        detect_rate_limit_fn=detect_rate_limit_fn,
        requeue_unhealthy=args.unhealthy_action == "retry",
        max_unhealthy_requeues=args.unhealthy_retries,
        on_result=handle_result,
        on_delay=print_job_delay if requeue_delayed or args.unhealthy_action == "retry" else None,
    )

    # Sortiere Ergebnisse nach Prioritaet fuer die finale Zusammenfassung
    sorted_results = sorted(results, key=get_result_priority)
    
    solved = sum(1 for result in results if result.ok)
    delayed_count = sum(1 for result in results if result.delayed)
    warning_count = sum(
        1 for result in results 
        if result.returncode == 0 and not result.ok and not result.delayed
    )
    failed = len(results) - solved - delayed_count - warning_count

    print("\n" + "─" * 50)
    print(f"  ✅ Erfolgreich: {solved}")
    print(f"  ⚠️  Warnungen:   {warning_count}")
    print(f"  ⏳ Verzögert:   {delayed_count}")
    print(f"  ❌ Fehler:      {failed}")
    print("─" * 50)
    
    # Zeige sortierte Ergebnisse mit Badges
    print("\nReview-Reihenfolge (clean -> warnings -> delayed -> failed):")
    for result in sorted_results:
        badge = get_result_badge(result)
        status = "OK" if result.ok else ("DELAYED" if result.delayed else "FAIL")
        print(f"  {badge} {result.job.label} — {status} (Exit {result.returncode})")
    
    print("─" * 50 + "\n")

    return 0 if failed == 0 and delayed_count == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
