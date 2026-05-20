#!/usr/bin/env python3
"""
github_summary.py — Kompakte GitHub-Übersicht
Morpheus-Style AI Issue Solver — github.com/SaJaToGu

Zeigt offene Issues, offene PRs, zuletzt gemergte PRs und fehlgeschlagene
GitHub-Actions-Läufe über die GitHub API. Die GitHub CLI wird nicht benötigt.

Verwendung:
    python scripts/github_summary.py
    python scripts/github_summary.py --repo ai-issue-solver
    python scripts/github_summary.py --limit 3 --merged-days 7 --run-days 7
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import sys
from pathlib import Path

try:
    import requests
except ModuleNotFoundError:
    requests = None

sys.path.insert(0, str(Path(__file__).parent))
from utils import (  # noqa: E402
    handle_github_request_error,
    load_env,
    print_banner,
    print_err,
    print_step,
    raise_for_github_response,
    require_github_config,
)


FAILED_RUN_CONCLUSIONS = {"failure", "timed_out", "action_required"}


@dataclass(frozen=True)
class RepoSummary:
    repo: str
    open_issues: list[dict]
    open_prs: list[dict]
    merged_prs: list[dict]
    failed_runs: list[dict]


class GitHubClient:
    BASE = "https://api.github.com"

    def __init__(self, token: str, owner: str):
        self.owner = owner
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        })

    def get_page(self, path: str, **params) -> dict | list | None:
        try:
            resp = self.session.get(f"{self.BASE}{path}", params=params)
        except requests.RequestException as exc:
            handle_github_request_error(exc, f"GET {path}")
        if resp.status_code == 404:
            return None
        raise_for_github_response(resp, f"GET {path}")
        return resp.json()

    def get_all_pages(self, path: str, stop_after=None, **params) -> list:
        results = []
        params["per_page"] = min(int(params.get("per_page", 100)), 100)
        page = 1
        while True:
            params["page"] = page
            data = self.get_page(path, **params)
            if data is None:
                return []

            if isinstance(data, dict) and "workflow_runs" in data:
                items = data["workflow_runs"]
            else:
                items = data

            if not items:
                break
            results.extend(items)
            if stop_after and any(stop_after(item) for item in items):
                break
            if len(items) < params["per_page"]:
                break
            page += 1
        return results

    def get_repos(self) -> list[dict]:
        repos = self.get_all_pages(
            f"/users/{self.owner}/repos",
            type="owner",
            sort="updated",
            direction="desc",
        )
        return [repo for repo in repos if not repo.get("archived")]

    def get_repo(self, repo: str) -> dict | None:
        return self.get_page(f"/repos/{self.owner}/{repo}")

    def get_open_issues(self, repo: str) -> list[dict]:
        issues = self.get_all_pages(
            f"/repos/{self.owner}/{repo}/issues",
            state="open",
            sort="updated",
            direction="desc",
        )
        return [issue for issue in issues if "pull_request" not in issue]

    def get_open_prs(self, repo: str) -> list[dict]:
        return self.get_all_pages(
            f"/repos/{self.owner}/{repo}/pulls",
            state="open",
            sort="updated",
            direction="desc",
        )

    def get_merged_prs(self, repo: str, since: datetime | None = None) -> list[dict]:
        def is_older_than_window(pull: dict) -> bool:
            updated_at = parse_github_datetime(pull.get("updated_at"))
            return bool(since and updated_at and updated_at < since)

        pulls = self.get_all_pages(
            f"/repos/{self.owner}/{repo}/pulls",
            stop_after=is_older_than_window,
            state="closed",
            sort="updated",
            direction="desc",
        )
        merged = [pull for pull in pulls if pull.get("merged_at")]
        if since is None:
            return merged
        return [
            pull for pull in merged
            if (parse_github_datetime(pull.get("merged_at")) or datetime.min.replace(tzinfo=timezone.utc)) >= since
        ]

    def get_failed_runs(self, repo: str, since: datetime) -> list[dict]:
        runs = self.get_all_pages(
            f"/repos/{self.owner}/{repo}/actions/runs",
            status="completed",
            created=f">={since.isoformat(timespec='seconds').replace('+00:00', 'Z')}",
        )
        return [
            run for run in runs
            if run.get("conclusion") in FAILED_RUN_CONCLUSIONS
        ]


def parse_github_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def short_age(value: str | None, now: datetime | None = None) -> str:
    timestamp = parse_github_datetime(value)
    if not timestamp:
        return "unbekannt"
    now = now or datetime.now(timezone.utc)
    delta = now - timestamp
    if delta.days > 0:
        return f"vor {delta.days}d"
    hours = delta.seconds // 3600
    if hours > 0:
        return f"vor {hours}h"
    minutes = max(1, delta.seconds // 60)
    return f"vor {minutes}m"


def trim_title(title: str, max_length: int = 72) -> str:
    cleaned = " ".join((title or "").split())
    if len(cleaned) <= max_length:
        return cleaned
    return cleaned[: max_length - 1].rstrip() + "…"


def format_issue(item: dict) -> str:
    return f"#{item.get('number', '?')} {trim_title(item.get('title', ''))} ({short_age(item.get('updated_at'))})"


def format_pr(item: dict) -> str:
    user = item.get("user") or {}
    author = user.get("login", "?")
    return (
        f"#{item.get('number', '?')} {trim_title(item.get('title', ''))} "
        f"von @{author} ({short_age(item.get('updated_at'))})"
    )


def format_run(item: dict) -> str:
    workflow = item.get("name") or item.get("display_title") or "Workflow"
    branch = item.get("head_branch") or "?"
    conclusion = item.get("conclusion") or "failed"
    return (
        f"{trim_title(workflow, 48)} [{branch}] "
        f"{conclusion} ({short_age(item.get('updated_at') or item.get('created_at'))})"
    )


def limited(items: list[dict], limit: int) -> tuple[list[dict], int]:
    return items[:limit], max(0, len(items) - limit)


def print_section(title: str, items: list[dict], formatter, limit: int) -> None:
    visible, remaining = limited(items, limit)
    print(f"      {title}: {len(items)}")
    for item in visible:
        print(f"        - {formatter(item)}")
    if remaining:
        print(f"        - … {remaining} weitere")


def build_repo_summary(
    client: GitHubClient,
    repo: str,
    run_since: datetime,
    merged_since: datetime | None = None,
) -> RepoSummary:
    return RepoSummary(
        repo=repo,
        open_issues=client.get_open_issues(repo),
        open_prs=client.get_open_prs(repo),
        merged_prs=client.get_merged_prs(repo, merged_since),
        failed_runs=client.get_failed_runs(repo, run_since),
    )


def print_repo_summary(summary: RepoSummary, limit: int) -> None:
    has_items = any((
        summary.open_issues,
        summary.open_prs,
        summary.merged_prs,
        summary.failed_runs,
    ))
    if not has_items:
        print(f"\n   📁 {summary.repo}: keine offenen oder aktuellen Einträge")
        return

    print(f"\n   📁 {summary.repo}")
    print_section("Offene Issues", summary.open_issues, format_issue, limit)
    print_section("Offene PRs", summary.open_prs, format_pr, limit)
    print_section("Gemergte PRs", summary.merged_prs, format_pr, limit)
    print_section("Fehlgeschlagene Runs", summary.failed_runs, format_run, limit)


def main() -> int:
    print_banner("GITHUB-ÜBERSICHT")

    parser = argparse.ArgumentParser(
        description="Kompakte Übersicht über Issues, PRs und fehlgeschlagene GitHub-Actions-Runs"
    )
    parser.add_argument("--repo", help="Nur dieses Repository zusammenfassen")
    parser.add_argument("--limit", type=int, default=5, help="Maximale Einträge pro Abschnitt")
    parser.add_argument(
        "--merged-days",
        type=int,
        default=14,
        help="Zeitraum für gemergte Pull Requests in Tagen",
    )
    parser.add_argument(
        "--run-days",
        type=int,
        default=14,
        help="Zeitraum für fehlgeschlagene Actions-Runs in Tagen",
    )
    args = parser.parse_args()

    if args.limit < 1:
        parser.error("--limit muss mindestens 1 sein")
    if args.merged_days < 1:
        parser.error("--merged-days muss mindestens 1 sein")
    if args.run_days < 1:
        parser.error("--run-days muss mindestens 1 sein")

    if requests is None:
        print_err("Python-Abhängigkeit fehlt: requests")
        print("   → Installieren mit: pip install -r requirements.txt")
        return 1

    config = load_env()
    token, user = require_github_config(config)
    client = GitHubClient(token, user)
    now = datetime.now(timezone.utc)
    run_since = now - timedelta(days=args.run_days)
    merged_since = now - timedelta(days=args.merged_days)

    if args.repo:
        if client.get_repo(args.repo) is None:
            print_err(f"Repository nicht gefunden: {user}/{args.repo}")
            return 1
        repos = [args.repo]
    else:
        repos = [repo["name"] for repo in client.get_repos()]

    print_step(1, f"Prüfe {len(repos)} Repo(s) für @{user}")
    print(f"   Gemergte PRs seit: {merged_since.strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"   Fehlgeschlagene Runs seit: {run_since.strftime('%Y-%m-%d %H:%M UTC')}")

    totals = {"issues": 0, "open_prs": 0, "merged_prs": 0, "failed_runs": 0}
    for repo in repos:
        summary = build_repo_summary(client, repo, run_since, merged_since)
        totals["issues"] += len(summary.open_issues)
        totals["open_prs"] += len(summary.open_prs)
        totals["merged_prs"] += len(summary.merged_prs)
        totals["failed_runs"] += len(summary.failed_runs)
        print_repo_summary(summary, args.limit)

    print("\n" + "─" * 50)
    print(
        "  Übersicht: "
        f"{totals['issues']} offene Issues | "
        f"{totals['open_prs']} offene PRs | "
        f"{totals['merged_prs']} gemergte PRs | "
        f"{totals['failed_runs']} fehlgeschlagene Runs"
    )
    print("─" * 50 + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
