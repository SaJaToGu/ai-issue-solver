#!/usr/bin/env python3
"""
status_dashboard.py - Lokales HTML-Dashboard fuer Run-Reports
Morpheus-Style AI Issue Solver - github.com/SaJaToGu

Liest reports/runs/*/summary.txt und erzeugt eine statische HTML-Uebersicht
ueber laufende, erfolgreiche, fehlgeschlagene und No-op-Jobs.

Verwendung:
    python scripts/status_dashboard.py
    python scripts/status_dashboard.py --runs-dir reports/runs --output reports/status-dashboard.html
    python scripts/status_dashboard.py --owner SaJaToGu
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from html import escape
import json
import os
import re
import shlex
import sys
from pathlib import Path
from urllib.parse import quote

try:
    import requests
except ModuleNotFoundError:
    requests = None

sys.path.insert(0, str(Path(__file__).parent))
from utils import is_placeholder_value, load_env, print_banner, print_step  # noqa: E402


DEFAULT_RUNS_DIR = Path("reports") / "runs"
DEFAULT_OUTPUT = Path("reports") / "status-dashboard.html"
DEFAULT_GITHUB_CACHE = Path("reports") / "status-dashboard.github-cache.json"
DEFAULT_HEALTH_TIMEOUT_MINUTES = 60
DEFAULT_GITHUB_CACHE_TTL_SECONDS = 600
GITHUB_RE = re.compile(r"https://github\.com/([^/\s]+)/([^/\s]+)/")
GITHUB_PR_RE = re.compile(r"https://github\.com/([^/\s]+)/([^/\s]+)/pull/(\d+)")
CODEX_RATE_LIMIT_RESET_RE = re.compile(
    r"rate limit will be reset on\s+(.+?)(?:\.|\n|$)",
    re.IGNORECASE,
)
CODEX_RATE_LIMIT_MESSAGE_RE = re.compile(
    r"(?:reached the codex message limit|rate limit will be reset)",
    re.IGNORECASE,
)

STATUS_LABELS = {
    "queued": "Queued",
    "running": "Running",
    "unhealthy": "Unhealthy",
    "failed": "Failed",
    "recovered": "Recovered",
    "superseded": "Superseded",
    "successful": "Successful",
    "noop": "No-op",
    "archived": "Archived",
    "unknown": "Unknown",
}

STATUS_ORDER = ("queued", "running", "unhealthy", "failed", "recovered", "superseded", "successful", "noop", "archived", "unknown")
SUCCESS_STATUSES = {
    "pr_created",
    "pr_created_from_existing_branch",
    "cleanup_successful",
}
NOOP_STATUSES = {
    "no_changes",
    "skip_existing_pr",
    "skip_merged_pr",
    "skip_closed_pr",
    "cleanup_noop",
}
FAILED_STATUSES = {
    "branch_create_failed",
    "checkout_failed",
    "clone_failed",
    "nonzero_without_changes",
    "pr_failed",
    "pr_failed_from_existing_branch",
    "push_failed",
    "cleanup_failed",
    "rate_limit_deferred",
    "validation_failed",
}
ARCHIVED_STATUSES = {
    "archived",
    "cleanup_archived",
}
CLEANUP_STATUS_VALUES = {
    "successful": "cleanup_successful",
    "failed": "cleanup_failed",
    "noop": "cleanup_noop",
    "archived": "archived",
}


@dataclass(frozen=True)
class DashboardIssue:
    number: str
    title: str
    repo: str
    html_url: str
    state: str
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class DashboardRun:
    path: Path
    name: str
    created_at: datetime | None
    status: str
    category: str
    repo: str
    issue_number: str
    issue_title: str
    branch: str
    base_branch: str
    model: str
    worker_exit_code: str
    last_activity_at: datetime | None
    last_report_update_at: datetime | None
    health_status: str
    health_reason: str
    recovery_hint: str
    pr_url: str
    preserved_worktree: str
    note: str
    git_diff_stat: str
    output_tail: str
    lifecycle_label: str = ""
    lifecycle_state: str = ""
    lifecycle_needs_attention: bool = False
    lifecycle_note: str = ""


@dataclass(frozen=True)
class CleanupResult:
    candidates: list[DashboardRun]
    changed: list[Path]
    target_status: str
    cutoff: datetime
    dry_run: bool


@dataclass(frozen=True)
class GitHubEnrichmentResult:
    runs: list[DashboardRun]
    used_github: bool
    used_cache: bool
    error: str = ""


class DashboardGitHubClient:
    BASE = "https://api.github.com"

    def __init__(self, token: str, owner: str):
        self.owner = owner
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        })

    def repo_api_path(self, repo: str) -> str:
        return github_repo_api_path(repo, self.owner)

    def get_json(self, path: str, **params) -> dict | list | None:
        resp = self.session.get(f"{self.BASE}{path}", params=params, timeout=10)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.json()

    def get_pull_request(self, repo: str, number: str | int) -> dict | None:
        return self.get_json(f"{self.repo_api_path(repo)}/pulls/{quote(str(number), safe='')}")

    def get_pull_requests_for_branch(self, repo: str, branch: str) -> list[dict]:
        repo_owner = repo_owner_for_url(repo, self.owner) or self.owner
        data = self.get_json(
            f"{self.repo_api_path(repo)}/pulls",
            state="all",
            head=f"{repo_owner}:{branch}",
            per_page=10,
            sort="updated",
            direction="desc",
        )
        return data if isinstance(data, list) else []

    def get_pull_requests_for_issue(self, repo: str, issue_number: str | int) -> list[dict]:
        repo_owner = repo_owner_for_url(repo, self.owner) or self.owner
        repo_name = repo_name_for_url(repo)
        data = self.get_json(
            "/search/issues",
            q=f"repo:{repo_owner}/{repo_name} is:pr {issue_number}",
            per_page=10,
            sort="updated",
            order="desc",
        )
        if not isinstance(data, dict):
            return []
        items = data.get("items", [])
        if not isinstance(items, list):
            return []

        pulls = []
        for item in items:
            number = item.get("number") if isinstance(item, dict) else None
            if number:
                pr = self.get_pull_request(repo, number)
                if pr:
                    pulls.append(pr)
        return pulls

    def get_issue(self, repo: str, issue_number: str | int) -> dict | None:
        data = self.get_json(f"{self.repo_api_path(repo)}/issues/{quote(str(issue_number), safe='')}")
        if data and "pull_request" in data:
            return None
        return data

    def branch_contains_commit(self, repo: str, branch: str, sha: str) -> bool:
        if not branch or not sha:
            return False
        data = self.get_json(
            f"{self.repo_api_path(repo)}/compare/{quote(branch, safe='')}...{quote(sha, safe='')}"
        )
        if not isinstance(data, dict):
            return False
        return data.get("status") in {"behind", "identical"}

    def get_open_issues(self, repo: str) -> list[dict]:
        repo_owner = repo_owner_for_url(repo, self.owner) or self.owner
        repo_name = repo_name_for_url(repo)
        data = self.get_json(
            f"{self.repo_api_path(repo)}/issues",
            state="open",
            sort="updated",
            direction="desc",
            per_page=100,
        )
        if not isinstance(data, list):
            return []
        # Filter out pull requests
        return [issue for issue in data if "pull_request" not in issue]

    def get_repos(self) -> list[dict]:
        data = self.get_json(
            f"/users/{quote(self.owner, safe='')}/repos",
            type="owner",
            sort="updated",
            direction="desc",
            per_page=100,
        )
        if not isinstance(data, list):
            return []
        return [repo for repo in data if not repo.get("archived", False)]


def parse_summary(path: Path) -> dict[str, str]:
    fields: dict[str, str] = {}
    if not path.exists():
        return fields

    multiline_keys = {"git_diff_stat", "output_tail"}
    current_multiline_key = None
    multiline_parts: list[str] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        key, separator, value = raw_line.partition(":")
        key = key.strip()
        value = value.strip()
        starts_multiline_key = bool(separator and key in multiline_keys)

        if current_multiline_key:
            if starts_multiline_key:
                fields[current_multiline_key] = "\n".join(multiline_parts).strip()
                current_multiline_key = key
                multiline_parts = [value] if value else []
                continue
            multiline_parts.append(raw_line)
            continue

        if not raw_line.strip():
            continue
        if not separator:
            continue
        if key in multiline_keys:
            current_multiline_key = key
            if value:
                multiline_parts.append(value)
            continue
        fields[key] = value

    if current_multiline_key:
        fields[current_multiline_key] = "\n".join(multiline_parts).strip()
    return fields


def parse_created_at(run_dir_name: str) -> datetime | None:
    match = re.match(r"^(\d{8}-\d{6})(?:-(\d{6}))?", run_dir_name)
    if not match:
        return None
    value = "".join(part for part in match.groups(default="") if part)
    fmt = "%Y%m%d-%H%M%S%f" if match.group(2) else "%Y%m%d-%H%M%S"
    try:
        return datetime.strptime(value, fmt)
    except ValueError:
        return None


def parse_datetime_value(value: str) -> datetime | None:
    if not value:
        return None
    normalized = value.strip()
    for date_format in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(normalized[:19], date_format)
        except ValueError:
            pass
    return None


def read_health_file(run_dir: Path) -> dict[str, str]:
    health_path = run_dir / "health.json"
    if not health_path.exists():
        return {}
    try:
        data = json.loads(health_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return {str(key): "" if value is None else str(value) for key, value in data.items()}


def file_mtime(path: Path) -> datetime | None:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime)
    except OSError:
        return None


def parse_codex_reset_datetime(reset_text: str) -> datetime | None:
    normalized = re.sub(r"\s+", " ", reset_text.strip())
    normalized = normalized.replace(", at ", " ").replace(" at ", " ")
    for date_format in (
        "%B %d, %Y %I:%M %p",
        "%b %d, %Y %I:%M %p",
        "%B %d %Y %I:%M %p",
        "%b %d %Y %I:%M %p",
    ):
        try:
            return datetime.strptime(normalized, date_format)
        except ValueError:
            pass
    return None


def codex_rate_limit_wait_until(output_tail: str) -> datetime | None:
    match = CODEX_RATE_LIMIT_RESET_RE.search(output_tail)
    if not match:
        return None
    return parse_codex_reset_datetime(match.group(1).strip())


def latest_datetime(*values: datetime | None) -> datetime | None:
    parsed = [value for value in values if value is not None]
    return max(parsed) if parsed else None


def recovery_hint_for_unhealthy(run_dir: Path) -> str:
    return (
        "Pruefe worker-output.log und den Worker-Prozess. "
        f"Report: {run_dir}. Bei haengendem Prozess Batch mit --unhealthy-action stop "
        "oder --unhealthy-action retry erneut ausfuehren."
    )


def classify_status(status: str, worker_exit_code: str = "") -> str:
    if not status:
        return "unknown"
    if status == "queued":
        return "queued"
    if status == "started":
        return "running"
    if status in ARCHIVED_STATUSES:
        return "archived"
    if status in SUCCESS_STATUSES:
        return "successful"
    if status in NOOP_STATUSES:
        return "noop"
    if status in FAILED_STATUSES or status.endswith("_failed"):
        return "failed"
    if worker_exit_code and worker_exit_code != "0":
        return "failed"
    return "noop"


def read_runs(runs_dir: Path,
              health_timeout_minutes: int = DEFAULT_HEALTH_TIMEOUT_MINUTES,
              now_fn=datetime.now) -> list[DashboardRun]:
    if not runs_dir.exists():
        return []

    runs = []
    now = now_fn()
    timeout = timedelta(minutes=health_timeout_minutes)
    for run_dir in sorted((path for path in runs_dir.iterdir() if path.is_dir()), reverse=True):
        fields = parse_summary(run_dir / "summary.txt")
        health = read_health_file(run_dir)
        status = fields.get("status", "")
        exit_code = fields.get("worker_exit_code", "")
        output_tail = health.get("output_tail") or fields.get("output_tail", "")
        summary_mtime = file_mtime(run_dir / "summary.txt")
        health_mtime = file_mtime(run_dir / "health.json")
        explicit_activity_at = (
            parse_datetime_value(health.get("last_activity_at", ""))
            or parse_datetime_value(fields.get("last_activity_at", ""))
        )
        explicit_report_update_at = (
            parse_datetime_value(health.get("last_report_update_at", ""))
            or parse_datetime_value(fields.get("last_report_update_at", ""))
        )
        last_activity_at = explicit_activity_at or file_mtime(run_dir / "worker-output.log")
        if last_activity_at is None and explicit_report_update_at is None:
            last_activity_at = summary_mtime or parse_created_at(run_dir.name)
        last_report_update_at = explicit_report_update_at
        if last_report_update_at is None and explicit_activity_at is None:
            last_report_update_at = latest_datetime(health_mtime, summary_mtime)
        category = classify_status(status, exit_code)
        health_status = "ok"
        health_reason = ""
        recovery_hint = ""
        rate_limit_until = codex_rate_limit_wait_until(output_tail)
        in_known_wait = bool(rate_limit_until and rate_limit_until > now)
        last_progress_at = latest_datetime(last_activity_at, last_report_update_at)
        if (
            category == "running"
            and CODEX_RATE_LIMIT_MESSAGE_RE.search(output_tail)
            and not in_known_wait
        ):
            category = "unhealthy"
            health_status = "unhealthy"
            health_reason = "Codex-Rate-Limit ohne zukuenftige Reset-Zeit"
            recovery_hint = recovery_hint_for_unhealthy(run_dir)
        elif category == "running" and not in_known_wait:
            if last_progress_at is None:
                category = "unhealthy"
                health_status = "unhealthy"
                health_reason = "keine Aktivitaetszeit im Run-Report gefunden"
                recovery_hint = recovery_hint_for_unhealthy(run_dir)
            elif now - last_progress_at > timeout:
                category = "unhealthy"
                health_status = "unhealthy"
                health_reason = (
                    "letzte sinnvolle Aktivitaet "
                    f"{format_datetime(last_progress_at)}; Timeout {health_timeout_minutes} min"
                )
                recovery_hint = recovery_hint_for_unhealthy(run_dir)
        elif category == "running" and in_known_wait:
            health_reason = f"Codex-Rate-Limit-Wartezeit bis {format_datetime(rate_limit_until)}"
        model = fields.get("model", "")
        fallback_from = fields.get("fallback_from", "")
        actual_model = fields.get("actual_model", "")
        if fallback_from and actual_model:
            model = f"{actual_model} (Fallback von {fallback_from})"
        runs.append(
            DashboardRun(
                path=run_dir,
                name=run_dir.name,
                created_at=parse_created_at(run_dir.name),
                status=status,
                category=category,
                repo=fields.get("repo") or fields.get("selected_repo", ""),
                issue_number=fields.get("issue_number") or fields.get("issue", ""),
                issue_title=fields.get("issue_title", ""),
                branch=fields.get("branch", ""),
                base_branch=fields.get("base_branch", ""),
                model=model,
                worker_exit_code=exit_code,
                last_activity_at=last_activity_at,
                last_report_update_at=last_report_update_at,
                health_status=health_status,
                health_reason=health_reason,
                recovery_hint=recovery_hint,
                pr_url=fields.get("pr_url", ""),
                preserved_worktree=fields.get("preserved_worktree", ""),
                note=fields.get("note") or fields.get("cleanup_note", ""),
                git_diff_stat=fields.get("git_diff_stat", ""),
                output_tail=output_tail,
            )
        )
    return runs


def cleanup_candidates(runs: list[DashboardRun], cutoff: datetime,
                       include_undated: bool = False) -> list[DashboardRun]:
    candidates = []
    for run in runs:
        if run.category not in {"queued", "running", "unhealthy", "unknown"}:
            continue
        if run.created_at is None:
            if include_undated:
                candidates.append(run)
            continue
        if run.created_at <= cutoff:
            candidates.append(run)
    return candidates


def write_cleanup_status(run: DashboardRun, status: str,
                         cleaned_at: datetime | None = None) -> Path:
    cleaned_at = cleaned_at or datetime.now()
    summary_path = run.path / "summary.txt"
    lines = []
    if summary_path.exists():
        lines = summary_path.read_text(encoding="utf-8").splitlines()

    status_line = f"status: {status}"
    for index, line in enumerate(lines):
        key, separator, _value = line.partition(":")
        if separator and key.strip() == "status":
            lines[index] = status_line
            break
    else:
        lines.insert(0, status_line)

    insert_at = len(lines)
    for index, line in enumerate(lines):
        key, separator, _value = line.partition(":")
        if separator and key.strip() == "output_tail":
            insert_at = index
            break

    cleanup_lines = [
        f"cleanup_at: {cleaned_at.isoformat(timespec='seconds')}",
        "cleanup_note: Dashboard-Cleanup hat diesen alten unvollstaendigen Run markiert.",
    ]
    if insert_at > 0 and lines[insert_at - 1].strip():
        cleanup_lines.insert(0, "")
    if insert_at < len(lines) and lines[insert_at].strip():
        cleanup_lines.append("")
    lines[insert_at:insert_at] = cleanup_lines

    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return summary_path


def cleanup_stale_runs(runs_dir: Path, mark: str = "archived",
                       older_than_days: int = 7,
                       apply: bool = False,
                       include_undated: bool = False,
                       now_fn=datetime.now) -> CleanupResult:
    if mark not in CLEANUP_STATUS_VALUES:
        choices = ", ".join(sorted(CLEANUP_STATUS_VALUES))
        raise ValueError(f"ungueltiger Cleanup-Status {mark!r}; erlaubt: {choices}")
    if older_than_days < 0:
        raise ValueError("--older-than-days darf nicht negativ sein")

    now = now_fn()
    cutoff = now - timedelta(days=older_than_days)
    runs = read_runs(runs_dir)
    candidates = cleanup_candidates(runs, cutoff, include_undated=include_undated)
    target_status = CLEANUP_STATUS_VALUES[mark]
    changed = []
    if apply:
        for run in candidates:
            changed.append(write_cleanup_status(run, target_status, cleaned_at=now))
    return CleanupResult(candidates, changed, target_status, cutoff, dry_run=not apply)


def infer_owner_from_runs(runs: list[DashboardRun]) -> str | None:
    for run in runs:
        match = GITHUB_RE.match(run.pr_url)
        if match:
            return match.group(1)
    return None


def issue_to_dashboard_issue(issue: dict, repo: str, owner: str | None) -> DashboardIssue:
    repo_owner = repo_owner_for_url(repo, owner) or owner or ""
    repo_name = repo_name_for_url(repo)
    return DashboardIssue(
        number=str(issue.get("number", "")),
        title=issue.get("title", ""),
        repo=repo,
        html_url=issue.get("html_url", ""),
        state=issue.get("state", "open"),
        created_at=issue.get("created_at", ""),
        updated_at=issue.get("updated_at", ""),
    )


def get_issue_numbers_from_runs(runs: list[DashboardRun]) -> set[str]:
    """Extract all issue numbers that have runs."""
    issue_numbers = set()
    for run in runs:
        if run.issue_number:
            issue_numbers.add(run.issue_number)
    return issue_numbers


def find_unstarted_issues(
    runs: list[DashboardRun],
    owner: str | None,
    client: DashboardGitHubClient | None = None,
) -> list[DashboardIssue]:
    """Find open issues that don't have corresponding runs yet."""
    if client is None:
        return []

    # Get all repos from runs
    repos_with_runs = {run.repo for run in runs if run.repo}
    if not repos_with_runs:
        return []

    # Get issue numbers that already have runs
    issue_numbers_with_runs = get_issue_numbers_from_runs(runs)

    unstarted: list[DashboardIssue] = []
    for repo in repos_with_runs:
        issues = client.get_open_issues(repo)
        for issue in issues:
            issue_number = str(issue.get("number", ""))
            if issue_number not in issue_numbers_with_runs:
                unstarted.append(issue_to_dashboard_issue(issue, repo, owner))

    # Sort by updated_at descending (most recently updated first)
    return sorted(
        unstarted,
        key=lambda i: i.updated_at if i.updated_at else "",
        reverse=True,
    )


def repo_name_for_url(repo: str) -> str:
    return repo.split("/", 1)[1] if "/" in repo else repo


def repo_owner_for_url(repo: str, owner: str | None) -> str | None:
    if "/" in repo:
        return repo.split("/", 1)[0]
    return owner


def github_repo_api_path(repo: str, owner: str | None) -> str:
    repo_owner = repo_owner_for_url(repo, owner) or ""
    repo_name = repo_name_for_url(repo)
    return f"/repos/{quote(repo_owner, safe='')}/{quote(repo_name, safe='')}"


def github_links(run: DashboardRun, owner: str | None) -> dict[str, str]:
    repo_owner = repo_owner_for_url(run.repo, owner)
    repo_name = repo_name_for_url(run.repo)
    if not repo_owner or not repo_name:
        return {}

    base = f"https://github.com/{quote(repo_owner)}/{quote(repo_name)}"
    links = {}
    if run.issue_number:
        links["issue"] = f"{base}/issues/{quote(run.issue_number)}"
    if run.branch:
        links["branch"] = f"{base}/tree/{quote(run.branch, safe='')}"
    if run.pr_url:
        links["pr"] = run.pr_url
    return links


def fallback_lifecycle_for_run(run: DashboardRun) -> DashboardRun:
    if run.category != "successful":
        return run
    if run.status.startswith("pr_created"):
        note = "GitHub-Status nicht geladen; pruefe PR-Link."
        return replace(
            run,
            lifecycle_label="PR created",
            lifecycle_state="unknown",
            lifecycle_needs_attention=True,
            lifecycle_note=note,
        )
    if run.status == "cleanup_successful":
        return replace(
            run,
            lifecycle_label="Cleanup done",
            lifecycle_state="done",
            lifecycle_needs_attention=False,
            lifecycle_note="Lokaler Cleanup-Run ohne PR-Lifecycle.",
        )
    return run


def with_fallback_lifecycle(runs: list[DashboardRun]) -> list[DashboardRun]:
    return [fallback_lifecycle_for_run(run) for run in runs]


def pr_number_from_url(pr_url: str) -> str:
    match = GITHUB_PR_RE.match(pr_url or "")
    return match.group(3) if match else ""


def pr_number_from_data(pr: dict | None) -> str:
    if not pr:
        return ""
    return str(pr.get("number") or pr_number_from_url(str(pr.get("html_url") or "")))


def is_recoverable_failed_candidate(run: DashboardRun) -> bool:
    return bool(
        run.category == "failed"
        and run.preserved_worktree
        and run.branch
        and run.issue_number
    )


def is_failed_with_closed_issue(run: DashboardRun) -> bool:
    """Check if a failed run has a closed issue and should be marked as superseded."""
    return bool(
        run.category == "failed"
        and run.issue_number
        and not run.preserved_worktree
    )


def lifecycle_from_github(run: DashboardRun, pr: dict | None,
                          issue: dict | None, in_main: bool) -> DashboardRun:
    issue_closed = bool(issue and issue.get("state") == "closed")
    if in_main:
        if issue_closed:
            label = "Issue closed"
            state = "issue-closed"
            note = "Code ist in main und Issue ist geschlossen."
        else:
            label = "In main (Issue offen)"
            state = "in-main-issue-open"
            note = "Code ist in main; Issue ist noch offen." if issue else "Merge-Commit ist in main."
        return replace(
            run,
            lifecycle_label=label,
            lifecycle_state=state,
            lifecycle_needs_attention=not issue_closed,
            lifecycle_note=note,
        )

    if pr and pr.get("merged_at"):
        base = ((pr.get("base") or {}).get("ref")) or run.base_branch or "develop"
        if issue_closed:
            note = "Issue ist geschlossen, aber main enthaelt den Merge-Commit noch nicht."
            label = f"Merged to {base}"
            state = "merged"
        else:
            note = "PR gemergt, aber Issue ist noch offen."
            label = f"Merged to {base} (Issue offen)"
            state = "merged-issue-open"
        return replace(
            run,
            lifecycle_label=label,
            lifecycle_state=state,
            lifecycle_needs_attention=True,
            lifecycle_note=note,
        )

    if pr and pr.get("state") == "open":
        return replace(
            run,
            lifecycle_label="PR open",
            lifecycle_state="pr-open",
            lifecycle_needs_attention=True,
            lifecycle_note="Review oder Merge steht noch aus.",
        )

    if pr and pr.get("state") == "closed":
        return replace(
            run,
            lifecycle_label="PR closed",
            lifecycle_state="pr-closed",
            lifecycle_needs_attention=True,
            lifecycle_note="PR wurde ohne Merge geschlossen.",
        )

    return fallback_lifecycle_for_run(run)


def recovered_lifecycle_from_github(run: DashboardRun, pr: dict,
                                    issue: dict | None, in_main: bool) -> DashboardRun:
    issue_closed = bool(issue and issue.get("state") == "closed")
    pr_number = pr_number_from_data(pr)
    pr_label = f"PR #{pr_number}" if pr_number else "PR"
    base = ((pr.get("base") or {}).get("ref")) or run.base_branch or "develop"

    if in_main:
        label = "Issue closed" if issue_closed else "In main (Issue offen)"
        state = "issue-closed" if issue_closed else "in-main-issue-open"
        needs_attention = not issue_closed
    else:
        if issue_closed:
            label = f"Recovered to {base}"
            state = "recovered"
            needs_attention = False
        else:
            label = f"Recovered to {base} (Issue offen)"
            state = "recovered-issue-open"
            needs_attention = True

    note = f"Original run failed; recovered via {pr_label}"
    if not issue_closed and not in_main:
        note += "; Issue ist noch offen."
    return replace(
        run,
        category="recovered",
        pr_url=run.pr_url or str(pr.get("html_url") or ""),
        lifecycle_label=label,
        lifecycle_state=state,
        lifecycle_needs_attention=needs_attention,
        lifecycle_note=note,
    )


def superseded_lifecycle_from_github(run: DashboardRun, issue: dict | None) -> DashboardRun:
    """Mark a failed run as superseded when the related issue is closed."""
    issue_closed = bool(issue and issue.get("state") == "closed")

    if issue_closed:
        return replace(
            run,
            category="superseded",
            lifecycle_label="Issue closed",
            lifecycle_state="issue-closed",
            lifecycle_needs_attention=False,
            lifecycle_note="Originaler fehlgeschlagener Run; Issue wurde geschlossen oder durch andere Arbeit gelost.",
        )
    return run


def select_merged_pull_request(pulls: list[dict]) -> dict | None:
    for pr in pulls:
        if isinstance(pr, dict) and pr.get("merged_at"):
            return pr
    return None


def github_cache_is_fresh(cache_path: Path, ttl_seconds: int,
                          now_fn=datetime.now) -> bool:
    if ttl_seconds < 0:
        return True
    try:
        mtime = datetime.fromtimestamp(cache_path.stat().st_mtime)
    except OSError:
        return False
    return now_fn() - mtime <= timedelta(seconds=ttl_seconds)


def load_github_cache(cache_path: Path, ttl_seconds: int,
                      now_fn=datetime.now) -> dict[str, dict] | None:
    if not cache_path.exists() or not github_cache_is_fresh(cache_path, ttl_seconds, now_fn=now_fn):
        return None
    try:
        data = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    entries = data.get("entries", data)
    return entries if isinstance(entries, dict) else None


def write_github_cache(cache_path: Path, entries: dict[str, dict]) -> None:
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "entries": entries,
    }
    cache_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def lifecycle_cache_key(run: DashboardRun, owner: str | None) -> str:
    repo_owner = repo_owner_for_url(run.repo, owner) or ""
    repo_name = repo_name_for_url(run.repo)
    return "|".join([repo_owner, repo_name, run.issue_number, run.branch, run.pr_url])


def run_from_lifecycle_cache(run: DashboardRun, cached: dict) -> DashboardRun:
    return replace(
        run,
        category=str(cached.get("category", run.category)),
        pr_url=str(cached.get("pr_url", run.pr_url)),
        lifecycle_label=str(cached.get("label", "")),
        lifecycle_state=str(cached.get("state", "")),
        lifecycle_needs_attention=bool(cached.get("needs_attention", False)),
        lifecycle_note=str(cached.get("note", "")),
    )


def run_to_lifecycle_cache(run: DashboardRun) -> dict:
    return {
        "category": run.category,
        "pr_url": run.pr_url,
        "label": run.lifecycle_label,
        "state": run.lifecycle_state,
        "needs_attention": run.lifecycle_needs_attention,
        "note": run.lifecycle_note,
    }


def enrich_single_run_from_github(run: DashboardRun, owner: str | None,
                                  client: DashboardGitHubClient) -> DashboardRun:
    if run.category != "successful" and not is_recoverable_failed_candidate(run) and not is_failed_with_closed_issue(run):
        return run

    repo_owner = repo_owner_for_url(run.repo, owner)
    repo_name = repo_name_for_url(run.repo)
    if not repo_owner or not repo_name:
        return fallback_lifecycle_for_run(run)
    repo_for_api = run.repo if "/" in run.repo else repo_name

    if run.category == "successful":
        pr = None
        pr_number = pr_number_from_url(run.pr_url)
        if pr_number:
            pr = client.get_pull_request(repo_for_api, pr_number)
        elif run.branch:
            prs = client.get_pull_requests_for_branch(repo_for_api, run.branch)
            pr = prs[0] if prs else None

        issue = client.get_issue(repo_for_api, run.issue_number) if run.issue_number else None
        merge_sha = str((pr or {}).get("merge_commit_sha") or "")
        in_main = bool(merge_sha and client.branch_contains_commit(repo_for_api, "main", merge_sha))
        return lifecycle_from_github(run, pr, issue, in_main)

    if is_recoverable_failed_candidate(run):
        # Recovery-Erkennung bleibt bewusst flach: Branch-Suche zuerst, danach
        # eine einfache PR-Suche zur Issue-Nummer statt Timeline-/Review-Replikation.
        pulls = client.get_pull_requests_for_branch(repo_for_api, run.branch)
        pr = select_merged_pull_request(pulls)
        if not pr and run.issue_number and hasattr(client, "get_pull_requests_for_issue"):
            pr = select_merged_pull_request(client.get_pull_requests_for_issue(repo_for_api, run.issue_number))
        if not pr:
            return run

        issue = client.get_issue(repo_for_api, run.issue_number) if run.issue_number else None
        merge_sha = str(pr.get("merge_commit_sha") or "")
        in_main = bool(merge_sha and client.branch_contains_commit(repo_for_api, "main", merge_sha))
        return recovered_lifecycle_from_github(run, pr, issue, in_main)

    if is_failed_with_closed_issue(run):
        issue = client.get_issue(repo_for_api, run.issue_number) if run.issue_number else None
        return superseded_lifecycle_from_github(run, issue)

    return run


def enrich_runs_with_github(runs: list[DashboardRun], owner: str | None, token: str | None,
                            cache_path: Path = DEFAULT_GITHUB_CACHE,
                            cache_ttl_seconds: int = DEFAULT_GITHUB_CACHE_TTL_SECONDS,
                            client: DashboardGitHubClient | None = None,
                            now_fn=datetime.now) -> GitHubEnrichmentResult:
    fallback_runs = with_fallback_lifecycle(runs)
    eligible = [
        run for run in runs
        if run.category == "successful"
        or is_recoverable_failed_candidate(run)
        or is_failed_with_closed_issue(run)
    ]
    if not eligible:
        return GitHubEnrichmentResult(fallback_runs, used_github=False, used_cache=False)

    cached_entries = load_github_cache(cache_path, cache_ttl_seconds, now_fn=now_fn)
    if cached_entries is not None:
        enriched = [
            run_from_lifecycle_cache(run, cached_entries[lifecycle_cache_key(run, owner)])
            if lifecycle_cache_key(run, owner) in cached_entries
            else fallback_lifecycle_for_run(run) if run.category == "successful" else run
            for run in runs
        ]
        return GitHubEnrichmentResult(enriched, used_github=False, used_cache=True)

    if client is None:
        if requests is None:
            return GitHubEnrichmentResult(
                fallback_runs,
                used_github=False,
                used_cache=False,
                error="requests ist nicht installiert",
            )
        if not owner or is_placeholder_value(token):
            return GitHubEnrichmentResult(fallback_runs, used_github=False, used_cache=False)
        client = DashboardGitHubClient(str(token), owner)

    entries: dict[str, dict] = {}
    enriched_runs = []
    try:
        for run in runs:
            enriched = enrich_single_run_from_github(run, owner, client)
            enriched_runs.append(enriched)
            if run.category == "successful" or is_recoverable_failed_candidate(run) or is_failed_with_closed_issue(run):
                entries[lifecycle_cache_key(run, owner)] = run_to_lifecycle_cache(enriched)
    except Exception as exc:  # Dashboard-Generierung darf nicht an GitHub scheitern.
        return GitHubEnrichmentResult(
            fallback_runs,
            used_github=False,
            used_cache=False,
            error=str(exc).splitlines()[0][:200],
        )

    try:
        write_github_cache(cache_path, entries)
    except OSError:
        pass
    return GitHubEnrichmentResult(enriched_runs, used_github=True, used_cache=False)


def format_datetime(value: datetime | None) -> str:
    if not value:
        return "unbekannt"
    return value.strftime("%Y-%m-%d %H:%M:%S")


def render_link(url: str, label: str) -> str:
    return f'<a href="{escape(url, quote=True)}">{escape(label)}</a>'


def render_issue_cell(run: DashboardRun) -> str:
    if not run.issue_number:
        return "-"

    issue = escape(f"#{run.issue_number}")
    if not run.issue_title:
        return issue
    return (
        f'<div class="issue-number">{issue}</div>'
        f'<div class="issue-title">{escape(run.issue_title)}</div>'
    )


def render_lifecycle_cell(run: DashboardRun) -> str:
    if not run.lifecycle_label:
        return "-"
    attention = " · action" if run.lifecycle_needs_attention else " · done"
    note = f'<div class="note">{escape(run.lifecycle_note)}</div>' if run.lifecycle_note else ""
    state = run.lifecycle_state or "unknown"
    return (
        f'<span class="lifecycle lifecycle-{escape(state)}">'
        f'{escape(run.lifecycle_label)}'
        f'<small>{escape(attention)}</small>'
        "</span>"
        f"{note}"
    )


def render_run_row(run: DashboardRun, owner: str | None, output_path: Path) -> str:
    links = github_links(run, owner)
    run_link = run.path / "summary.txt"
    try:
        href = os.path.relpath(run_link, output_path.parent)
    except ValueError:
        href = str(run_link)

    actions = [render_link(href, "Summary")]
    if "issue" in links:
        actions.append(render_link(links["issue"], f"Issue #{run.issue_number}"))
    if "branch" in links:
        actions.append(render_link(links["branch"], "Branch"))
    if "pr" in links:
        actions.append(render_link(links["pr"], "Pull Request"))
    if run.preserved_worktree:
        actions.append(f"<code>{escape(run.preserved_worktree)}</code>")

    tail = ""
    if run.git_diff_stat:
        tail += (
            "<details><summary>Diff stat</summary>"
            f"<pre>{escape(run.git_diff_stat)}</pre></details>"
        )
    if run.output_tail:
        tail += (
            "<details><summary>Output tail</summary>"
            f"<pre>{escape(run.output_tail)}</pre></details>"
        )

    note_parts = []
    if run.base_branch:
        note_parts.append(f"Base-Branch: <code>{escape(run.base_branch)}</code>")
    if run.note:
        note_parts.append(escape(run.note))
    if run.health_reason:
        note_parts.append(f"Health: {escape(run.health_reason)}")
    if run.recovery_hint:
        note_parts.append(f"Hinweis: {escape(run.recovery_hint)}")
    if run.preserved_worktree:
        note_parts.append(f"Recovery-Worktree: <code>{escape(run.preserved_worktree)}</code>")
    note = f"<div class=\"note\">{'<br>'.join(note_parts)}</div>" if note_parts else ""
    last_activity = escape(format_datetime(run.last_activity_at))
    return "\n".join([
        "<tr>",
        f'  <td><span class="badge badge-{escape(run.category)}">{escape(STATUS_LABELS[run.category])}</span></td>',
        f"  <td>{escape(format_datetime(run.created_at))}</td>",
        f"  <td>{escape(run.repo or '-')}</td>",
        f"  <td>{render_issue_cell(run)}</td>",
        f"  <td><code>{escape(run.branch or '-')}</code></td>",
        f"  <td>{render_lifecycle_cell(run)}</td>",
        f"  <td>{escape(run.model or '-')}</td>",
        f"  <td>{escape(run.worker_exit_code or '-')}</td>",
        f"  <td>{escape(run.status)}<div class=\"note\">Letzte Aktivitaet: {last_activity}</div>{note}{tail}</td>",
        f"  <td>{' '.join(actions)}</td>",
        "</tr>",
    ])


def classify_issue_cluster(issue: DashboardIssue) -> tuple[str, str]:
    text = f"{issue.title} {issue.repo}".lower()
    if "repolens" in text:
        return "repolens", "mittel"
    if any(word in text for word in ("dashboard", "scheduler", "cluster")):
        return "control-center", "mittel"
    if any(word in text for word in ("mistral", "opencode", "codex", "provider", "worker")):
        return "provider", "mittel"
    if any(word in text for word in ("doc", "language", "policy", "readme")):
        return "docs", "niedrig"
    return "general", "unbekannt"


def recommended_provider_for_issue(issue: DashboardIssue) -> str:
    cluster, _ = classify_issue_cluster(issue)
    if cluster == "docs":
        return "opencode"
    if cluster in {"provider", "control-center", "repolens"}:
        return "opencode"
    return "opencode"


def issue_solver_command(issue: DashboardIssue, provider: str, dry_run: bool) -> str:
    parts = [
        "python",
        "scripts/solve_issues.py",
        "--model",
        provider,
        "--repo",
        issue.repo,
        "--issue",
        issue.number,
        "--base-branch",
        "develop",
    ]
    if dry_run:
        parts.append("--dry-run")
    return " ".join(shlex.quote(part) for part in parts)


def render_command_block(command: str, label: str) -> str:
    return (
        f'<div class="command-label">{escape(label)}</div>'
        f'<code class="command">{escape(command)}</code>'
    )


def render_unstarted_issue_row(issue: DashboardIssue) -> str:
    updated = escape(issue.updated_at[:19].replace("T", " ") if issue.updated_at else "-")
    provider = recommended_provider_for_issue(issue)
    cluster, risk = classify_issue_cluster(issue)
    dry_run_command = issue_solver_command(issue, provider, dry_run=True)
    start_command = issue_solver_command(issue, provider, dry_run=False)
    actions = []
    if issue.html_url:
        actions.append(render_link(issue.html_url, f"Issue #{issue.number}"))
    actions.extend([
        render_command_block(dry_run_command, "Dry-run"),
        render_command_block(start_command, "Start"),
    ])
    return "\n".join([
        "<tr>",
        '  <td><span class="badge badge-queued">Open</span></td>',
        f"  <td>{updated}</td>",
        f"  <td>{escape(issue.repo or '-')}</td>",
        f"  <td><div class=\"issue-number\">#{escape(issue.number)}</div>"
        f"<div class=\"issue-title\">{escape(issue.title)}</div></td>",
        f"  <td><code>{escape(provider)}</code></td>",
        f"  <td><code>{escape(cluster)}</code><div class=\"note\">Konfliktrisiko: {escape(risk)}</div></td>",
        f"  <td>{escape(issue.state or 'open')}</td>",
        f"  <td>{''.join(actions)}</td>",
        "</tr>",
    ])


def render_unstarted_issues_section(unstarted_issues: list[DashboardIssue]) -> str:
    if not unstarted_issues:
        return ""
    rows = "\n".join(render_unstarted_issue_row(issue) for issue in unstarted_issues)
    return f"""
    <section class="section-block">
      <h2>Offene Issues ohne Run</h2>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Status</th>
              <th>Aktualisiert</th>
              <th>Repo</th>
              <th>Issue</th>
              <th>Provider</th>
              <th>Cluster</th>
              <th>State</th>
              <th>Aktionen</th>
            </tr>
          </thead>
          <tbody>
            {rows}
          </tbody>
        </table>
      </div>
    </section>
"""


def render_dashboard(runs: list[DashboardRun], owner: str | None, output_path: Path,
                     generated_at: datetime | None = None,
                     allow_shutdown: bool = False,
                     refresh_seconds: int | None = None,
                     unstarted_issues: list[DashboardIssue] | None = None) -> str:
    runs = [
        fallback_lifecycle_for_run(run)
        if run.category == "successful" and not run.lifecycle_label
        else run
        for run in runs
    ]
    generated_at = generated_at or datetime.now()
    counts = {category: 0 for category in STATUS_ORDER}
    for run in runs:
        counts[run.category] = counts.get(run.category, 0) + 1

    rows = "\n".join(render_run_row(run, owner, output_path) for run in runs)
    if not rows:
        rows = (
            '<tr><td colspan="10" class="empty">'
            "Keine Run-Reports unter reports/runs/ gefunden."
            "</td></tr>"
        )

    cards = "\n".join(
        f'<section class="metric metric-{category}">'
        f'<span>{escape(STATUS_LABELS[category])}</span>'
        f'<strong>{counts.get(category, 0)}</strong>'
        "</section>"
        for category in STATUS_ORDER
    )
    unstarted_section = render_unstarted_issues_section(unstarted_issues or [])

    refresh_meta = ""
    refresh_label = ""
    if refresh_seconds and refresh_seconds > 0:
        refresh_meta = f'<meta http-equiv="refresh" content="{int(refresh_seconds)}">'
        refresh_label = f'<span class="refresh-label">Auto-refresh: {int(refresh_seconds)}s</span>'

    shutdown_button = ""
    shutdown_script = ""
    if allow_shutdown:
        shutdown_button = (
            '<button class="shutdown-button" type="button" onclick="shutdownServer()">'
            'Dashboard-Server beenden'
            '</button>'
        )
        shutdown_script = """
  <script>
    async function shutdownServer() {
      const button = document.querySelector('.shutdown-button');
      if (button) {
        button.disabled = true;
        button.textContent = 'Server wird beendet...';
      }
      try {
        await fetch('/__shutdown__', { method: 'POST' });
        const notice = document.querySelector('.shutdown-notice');
        if (notice) {
          notice.textContent = 'Dashboard-Server wurde beendet. Dieses Fenster kann offen bleiben.';
        }
      } catch (error) {
        const notice = document.querySelector('.shutdown-notice');
        if (notice) {
          notice.textContent = 'Server konnte nicht per Button beendet werden. Terminal mit Ctrl+C stoppen.';
        }
        if (button) {
          button.disabled = false;
          button.textContent = 'Dashboard-Server beenden';
        }
      }
    }
  </script>
"""

    return f"""<!doctype html>
<html lang="de">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>AI Issue Solver Status Dashboard</title>
  {refresh_meta}
  <style>
    :root {{
      color-scheme: light;
      --bg: #f6f7f9;
      --panel: #ffffff;
      --text: #172026;
      --muted: #64707d;
      --line: #d8dee6;
      --queued: #946200;
      --running: #276ef1;
      --unhealthy: #d97706;
      --success: #18794e;
      --failed: #c92a2a;
      --recovered: #0f766e;
      --superseded: #6b7280;
      --noop: #6b7280;
      --archived: #7c4a03;
      --unknown: #8a63d2;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font: 14px/1.45 system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }}
    header {{
      padding: 28px 32px 18px;
      border-bottom: 1px solid var(--line);
      background: var(--panel);
    }}
    h1 {{ margin: 0 0 6px; font-size: 26px; letter-spacing: 0; }}
    h2 {{ margin: 0 0 12px; font-size: 18px; letter-spacing: 0; }}
    .meta {{ color: var(--muted); }}
    .header-row {{ display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; }}
    .shutdown-button {{
      border: 1px solid #b42318;
      background: #c92a2a;
      color: #fff;
      border-radius: 6px;
      padding: 9px 12px;
      font: inherit;
      cursor: pointer;
    }}
    .shutdown-button:disabled {{ opacity: .65; cursor: default; }}
    .shutdown-notice {{ margin-top: 6px; color: var(--muted); min-height: 20px; }}
    .refresh-label {{ display: inline-block; margin-top: 6px; color: var(--muted); }}
    main {{ padding: 24px 32px 36px; }}
    .metrics {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
      gap: 12px;
      margin-bottom: 22px;
    }}
    .metric {{
      border-left: 5px solid var(--line);
      background: var(--panel);
      padding: 14px 16px;
      border-radius: 6px;
      box-shadow: 0 1px 2px rgb(0 0 0 / 6%);
    }}
    .metric span {{ display: block; color: var(--muted); font-size: 13px; }}
    .metric strong {{ display: block; margin-top: 4px; font-size: 28px; }}
    .metric-queued {{ border-color: var(--queued); }}
    .metric-running {{ border-color: var(--running); }}
    .metric-unhealthy {{ border-color: var(--unhealthy); }}
    .metric-successful {{ border-color: var(--success); }}
    .metric-failed {{ border-color: var(--failed); }}
    .metric-recovered {{ border-color: var(--recovered); }}
    .metric-superseded {{ border-color: var(--superseded); }}
    .metric-noop {{ border-color: var(--noop); }}
    .metric-archived {{ border-color: var(--archived); }}
    .metric-unknown {{ border-color: var(--unknown); }}
    .table-wrap {{
      overflow-x: auto;
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 6px;
    }}
    .section-block {{ margin-bottom: 22px; }}
    table {{ width: 100%; border-collapse: collapse; min-width: 980px; }}
    th, td {{ padding: 10px 12px; border-bottom: 1px solid var(--line); text-align: left; vertical-align: top; }}
    th {{ color: var(--muted); font-size: 12px; text-transform: uppercase; letter-spacing: .04em; background: #fbfcfd; }}
    tr:last-child td {{ border-bottom: 0; }}
    code {{ font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 12px; }}
    a {{ color: #1259c3; text-decoration: none; margin-right: 10px; white-space: nowrap; }}
    a:hover {{ text-decoration: underline; }}
    .badge {{
      display: inline-block;
      min-width: 82px;
      padding: 3px 8px;
      border-radius: 999px;
      color: #fff;
      font-size: 12px;
      text-align: center;
    }}
    .badge-queued {{ background: var(--queued); }}
    .badge-running {{ background: var(--running); }}
    .badge-unhealthy {{ background: var(--unhealthy); }}
    .badge-successful {{ background: var(--success); }}
    .badge-failed {{ background: var(--failed); }}
    .badge-recovered {{ background: var(--recovered); }}
    .badge-superseded {{ background: var(--superseded); }}
    .badge-noop {{ background: var(--noop); }}
    .badge-archived {{ background: var(--archived); }}
    .badge-unknown {{ background: var(--unknown); }}
    .note {{ margin-top: 4px; color: var(--muted); }}
    .command-label {{ margin-top: 6px; color: var(--muted); font-size: 12px; }}
    .command {{
      display: block;
      max-width: 520px;
      margin-top: 2px;
      padding: 6px 8px;
      white-space: normal;
      overflow-wrap: anywhere;
      background: #f3f5f7;
      border: 1px solid var(--line);
      border-radius: 5px;
    }}
    .lifecycle {{
      display: inline-flex;
      align-items: center;
      gap: 5px;
      min-width: 112px;
      padding: 3px 8px;
      border-radius: 999px;
      background: #eef2f7;
      color: #27313c;
      font-size: 12px;
      font-weight: 650;
      white-space: nowrap;
    }}
    .lifecycle small {{ color: var(--muted); font-weight: 500; }}
    .lifecycle-pr-open, .lifecycle-merged, .lifecycle-pr-closed, .lifecycle-unknown {{ background: #fff4d6; color: #6f4500; }}
    .lifecycle-merged-issue-open {{ background: #fef3c7; color: #92400e; }}
    .lifecycle-recovered {{ background: #ccfbf1; color: #115e59; }}
    .lifecycle-recovered-issue-open {{ background: #fde68a; color: #92400e; }}
    .lifecycle-in-main {{ background: #dbeafe; color: #174ea6; }}
    .lifecycle-in-main-issue-open {{ background: #bfdbfe; color: #1e40af; }}
    .lifecycle-issue-closed, .lifecycle-done {{ background: #dcfce7; color: #166534; }}
    .issue-number {{ font-weight: 700; white-space: nowrap; }}
    .issue-title {{ max-width: 320px; margin-top: 2px; color: var(--text); overflow-wrap: anywhere; }}
    details {{ margin-top: 6px; }}
    summary {{ cursor: pointer; color: #1259c3; }}
    pre {{
      max-width: 620px;
      max-height: 260px;
      overflow: auto;
      margin: 8px 0 0;
      padding: 10px;
      background: #111827;
      color: #e5e7eb;
      border-radius: 5px;
      font-size: 12px;
    }}
    .empty {{ text-align: center; color: var(--muted); padding: 28px; }}
    @media (max-width: 720px) {{
      header, main {{ padding-left: 16px; padding-right: 16px; }}
      h1 {{ font-size: 22px; }}
    }}
  </style>
</head>
<body>
  <header>
    <div class="header-row">
      <div>
        <h1>AI Issue Solver Status Dashboard</h1>
        <div class="meta">Generiert: {escape(format_datetime(generated_at))} · Runs: {len(runs)}</div>
        {refresh_label}
        <div class="shutdown-notice" aria-live="polite"></div>
      </div>
      <div>{shutdown_button}</div>
    </div>
  </header>
  <main>
    <section class="metrics" aria-label="Status-Zusammenfassung">
      {cards}
    </section>
    {unstarted_section}
    <section class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Status</th>
            <th>Zeit</th>
            <th>Repo</th>
            <th>Issue</th>
            <th>Branch</th>
            <th>Lifecycle</th>
            <th>Modell</th>
            <th>Exit</th>
            <th>Details</th>
            <th>Links</th>
          </tr>
        </thead>
        <tbody>
          {rows}
        </tbody>
      </table>
    </section>
  </main>
  {shutdown_script}
</body>
</html>
"""


def write_dashboard(runs: list[DashboardRun], output_path: Path,
                    owner: str | None = None,
                    allow_shutdown: bool = False,
                    refresh_seconds: int | None = None,
                    github_enrich: bool = False,
                    github_token: str | None = None,
                    github_cache_path: Path = DEFAULT_GITHUB_CACHE,
                    github_cache_ttl_seconds: int = DEFAULT_GITHUB_CACHE_TTL_SECONDS) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    effective_owner = owner or infer_owner_from_runs(runs)
    unstarted_issues: list[DashboardIssue] = []
    github_client = None
    if requests is not None and effective_owner and not is_placeholder_value(github_token):
        github_client = DashboardGitHubClient(str(github_token), effective_owner)
    if github_enrich:
        enrichment = enrich_runs_with_github(
            runs,
            effective_owner,
            github_token,
            cache_path=github_cache_path,
            cache_ttl_seconds=github_cache_ttl_seconds,
            client=github_client,
        )
        runs = enrichment.runs
    else:
        runs = with_fallback_lifecycle(runs)
    if github_client is not None:
        try:
            unstarted_issues = find_unstarted_issues(runs, effective_owner, client=github_client)
        except Exception:
            unstarted_issues = []
    output_path.write_text(
        render_dashboard(
            runs,
            effective_owner,
            output_path,
            allow_shutdown=allow_shutdown,
            refresh_seconds=refresh_seconds,
            unstarted_issues=unstarted_issues,
        ),
        encoding="utf-8",
    )
    return output_path


def print_cleanup_preview(result: CleanupResult) -> None:
    mode = "Dry-run" if result.dry_run else "Apply"
    print(f"   Modus: {mode}")
    print(f"   Zielstatus: {result.target_status}")
    print(f"   Cutoff: {format_datetime(result.cutoff)}")
    print(f"   Kandidaten: {len(result.candidates)}")
    for run in result.candidates:
        print(
            "   - "
            f"{run.name} | {format_datetime(run.created_at)} | "
            f"{run.category} | {run.repo or '-'} | "
            f"Issue {run.issue_number or '-'}"
        )
    if result.dry_run and result.candidates:
        print("   Keine Dateien geaendert. Mit --apply wirklich markieren.")
    if not result.dry_run:
        print(f"   Geaenderte summary.txt-Dateien: {len(result.changed)}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Erzeugt ein lokales HTML-Dashboard aus reports/runs/."
    )
    parser.add_argument("--runs-dir", default=str(DEFAULT_RUNS_DIR), help="Run-Report-Verzeichnis")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="Zielpfad fuer die HTML-Datei")
    parser.add_argument("--owner", help="GitHub Owner fuer Issue- und Branch-Links")
    parser.add_argument(
        "--cleanup-stale",
        action="store_true",
        help="Alte running/unhealthy/unknown Run-Reports zuerst als Dry-run anzeigen",
    )
    parser.add_argument(
        "--mark",
        choices=sorted(CLEANUP_STATUS_VALUES),
        default="archived",
        help="Zielstatus fuer --cleanup-stale, Standard: archived",
    )
    parser.add_argument(
        "--older-than-days",
        type=int,
        default=7,
        help="Nur Runs aelter als diese Anzahl Tage markieren, Standard: 7",
    )
    parser.add_argument(
        "--include-undated",
        action="store_true",
        help="Auch Runs ohne parsbares Datum als Cleanup-Kandidaten aufnehmen",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Cleanup wirklich schreiben; ohne diese Option bleibt es beim Dry-run",
    )
    parser.add_argument(
        "--health-timeout-minutes",
        type=int,
        default=int(os.environ.get("AI_SOLVER_HEALTH_TIMEOUT_MINUTES", DEFAULT_HEALTH_TIMEOUT_MINUTES)),
        help=f"Running-Runs nach so vielen Minuten ohne Aktivitaet als unhealthy markieren, Standard: {DEFAULT_HEALTH_TIMEOUT_MINUTES}",
    )
    parser.add_argument(
        "--github-enrich",
        action="store_true",
        help="Erfolgreiche Runs optional per GitHub API um PR-/Merge-/Issue-Status anreichern",
    )
    parser.add_argument(
        "--github-cache",
        default=str(DEFAULT_GITHUB_CACHE),
        help="Cache-Datei fuer GitHub-Lifecycle-Daten",
    )
    parser.add_argument(
        "--github-cache-ttl-seconds",
        type=int,
        default=DEFAULT_GITHUB_CACHE_TTL_SECONDS,
        help=f"GitHub-Cache-TTL in Sekunden, Standard: {DEFAULT_GITHUB_CACHE_TTL_SECONDS}; -1 nutzt Cache ohne Ablauf",
    )
    args = parser.parse_args()

    config = load_env()
    owner = args.owner or config.get("GITHUB_USER")
    runs_dir = Path(args.runs_dir)
    output_path = Path(args.output)
    if args.health_timeout_minutes < 1:
        print("Fehler: --health-timeout-minutes muss mindestens 1 sein", file=sys.stderr)
        return 2

    if args.cleanup_stale:
        print_banner("STALE RUN-REPORTS BEREINIGEN")
        print_step(1, f"Pruefe alte Run-Reports in {runs_dir}")
        try:
            result = cleanup_stale_runs(
                runs_dir,
                mark=args.mark,
                older_than_days=args.older_than_days,
                apply=args.apply,
                include_undated=args.include_undated,
            )
        except ValueError as exc:
            print(f"Fehler: {exc}", file=sys.stderr)
            return 2
        print_cleanup_preview(result)
        return 0

    print_banner("STATUS-DASHBOARD GENERIEREN")
    print_step(1, f"Lese Run-Reports aus {runs_dir}")
    runs = read_runs(runs_dir, health_timeout_minutes=args.health_timeout_minutes)
    print(f"   Gefundene Runs: {len(runs)}")

    print_step(2, f"Schreibe HTML nach {output_path}")
    if args.github_enrich:
        print("   GitHub-Enrichment: an (mit Cache/Fallback)")
    write_dashboard(
        runs,
        output_path,
        owner=owner,
        github_enrich=args.github_enrich,
        github_token=config.get("GITHUB_TOKEN"),
        github_cache_path=Path(args.github_cache),
        github_cache_ttl_seconds=args.github_cache_ttl_seconds,
    )
    print(f"   Dashboard: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
