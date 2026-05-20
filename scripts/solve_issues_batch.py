#!/usr/bin/env python3
"""
solve_issues_batch.py — Mehrere Issues mit begrenzter Parallelität lösen.

Das Script plant Issue-Jobs zentral, überspringt bereits vorhandene
Issue-Branches und startet pro Job einen eigenen solve_issues.py-Prozess.
Dadurch laufen Worker parallel, während die Terminalausgabe pro Issue
zusammenhängend und lesbar bleibt.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
import subprocess
import sys
from pathlib import Path

from solve_issues import (
    GitHubClient,
    MODEL_CONFIGS,
    check_aider_installed,
    find_codex_executable,
    requests,
)
from utils import (
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
class BatchJob:
    repo: str
    issue_number: int
    title: str
    branch: str


@dataclass(frozen=True)
class BatchResult:
    job: BatchJob
    returncode: int
    output: str

    @property
    def ok(self) -> bool:
        return self.returncode == 0


def issue_branch_name(issue_number: int) -> str:
    return f"ai/fix-issue-{issue_number}"


def positive_worker_count(value: str) -> int:
    try:
        workers = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("--workers muss eine ganze Zahl sein") from exc
    if workers < 1:
        raise argparse.ArgumentTypeError("--workers muss mindestens 1 sein")
    return workers


def collect_jobs(client: GitHubClient, repos: list[str], label: str,
                 issue_number: int | None = None) -> tuple[list[BatchJob], int]:
    jobs: list[BatchJob] = []
    skipped = 0
    seen: set[tuple[str, int]] = set()

    for repo in repos:
        if issue_number:
            issue = client.get_single_issue(repo, issue_number)
            issues = [issue] if issue else []
        else:
            issues = client.get_open_issues(repo, label=label)

        if not issues:
            continue

        print(f"\n   📁 {repo}: {len(issues)} offene Issue(s)")
        for issue in issues:
            number = int(issue["number"])
            key = (repo, number)
            branch = issue_branch_name(number)

            if key in seen:
                skipped += 1
                print_warn(f"{repo}#{number} doppelt in der Planung; überspringe")
                continue
            seen.add(key)

            if client.branch_exists(repo, branch):
                skipped += 1
                print_warn(f"{repo}#{number} übersprungen: Branch '{branch}' existiert bereits")
                continue

            jobs.append(BatchJob(
                repo=repo,
                issue_number=number,
                title=issue.get("title", "(ohne Titel)"),
                branch=branch,
            ))

    return jobs, skipped


def build_solver_command(script_path: Path, args: argparse.Namespace, job: BatchJob) -> list[str]:
    cmd = [
        sys.executable,
        str(script_path),
        "--model", args.model,
        "--repo", job.repo,
        "--issue", str(job.issue_number),
        "--label", args.label,
    ]
    if args.model_name:
        cmd.extend(["--model-name", args.model_name])
    if args.base_branch:
        cmd.extend(["--base-branch", args.base_branch])
    if args.close_issues:
        cmd.append("--close-issues")
    if args.dry_run:
        cmd.append("--dry-run")
    return cmd


def run_job(script_path: Path, args: argparse.Namespace, job: BatchJob) -> BatchResult:
    cmd = build_solver_command(script_path, args, job)
    try:
        completed = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
        )
    except OSError as exc:
        return BatchResult(job=job, returncode=127, output=str(exc))

    return BatchResult(
        job=job,
        returncode=completed.returncode,
        output=(completed.stdout or "") + (completed.stderr or ""),
    )


def run_jobs(script_path: Path, args: argparse.Namespace, jobs: list[BatchJob]) -> list[BatchResult]:
    results: list[BatchResult] = []
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {
            executor.submit(run_job, script_path, args, job): job
            for job in jobs
        }
        for future in as_completed(futures):
            job = futures[future]
            try:
                results.append(future.result())
            except Exception as exc:  # Sicherheitsnetz fuer echte Batch-Laeufe
                results.append(BatchResult(
                    job=job,
                    returncode=1,
                    output=f"Batch-Worker intern fehlgeschlagen: {type(exc).__name__}: {exc}",
                ))
    return results


def print_job_result(result: BatchResult) -> None:
    status = "✅ OK" if result.ok else f"❌ Fehler ({result.returncode})"
    print("\n" + "─" * 50)
    print(f"  {status}: {result.job.repo}#{result.job.issue_number} — {result.job.title}")
    print(f"  Branch: {result.job.branch}")
    print("─" * 50)
    output = result.output.strip()
    if output:
        print(output)
    else:
        print("  (keine Ausgabe)")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Mehrere GitHub Issues parallel mit begrenzter Worker-Zahl lösen"
    )
    parser.add_argument(
        "--model", required=True, choices=["codex", "claude", "openai", "ollama"],
        help="KI-Modell: codex, claude, openai oder ollama",
    )
    parser.add_argument(
        "--model-name",
        help="Spezifisches Modell (für Codex optional, für Ollama z.B. 'deepseek-coder:6.7b')",
    )
    parser.add_argument("--repo", action="append", help="Nur dieses Repo bearbeiten; mehrfach nutzbar")
    parser.add_argument("--issue", type=int, help="Nur diese Issue-Nummer lösen")
    parser.add_argument("--dry-run", action="store_true", help="Nur anzeigen, nichts ändern")
    parser.add_argument("--label", default="ai-generated", help="Welche Issues holen (Label)")
    parser.add_argument(
        "--base-branch",
        help="Zielbranch für Klon und PR; ohne Angabe nutzt solve_issues.py den GitHub-Default-Branch",
    )
    parser.add_argument(
        "--close-issues",
        action="store_true",
        help="Issues nach PR-Erstellung direkt schließen",
    )
    parser.add_argument(
        "--workers",
        type=positive_worker_count,
        default=DEFAULT_WORKERS,
        help=f"Maximale Anzahl paralleler Solver-Prozesse (Standard: {DEFAULT_WORKERS})",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    print_banner("BATCH: ISSUES PARALLEL LÖSEN")
    args = parse_args(argv)

    if requests is None:
        print_err("Python-Abhängigkeit fehlt: requests")
        print("   → Installieren mit: pip install -r requirements.txt")
        return 1

    cfg = load_env()
    token = require_config_value(cfg, "GITHUB_TOKEN", "GitHub Token")
    user = require_config_value(cfg, "GITHUB_USER", "GitHub User")

    model_config = MODEL_CONFIGS[args.model]
    model_name = args.model_name or model_config.get("default_model_name", "")
    args.model_name = model_name

    if args.model == "codex" and not find_codex_executable() and not args.dry_run:
        print_err("Codex CLI wurde nicht gefunden!")
        print("   → Codex Desktop App installieren oder `codex` in PATH verfügbar machen")
        return 1

    if args.model != "codex" and not check_aider_installed() and not args.dry_run:
        print_err("aider ist nicht installiert!")
        print("   → Installieren mit: pip install aider-chat")
        print("   → Mehr Infos: docs/SETUP_AIDER.md")
        return 1

    env_key = model_config.get("env_key")
    if env_key and args.dry_run and is_placeholder_value(cfg.get(env_key)):
        print_warn(f"{env_key} fehlt oder ist noch ein Platzhalter")
    elif env_key:
        require_config_value(cfg, env_key)

    client = GitHubClient(token, user)
    if args.dry_run:
        print_warn("DRY-RUN Modus aktiv\n")

    print_step(1, f"Modell: {model_config['display_name']}")
    if model_name:
        print(f"   Modell-Name: {model_name}")
    print(f"   Worker-Limit: {args.workers}")

    if args.repo:
        repos = args.repo
    else:
        all_repos = client.get_repos()
        repos = [repo["name"] for repo in all_repos if not repo.get("archived")]

    print_step(2, f"Plane Jobs in {len(repos)} Repo(s)")
    jobs, skipped = collect_jobs(client, repos, args.label, args.issue)

    if not jobs:
        print_warn("Keine passenden Jobs gefunden")
        print("\n" + "─" * 50)
        print(f"  Geplant:       0")
        print(f"  Übersprungen:  {skipped}")
        print("─" * 50 + "\n")
        return 0

    print_step(3, f"Starte {len(jobs)} Job(s) mit maximal {args.workers} Worker(n)")
    script_path = Path(__file__).with_name("solve_issues.py")

    solved = 0
    failed = 0
    for result in run_jobs(script_path, args, jobs):
        print_job_result(result)
        if result.ok:
            solved += 1
        else:
            failed += 1

    print("\n" + "─" * 50)
    print(f"  ✅ Gelöst:       {solved}")
    print(f"  ❌ Fehler:       {failed}")
    print(f"  ⏭️  Übersprungen: {skipped}")
    print("─" * 50 + "\n")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
