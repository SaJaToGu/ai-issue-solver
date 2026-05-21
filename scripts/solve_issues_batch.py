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
import queue
import subprocess
import sys
import threading
import time
from pathlib import Path

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

    @property
    def ok(self) -> bool:
        return self.returncode == 0 and not self.delayed and not self.unhealthy

    @property
    def delayed(self) -> bool:
        return self.rate_limited


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
                         run_report_dir: Path | None = None) -> list[str]:
    cmd = [
        sys.executable,
        str(solve_script),
        "--model",
        args.model,
        "--repo",
        job.repo,
        "--issue",
        str(job.issue_number),
        "--label",
        args.label,
    ]

    if args.model_name:
        cmd.extend(["--model-name", args.model_name])
    if args.base_branch:
        cmd.extend(["--base-branch", args.base_branch])
    if args.dry_run:
        cmd.append("--dry-run")
    if args.close_issues:
        cmd.append("--close-issues")
    if args.model == "codex":
        cmd.append("--defer-codex-rate-limit")
    if run_report_dir:
        cmd.extend(["--run-report-dir", str(run_report_dir)])

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


def finalize_unclaimed_queued_report(report: QueuedRunReport,
                                     result: IssueJobResult) -> Path | None:
    if queued_report_status(report) != "queued":
        return None

    status = "rate_limit_deferred" if result.delayed else "worker_finished"
    output_tail = format_worker_output_tail(result.output)
    try:
        if result.output:
            (report.path / "worker-output.log").write_text(result.output, encoding="utf-8")
        if output_tail:
            (report.path / "output-tail.log").write_text(output_tail + "\n", encoding="utf-8")

        metadata = {
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
        (report.path / "metadata.json").write_text(
            json.dumps(metadata, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        summary_lines = [
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
            summary_lines.extend(["", "output_tail:", output_tail])
        (report.path / "summary.txt").write_text(
            "\n".join(summary_lines) + "\n",
            encoding="utf-8",
        )
    except OSError as exc:
        print_warn(f"Queue-Report konnte nicht finalisiert werden: {exc}")
        return None
    return report.path


def resolve_batch_base_branches(client: GitHubClient, repos: list[str],
                                requested_base: str | None) -> dict[str, str]:
    base_branches: dict[str, str] = {}
    for repo in repos:
        base_branch = client.resolve_base_branch(repo, requested_base)
        if base_branch:
            base_branches[repo] = base_branch
        elif requested_base:
            base_branches[repo] = requested_base
    return base_branches


def run_issue_job(job: IssueJob, cmd: list[str], project_root: Path,
                  env: dict[str, str],
                  health_timeout_seconds: float | None = None,
                  unhealthy_action: str = "warn",
                  detect_rate_limit_fn=detect_codex_rate_limit,
                  now_fn=datetime.now) -> IssueJobResult:
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


def mark_rate_limited_result(result: IssueJobResult, detect_rate_limit_fn) -> IssueJobResult:
    if result.returncode == 0:
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
    rate_limit = detect_rate_limit_fn(output)
    return bool(rate_limit and rate_limit.reset_at and rate_limit.reset_at > now_fn())


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
    results = []
    pending = list(jobs)
    delayed_jobs: list[tuple[datetime, int, IssueJob]] = []
    attempts = {job: 0 for job in jobs}
    sequence = 0

    with ThreadPoolExecutor(max_workers=workers) as executor:
        future_to_job = {}

        def promote_ready_delayed_jobs() -> None:
            now = now_fn()
            while delayed_jobs and delayed_jobs[0][0] <= now:
                _, _, ready_job = heapq.heappop(delayed_jobs)
                pending.append(ready_job)

        def submit_ready_jobs() -> None:
            promote_ready_delayed_jobs()
            while pending and len(future_to_job) < workers:
                job = pending.pop(0)
                attempts[job] += 1
                future_to_job[executor.submit(run_job_fn, job)] = job

        submit_ready_jobs()
        while future_to_job or pending or delayed_jobs:
            if not future_to_job:
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
                can_requeue = (
                    result.delayed
                    and requeue_delayed
                    and result.delayed_until is not None
                    and attempts[job] <= max_rate_limit_requeues
                )
                can_requeue_unhealthy = (
                    result.unhealthy
                    and requeue_unhealthy
                    and attempts[job] <= max_unhealthy_requeues
                )
                if can_requeue:
                    sequence += 1
                    heapq.heappush(delayed_jobs, (result.delayed_until, sequence, job))
                    if on_delay:
                        on_delay(result)
                elif can_requeue_unhealthy:
                    pending.append(job)
                    if on_delay:
                        on_delay(result)
                else:
                    results.append(result)
                    if on_result:
                        on_result(result, len(results), len(jobs))

                submit_ready_jobs()
                break
    return results


def print_job_result(result: IssueJobResult, completed: int, total: int) -> None:
    status = "UNHEALTHY" if result.unhealthy else ("VERZÖGERT" if result.delayed else ("OK" if result.ok else "FEHLER"))
    print("\n" + "─" * 60)
    print(
        f"[{completed}/{total}] {result.job.label} — {status} "
        f"({result.duration_seconds:.1f}s, Exit {result.returncode})"
    )
    if result.delayed:
        reset = (
            result.delayed_until.strftime("%Y-%m-%d %H:%M")
            if result.delayed_until
            else result.delayed_reset_text
        )
        print(
            "Codex-Rate-Limit erkannt; "
            f"Job bleibt bis {reset or 'zum naechsten Reset'} verzögert."
        )
    if result.unhealthy:
        print(f"Worker-Health: {result.unhealthy_reason or 'unhealthy'}")
    print("─" * 60)
    if result.output.strip():
        print(result.output.rstrip())
    else:
        print("(keine Worker-Ausgabe)")


def print_job_delay(result: IssueJobResult) -> None:
    if result.unhealthy:
        print_warn(
            f"{result.job.label}: Worker unhealthy; "
            f"Requeue ({result.unhealthy_reason or 'keine Details'})."
        )
        return
    reset = (
        result.delayed_until.strftime("%Y-%m-%d %H:%M")
        if result.delayed_until
        else result.delayed_reset_text
    )
    print_warn(
        f"{result.job.label}: Codex-Rate-Limit erkannt; "
        f"Requeue nach {reset or 'unbekanntem Reset'}."
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="GitHub Issues parallel mit begrenzter Worker-Zahl lösen"
    )
    parser.add_argument(
        "--model", required=True, choices=list(MODEL_CONFIGS.keys()),
        help="KI-Modell: codex, claude, openai, mistral oder ollama"
    )
    parser.add_argument(
        "--model-name",
        help=(
            "Spezifisches Modell (für Codex optional, für Mistral z.B. "
            "'magistral-small-latest', für Ollama z.B. 'deepseek-coder:6.7b')"
        ),
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
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    print_banner("ISSUES PARALLEL MIT KI LÖSEN")
    args = parse_args(argv)

    if requests is None:
        print_err("Python-Abhängigkeit fehlt: requests")
        print("   → Installieren mit: pip install -r requirements.txt")
        return 1

    cfg = load_env()
    token = require_config_value(cfg, "GITHUB_TOKEN", "GitHub Token")
    user = require_config_value(cfg, "GITHUB_USER", "GitHub User")

    model_config = MODEL_CONFIGS[args.model]
    env_key = model_config.get("env_key")
    if env_key and args.dry_run and is_placeholder_value(cfg.get(env_key)):
        print_warn(f"{env_key} fehlt oder ist noch ein Platzhalter")
    elif env_key:
        require_config_value(cfg, env_key)

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
        cmd = build_worker_command(
            args,
            job,
            solve_script,
            run_report_dir=queued_report.path if queued_report else None,
        )
        return run_issue_job(
            job,
            cmd,
            project_root,
            env,
            health_timeout_seconds=args.worker_health_timeout_minutes * 60,
            unhealthy_action=args.unhealthy_action,
            detect_rate_limit_fn=detect_rate_limit_fn,
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

    solved = sum(1 for result in results if result.ok)
    delayed = sum(1 for result in results if result.delayed)
    failed = len(results) - solved - delayed

    print("\n" + "─" * 50)
    print(f"  ✅ Erfolgreich: {solved}")
    print(f"  ⏳ Verzögert:   {delayed}")
    print(f"  ❌ Fehler:      {failed}")
    print("─" * 50 + "\n")

    return 0 if failed == 0 and delayed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
