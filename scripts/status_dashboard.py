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
from workflow_congestion import (  # noqa: E402
    WorkflowCongestionSummary,
    analyze_workflow_congestion,
    issue_from_github,
    pull_request_from_github,
)

try:
    from solver_supervisor import (  # noqa: E402
        DEFAULT_STALE_SECONDS,
        get_supervisor_summary,
        format_stop_command,
    )
except ImportError:
    get_supervisor_summary = None
    format_stop_command = None
    DEFAULT_STALE_SECONDS = 900


DEFAULT_RUNS_DIR = Path("reports") / "runs"
DEFAULT_OUTPUT = Path("reports") / "status-dashboard.html"
DEFAULT_GITHUB_CACHE = Path("reports") / "status-dashboard.github-cache.json"
DEFAULT_HEALTH_TIMEOUT_MINUTES = 60
DEFAULT_GITHUB_CACHE_TTL_SECONDS = 600
DEFAULT_WORKFLOW_PR_THRESHOLD = 3
DEFAULT_WORKFLOW_STALE_DAYS = 7
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

# =============================================================================
# Status-Konstanten und Klassifizierung
# =============================================================================

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

# Solver-Status-Werte: Gruppen für die Klassifizierung
SUCCESS_STATUSES = {
    "pr_created",
    "pr_created_with_warning",
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


# =============================================================================
# Run-Prädikate für Klassifizierung und Lifecycle
# =============================================================================

def has_preserved_worktree(run: DashboardRun) -> bool:
    """Prüft ob der Run ein erhaltenes Working Directory hat (Recovery möglich)."""
    return bool(run.preserved_worktree)


def has_issue_number(run: DashboardRun) -> bool:
    """Prüft ob der Run eine verknüpfte Issue-Nummer hat."""
    return bool(run.issue_number)


def has_branch(run: DashboardRun) -> bool:
    """Prüft ob der Run einen Branch hat."""
    return bool(run.branch)


def is_recoverable_failed(run: DashboardRun) -> bool:
    """
    Prüft ob ein fehlgeschlagener Run potenziell wiederhergestellt werden kann.

    Ein Run gilt als wiederherstellbar wenn:
    - Er den Status "failed" hat
    - Ein preserved_worktree existiert
    - Ein Branch vorhanden ist
    - Eine Issue-Nummer verknüpft ist
    """
    return bool(
        run.category == "failed"
        and has_preserved_worktree(run)
        and has_branch(run)
        and has_issue_number(run)
    )


def is_failed_with_closed_issue_candidate(run: DashboardRun) -> bool:
    """
    Prüft ob ein fehlgeschlagener Run potenziell als "superseded" markiert werden kann.

    Ein Run gilt als Kandidat für Superseded wenn:
    - Er den Status "failed" hat
    - Eine Issue-Nummer verknüpft ist
    - KEIN preserved_worktree existiert (also kein Recovery möglich)
    """
    return bool(
        run.category == "failed"
        and has_issue_number(run)
        and not has_preserved_worktree(run)
    )


@dataclass(frozen=True)
class DashboardIssue:
    number: str
    title: str
    repo: str
    html_url: str
    state: str
    created_at: str
    updated_at: str
    priority: int | None = None
    risk: str = "unbekannt"
    cluster: str = "general"


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

    # Neue Felder für Kosten, Laufzeit und Priorisierung
    runtime_seconds: int | None = None
    cost_estimate: float | None = None
    cost_confidence: str = "unavailable"
    priority: int | None = None
    provider: str = ""
    run_outcome_worker_status: str = ""
    run_outcome_has_changes: bool = False
    run_outcome_test_status: str = ""
    run_outcome_delivery_status: str = ""
    run_outcome_failure_class: str = ""
    run_outcome_recovery_status: str = ""
    
    # Provider-Scorecard Felder
    provider_scorecard_requested_model: str = ""
    provider_scorecard_actual_model: str = ""
    provider_scorecard_fallback_source: str = ""
    provider_scorecard_duration_seconds: int | None = None
    provider_scorecard_worker_exit_code: int | None = None
    provider_scorecard_run_status: str = ""
    provider_scorecard_pr_url: str = ""
    provider_scorecard_test_command: str = ""
    provider_scorecard_test_result: str = ""
    provider_scorecard_no_change: bool = False
    provider_scorecard_fallback_used: bool = False
    
    # Kosteninformationen
    provider_scorecard_estimated_cost: float | None = None
    provider_scorecard_cost_currency: str | None = None
    provider_scorecard_cost_confidence: str | None = None
    provider_scorecard_cost_source: str | None = None


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


@dataclass(frozen=True)
class RepoSummary:
    """Zusammenfassung der Run-Statistiken für ein Repository."""
    name: str
    total: int
    successful: int
    failed: int
    noop: int
    recovered: int
    superseded: int
    queued: int
    running: int
    unhealthy: int
    archived: int
    unknown: int
    needs_attention: int

    # Neue Felder für Kosten und Laufzeit
    total_runtime_seconds: int = 0
    total_cost_estimate: float = 0.0
    avg_runtime_seconds: float = 0.0
    avg_cost_estimate: float = 0.0
    
    # Provider-Scorecard Felder
    total_provider_duration: int = 0
    avg_provider_duration_seconds: float = 0.0
    fallback_rate: float = 0.0
    no_change_rate: float = 0.0
    pr_rate: float = 0.0


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

    def get_open_pull_requests(self, repo: str) -> list[dict]:
        data = self.get_json(
            f"{self.repo_api_path(repo)}/pulls",
            state="open",
            sort="updated",
            direction="desc",
            per_page=100,
        )
        return data if isinstance(data, list) else []

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


# =============================================================================
# Status-Klassifizierungsfunktionen
# =============================================================================

def classify_status(status: str, worker_exit_code: str = "") -> str:
    """
    Klassifiziert einen Solver-Status in eine Dashboard-Kategorie.

    Args:
        status: Der Roh-Status aus dem Run-Report (z.B. "pr_created", "started")
        worker_exit_code: Der Exit-Code des Workers (für Fallback-Klassifizierung)

    Returns:
        Die Dashboard-Kategorie: queued, running, unhealthy, failed, recovered,
        superseded, successful, noop, archived, oder unknown
    """
    if not status:
        return "unknown"

    # Direkte Zuordnung für spezifische Zustände
    if status == "queued":
        return "queued"
    if status == "started":
        return "running"

    # Zuordnung über Status-Gruppen
    if status in ARCHIVED_STATUSES:
        return "archived"
    if status in SUCCESS_STATUSES:
        return "successful"
    if status in NOOP_STATUSES:
        return "noop"
    if status in FAILED_STATUSES or status.endswith("_failed"):
        return "failed"

    # Fallback: Nicht-Null Exit-Code = failed
    if worker_exit_code and worker_exit_code != "0":
        return "failed"

    # Default für unbekannte erfolgreiche Zustände
    return "noop"


# =============================================================================
# Gesundheitsprüfung für Runs
# =============================================================================

@dataclass(frozen=True)
class HealthCheckResult:
    """Ergebnis der Gesundheitsprüfung für einen Run."""
    category: str
    health_status: str
    health_reason: str
    recovery_hint: str


def check_run_health(
    category: str,
    output_tail: str,
    last_progress_at: datetime | None,
    timeout: timedelta,
    now: datetime,
    run_dir: Path,
) -> HealthCheckResult:
    """
    Führt die Gesundheitsprüfung für einen Running-Run durch.

    Prüft ob ein Running-Run als "unhealthy" eingestuft werden muss aufgrund von:
    - Codex-Rate-Limit ohne Reset-Zeit
    - Fehlender Aktivitätszeit
    - Timeout seit letzter Aktivität

    Args:
        category: Die aktuelle Kategorie des Runs
        output_tail: Der Output-Tail für Rate-Limit-Prüfung
        last_progress_at: Zeitpunkt der letzten Aktivität
        timeout: Gesundheits-Timeout
        now: Aktueller Zeitpunkt
        run_dir: Das Verzeichnis des Runs (für Recovery-Hinweise)

    Returns:
        HealthCheckResult mit möglicherweise angepasster Kategorie und Gesundheitsinfo
    """
    # Prüfe Codex-Rate-Limit
    rate_limit_until = codex_rate_limit_wait_until(output_tail)
    in_known_wait = bool(rate_limit_until and rate_limit_until > now)

    if category == "running" and CODEX_RATE_LIMIT_MESSAGE_RE.search(output_tail):
        if not in_known_wait:
            # Rate-Limit ohne zukünftige Reset-Zeit = unhealthy
            return HealthCheckResult(
                category="unhealthy",
                health_status="unhealthy",
                health_reason="Codex-Rate-Limit ohne zukuenftige Reset-Zeit",
                recovery_hint=recovery_hint_for_unhealthy(run_dir),
            )
        else:
            # Rate-Limit mit bekannter Wartezeit = running mit Hinweis
            return HealthCheckResult(
                category="running",
                health_status="ok",
                health_reason=f"Codex-Rate-Limit-Wartezeit bis {format_datetime(rate_limit_until)}",
                recovery_hint="",
            )

    if category == "running" and not in_known_wait:
        if last_progress_at is None:
            # Keine Aktivitätszeit gefunden = unhealthy
            return HealthCheckResult(
                category="unhealthy",
                health_status="unhealthy",
                health_reason="keine Aktivitaetszeit im Run-Report gefunden",
                recovery_hint=recovery_hint_for_unhealthy(run_dir),
            )
        elif now - last_progress_at > timeout:
            # Timeout seit letzter Aktivität = unhealthy
            return HealthCheckResult(
                category="unhealthy",
                health_status="unhealthy",
                health_reason=(
                    "letzte sinnvolle Aktivitaet "
                    f"{format_datetime(last_progress_at)}; Timeout {int(timeout.total_seconds() / 60)} min"
                ),
                recovery_hint=recovery_hint_for_unhealthy(run_dir),
            )

    # Keine Gesundheitsprobleme erkannt
    return HealthCheckResult(
        category=category,
        health_status="ok",
        health_reason="",
        recovery_hint="",
    )


def read_runs(runs_dir: Path,
               health_timeout_minutes: int = DEFAULT_HEALTH_TIMEOUT_MINUTES,
               now_fn=datetime.now) -> list[DashboardRun]:
    """
    Liest alle Run-Reports aus dem angegebenen Verzeichnis.

    Args:
        runs_dir: Das Verzeichnis mit den Run-Reports
        health_timeout_minutes: Timeout in Minuten für Running-Runs
        now_fn: Funktion zur Bestimmung der aktuellen Zeit (für Tests)

    Returns:
        Liste von DashboardRun-Objekten
    """
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

        # Klassifiziere den Status
        category = classify_status(status, exit_code)

        # Führe Gesundheitsprüfung durch
        last_progress_at = latest_datetime(last_activity_at, last_report_update_at)
        health_result = check_run_health(
            category, output_tail, last_progress_at, timeout, now, run_dir
        )
        category = health_result.category
        health_status = health_result.health_status
        health_reason = health_result.health_reason
        recovery_hint = health_result.recovery_hint
        model = fields.get("model", "")
        fallback_from = fields.get("fallback_from", "")
        actual_model = fields.get("actual_model", "")
        if fallback_from and actual_model:
            model = f"{actual_model} (Fallback von {fallback_from})"

        # Neue Felder für Laufzeit, Kosten und Priorisierung
        runtime_seconds = int(fields.get("runtime_seconds", 0)) if fields.get("runtime_seconds") else None
        cost_estimate = float(fields.get("cost_estimate", 0.0)) if fields.get("cost_estimate") else None
        cost_confidence = fields.get("cost_confidence", "unavailable")
        priority = int(fields.get("priority", 0)) if fields.get("priority") else None
        provider = fields.get("provider", "")
        run_outcome_worker_status = fields.get("run_outcome_worker_status", "")
        run_outcome_has_changes = fields.get("run_outcome_has_changes", "").lower() in ("true", "1", "yes")
        run_outcome_test_status = fields.get("run_outcome_test_status", "")
        run_outcome_delivery_status = fields.get("run_outcome_delivery_status", "")
        run_outcome_failure_class = fields.get("run_outcome_failure_class", "")
        run_outcome_recovery_status = fields.get("run_outcome_recovery_status", "")
        
        # Provider-Scorecard Felder
        provider_scorecard_requested_model = fields.get("provider_scorecard_requested_model", "")
        provider_scorecard_actual_model = fields.get("provider_scorecard_actual_model", "")
        provider_scorecard_fallback_source = fields.get("provider_scorecard_fallback_source", "")
        provider_scorecard_duration_seconds = int(fields.get("provider_scorecard_duration_seconds", 0)) if fields.get("provider_scorecard_duration_seconds") else None
        provider_scorecard_worker_exit_code = int(fields.get("provider_scorecard_worker_exit_code", 0)) if fields.get("provider_scorecard_worker_exit_code") else None
        provider_scorecard_run_status = fields.get("provider_scorecard_run_status", "")
        provider_scorecard_pr_url = fields.get("provider_scorecard_pr_url", "")
        provider_scorecard_test_command = fields.get("provider_scorecard_test_command", "")
        provider_scorecard_test_result = fields.get("provider_scorecard_test_result", "")
        provider_scorecard_no_change = fields.get("provider_scorecard_no_change", "").lower() in ("true", "1", "yes")
        provider_scorecard_fallback_used = fields.get("provider_scorecard_fallback_used", "").lower() in ("true", "1", "yes")

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
                runtime_seconds=runtime_seconds,
                cost_estimate=cost_estimate,
                cost_confidence=cost_confidence,
                priority=priority,
                provider=provider,
                run_outcome_worker_status=run_outcome_worker_status,
                run_outcome_has_changes=run_outcome_has_changes,
                run_outcome_test_status=run_outcome_test_status,
                run_outcome_delivery_status=run_outcome_delivery_status,
                run_outcome_failure_class=run_outcome_failure_class,
                run_outcome_recovery_status=run_outcome_recovery_status,
                provider_scorecard_requested_model=provider_scorecard_requested_model,
                provider_scorecard_actual_model=provider_scorecard_actual_model,
                provider_scorecard_fallback_source=provider_scorecard_fallback_source,
                provider_scorecard_duration_seconds=provider_scorecard_duration_seconds,
                provider_scorecard_worker_exit_code=provider_scorecard_worker_exit_code,
                provider_scorecard_run_status=provider_scorecard_run_status,
                provider_scorecard_pr_url=provider_scorecard_pr_url,
                provider_scorecard_test_command=provider_scorecard_test_command,
                provider_scorecard_test_result=provider_scorecard_test_result,
                provider_scorecard_no_change=provider_scorecard_no_change,
                provider_scorecard_fallback_used=provider_scorecard_fallback_used,
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


def repos_for_workflow_status(runs: list[DashboardRun], unstarted_issues: list[DashboardIssue]) -> list[str]:
    repos = {run.repo for run in runs if run.repo}
    repos.update(issue.repo for issue in unstarted_issues if issue.repo)
    return sorted(repos)


def build_workflow_congestion_summaries(
    repos: list[str],
    client: DashboardGitHubClient | None,
    *,
    pr_threshold: int = DEFAULT_WORKFLOW_PR_THRESHOLD,
    stale_days: int = DEFAULT_WORKFLOW_STALE_DAYS,
) -> dict[str, WorkflowCongestionSummary]:
    if client is None:
        return {}
    summaries: dict[str, WorkflowCongestionSummary] = {}
    for repo in repos:
        raw_prs = client.get_open_pull_requests(repo)
        detailed_prs = []
        for pr in raw_prs:
            if isinstance(pr, dict) and not pr.get("mergeable_state") and pr.get("number"):
                detailed = client.get_pull_request(repo, pr["number"])
                if detailed:
                    pr = {**pr, **detailed}
            detailed_prs.append(pr)
        open_prs = [
            pull_request_from_github(pr)
            for pr in detailed_prs
        ]
        open_issues = [
            issue_from_github(issue)
            for issue in client.get_open_issues(repo)
        ]
        summaries[repo] = analyze_workflow_congestion(
            open_prs,
            open_issues,
            pr_threshold=pr_threshold,
            stale_days=stale_days,
        )
    return summaries


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


# =============================================================================
# Lifecycle-Helperfunktionen
# =============================================================================

def is_successful_pr_created(run: DashboardRun) -> bool:
    """Prüft ob ein Run erfolgreich mit PR-Erstellung abgeschlossen wurde."""
    return run.category == "successful" and run.status.startswith("pr_created")


def is_cleanup_successful(run: DashboardRun) -> bool:
    """Prüft ob ein Run ein erfolgreicher Cleanup-Run ist."""
    return run.category == "successful" and run.status == "cleanup_successful"


def fallback_lifecycle_for_run(run: DashboardRun) -> DashboardRun:
    """
    Erstellt einen Fallback-Lifecycle für Runs ohne GitHub-Daten.

    Args:
        run: Der DashboardRun

    Returns:
        Der Run mit Lifecycle-Informationen oder unverändert
    """
    if run.category != "successful":
        return run

    if is_successful_pr_created(run):
        note = "GitHub-Status nicht geladen; pruefe PR-Link."
        if run.status == "pr_created_with_warning":
            note = "GitHub-Status nicht geladen; PR erstellt aber mit Warnung (z.B. Turn-Limit erreicht). Pruefe PR-Link."
        return replace(
            run,
            lifecycle_label="PR created",
            lifecycle_state="unknown",
            lifecycle_needs_attention=True,
            lifecycle_note=note,
        )

    if is_cleanup_successful(run):
        return replace(
            run,
            lifecycle_label="Cleanup done",
            lifecycle_state="done",
            lifecycle_needs_attention=False,
            lifecycle_note="Lokaler Cleanup-Run ohne PR-Lifecycle.",
        )

    return run


def with_fallback_lifecycle(runs: list[DashboardRun]) -> list[DashboardRun]:
    """Wendet Fallback-Lifecycle auf alle Runs an."""
    return [fallback_lifecycle_for_run(run) for run in runs]


def pr_number_from_url(pr_url: str) -> str:
    match = GITHUB_PR_RE.match(pr_url or "")
    return match.group(3) if match else ""


def pr_number_from_data(pr: dict | None) -> str:
    if not pr:
        return ""
    return str(pr.get("number") or pr_number_from_url(str(pr.get("html_url") or "")))


# Kompatibilitäts-Aliase für bestehende Aufrufe (deprecated, aber für Backwards-Kompatibilität)
def is_recoverable_failed_candidate(run: DashboardRun) -> bool:
    """
    DEPRECATED: Verwende stattdessen is_recoverable_failed().

    Prüft ob ein fehlgeschlagener Run ein Recovery-Kandidat ist.
    """
    return is_recoverable_failed(run)


def is_failed_with_closed_issue(run: DashboardRun) -> bool:
    """
    DEPRECATED: Verwende stattdessen is_failed_with_closed_issue_candidate().

    Check if a failed run has a closed issue and should be marked as superseded.
    """
    return is_failed_with_closed_issue_candidate(run)


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
        if run.status == "pr_created_with_warning":
            note = (
                "Code ist in main und Issue ist geschlossen (PR mit Warnung, z.B. Turn-Limit erreicht)."
                if issue_closed
                else "Code ist in main; Issue ist noch offen (PR mit Warnung, z.B. Turn-Limit erreicht)."
                if issue else "Merge-Commit ist in main (PR mit Warnung, z.B. Turn-Limit erreicht)."
            )
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
        if run.status == "pr_created_with_warning":
            note = (
                "Issue ist geschlossen, aber main enthaelt den Merge-Commit noch nicht (PR mit Warnung, z.B. Turn-Limit erreicht)."
                if issue_closed
                else "PR gemergt, aber Issue ist noch offen (PR mit Warnung, z.B. Turn-Limit erreicht)."
            )
        return replace(
            run,
            lifecycle_label=label,
            lifecycle_state=state,
            lifecycle_needs_attention=True,
            lifecycle_note=note,
        )

    if pr and pr.get("state") == "open":
        note = "Review oder Merge steht noch aus."
        if run.status == "pr_created_with_warning":
            note = "PR offen, aber mit Warnung (z.B. Turn-Limit erreicht); Review oder Merge steht noch aus."
        return replace(
            run,
            lifecycle_label="PR open",
            lifecycle_state="pr-open",
            lifecycle_needs_attention=True,
            lifecycle_note=note,
        )

    if pr and pr.get("state") == "closed":
        note = "PR wurde ohne Merge geschlossen."
        if run.status == "pr_created_with_warning":
            note = "PR ohne Merge geschlossen, aber mit Warnung (z.B. Turn-Limit erreicht)."
        return replace(
            run,
            lifecycle_label="PR closed",
            lifecycle_state="pr-closed",
            lifecycle_needs_attention=True,
            lifecycle_note=note,
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
    """
    Reichert einen einzelnen Run mit GitHub-Lifecycle-Daten an.

    Args:
        run: Der zu anreichende Run
        owner: Der GitHub Owner
        client: Der GitHub API Client

    Returns:
        Der angereicherte Run (oder unverändert falls nicht anreichbar)
    """
    # Prüfe ob dieser Run für Anreicherung infrage kommt
    if run.category != "successful" and not is_recoverable_failed(run) and not is_failed_with_closed_issue_candidate(run):
        return run

    repo_owner = repo_owner_for_url(run.repo, owner)
    repo_name = repo_name_for_url(run.repo)
    if not repo_owner or not repo_name:
        return fallback_lifecycle_for_run(run)

    repo_for_api = run.repo if "/" in run.repo else repo_name

    # --- Erfolgreiche Runs: PR- und Issue-Status abfragen ---
    if run.category == "successful":
        pr = _fetch_pull_request_for_run(run, repo_for_api, client)
        issue = client.get_issue(repo_for_api, run.issue_number) if has_issue_number(run) else None
        merge_sha = str((pr or {}).get("merge_commit_sha") or "")
        in_main = bool(merge_sha and client.branch_contains_commit(repo_for_api, "main", merge_sha))
        return lifecycle_from_github(run, pr, issue, in_main)

    # --- Wiederherstellbare fehlgeschlagene Runs: Recovery erkennen ---
    if is_recoverable_failed(run):
        # Recovery-Erkennung bleibt bewusst flach: Branch-Suche zuerst, danach
        # eine einfache PR-Suche zur Issue-Nummer statt Timeline-/Review-Replikation.
        pulls = client.get_pull_requests_for_branch(repo_for_api, run.branch)
        pr = select_merged_pull_request(pulls)
        if not pr and has_issue_number(run) and hasattr(client, "get_pull_requests_for_issue"):
            pr = select_merged_pull_request(
                client.get_pull_requests_for_issue(repo_for_api, run.issue_number)
            )
        if not pr:
            return run

        issue = client.get_issue(repo_for_api, run.issue_number) if has_issue_number(run) else None
        merge_sha = str(pr.get("merge_commit_sha") or "")
        in_main = bool(merge_sha and client.branch_contains_commit(repo_for_api, "main", merge_sha))
        return recovered_lifecycle_from_github(run, pr, issue, in_main)

    # --- Fehlgeschlagene Runs mit geschlossener Issue: Superseded markieren ---
    if is_failed_with_closed_issue_candidate(run):
        issue = client.get_issue(repo_for_api, run.issue_number) if has_issue_number(run) else None
        return superseded_lifecycle_from_github(run, issue)

    return run


def _fetch_pull_request_for_run(run: DashboardRun, repo: str,
                                  client: DashboardGitHubClient) -> dict | None:
    """
    Holt die Pull Request Daten für einen Run.

    Sucht zuerst nach PR-Nummer in der URL, dann nach Branch.

    Args:
        run: Der DashboardRun
        repo: Das Repository für die API
        client: Der GitHub API Client

    Returns:
        Die PR-Daten oder None
    """
    pr = None
    pr_number = pr_number_from_url(run.pr_url)
    if pr_number:
        pr = client.get_pull_request(repo, pr_number)
    elif has_branch(run):
        prs = client.get_pull_requests_for_branch(repo, run.branch)
        pr = prs[0] if prs else None
    return pr


def enrich_runs_with_github(runs: list[DashboardRun], owner: str | None, token: str | None,
                            cache_path: Path = DEFAULT_GITHUB_CACHE,
                            cache_ttl_seconds: int = DEFAULT_GITHUB_CACHE_TTL_SECONDS,
                            client: DashboardGitHubClient | None = None,
                            now_fn=datetime.now) -> GitHubEnrichmentResult:
    """
    Reichert Runs mit GitHub-Lifecycle-Daten an (mit Cache-Unterstützung).

    Args:
        runs: Liste der DashboardRuns
        owner: GitHub Owner
        token: GitHub API Token
        cache_path: Pfad zur Cache-Datei
        cache_ttl_seconds: Cache TTL in Sekunden
        client: Optionaler GitHub Client
        now_fn: Funktion für aktuelle Zeit (für Tests)

    Returns:
        GitHubEnrichmentResult mit angereicherten Runs
    """
    fallback_runs = with_fallback_lifecycle(runs)

    # Bestimme welche Runs für Anreicherung infrage kommen
    eligible = [
        run for run in runs
        if run.category == "successful"
        or is_recoverable_failed(run)
        or is_failed_with_closed_issue_candidate(run)
    ]

    if not eligible:
        return GitHubEnrichmentResult(fallback_runs, used_github=False, used_cache=False)

    cached_entries = load_github_cache(cache_path, cache_ttl_seconds, now_fn=now_fn)
    if cached_entries is not None:
        # Cache-Treffer: Lifecycle aus Cache laden
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
            # Cache nur für Runs die Anreicherung benötigen
            if (run.category == "successful"
                or is_recoverable_failed(run)
                or is_failed_with_closed_issue_candidate(run)):
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


def format_provider_scorecard(run: DashboardRun) -> list[str]:
    """Formatiert die Provider-Scorecard für die Anzeige."""
    lines = []
    if not any(
        field for field in [
            run.provider_scorecard_requested_model,
            run.provider_scorecard_actual_model,
            run.provider_scorecard_duration_seconds,
            run.provider_scorecard_fallback_used,
            run.provider_scorecard_estimated_cost
        ]
    ):
        return lines

    lines.append("Provider Scorecard:")
    if run.provider_scorecard_requested_model:
        lines.append(f"  Requested: {run.provider_scorecard_requested_model}")
    if run.provider_scorecard_actual_model:
        lines.append(f"  Actual: {run.provider_scorecard_actual_model}")
    if run.provider_scorecard_fallback_used:
        lines.append(f"  Fallback: {run.provider_scorecard_fallback_source or 'unknown'} (used)")
    elif run.provider_scorecard_fallback_source:
        lines.append(f"  Fallback: {run.provider_scorecard_fallback_source} (not used)")
    if run.provider_scorecard_duration_seconds:
        lines.append(f"  Duration: {run.provider_scorecard_duration_seconds}s")
    if run.provider_scorecard_worker_exit_code is not None:
        lines.append(f"  Exit Code: {run.provider_scorecard_worker_exit_code}")
    if run.provider_scorecard_run_status:
        lines.append(f"  Status: {run.provider_scorecard_run_status}")
    if run.provider_scorecard_no_change:
        lines.append("  No Change: ✓")
    if run.provider_scorecard_test_result:
        lines.append(f"  Test: {run.provider_scorecard_test_result}")
    
    # Kosteninformationen anzeigen
    if run.provider_scorecard_estimated_cost is not None:
        cost_line = f"  Cost: {run.provider_scorecard_estimated_cost}"
        if run.provider_scorecard_cost_currency:
            cost_line += f" {run.provider_scorecard_cost_currency}"
        if run.provider_scorecard_cost_confidence:
            cost_line += f" ({run.provider_scorecard_cost_confidence} confidence)"
        if run.provider_scorecard_cost_source:
            cost_line += f" via {run.provider_scorecard_cost_source}"
        lines.append(cost_line)
    
    return lines


def format_datetime(value: datetime | None) -> str:
    if not value:
        return "unbekannt"
    return value.strftime("%Y-%m-%d %H:%M:%S")


def compute_repo_summaries(runs: list[DashboardRun]) -> list[RepoSummary]:
    """
    Berechnet Zusammenfassungen der Run-Statistiken pro Repository.

    Args:
        runs: Liste aller DashboardRuns

    Returns:
        Liste von RepoSummary-Objekten, sortiert nach Repository-Namen
    """
    repo_stats: dict[str, dict[str, int | float]] = {}

    for run in runs:
        repo_name = run.repo or "Unbekannt"
        if repo_name not in repo_stats:
            repo_stats[repo_name] = {
                "total": 0,
                "successful": 0,
                "failed": 0,
                "noop": 0,
                "recovered": 0,
                "superseded": 0,
                "queued": 0,
                "running": 0,
                "unhealthy": 0,
                "archived": 0,
                "unknown": 0,
                "needs_attention": 0,
                "total_runtime_seconds": 0,
                "total_cost_estimate": 0.0,
            }

        stats = repo_stats[repo_name]
        stats["total"] += 1

        # Zähle nach Kategorie
        if run.category in stats:
            stats[run.category] += 1

        # Zähle Runs die Aufmerksamkeit benötigen (lifecycle_needs_attention)
        if run.lifecycle_needs_attention:
            stats["needs_attention"] += 1

        # Summiere Laufzeit und Kosten
        if run.runtime_seconds:
            stats["total_runtime_seconds"] += run.runtime_seconds
        if run.cost_estimate:
            stats["total_cost_estimate"] += run.cost_estimate
        
        # Provider-Scorecard Statistiken
        if run.provider_scorecard_duration_seconds:
            stats.setdefault("total_provider_duration", 0)
            stats["total_provider_duration"] += run.provider_scorecard_duration_seconds
            stats.setdefault("provider_runs", 0)
            stats["provider_runs"] += 1
            
            if run.provider_scorecard_fallback_used:
                stats.setdefault("fallback_runs", 0)
                stats["fallback_runs"] += 1
            
            if run.provider_scorecard_no_change:
                stats.setdefault("no_change_runs", 0)
                stats["no_change_runs"] += 1
            
            if run.pr_url:
                stats.setdefault("pr_runs", 0)
                stats["pr_runs"] += 1

    # Konvertiere zu RepoSummary-Objekten und sortiere nach Namen
    summaries = []
    for repo_name, stats in repo_stats.items():
        total_runs = stats["total"]
        avg_runtime = stats["total_runtime_seconds"] / total_runs if total_runs > 0 else 0
        avg_cost = stats["total_cost_estimate"] / total_runs if total_runs > 0 else 0.0
        
        # Provider-Scorecard Statistiken
        avg_provider_duration = 0
        fallback_rate = 0.0
        no_change_rate = 0.0
        pr_rate = 0.0
        
        if "provider_runs" in stats and stats["provider_runs"] > 0:
            avg_provider_duration = stats["total_provider_duration"] / stats["provider_runs"]
            fallback_rate = (stats.get("fallback_runs", 0) / stats["provider_runs"]) * 100
            no_change_rate = (stats.get("no_change_runs", 0) / stats["provider_runs"]) * 100
            pr_rate = (stats.get("pr_runs", 0) / stats["provider_runs"]) * 100

        summaries.append(
            RepoSummary(
                name=repo_name,
                total=stats["total"],
                successful=stats["successful"],
                failed=stats["failed"],
                noop=stats["noop"],
                recovered=stats["recovered"],
                superseded=stats["superseded"],
                queued=stats["queued"],
                running=stats["running"],
                unhealthy=stats["unhealthy"],
                archived=stats["archived"],
                unknown=stats["unknown"],
                needs_attention=stats["needs_attention"],
                total_runtime_seconds=stats["total_runtime_seconds"],
                total_cost_estimate=stats["total_cost_estimate"],
                avg_runtime_seconds=avg_runtime,
                avg_cost_estimate=avg_cost,
                # Provider-Scorecard Felder
                total_provider_duration=stats.get("total_provider_duration", 0),
                avg_provider_duration_seconds=avg_provider_duration,
                fallback_rate=fallback_rate,
                no_change_rate=no_change_rate,
                pr_rate=pr_rate,
            )
        )

    return sorted(summaries, key=lambda s: s.name.lower())


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


def render_model_comparison_rows(runs: list[DashboardRun]) -> str:
    """Generiert die Zeilen für den Modellvergleich."""
    model_stats = {}

    for run in runs:
        model = run.model
        if model not in model_stats:
            model_stats[model] = {
                "total": 0,
                "successful": 0,
                "pr_created": 0,
                "noop": 0,
                "failed": 0,
                "runtime_seconds": [],
                "cost_estimate": [],
            }

        stats = model_stats[model]
        stats["total"] += 1

        if run.category == "successful":
            stats["successful"] += 1
            if run.status.startswith("pr_created"):
                stats["pr_created"] += 1
        elif run.category == "noop":
            stats["noop"] += 1
        elif run.category == "failed":
            stats["failed"] += 1

        if run.runtime_seconds:
            stats["runtime_seconds"].append(run.runtime_seconds)
        if run.cost_estimate:
            stats["cost_estimate"].append(run.cost_estimate)

    rows = []
    for model, stats in model_stats.items():
        total = stats["total"]
        successful = stats["successful"]
        pr_created = stats["pr_created"]
        noop = stats["noop"]
        failed = stats["failed"]

        success_rate = (successful / total * 100) if total > 0 else 0
        pr_rate = (pr_created / total * 100) if total > 0 else 0
        noop_rate = (noop / total * 100) if total > 0 else 0
        fail_rate = (failed / total * 100) if total > 0 else 0

        median_runtime = sorted(stats["runtime_seconds"])[len(stats["runtime_seconds"]) // 2] if stats["runtime_seconds"] else 0

        avg_cost_per_success = sum(stats["cost_estimate"]) / successful if successful > 0 and stats["cost_estimate"] else 0

        rows.append(f"""
        <tr>
          <td>{escape(model)}</td>
          <td>{success_rate:.1f}%</td>
          <td>{pr_rate:.1f}%</td>
          <td>{noop_rate:.1f}%</td>
          <td>{fail_rate:.1f}%</td>
          <td>{median_runtime}s</td>
          <td>${avg_cost_per_success:.2f}</td>
        </tr>
        """)

    return "\n".join(rows)


def render_backlog_rows(issues: list[DashboardIssue]) -> str:
    """Generiert die Zeilen für das Backlog."""
    rows = []
    for issue in issues:
        priority_badge = ""
        if issue.priority == 1:
            priority_badge = '<span class="priority-badge priority-high">Hoch</span>'
        elif issue.priority == 2:
            priority_badge = '<span class="priority-badge priority-medium">Mittel</span>'
        elif issue.priority == 3:
            priority_badge = '<span class="priority-badge priority-low">Niedrig</span>'

        rows.append(f"""
        <tr>
          <td>{priority_badge}</td>
          <td><div class="issue-number">#{escape(issue.number)}</div><div class="issue-title">{escape(issue.title)}</div></td>
          <td>{escape(issue.repo or '-')}</td>
          <td>{escape(issue.cluster)}</td>
          <td>{escape(issue.risk)}</td>
          <td>{escape(recommended_provider_for_issue(issue))}</td>
          <td>
            {render_link(issue.html_url, f"Issue #{issue.number}") if issue.html_url else ""}
            {render_command_block(issue_solver_command(issue, recommended_provider_for_issue(issue), dry_run=True), "Dry-run")}
            {render_command_block(issue_solver_command(issue, recommended_provider_for_issue(issue), dry_run=False), "Start")}
          </td>
        </tr>
        """)

    return "\n".join(rows)


def render_charts_script(runs: list[DashboardRun]) -> str:
    """Generiert das JavaScript für die Diagramme."""
    model_stats = {}

    for run in runs:
        model = run.model
        if model not in model_stats:
            model_stats[model] = {
                "successful": 0,
                "failed": 0,
                "runtime_seconds": [],
                "cost_estimate": [],
            }

        stats = model_stats[model]
        if run.category == "successful":
            stats["successful"] += 1
        elif run.category == "failed":
            stats["failed"] += 1

        if run.runtime_seconds:
            stats["runtime_seconds"].append(run.runtime_seconds)
        if run.cost_estimate:
            stats["cost_estimate"].append(run.cost_estimate)

    # Daten für Erfolgsquote-Diagramm
    success_data = {}
    for model, stats in model_stats.items():
        total = stats["successful"] + stats["failed"]
        success_rate = (stats["successful"] / total * 100) if total > 0 else 0
        success_data[model] = success_rate

    # Daten für Kosten- und Laufzeit-Diagramm
    cost_runtime_data = []
    for model, stats in model_stats.items():
        avg_runtime = sum(stats["runtime_seconds"]) / len(stats["runtime_seconds"]) if stats["runtime_seconds"] else 0
        avg_cost = sum(stats["cost_estimate"]) / len(stats["cost_estimate"]) if stats["cost_estimate"] else 0
        cost_runtime_data.append({
            "model": model,
            "runtime": avg_runtime,
            "cost": avg_cost
        })

    return f"""
    // Erfolgsquote-Diagramm
    const successCtx = document.getElementById('successRateChart').getContext('2d');
    new Chart(successCtx, {{
      type: 'bar',
      data: {{
        labels: {list(success_data.keys())},
        datasets: [{{
          label: 'Erfolgsquote (%)',
          data: {list(success_data.values())},
          backgroundColor: 'rgba(54, 162, 235, 0.5)',
          borderColor: 'rgba(54, 162, 235, 1)',
          borderWidth: 1
        }}]
      }},
      options: {{
        responsive: true,
        scales: {{
          y: {{
            beginAtZero: true,
            max: 100
          }}
        }}
      }}
    }});

    // Kosten- und Laufzeit-Diagramm
    const costRuntimeCtx = document.getElementById('costRuntimeChart').getContext('2d');
    new Chart(costRuntimeCtx, {{
      type: 'scatter',
      data: {{
        datasets: [{{
          label: 'Modelle',
          data: {json.dumps(cost_runtime_data)},
          backgroundColor: 'rgba(255, 99, 132, 0.5)',
          parsing: {{
            xAxisKey: 'runtime',
            yAxisKey: 'cost'
          }}
        }}]
      }},
      options: {{
        responsive: true,
        scales: {{
          x: {{
            type: 'linear',
            position: 'bottom',
            title: {{
              display: true,
              text: 'Durchschnittliche Laufzeit (Sekunden)'
            }}
          }},
          y: {{
            type: 'linear',
            position: 'left',
            title: {{
              display: true,
              text: 'Durchschnittliche Kosten (USD)'
            }}
          }}
        }}
      }}
    }});
    """


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


AGENT_KEYWORDS: list[tuple[str, str]] = [
    ("research",   ["evaluate", "research", "analyse", "analyse", "benchmark", "evidence"]),
    ("planner",    ["plan", "backlog", "priorit", "cleanup", "backlog"]),
    ("cost",       ["cost", "budget", "provider scorecard"]),
    ("supervisor", ["supervisor", "health", "monitor", "heartbeat"]),
    ("reviewer",   ["review", "quality"]),
    ("triage",     ["triage", "classify", "label", "route"]),
]


def agent_for_issue(title: str) -> str:
    """Ermittelt den Agent aus dem Issue-Titel via Keyword-Heuristik."""
    lower = title.lower()
    for agent, keywords in AGENT_KEYWORDS:
        if any(kw in lower for kw in keywords):
            return agent
    return "solver"


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
    if run.run_outcome_failure_class:
        note_parts.append(
            "Outcome: "
            f"{escape(run.run_outcome_failure_class)} / "
            f"{escape(run.run_outcome_delivery_status or 'unknown')} / "
            f"{escape(run.run_outcome_recovery_status or 'none')}"
        )
    if run.preserved_worktree:
        note_parts.append(f"Recovery-Worktree: <code>{escape(run.preserved_worktree)}</code>")
    note = f"<div class=\"note\">{'<br>'.join(note_parts)}</div>" if note_parts else ""
    last_activity = escape(format_datetime(run.last_activity_at))

    # Neue Felder für Laufzeit und Kosten
    runtime_display = escape(str(run.runtime_seconds) + "s" if run.runtime_seconds else "-")
    cost_display = escape(f"${run.cost_estimate:.2f} ({run.cost_confidence})" if run.cost_estimate else "-")

    # Prioritätsanzeige
    priority_badge = ""
    if run.priority == 1:
        priority_badge = '<span class="priority-badge priority-high">Hoch</span>'
    elif run.priority == 2:
        priority_badge = '<span class="priority-badge priority-medium">Mittel</span>'
    elif run.priority == 3:
        priority_badge = '<span class="priority-badge priority-low">Niedrig</span>'

    agent = agent_for_issue(run.issue_title or "")
    return "\n".join([
        f'<tr data-repo="{escape(run.repo or "")}" data-agent="{escape(agent)}">',
        f'  <td><span class="badge badge-{escape(run.category)}">{escape(STATUS_LABELS[run.category])}</span></td>',
        f"  <td>{escape(format_datetime(run.created_at))}</td>",
        f"  <td>{escape(run.repo or '-')}</td>",
        f"  <td>{priority_badge}{render_issue_cell(run)}</td>",
        f"  <td><code>{escape(run.branch or '-')}</code></td>",
        f"  <td>{render_lifecycle_cell(run)}</td>",
        f"  <td>{escape(run.model or '-')}</td>",
        f"  <td>{escape(run.provider or '-')}</td>",
        f"  <td>{runtime_display}</td>",
        f"  <td>{cost_display}</td>",
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

    # Prioritätsbadge hinzufügen
    priority_badge = ""
    if issue.priority == 1:
        priority_badge = '<span class="priority-badge priority-high">Hoch</span>'
    elif issue.priority == 2:
        priority_badge = '<span class="priority-badge priority-medium">Mittel</span>'
    elif issue.priority == 3:
        priority_badge = '<span class="priority-badge priority-low">Niedrig</span>'

    return "\n".join([
        "<tr>",
        '  <td><span class="badge badge-queued">Open</span></td>',
        f"  <td>{updated}</td>",
        f"  <td>{escape(issue.repo or '-')}</td>",
        f"  <td><div class=\"issue-number\">#{escape(issue.number)}</div>"
        f"<div class=\"issue-title\">{escape(issue.title)}</div></td>",
        f"  <td>{priority_badge or '-'}</td>",
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
              <th>Priorität</th>
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


def render_supervisor_section(supervisor_summary: dict | None) -> str:
    """Rendert die Supervisor-Status-Sektion für das Dashboard."""
    if supervisor_summary is None or get_supervisor_summary is None:
        return ""

    if supervisor_summary.get("needs_attention", 0) == 0:
        return ""

    stale_runs = supervisor_summary.get("stale_runs", [])
    unhealthy_runs = supervisor_summary.get("unhealthy_runs", [])

    rows = []
    for run in stale_runs:
        rows.append(f"""
        <tr class="supervisor-stale">
          <td><span class="badge badge-stale">Stale</span></td>
          <td>{escape(run.get('repo', '-'))}</td>
          <td>#{escape(run.get('issue', '-'))}</td>
          <td>{escape(run.get('phase', '-'))}</td>
          <td>{escape(run.get('health_reason', '-'))}</td>
          <td>
            <code class="command">{escape(run.get('stop_command', ''))}</code>
            <div class="command-label">Dry-run:</div>
            <code class="command">{escape(run.get('stop_command', '') + ' --dry-run')}</code>
          </td>
        </tr>
        """)
    for run in unhealthy_runs:
        rows.append(f"""
        <tr class="supervisor-unhealthy">
          <td><span class="badge badge-unhealthy">Unhealthy</span></td>
          <td>{escape(run.get('repo', '-'))}</td>
          <td>#{escape(run.get('issue', '-'))}</td>
          <td>{escape(run.get('phase', '-'))}</td>
          <td>{escape(run.get('health_reason', '-'))}</td>
          <td>
            <code class="command">{escape(run.get('stop_command', ''))}</code>
            <div class="command-label">Dry-run:</div>
            <code class="command">{escape(run.get('stop_command', '') + ' --dry-run')}</code>
          </td>
        </tr>
        """)

    if not rows:
        return ""

    rows_html = "\n".join(rows)
    return f"""
    <section class="section-block supervisor-section">
      <h2>Supervisor-Status <span class="attention-badge">{supervisor_summary.get('needs_attention', 0)}</span></h2>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Status</th>
              <th>Repo</th>
              <th>Issue</th>
              <th>Phase</th>
              <th>Grund</th>
              <th>Stop-Befehl</th>
            </tr>
          </thead>
          <tbody>
            {rows_html}
          </tbody>
        </table>
      </div>
      <div class="note">
        Aktive Runs: {supervisor_summary.get('total_active', 0)} ·
        Healthy: {supervisor_summary.get('healthy', 0)} ·
        Stale: {supervisor_summary.get('stale', 0)} ·
        Unhealthy: {supervisor_summary.get('unhealthy', 0)}
      </div>
    </section>
"""


def render_workflow_congestion_section(summaries: dict[str, WorkflowCongestionSummary] | None) -> str:
    if not summaries:
        return ""
    rows = []
    finding_rows = []
    for repo, summary in sorted(summaries.items()):
        attention = "Ja" if summary.needs_attention else "Nein"
        rows.append(f"""
        <tr>
          <td><strong>{escape(repo)}</strong></td>
          <td>{summary.open_pr_count}</td>
          <td>{summary.red_pr_count}</td>
          <td>{summary.green_unreviewed_pr_count}</td>
          <td>{summary.stale_pr_count}</td>
          <td>{summary.duplicate_issue_pr_count}</td>
          <td><code>{escape(summary.recommended_action)}</code></td>
          <td>{attention}</td>
        </tr>
        """)
        for finding in summary.findings[:8]:
            target = []
            if finding.issue_number:
                target.append(f"Issue #{finding.issue_number}")
            if finding.pr_number:
                target.append(f"PR #{finding.pr_number}")
            finding_rows.append(f"""
            <tr>
              <td>{escape(repo)}</td>
              <td><span class="badge badge-{escape(finding.severity)}">{escape(finding.severity)}</span></td>
              <td>{escape(", ".join(target) or "-")}</td>
              <td>{escape(finding.message)}</td>
              <td><code>{escape(finding.action)}</code></td>
            </tr>
            """)

    findings_html = ""
    if finding_rows:
        findings_html = f"""
      <h3>Workflow-Befunde</h3>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Repo</th>
              <th>Schwere</th>
              <th>Ziel</th>
              <th>Befund</th>
              <th>Aktion</th>
            </tr>
          </thead>
          <tbody>
            {"".join(finding_rows)}
          </tbody>
        </table>
      </div>
        """

    return f"""
    <section class="section-block">
      <h2>Workflow-Status</h2>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Repo</th>
              <th>Offene PRs</th>
              <th>Rote PRs</th>
              <th>Grün ohne Review</th>
              <th>Stale PRs</th>
              <th>Issue/PR-Duplikate</th>
              <th>Empfohlene Aktion</th>
              <th>Achtung</th>
            </tr>
          </thead>
          <tbody>
            {"".join(rows)}
          </tbody>
        </table>
      </div>
      {findings_html}
    </section>
"""


def render_repo_summary_row(summary: RepoSummary) -> str:
    """Render eine Zeile für die Repository-Zusammenfassung."""
    needs_attention_badge = ""
    if summary.needs_attention > 0:
        needs_attention_badge = (
            f'<span class="attention-badge" title="Benötigt Aufmerksamkeit">'
            f"{summary.needs_attention}</span>"
        )

    return f"""
    <tr>
      <td><strong>{escape(summary.name)}</strong>{needs_attention_badge}</td>
      <td>{summary.total}</td>
      <td>{summary.successful}</td>
      <td>{summary.failed}</td>
      <td>{summary.noop}</td>
      <td>{summary.recovered}</td>
      <td>{summary.total_runtime_seconds}s</td>
      <td>${summary.total_cost_estimate:.2f}</td>
      <td>{summary.avg_runtime_seconds:.1f}s</td>
      <td>${summary.avg_cost_estimate:.2f}</td>
    </tr>
"""


def render_repo_summary_section(runs: list[DashboardRun]) -> str:
    """
    Render die Repository-Zusammenfassungssektion.

    Args:
        runs: Liste aller DashboardRuns

    Returns:
        HTML-String für die Repository-Zusammenfassung oder leer falls keine Runs
    """
    summaries = compute_repo_summaries(runs)
    if not summaries:
        return ""

    rows = "\n".join(render_repo_summary_row(summary) for summary in summaries)

    return f"""
    <section class="section-block">
      <h2>Repository-Übersicht</h2>
      <div class="table-wrap repo-summary">
        <table>
          <thead>
            <tr>
              <th>Repository</th>
              <th>Total</th>
              <th>Erfolgreich</th>
              <th>Fehlgeschlagen</th>
              <th>No-op</th>
              <th>Wiederhergestellt</th>
              <th>Gesamtlaufzeit</th>
              <th>Gesamtkosten</th>
              <th>Durchschnittslaufzeit</th>
              <th>Durchschnittskosten</th>
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
                     unstarted_issues: list[DashboardIssue] | None = None,
                     active_tab: str = "run-list",
                     supervisor_summary: dict | None = None,
                     workflow_congestion: dict[str, WorkflowCongestionSummary] | None = None) -> str:
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

    # Repos mit aktuell laufenden Jobs ermitteln (für Default-Auswahl)
    running_repos: dict[str, datetime] = {}
    for run in runs:
        if run.repo and run.category == "running" and run.created_at:
            if run.repo not in running_repos or run.created_at > running_repos[run.repo]:
                running_repos[run.repo] = run.created_at

    if len(running_repos) == 1:
        default_repos = [list(running_repos.keys())[0]]
    elif len(running_repos) > 1:
        default_repos = [max(running_repos, key=lambda r: running_repos[r])]
    else:
        default_repos = []

    # Alle Repos nach letzter Aktivität sortieren (für Checkbox-Reihenfolge)
    repo_activity: dict[str, datetime] = {}
    for run in runs:
        if run.repo:
            ts = run.last_activity_at or run.created_at
            if ts and (run.repo not in repo_activity or ts > repo_activity[run.repo]):
                repo_activity[run.repo] = ts
    repos_sorted = sorted(repo_activity, key=lambda r: repo_activity[r], reverse=True)

    # Checkbox-HTML für die Repo-Übersicht
    repo_checkboxes = "".join(
        f'<label class="repo-checkbox"><input type="checkbox" value="{escape(r)}" onchange="onFilterChange()"'
        f'{" checked" if r in default_repos else ""}>'
        f'{escape(r)}</label>'
        for r in repos_sorted
    )

    agent_filter_options = "".join(
        f'<option value="{agent}">{agent}</option>'
        for agent in sorted({agent_for_issue(run.issue_title or "") for run in runs if run.issue_title})
    )
    if not rows:
        rows = (
            '<tr><td colspan="13" class="empty">'
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
    repo_summary_section = render_repo_summary_section(runs)
    unstarted_section = render_unstarted_issues_section(unstarted_issues or [])
    supervisor_section = render_supervisor_section(supervisor_summary)
    workflow_congestion_section = render_workflow_congestion_section(workflow_congestion)

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
      --tab-active: #276ef1;
      --tab-inactive: #d8dee6;
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
    .repo-summary table {{ min-width: 0; }}
    .repo-summary th, .repo-summary td {{ padding: 8px 12px; font-size: 13px; }}
    .repo-summary th {{ background: #fbfcfd; }}
    .attention-badge {{
      display: inline-block;
      margin-left: 8px;
      padding: 2px 6px;
      background: var(--failed);
      color: #fff;
      border-radius: 999px;
      font-size: 11px;
      font-weight: 600;
    }}
    .tabs {{
      display: flex;
      border-bottom: 1px solid var(--line);
      margin-bottom: 20px;
    }}
    .tab {{
      padding: 10px 16px;
      cursor: pointer;
      border-bottom: 3px solid transparent;
      margin-right: 4px;
      color: var(--muted);
    }}
    .tab.active {{
      color: var(--tab-active);
      border-bottom-color: var(--tab-active);
      font-weight: 600;
    }}
    .tab-content {{ display: none; }}
    .tab-content.active {{ display: block; }}
    .filter-bar {{ padding: 12px 16px 4px; display: flex; align-items: center; gap: 8px; }}
    .filter-bar label {{ color: var(--muted); font-size: 13px; }}
    .filter-bar select {{ font-size: 13px; padding: 3px 6px; border: 1px solid var(--line); border-radius: 4px; background: var(--panel); color: var(--text); }}
    .repo-bar {{ background: var(--panel); border: 1px solid var(--line); border-radius: 8px; margin: 12px 16px; overflow: hidden; }}
    .repo-bar summary {{ padding: 10px 14px; cursor: pointer; font-weight: 600; font-size: 14px; user-select: none; }}
    .repo-bar summary::marker {{ color: var(--muted); }}
    .repo-bar-body {{ padding: 4px 14px 12px; display: flex; flex-wrap: wrap; align-items: center; gap: 6px 14px; }}
    .repo-checkbox {{ font-size: 13px; cursor: pointer; white-space: nowrap; }}
    .repo-checkbox input {{ margin-right: 3px; vertical-align: middle; }}
    .repo-all {{ font-weight: 600; }}
    .repo-bar-sep {{ display: inline-block; width: 1px; height: 18px; background: var(--line); margin: 0 4px; }}
    .repo-count {{ font-size: 12px; color: var(--muted); margin-left: auto; }}
    .chart-container {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 16px;
      margin-bottom: 20px;
    }}
    .comparison-table {{
      width: 100%;
      border-collapse: collapse;
    }}
    .comparison-table th, .comparison-table td {{
      padding: 10px 12px;
      text-align: left;
      border-bottom: 1px solid var(--line);
    }}
    .comparison-table th {{
      background: #fbfcfd;
      font-weight: 600;
    }}
    .priority-badge {{
      display: inline-block;
      padding: 2px 6px;
      border-radius: 999px;
      font-size: 11px;
      font-weight: 600;
      margin-right: 4px;
    }}
    .priority-high {{ background: var(--failed); color: #fff; }}
    .priority-medium {{ background: var(--unhealthy); color: #fff; }}
    .priority-low {{ background: var(--success); color: #fff; }}
    @media (max-width: 720px) {{
      header, main {{ padding-left: 16px; padding-right: 16px; }}
      h1 {{ font-size: 22px; }}
      .repo-summary th, .repo-summary td {{ padding: 6px 8px; font-size: 12px; }}
    }}
  </style>
  <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
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
    <div class="tabs">
      <div class="tab {'active' if active_tab == 'overview' else ''}" onclick="switchTab('overview')">Übersicht</div>
      <div class="tab {'active' if active_tab == 'model-comparison' else ''}" onclick="switchTab('model-comparison')">Modellvergleich</div>
      <div class="tab {'active' if active_tab == 'backlog' else ''}" onclick="switchTab('backlog')">Backlog/Priorisierung</div>
      <div class="tab {'active' if active_tab == 'run-list' else ''}" onclick="switchTab('run-list')">Run-Liste</div>
      <div class="tab {'active' if active_tab == 'diagnostics' else ''}" onclick="switchTab('diagnostics')">Diagnose</div>
    </div>

    <details class="repo-bar" id="repo-bar" open>
      <summary>Repository-Übersicht ⏷ <span id="repo-summary-label">{escape(repos_sorted[0] if repos_sorted else "")}</span></summary>
      <div class="repo-bar-body">
        <label class="repo-checkbox repo-all"><input type="checkbox" id="repo-all" checked onchange="toggleAllRepos(this.checked)">Alle</label>
        {repo_checkboxes}
        <span class="repo-bar-sep"></span>
        <label for="agent-filter">Agent:</label>
        <select id="agent-filter" onchange="onFilterChange()">
          <option value="">Alle</option>
          {agent_filter_options}
        </select>
        <span id="repo-count" class="repo-count">1 Repo ausgewählt</span>
      </div>
    </details>

    <div id="overview" class="tab-content {'active' if active_tab == 'overview' else ''}">
      <section class="metrics" aria-label="Status-Zusammenfassung">
        {cards}
      </section>
      {workflow_congestion_section}
      {supervisor_section}
      {repo_summary_section}
      {unstarted_section}
    </div>

    <div id="model-comparison" class="tab-content {'active' if active_tab == 'model-comparison' else ''}">
      <h2>Modellvergleich</h2>
      <div class="chart-container">
        <h3>Erfolgsquote nach Modell</h3>
        <canvas id="successRateChart" width="400" height="200"></canvas>
      </div>
      <div class="table-wrap">
        <table class="comparison-table">
          <thead>
            <tr>
              <th>Modell</th>
              <th>Erfolgsquote</th>
              <th>PR-Erstellungsrate</th>
              <th>Keine-Änderungen-Rate</th>
              <th>Fehlerquote</th>
              <th>Mediane Laufzeit</th>
              <th>Geschätzte Kosten pro erfolgreicher PR</th>
            </tr>
          </thead>
          <tbody>
            {render_model_comparison_rows(runs)}
          </tbody>
        </table>
      </div>
    </div>

    <div id="backlog" class="tab-content {'active' if active_tab == 'backlog' else ''}">
      <h2>Backlog/Priorisierung</h2>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Priorität</th>
              <th>Issue</th>
              <th>Repository</th>
              <th>Cluster</th>
              <th>Risiko</th>
              <th>Empfohlener Provider</th>
              <th>Aktionen</th>
            </tr>
          </thead>
          <tbody>
            {render_backlog_rows(unstarted_issues or [])}
          </tbody>
        </table>
      </div>
    </div>

    <div id="run-list" class="tab-content {'active' if active_tab == 'run-list' else ''}">
      <h2>Run-Liste</h2>
      <div class="table-wrap">
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
              <th>Provider</th>
              <th>Laufzeit</th>
              <th>Kosten</th>
              <th>Exit</th>
              <th>Details</th>
              <th>Links</th>
            </tr>
          </thead>
          <tbody>
            {rows}
          </tbody>
        </table>
      </div>
    </div>

    <div id="diagnostics" class="tab-content {'active' if active_tab == 'diagnostics' else ''}">
      <h2>Diagnose</h2>
      <div class="chart-container">
        <h3>Kosten- und Laufzeittrends</h3>
        <canvas id="costRuntimeChart" width="400" height="200"></canvas>
      </div>
    </div>
  </main>
  {shutdown_script}
  <script>
    function parseUrlParams() {{
      const params = new URLSearchParams(location.search);
      return {{
        tab: params.get('tab') || '',
        repo: params.get('repo') || '',
        agent: params.get('agent') || ''
      }};
    }}

    function updateUrlParams(tab, repo, agent) {{
      const params = new URLSearchParams();
      if (tab) params.set('tab', tab);
      if (repo) params.set('repo', repo);
      if (agent) params.set('agent', agent);
      const newUrl = location.pathname + '?' + params.toString() + location.hash;
      history.replaceState(null, '', newUrl);
    }}

    function getSelectedRepos() {{
      return [...document.querySelectorAll('#repo-bar .repo-checkbox input:not(#repo-all):checked')]
        .map(cb => cb.value);
    }}

    function updateRepoLabel(repos) {{
      const label = document.getElementById('repo-summary-label');
      const count = document.getElementById('repo-count');
      const all = document.getElementById('repo-all');
      if (label) label.textContent = repos.length ? repos.join(', ') : '\u2013';
      if (count) count.textContent = repos.length + ' Repo(s) ausgew\u00e4hlt';
      if (all) all.checked = repos.length === document.querySelectorAll('#repo-bar .repo-checkbox:not(#repo-all)').length;
    }}

    function toggleAllRepos(checked) {{
      document.querySelectorAll('#repo-bar .repo-checkbox:not(#repo-all) input').forEach(cb => {{
        cb.checked = checked;
      }});
      onFilterChange();
    }}

    function applyFilters(repos, agent) {{
      document.querySelectorAll('#run-list table tbody tr').forEach(row => {{
        const matchRepo = !repos.length || repos.includes(row.dataset.repo || '');
        const matchAgent = !agent || row.dataset.agent === agent;
        row.style.display = (matchRepo && matchAgent) ? '' : 'none';
      }});
    }}

    function getActiveTab() {{
      const active = document.querySelector('.tab.active');
      if (active) {{
        const match = active.getAttribute('onclick')?.match(/'([^']+)'/);
        if (match) return match[1];
      }}
      return 'run-list';
    }}

    function switchTab(tabId) {{
      document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
      document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
      document.getElementById(tabId).classList.add('active');
      [...document.querySelectorAll('.tab')].forEach(t => {{
        const onclick = t.getAttribute('onclick') || '';
        if (onclick.includes("'" + tabId + "'")) t.classList.add('active');
      }});
      const repos = getSelectedRepos();
      const agent = document.getElementById('agent-filter').value;
      updateUrlParams(tabId, repos.length === 1 ? repos[0] : '', agent !== '' ? agent : '');
    }}

    function onFilterChange() {{
      const repos = getSelectedRepos();
      const agent = document.getElementById('agent-filter').value;
      applyFilters(repos, agent);
      updateRepoLabel(repos);
      updateUrlParams(
        getActiveTab(),
        repos.length === 1 ? repos[0] : '',
        agent !== '' ? agent : ''
      );
    }}

    function findDefaultRepo() {{
      const rows = document.querySelectorAll('#run-list table tbody tr');
      const runningByRepo = {{}};
      rows.forEach(row => {{
        const badge = row.querySelector('.badge-running');
        if (badge) {{
          const repo = row.dataset.repo;
          const timeCell = row.querySelector('td:nth-child(2)');
          if (repo && timeCell) {{
            const time = timeCell.textContent.trim();
            if (!runningByRepo[repo] || time > runningByRepo[repo]) {{
              runningByRepo[repo] = time;
            }}
          }}
        }}
      }});
      const repos = Object.keys(runningByRepo);
      if (repos.length === 1) return repos[0];
      if (repos.length > 1) {{
        return repos.reduce((a, b) => runningByRepo[a] > runningByRepo[b] ? a : b);
      }}
      return '';
    }}

    document.addEventListener('DOMContentLoaded', function() {{
      {render_charts_script(runs)}
      const params = parseUrlParams();

      // Tab aus URL-Parameter oder Default "run-list"
      const tabId = params.tab || 'run-list';
      const tabEl = document.getElementById(tabId);
      if (tabEl) {{
        document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
        document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
        tabEl.classList.add('active');
        [...document.querySelectorAll('.tab')].forEach(t => {{
          const onclick = t.getAttribute('onclick') || '';
          if (onclick.includes("'" + tabId + "'")) t.classList.add('active');
        }});
      }}

      // Repo aus URL oder Default (Repo mit laufenden Jobs)
      const allCheckboxes = [...document.querySelectorAll('#repo-bar .repo-checkbox:not(#repo-all) input')];
      const urlRepo = params.repo;
      const runningRepo = findDefaultRepo();
      const selectedRepo = urlRepo || runningRepo;

      if (selectedRepo) {{
        allCheckboxes.forEach(cb => {{ cb.checked = cb.value === selectedRepo; }});
        document.getElementById('repo-all').checked = allCheckboxes.every(cb => cb.checked);
      }} else {{
        allCheckboxes.forEach(cb => {{ cb.checked = true; }});
        document.getElementById('repo-all').checked = true;
      }}

      // Agent aus URL oder Default (Alle)
      const agentValue = params.agent || '';
      const sel = document.getElementById('agent-filter');
      if (agentValue && [...sel.options].some(o => o.value === agentValue)) {{
        sel.value = agentValue;
      }}

      const selected = getSelectedRepos();
      applyFilters(selected, document.getElementById('agent-filter').value);
      updateRepoLabel(selected);

      // URL-Parameter beim initialen Laden setzen, falls noch nicht vorhanden
      updateUrlParams(
        tabId,
        selected.length === 1 ? selected[0] : '',
        document.getElementById('agent-filter').value || ''
      );
    }});
  </script>
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
                     github_cache_ttl_seconds: int = DEFAULT_GITHUB_CACHE_TTL_SECONDS,
                     active_tab: str = "run-list",
                     supervisor_summary: dict | None = None) -> Path:
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
    workflow_congestion = {}
    if github_client is not None:
        try:
            workflow_congestion = build_workflow_congestion_summaries(
                repos_for_workflow_status(runs, unstarted_issues),
                github_client,
            )
        except Exception:
            workflow_congestion = {}
    output_path.write_text(
        render_dashboard(
            runs,
            effective_owner,
            output_path,
            allow_shutdown=allow_shutdown,
            refresh_seconds=refresh_seconds,
            unstarted_issues=unstarted_issues,
            active_tab=active_tab,
            supervisor_summary=supervisor_summary,
            workflow_congestion=workflow_congestion,
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
    parser.add_argument(
        "--tab",
        default="run-list",
        help="Standard-Tab beim Öffnen des Dashboards",
    )
    args = parser.parse_args()

    config = load_env()
    owner = args.owner or config.get("GITHUB_USER")
    runs_dir = Path(args.runs_dir)
    output_path = Path(args.output)
    allow_shutdown = False
    refresh_seconds = None
    github_enrich = args.github_enrich
    github_token = config.get("GITHUB_TOKEN")
    github_cache_path = Path(args.github_cache)
    github_cache_ttl_seconds = args.github_cache_ttl_seconds
    active_tab = args.tab
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

    supervisor_summary = None
    if get_supervisor_summary is not None:
        print_step(2, "Lese Supervisor-Status")
        try:
            supervisor_summary = get_supervisor_summary(runs_dir)
            if supervisor_summary.get("needs_attention", 0) > 0:
                print(f"   Achtung: {supervisor_summary['needs_attention']} Run(s) brauchen Aufmerksamkeit")
        except Exception as exc:
            print(f"   Supervisor-Status konnte nicht gelesen werden: {exc}")

    print_step(3, f"Schreibe HTML nach {output_path}")
    if args.github_enrich:
        print("   GitHub-Enrichment: an (mit Cache/Fallback)")
    write_dashboard(
        runs,
        output_path,
        owner=owner,
        allow_shutdown=allow_shutdown,
        refresh_seconds=refresh_seconds,
        github_enrich=github_enrich,
        github_token=github_token,
        github_cache_path=github_cache_path,
        github_cache_ttl_seconds=github_cache_ttl_seconds,
        active_tab=active_tab,
        supervisor_summary=supervisor_summary,
    )
    print(f"   Dashboard: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
