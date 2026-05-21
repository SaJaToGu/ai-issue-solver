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
from dataclasses import dataclass
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from solve_issues import GitHubClient, MODEL_CONFIGS, requests  # noqa: E402
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

    @property
    def ok(self) -> bool:
        return self.returncode == 0


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
                         solve_script: Path) -> list[str]:
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

    return cmd


def run_issue_job(job: IssueJob, cmd: list[str], project_root: Path,
                  env: dict[str, str]) -> IssueJobResult:
    started_at = time.monotonic()
    try:
        result = subprocess.run(
            cmd,
            cwd=project_root,
            env=env,
            capture_output=True,
            text=True,
        )
        output = (result.stdout or "") + (result.stderr or "")
        returncode = result.returncode
    except OSError as exc:
        output = f"Worker konnte nicht gestartet werden: {exc}\n"
        returncode = 127

    return IssueJobResult(
        job=job,
        returncode=returncode,
        output=output,
        duration_seconds=time.monotonic() - started_at,
    )


def run_issue_jobs(jobs: list[IssueJob], workers: int, run_job_fn) -> list[IssueJobResult]:
    results = []
    with ThreadPoolExecutor(max_workers=workers) as executor:
        future_to_job = {executor.submit(run_job_fn, job): job for job in jobs}
        for future in as_completed(future_to_job):
            job = future_to_job[future]
            try:
                results.append(future.result())
            except Exception as exc:  # pragma: no cover - defensiver Schutz fuer Batch-Laeufe
                results.append(
                    IssueJobResult(
                        job=job,
                        returncode=1,
                        output=f"Unerwarteter Worker-Fehler: {exc}\n",
                        duration_seconds=0.0,
                    )
                )
    return results


def print_job_result(result: IssueJobResult, completed: int, total: int) -> None:
    status = "OK" if result.ok else "FEHLER"
    print("\n" + "─" * 60)
    print(
        f"[{completed}/{total}] {result.job.label} — {status} "
        f"({result.duration_seconds:.1f}s, Exit {result.returncode})"
    )
    print("─" * 60)
    if result.output.strip():
        print(result.output.rstrip())
    else:
        print("(keine Worker-Ausgabe)")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="GitHub Issues parallel mit begrenzter Worker-Zahl lösen"
    )
    parser.add_argument(
        "--model", required=True, choices=list(MODEL_CONFIGS.keys()),
        help="KI-Modell: codex, claude, openai oder ollama"
    )
    parser.add_argument(
        "--model-name",
        help="Spezifisches Modell (für Codex optional, für Ollama z.B. 'deepseek-coder:6.7b')",
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

    print_step(2, f"Starte {len(jobs)} Job(s) mit maximal {args.workers} Worker(n)")
    for job in jobs:
        print(f"   - {job.label}")

    project_root = Path(__file__).resolve().parents[1]
    solve_script = Path(__file__).with_name("solve_issues.py")
    env = os.environ.copy()

    def run(job: IssueJob) -> IssueJobResult:
        cmd = build_worker_command(args, job, solve_script)
        return run_issue_job(job, cmd, project_root, env)

    completed = 0
    results = []
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        future_to_job = {executor.submit(run, job): job for job in jobs}
        for future in as_completed(future_to_job):
            completed += 1
            job = future_to_job[future]
            try:
                result = future.result()
            except Exception as exc:  # pragma: no cover - Schutz gegen unerwartete Runner-Fehler
                result = IssueJobResult(job, 1, f"Unerwarteter Worker-Fehler: {exc}\n", 0.0)
            results.append(result)
            print_job_result(result, completed, len(jobs))

    solved = sum(1 for result in results if result.ok)
    failed = len(results) - solved

    print("\n" + "─" * 50)
    print(f"  ✅ Erfolgreich: {solved}")
    print(f"  ❌ Fehler:      {failed}")
    print("─" * 50 + "\n")

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
