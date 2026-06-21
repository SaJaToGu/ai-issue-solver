#!/usr/bin/env python3
"""
validation_run.py — Validation Metrics & Run (Release 0.9.0)

Measures whether ai-issue-solver actually solves real GitHub issues
end-to-end. The answer must be a number.

Definition of Solved:
  An issue counts as solved iff:
    1. The solver produced a PR.
    2. The PR was merged into the default branch.
    3. The merge commit's CI run is green.
  Anything less is NOT solved.

Subcommands:
  run       — Execute the solver pipeline on N issues and generate report
  report    — Generate the validation report from existing run data
  check-prs — Re-check PR merge + CI status for a previous validation run
  list      — List open issues suitable for validation

Usage:
  python scripts/validation_run.py run --count 10 --model opencode
  python scripts/validation_run.py run --issues 3,4,5 --model opencode --dry-run
  python scripts/validation_run.py report --run-id <id>
  python scripts/validation_run.py check-prs --run-id <id>
  python scripts/validation_run.py list --count 20
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import requests
except ModuleNotFoundError:
    requests = None

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(SCRIPT_DIR))
sys.path.insert(0, str(PROJECT_ROOT))

from utils import (
    load_env,
    print_banner,
    print_err,
    print_ok,
    print_step,
    print_warn,
    raise_for_github_response,
    require_config_value,
)

REPORT_PATH = PROJECT_ROOT / "reports" / "validation-0.9.0.md"
RUNS_ROOT = PROJECT_ROOT / "reports" / "runs"
VALIDATION_RUNS_ROOT = PROJECT_ROOT / "reports" / "validation-runs"
GITHUB_API_BASE = "https://api.github.com"
DEFAULT_MODEL = "opencode"
DEFAULT_MODEL_NAME = "opencode/deepseek-v4-flash-free"
DEFAULT_MAX_COST_USD = 5.0
DEFAULT_ISSUE_COUNT = 10
DEFAULT_OWNER = "SaJaToGu"
DEFAULT_REPO = "ai-issue-solver"

STATUS_CATEGORY_SOLVED = frozenset({
    "pr_created",
    "pr_created_from_existing_branch",
    "pr_created_with_warning",
})

RUNNING_STATUSES = frozenset({
    "started", "running", "queued", "unhealthy",
})


# ── Data classes ────────────────────────────────────────────────

@dataclass
class ValidationIssue:
    number: int
    title: str
    repo: str
    body: str = ""
    labels: list[str] = field(default_factory=list)


@dataclass
class RunReportData:
    run_dir: Path
    status: str
    worker_exit_code: str
    pr_url: str
    model: str
    issue_number: str
    issue_title: str
    branch: str
    duration_seconds: float | None = None
    estimated_cost: float | None = None
    error_class: str | None = None

    def summary_dict(self) -> dict[str, Any]:
        return {
            "run_dir": str(self.run_dir),
            "status": self.status,
            "worker_exit_code": self.worker_exit_code,
            "pr_url": self.pr_url,
            "model": self.model,
            "issue_number": self.issue_number,
            "issue_title": self.issue_title,
            "branch": self.branch,
            "duration_seconds": self.duration_seconds,
            "estimated_cost": self.estimated_cost,
            "error_class": self.error_class,
        }


@dataclass
class ValidationConfig:
    validation_run_id: str
    created_at: str
    model: str
    model_name: str
    owner: str
    repo: str
    max_run_cost_usd: float | None
    issue_count: int
    issues: list[dict[str, Any]]
    run_report_paths: list[str] = field(default_factory=list)


@dataclass
class ValidationMetrics:
    issues_processed: int
    prs_merged: int
    prs_created_not_merged: int
    success_rate: float
    total_cost: float
    total_time_seconds: float
    cost_per_solved: float
    time_per_solved: float
    top_errors: list[tuple[str, int]]
    outcomes: list[dict[str, Any]]


# ── GitHub helpers ──────────────────────────────────────────────

class ValidationGitHubClient:
    BASE = "https://api.github.com"

    def __init__(self, token: str, owner: str):
        self.owner = owner
        self.token = token
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        })

    def get_open_issues(self, repo: str, label: str | None = None,
                        per_page: int = 100) -> list[dict]:
        params: dict[str, Any] = {
            "state": "open",
            "per_page": min(per_page, 100),
            "sort": "created",
            "direction": "asc",
        }
        if label:
            params["labels"] = label
        try:
            resp = self.session.get(
                f"{self.BASE}/repos/{self.owner}/{repo}/issues",
                params=params,
            )
        except requests.RequestException as exc:
            print_err(f"Failed to fetch issues: {exc}")
            return []
        if resp.status_code == 404:
            return []
        raise_for_github_response(resp, "Fetch open issues")
        return [i for i in resp.json() if "pull_request" not in i]

    def get_issue(self, repo: str, number: int) -> dict | None:
        try:
            resp = self.session.get(
                f"{self.BASE}/repos/{self.owner}/{repo}/issues/{number}"
            )
        except requests.RequestException as exc:
            print_err(f"Failed to fetch issue #{number}: {exc}")
            return None
        if resp.status_code == 404:
            return None
        raise_for_github_response(resp, f"Fetch issue #{number}")
        return resp.json()

    def get_pull_request(self, repo: str, pr_number: int) -> dict | None:
        try:
            resp = self.session.get(
                f"{self.BASE}/repos/{self.owner}/{repo}/pulls/{pr_number}"
            )
        except requests.RequestException as exc:
            print_err(f"Failed to fetch PR #{pr_number}: {exc}")
            return None
        if resp.status_code == 404:
            return None
        raise_for_github_response(resp, f"Fetch PR #{pr_number}")
        return resp.json()

    def get_pr_commit_status(self, repo: str, ref: str) -> dict | None:
        """Get the combined commit status for a given ref (SHA or branch)."""
        try:
            resp = self.session.get(
                f"{self.BASE}/repos/{self.owner}/{repo}/commits/{ref}/status"
            )
        except requests.RequestException as exc:
            print_err(f"Failed to fetch commit status for {ref}: {exc}")
            return None
        if resp.status_code == 404:
            return None
        raise_for_github_response(resp, f"Fetch commit status for {ref}")
        return resp.json()

    def get_pr_check_runs(self, repo: str, pr_number: int) -> list[dict]:
        """Get all check runs for the latest commit on a PR."""
        try:
            resp = self.session.get(
                f"{self.BASE}/repos/{self.owner}/{repo}/pulls/{pr_number}/commits",
                params={"per_page": 1},
            )
        except requests.RequestException as exc:
            print_err(f"Failed to fetch PR commits for #{pr_number}: {exc}")
            return []
        if resp.status_code != 200:
            return []
        commits = resp.json()
        if not commits:
            return []
        sha = commits[-1].get("sha", "")
        if not sha:
            return []
        try:
            resp = self.session.get(
                f"{self.BASE}/repos/{self.owner}/{repo}/commits/{sha}/check-runs",
                params={"per_page": 100},
            )
        except requests.RequestException as exc:
            print_err(f"Failed to fetch check runs for {sha}: {exc}")
            return []
        if resp.status_code != 200:
            return []
        data = resp.json()
        return data.get("check_runs", [])

    def is_pr_merged(self, repo: str, pr_number: int) -> bool | None:
        """Check if a PR is merged (returns True/False/None on error)."""
        pr = self.get_pull_request(repo, pr_number)
        if pr is None:
            return None
        return bool(pr.get("merged_at"))

    def is_pr_ci_green(self, repo: str, pr_number: int) -> bool | None:
        """Check if a PR's CI is green by looking at check runs and status."""
        pr = self.get_pull_request(repo, pr_number)
        if pr is None:
            return None
        head_sha = (pr.get("head") or {}).get("sha", "")
        if not head_sha:
            return None

        combined = self.get_pr_commit_status(repo, head_sha)
        if combined is not None:
            state = combined.get("state", "")
            if state == "success":
                return True
            if state == "failure":
                return False
            if state == "pending":
                return None

        check_runs = self.get_pr_check_runs(repo, pr_number)
        if not check_runs:
            return None

        all_green = True
        has_checks = False
        for run in check_runs:
            conclusion = run.get("conclusion")
            status = run.get("status")
            if status == "completed":
                has_checks = True
                if conclusion not in ("success", "neutral", "skipped"):
                    all_green = False
            elif status in ("queued", "in_progress"):
                return None

        return all_green if has_checks else None


# ── Run report reading ──────────────────────────────────────────

def parse_summary_file(path: Path) -> dict[str, str]:
    """Parse a summary.txt file into key-value pairs."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return {}

    fields: dict[str, str] = {}
    current_key: str | None = None
    parts: list[str] = []
    multiline_keys = {"output_tail", "git_diff_stat", "git_change_summary"}

    for raw_line in lines:
        key, separator, value = raw_line.partition(":")
        if current_key:
            if separator and not raw_line.startswith((" ", "\t")):
                fields[current_key] = "\n".join(parts).strip()
                current_key = None
                parts = []
            else:
                parts.append(raw_line)
                continue

        if not raw_line.strip() or not separator:
            continue
        key = key.strip()
        value = value.strip()
        if key in multiline_keys:
            current_key = key
            parts = [value] if value else []
            continue
        fields[key] = value

    if current_key:
        fields[current_key] = "\n".join(parts).strip()
    return fields


def read_run_report(run_dir: Path) -> RunReportData | None:
    """Read a single solver run report and return structured data."""
    summary_path = run_dir / "summary.txt"
    metadata_path = run_dir / "metadata.json"

    summary = parse_summary_file(summary_path) if summary_path.exists() else {}
    metadata: dict[str, Any] = {}
    if metadata_path.exists():
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            metadata = {}

    status = metadata.get("status", "") or summary.get("status", "")
    if not status:
        return None

    worker_exit_code = str(
        metadata.get("worker_exit_code", "") or summary.get("worker_exit_code", "")
    )
    pr_url = metadata.get("pr_url", "") or summary.get("pr_url", "")
    model = metadata.get("model", "") or summary.get("model", "")
    issue_number = (
        str(metadata.get("issue_number", "") or metadata.get("issue", ""))
        or summary.get("issue_number", "")
        or summary.get("issue", "")
    )
    issue_title = metadata.get("issue_title", "") or summary.get("issue_title", "")
    branch = metadata.get("branch", "") or summary.get("branch", "")

    duration_seconds = None
    scorecard = metadata.get("provider_scorecard", {})
    if isinstance(scorecard, dict):
        duration_seconds = scorecard.get("duration_seconds")
        estimated_cost = scorecard.get("estimated_cost")
    else:
        estimated_cost = None

    if duration_seconds is None:
        duration_seconds = summary.get("provider_scorecard_duration_seconds")
        if duration_seconds:
            try:
                duration_seconds = float(duration_seconds)
            except (ValueError, TypeError):
                duration_seconds = None

    if estimated_cost is None:
        cost_str = summary.get("provider_scorecard_estimated_cost", "")
        if cost_str:
            try:
                estimated_cost = float(cost_str)
            except (ValueError, TypeError):
                estimated_cost = None

    error_class = None
    run_outcome = metadata.get("run_outcome", {})
    if isinstance(run_outcome, dict):
        error_class = run_outcome.get("failure_class")
    if not error_class:
        f_class = summary.get("run_outcome_failure_class", "")
        error_class = f_class if f_class not in ("", "success") else None

    return RunReportData(
        run_dir=run_dir,
        status=status,
        worker_exit_code=worker_exit_code,
        pr_url=pr_url,
        model=model,
        issue_number=issue_number,
        issue_title=issue_title,
        branch=branch,
        duration_seconds=duration_seconds,
        estimated_cost=estimated_cost,
        error_class=error_class,
    )


def collect_run_reports(run_paths: list[Path] | None = None) -> list[RunReportData]:
    """Collect all run reports from given paths or from reports/runs/."""
    if run_paths:
        dirs = run_paths
    else:
        if not RUNS_ROOT.exists():
            return []
        dirs = sorted(
            d for d in RUNS_ROOT.iterdir()
            if d.is_dir() and not d.name.startswith(".")
        )

    reports: list[RunReportData] = []
    for run_dir in dirs:
        report = read_run_report(run_dir)
        if report is not None:
            reports.append(report)
    return reports


# ── PR status checking ──────────────────────────────────────────

def check_pr_statuses(
    reports: list[RunReportData],
    owner: str,
    repo: str,
    client: ValidationGitHubClient | None = None,
) -> tuple[list[dict[str, Any]], int, int]:
    """Check merge + CI status for all PRs in the given run reports.

    Returns (outcomes, merged_count, ci_green_count) for PRs that exist.
    """
    outcomes: list[dict[str, Any]] = []
    merged = 0
    ci_green = 0

    for report in reports:
        if not report.pr_url or not client:
            outcomes.append({
                "run_dir": str(report.run_dir),
                "issue_number": report.issue_number,
                "status": report.status,
                "pr_url": report.pr_url or "",
                "pr_merged": None,
                "ci_green": None,
                "solved": False,
                "error_class": report.error_class or "no_pr",
            })
            continue

        pr_match = re.search(r"/pull/(\d+)$", report.pr_url)
        if not pr_match:
            outcomes.append({
                "run_dir": str(report.run_dir),
                "issue_number": report.issue_number,
                "status": report.status,
                "pr_url": report.pr_url,
                "pr_merged": None,
                "ci_green": None,
                "solved": False,
                "error_class": "invalid_pr_url",
            })
            continue

        pr_number = int(pr_match.group(1))
        is_merged = client.is_pr_merged(repo, pr_number)
        is_ci_green = client.is_pr_ci_green(repo, pr_number) if is_merged else None

        if is_merged:
            merged += 1
        if is_ci_green:
            ci_green += 1

        solved = bool(is_merged and is_ci_green)

        outcomes.append({
            "run_dir": str(report.run_dir),
            "issue_number": report.issue_number,
            "status": report.status,
            "pr_url": report.pr_url,
            "pr_merged": is_merged,
            "ci_green": is_ci_green,
            "solved": solved,
            "error_class": report.error_class or ("success" if solved else "not_merged"),
        })

    return outcomes, merged, ci_green


# ── Issue selection ─────────────────────────────────────────────

def select_issues_by_label(
    client: ValidationGitHubClient | None,
    repo: str,
    count: int,
    label: str = "ai-generated",
    explicit_numbers: list[int] | None = None,
) -> list[ValidationIssue]:
    """Select N open issues for validation.

    If explicit_numbers is given, fetch those specific issues.
    Otherwise, fetch the N oldest open issues with the given label.
    """
    issues: list[ValidationIssue] = []

    if explicit_numbers:
        for num in explicit_numbers:
            if client is None:
                issues.append(ValidationIssue(
                    number=num,
                    title=f"(issue #{num})",
                    repo=repo,
                    labels=[],
                ))
                continue
            issue_data = client.get_issue(repo, num)
            if issue_data is None:
                print_warn(f"Issue #{num} not found or not accessible")
                continue
            if "pull_request" in issue_data:
                print_warn(f"#{num} is a pull request, skipping")
                continue
            issues.append(ValidationIssue(
                number=issue_data["number"],
                title=issue_data.get("title", ""),
                repo=repo,
                body=issue_data.get("body", ""),
                labels=[lbl.get("name", "") for lbl in issue_data.get("labels", [])],
            ))
        return issues

    if client is None:
        print_err("GitHub client required for auto-selection (no --issues given)")
        return []

    raw = client.get_open_issues(repo, label=label, per_page=count)
    for item in raw[:count]:
        issues.append(ValidationIssue(
            number=item["number"],
            title=item.get("title", ""),
            repo=repo,
            body=item.get("body", ""),
            labels=[lbl.get("name", "") for lbl in item.get("labels", [])],
        ))

    return issues


# ── Solver invocation ───────────────────────────────────────────

def run_solver_for_issue(
    issue: ValidationIssue,
    model: str,
    model_name: str,
    owner: str,
    repo: str,
    max_run_cost_usd: float | None = None,
    dry_run: bool = False,
    verbose: bool = False,
    base_branch: str | None = None,
) -> str | None:
    """Run the solver for a single issue by calling solve_issues.py.

    Returns the run report directory name (last path component) on success,
    or None if the solver was not started (dry-run) or failed.
    """
    cmd = [
        sys.executable,
        str(SCRIPT_DIR / "solve_issues.py"),
        "--model", model,
        "--repo", repo,
        "--issue", str(issue.number),
    ]
    if model_name:
        cmd.extend(["--model-name", model_name])
    if dry_run:
        cmd.append("--dry-run")
    if base_branch:
        cmd.extend(["--base-branch", base_branch])
    if max_run_cost_usd is not None:
        cmd.extend(["--max-run-cost-usd", str(max_run_cost_usd)])
    if verbose:
        cmd.append("--verbosity")
        cmd.append("verbose")
    else:
        cmd.append("--verbosity")
        cmd.append("normal")

    if dry_run:
        print(f"      [DRY-RUN] Would run: {' '.join(cmd)}")
        return None

    print(f"   Solver: Issue #{issue.number} — {issue.title}")
    print(f"      {' '.join(cmd)}")

    result = subprocess.run(
        cmd,
        cwd=PROJECT_ROOT,
        capture_output=not verbose,
        text=True,
        timeout=1800,  # 30 min per issue
    )

    if result.returncode != 0:
        output = (result.stderr or result.stdout or "").strip()
        print_err(f"      Solver exited with code {result.returncode}")
        if output:
            for line in output.splitlines()[-10:]:
                print(f"      | {line}")
        return None

    # Find the latest run report directory for this issue
    if not RUNS_ROOT.exists():
        print_warn("No reports/runs/ directory found after solver run")
        return None

    matching = sorted(
        [
            d for d in RUNS_ROOT.iterdir()
            if d.is_dir() and f"issue-{issue.number}" in d.name
        ],
        key=lambda d: d.name,
        reverse=True,
    )
    if matching:
        run_name = matching[0].name
        print_ok(f"      Run report: {run_name}")
        return run_name

    print_warn(f"No run report directory found for issue #{issue.number}")
    return None


def run_reviewer_for_pr(
    pr_url: str,
    role: str = "code",
    owner: str = "SaJaToGu",
    repo: str = "ai-issue-solver",
    dry_run: bool = False,
) -> str | None:
    """Run the reviewer for a given PR URL.

    Returns the reviewer verdict text or None on failure.
    """
    pr_match = re.search(r"/pull/(\d+)$", pr_url)
    if not pr_match:
        print_warn(f"Cannot parse PR number from URL: {pr_url}")
        return None

    pr_number = int(pr_match.group(1))
    cmd = [
        sys.executable,
        str(SCRIPT_DIR / "review_pr.py"),
        "--pr", str(pr_number),
        "--role", role,
        "--owner", owner,
        "--repo", repo,
    ]

    if dry_run:
        cmd.append("--dry-run")
        print(f"      [DRY-RUN] Would run: {' '.join(cmd)}")
        return None

    print(f"      Reviewer ({role}): PR #{pr_number}")
    result = subprocess.run(
        cmd,
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        timeout=300,
    )

    if result.returncode > 1:
        output = (result.stderr or result.stdout or "").strip()
        print_warn(f"      Reviewer exited with code {result.returncode}")
        if output:
            for line in output.splitlines()[-5:]:
                print(f"      | {line}")
        return None

    verdict_text = (result.stdout or "").strip()
    if result.returncode == 2:
        print_warn("      Reviewer ran but no **Verdict**: line found")
    else:
        print_ok("      Reviewer verdict emitted")

    return verdict_text


# ── Metrics computation ─────────────────────────────────────────

def compute_metrics(
    reports: list[RunReportData],
    pr_outcomes: list[dict[str, Any]] | None = None,
) -> ValidationMetrics:
    """Compute aggregated validation metrics from run reports and PR outcomes."""

    pr_number_for_url = {}
    po_by_run_dir: dict[str, dict[str, Any]] = {}
    if pr_outcomes:
        for po in pr_outcomes:
            run_dir = po["run_dir"]
            po_by_run_dir[run_dir] = po
            if po["pr_url"]:
                pr_match = re.search(r"/pull/(\d+)$", po["pr_url"])
                if pr_match:
                    pr_number_for_url[po["pr_url"]] = int(pr_match.group(1))

    total_cost = 0.0
    total_duration = 0.0
    cost_issues = 0
    duration_issues = 0

    prs_merged = 0
    prs_created_not_merged = 0
    solved_count = 0

    error_counter: dict[str, int] = {}
    issue_outcomes: list[dict[str, Any]] = []

    for report in reports:
        run_dir_str = str(report.run_dir)
        po = po_by_run_dir.get(run_dir_str, {})

        is_solved = po.get("solved", False)
        pr_merged = po.get("pr_merged")
        pr_url = po.get("pr_url", report.pr_url)

        if is_solved:
            solved_count += 1
            prs_merged += 1
        elif pr_merged:
            prs_merged += 1
            prs_created_not_merged += 1
        elif po.get("status") in STATUS_CATEGORY_SOLVED:
            prs_created_not_merged += 1
        elif report.pr_url and pr_merged is None:
            pass
        elif report.pr_url:
            if pr_merged is False:
                prs_created_not_merged += 1

        if report.estimated_cost is not None:
            total_cost += report.estimated_cost
            cost_issues += 1
        if report.duration_seconds is not None:
            total_duration += report.duration_seconds
            duration_issues += 1

        error_class = po.get("error_class") or report.error_class
        if error_class:
            error_counter[error_class] = error_counter.get(error_class, 0) + 1

        issue_outcomes.append({
            "issue_number": report.issue_number,
            "issue_title": report.issue_title,
            "status": report.status,
            "run_dir": run_dir_str,
            "pr_url": pr_url,
            "pr_merged": pr_merged,
            "pr_ci_green": po.get("ci_green"),
            "solved": is_solved,
            "error_class": error_class or "",
            "estimated_cost": report.estimated_cost,
            "duration_seconds": report.duration_seconds,
            "model": report.model,
        })

    total_issues = len(reports)
    success_rate = (solved_count / total_issues * 100) if total_issues > 0 else 0.0
    cost_per_solved = (total_cost / solved_count) if solved_count > 0 else 0.0
    time_per_solved = (total_duration / solved_count) if solved_count > 0 else 0.0

    sorted_errors = sorted(
        error_counter.items(),
        key=lambda x: x[1],
        reverse=True,
    )

    return ValidationMetrics(
        issues_processed=total_issues,
        prs_merged=prs_merged,
        prs_created_not_merged=prs_created_not_merged,
        success_rate=success_rate,
        total_cost=total_cost,
        total_time_seconds=total_duration,
        cost_per_solved=cost_per_solved,
        time_per_solved=time_per_solved,
        top_errors=sorted_errors[:5],
        outcomes=issue_outcomes,
    )


# ── Report generation ───────────────────────────────────────────

def format_duration(seconds: float) -> str:
    """Format seconds into a human-readable duration string."""
    if seconds < 60:
        return f"{seconds:.0f}s"
    minutes = int(seconds // 60)
    secs = int(seconds % 60)
    if minutes < 60:
        return f"{minutes}m {secs:02d}s"
    hours = minutes // 60
    minutes = minutes % 60
    return f"{hours}h {minutes:02d}m {secs:02d}s"


def format_cost(usd: float | None) -> str:
    if usd is None or usd == 0.0:
        return "$0.00"
    return f"${usd:.2f}"


def generate_report(
    metrics: ValidationMetrics,
    config: ValidationConfig | None = None,
    report_path: Path = REPORT_PATH,
) -> Path:
    """Generate the validation-0.9.0.md report file.

    Returns the path to the generated report.
    """
    lines: list[str] = [
        "# Validation Report 0.9.0",
        "",
    ]

    if config:
        lines.append(f"- **Validation Run ID:** `{config.validation_run_id}`")
        lines.append(f"- **Date:** {config.created_at}")
        lines.append(f"- **Model:** {config.model_name or config.model}")
        lines.append(f"- **Repository:** `{config.owner}/{config.repo}`")
        lines.append(f"- **Target issue count:** {config.issue_count}")
        lines.append("")

    lines.append("## Summary")
    lines.append("")
    lines.append(f"| Metric | Value |")
    lines.append(f"|--------|-------|")
    lines.append(f"| Issues processed | {metrics.issues_processed} |")
    lines.append(f"| PRs merged (solved) | {metrics.prs_merged} |")
    lines.append(f"| PRs created but not merged | {metrics.prs_created_not_merged} |")
    lines.append(f"| Success rate | {metrics.success_rate:.1f}% |")
    lines.append(f"| Total cost | {format_cost(metrics.total_cost)} |")
    lines.append(f"| Total time | {format_duration(metrics.total_time_seconds)} |")
    lines.append(f"| Cost per solved issue | {format_cost(metrics.cost_per_solved)} |")
    lines.append(f"| Time per solved issue | {format_duration(metrics.time_per_solved)} |")
    lines.append("")

    if metrics.top_errors:
        lines.append("## Top 5 Error Classes")
        lines.append("")
        for i, (error_class, count) in enumerate(metrics.top_errors, 1):
            description = ERROR_CLASS_DESCRIPTIONS.get(error_class, error_class)
            lines.append(f"{i}. `{error_class}` — {count} issue(s): {description}")
        lines.append("")

    lines.append("## Definition of Solved")
    lines.append("")
    lines.append("An issue counts as **solved** if and only if:")
    lines.append("")
    lines.append("1. The solver produced a PR.")
    lines.append("2. The PR was **merged** into the default branch.")
    lines.append("3. The merge commit's CI run is **green**.")
    lines.append("")
    lines.append("Anything less is NOT solved. \"Solved\" is a machine-checkable state, not a judgment.")
    lines.append("")

    if metrics.outcomes:
        lines.append("## Per-Issue Outcomes")
        lines.append("")
        lines.append("| # | Issue | Title | Status | PR | Merged | CI | Cost | Time |")
        lines.append("|---|-------|-------|--------|----|--------|----|------|------|")

        for outcome in metrics.outcomes:
            issue_num = outcome["issue_number"]
            title = outcome["issue_title"][:50]
            status = outcome["status"]
            pr_url = outcome["pr_url"]
            pr_merged = outcome["pr_merged"]
            pr_ci = outcome["pr_ci_green"]
            cost = outcome["estimated_cost"]
            duration = outcome["duration_seconds"]

            pr_link = f"[PR]({pr_url})" if pr_url else "—"
            merged_str = "✅" if pr_merged else ("❌" if pr_merged is False else "—")
            ci_str = "✅" if pr_ci else ("❌" if pr_ci is False else "—")
            cost_str = format_cost(cost) if cost is not None else "—"
            time_str = format_duration(duration) if duration is not None else "—"

            lines.append(
                f"| #{issue_num} | `{issue_num}` | {title} | {status} | "
                f"{pr_link} | {merged_str} | {ci_str} | {cost_str} | {time_str} |"
            )
        lines.append("")

    lines.append("## Error Class Descriptions")
    lines.append("")
    lines.append("| Class | Description |")
    lines.append("|-------|-------------|")
    for cls, desc in ERROR_CLASS_DESCRIPTIONS.items():
        lines.append(f"| `{cls}` | {desc} |")
    lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("*Report generated by `scripts/validation_run.py`*")
    if config:
        lines.append(f"*Validation run: `{config.validation_run_id}`*")
    lines.append(f"*Generated at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*")
    lines.append("")

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines), encoding="utf-8")
    print_ok(f"Report written to {report_path}")
    return report_path


ERROR_CLASS_DESCRIPTIONS: dict[str, str] = {
    "success": "PR created, merged, and CI green (solved)",
    "noop": "No changes needed or issue already resolved",
    "model_failure": "Worker returned nonzero exit code without meaningful changes",
    "pipeline_failure": "Branch pushed but PR creation or delivery failed",
    "runtime_failure": "Runtime error during cloning, checkout, or worker startup",
    "control_failure": "Budget exceeded or cost control triggered termination",
    "validation_failure": "Worker produced changes but post-solve validation failed (e.g. syntax errors, conflict markers)",
    "interrupted": "Run was interrupted before completion (e.g. timeout, signal)",
    "no_pr": "No pull request was created by the solver",
    "not_merged": "PR was created but not yet merged into the default branch",
    "ci_red": "PR merged but CI run on merge commit is not green",
    "skip_existing_pr": "Issue already has an open PR, skipped",
    "skip_merged_pr": "Issue already has a merged PR, skipped",
    "invalid_pr_url": "PR URL could not be parsed from run report",
    "unknown": "Unclassified or missing error information",
}


# ── Validation run management ────────────────────────────────────

def create_validation_run(config: ValidationConfig) -> Path:
    """Persist the validation run configuration to disk.

    Returns the path to the validation run directory.
    """
    run_dir = VALIDATION_RUNS_ROOT / config.validation_run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    config_dict = {
        "validation_run_id": config.validation_run_id,
        "created_at": config.created_at,
        "model": config.model,
        "model_name": config.model_name,
        "owner": config.owner,
        "repo": config.repo,
        "max_run_cost_usd": config.max_run_cost_usd,
        "issue_count": config.issue_count,
        "issues": config.issues,
        "run_report_paths": config.run_report_paths,
    }
    (run_dir / "config.json").write_text(
        json.dumps(config_dict, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print_ok(f"Validation run config saved to {run_dir / 'config.json'}")
    return run_dir


def load_validation_run(validation_run_id: str) -> ValidationConfig | None:
    """Load a validation run configuration from disk."""
    run_dir = VALIDATION_RUNS_ROOT / validation_run_id
    config_path = run_dir / "config.json"
    if not config_path.exists():
        print_err(f"Validation run not found: {validation_run_id}")
        return None

    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        print_err(f"Failed to load validation run config: {exc}")
        return None

    return ValidationConfig(
        validation_run_id=data.get("validation_run_id", validation_run_id),
        created_at=data.get("created_at", ""),
        model=data.get("model", DEFAULT_MODEL),
        model_name=data.get("model_name", ""),
        owner=data.get("owner", DEFAULT_OWNER),
        repo=data.get("repo", DEFAULT_REPO),
        max_run_cost_usd=data.get("max_run_cost_usd"),
        issue_count=data.get("issue_count", 0),
        issues=data.get("issues", []),
        run_report_paths=data.get("run_report_paths", []),
    )


def update_validation_run_run_reports(
    validation_run_id: str,
    run_report_paths: list[str],
) -> None:
    """Update the run report paths in an existing validation run config."""
    config = load_validation_run(validation_run_id)
    if config is None:
        return
    config.run_report_paths = run_report_paths
    run_dir = VALIDATION_RUNS_ROOT / validation_run_id
    config_dict = {
        "validation_run_id": config.validation_run_id,
        "created_at": config.created_at,
        "model": config.model,
        "model_name": config.model_name,
        "owner": config.owner,
        "repo": config.repo,
        "max_run_cost_usd": config.max_run_cost_usd,
        "issue_count": config.issue_count,
        "issues": config.issues,
        "run_report_paths": config.run_report_paths,
    }
    (run_dir / "config.json").write_text(
        json.dumps(config_dict, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def list_validation_runs() -> list[Path]:
    """List all previous validation run directories."""
    if not VALIDATION_RUNS_ROOT.exists():
        return []
    return sorted(
        [d for d in VALIDATION_RUNS_ROOT.iterdir() if d.is_dir()],
        key=lambda d: d.name,
        reverse=True,
    )


# ── Subcommand implementations ──────────────────────────────────

def cmd_run(args: argparse.Namespace) -> int:
    """Execute the full validation pipeline (solver + report)."""
    print_banner("VALIDATION RUN 0.9.0")

    config = load_env()

    token = config.get("GITHUB_TOKEN", "")
    owner = args.owner or config.get("GITHUB_USER", DEFAULT_OWNER)
    repo = args.repo or DEFAULT_REPO

    if not token or token.strip().startswith("ghp_DEIN"):
        if args.dry_run:
            print_warn("GitHub token is a placeholder; dry-run mode uses no API calls")
        else:
            if requests is None:
                print_err("Python module 'requests' is required. Install: pip install requests")
                return 1
            print_warn("GitHub token is a placeholder; PR status checking will be skipped")
            token = ""

    client: ValidationGitHubClient | None = None
    if token and requests:
        client = ValidationGitHubClient(token, owner)

    if args.list_runs:
        runs = list_validation_runs()
        if not runs:
            print("No previous validation runs found.")
        else:
            print(f"Found {len(runs)} previous validation run(s):")
            for run_dir in runs:
                cfg_path = run_dir / "config.json"
                if cfg_path.exists():
                    try:
                        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
                        created = cfg.get("created_at", "?")
                        model = cfg.get("model_name", cfg.get("model", "?"))
                        count = cfg.get("issue_count", "?")
                        print(f"   {run_dir.name}  ({created})  model={model}  count={count}")
                    except (json.JSONDecodeError, OSError):
                        print(f"   {run_dir.name}  (config unreadable)")
                else:
                    print(f"   {run_dir.name}")
        return 0

    validation_run_id = datetime.now().strftime("v-%Y%m%d-%H%M%S")
    print(f"   Validation run ID: {validation_run_id}")
    print(f"   Model: {args.model_name or args.model}")
    print(f"   Count: {args.count}")
    print()

    # ── Step 1: Select issues ──
    print_step(1, "Selecting issues for validation")

    issues = select_issues_by_label(
        client,
        repo,
        count=args.count,
        label=args.label,
        explicit_numbers=args.issues,
    )

    if not issues:
        print_err("No issues found for validation. Use --issues to specify explicitly.")
        return 1

    print(f"   Selected {len(issues)} issue(s):")
    for iss in issues:
        print(f"      #{iss.number}: {iss.title}")
    print()

    # ── Step 2: Run solver ──
    print_step(2, f"Running solver on {len(issues)} issue(s)")

    run_report_names: list[str] = []
    for i, iss in enumerate(issues, 1):
        print(f"   [{i}/{len(issues)}] Processing issue #{iss.number}")
        run_name = run_solver_for_issue(
            issue=iss,
            model=args.model,
            model_name=args.model_name,
            owner=owner,
            repo=repo,
            max_run_cost_usd=args.max_run_cost_usd,
            dry_run=args.dry_run,
            verbose=args.verbose,
            base_branch=args.base_branch,
        )
        if run_name:
            run_report_names.append(run_name)
        print()
        if not args.dry_run:
            time.sleep(2)

    # ── Step 3a: Persist validation run config ──
    config_obj = ValidationConfig(
        validation_run_id=validation_run_id,
        created_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        model=args.model,
        model_name=args.model_name or "",
        owner=owner,
        repo=repo,
        max_run_cost_usd=args.max_run_cost_usd,
        issue_count=args.count,
        issues=[{"number": iss.number, "title": iss.title} for iss in issues],
        run_report_paths=run_report_names,
    )

    if not args.dry_run:
        run_dir = create_validation_run(config_obj)
    else:
        run_dir = VALIDATION_RUNS_ROOT / validation_run_id
        print(f"   [DRY-RUN] Would create validation run at {run_dir}")

    # ── Step 3b: Run reviewer on each PR (optional) ──
    if args.run_reviewer and run_report_names and not args.dry_run:
        print_step(3, f"Running reviewer on PRs")

        run_reports = collect_run_reports([
            RUNS_ROOT / name for name in run_report_names
        ])

        for report in run_reports:
            if report.pr_url:
                verdict = run_reviewer_for_pr(
                    report.pr_url,
                    role=args.reviewer_role,
                    owner=owner,
                    repo=repo,
                    dry_run=args.dry_run,
                )
                if verdict:
                    print(f"         Verdict available ({len(verdict)} chars)")
            else:
                print(f"      No PR for issue #{report.issue_number}, skipping reviewer")

    # ── Step 4: Check PR statuses ──
    if not args.dry_run:
        run_reports = collect_run_reports([
            RUNS_ROOT / name for name in run_report_names
        ])

        if client:
            print_step(4, "Checking PR merge and CI status")
            pr_outcomes, merged_count, ci_green_count = check_pr_statuses(
                run_reports, owner, repo, client,
            )
            print(f"   PRs merged: {merged_count}")
            print(f"   CI green:   {ci_green_count}")
        else:
            pr_outcomes = None
            print_step(4, "PR status check skipped (no GitHub client)")
    else:
        run_reports = []
        pr_outcomes = None
        print_step(4, "PR status check skipped (dry-run)")

    # ── Step 5: Compute metrics and generate report ──
    print_step(5, "Computing metrics and generating report")

    run_reports = collect_run_reports([
        RUNS_ROOT / name for name in run_report_names
    ])

    metrics = compute_metrics(run_reports, pr_outcomes)

    if args.dry_run:
        print()
        print("   [DRY-RUN] Projected metrics:")
        print(f"      Issues processed: {metrics.issues_processed}")
        print(f"      Success rate: {metrics.success_rate:.1f}%")
        print(f"      Total cost: {format_cost(metrics.total_cost)}")
        print(f"      Total time: {format_duration(metrics.total_time_seconds)}")
        print()
        print(f"   [DRY-RUN] Would write report to {REPORT_PATH}")
    else:
        report_path = generate_report(metrics, config_obj)
        print_ok(f"Validation report: {report_path}")

    # ── Summary ──
    print()
    print("─" * 50)
    print(f"  Issues processed:  {metrics.issues_processed}")
    print(f"  PRs merged:        {metrics.prs_merged}")
    print(f"  Success rate:      {metrics.success_rate:.1f}%")
    print(f"  Total cost:        {format_cost(metrics.total_cost)}")
    print(f"  Total time:        {format_duration(metrics.total_time_seconds)}")
    print("─" * 50)

    return 0


def cmd_report(args: argparse.Namespace) -> int:
    """Generate the validation report from existing run data."""
    print_banner("VALIDATION REPORT 0.9.0")

    # Load validation run config if --run-id is given
    config: ValidationConfig | None = None
    run_report_paths: list[Path] | None = None

    if args.run_id:
        config = load_validation_run(args.run_id)
        if config is None:
            return 1
        run_report_paths = [
            RUNS_ROOT / name for name in config.run_report_paths
        ]
        print(f"   Validation run: {args.run_id}")
    elif args.report_dir:
        run_report_paths = [Path(p) for p in args.report_dir]
        print(f"   Using specified run directories ({len(run_report_paths)} dirs)")
    else:
        print("   Scanning all run reports in reports/runs/")
        run_report_paths = None

    reports = collect_run_reports(run_report_paths)
    if not reports:
        print_err("No run reports found")
        return 1

    print(f"   Found {len(reports)} run report(s)")

    # Check PR statuses if GitHub client is available
    config_obj = load_env()
    token = config_obj.get("GITHUB_TOKEN", "")
    owner = config.owner if config else (args.owner or config_obj.get("GITHUB_USER", DEFAULT_OWNER))
    repo = config.repo if config else (args.repo or DEFAULT_REPO)

    pr_outcomes: list[dict[str, Any]] | None = None
    if token and not token.strip().startswith("ghp_DEIN") and requests:
        client = ValidationGitHubClient(token, owner)
        print_step(2, "Checking PR merge and CI status")
        pr_outcomes, merged_count, ci_green_count = check_pr_statuses(
            reports, owner, repo, client,
        )
        print(f"   PRs merged: {merged_count}")
        print(f"   CI green:   {ci_green_count}")
    else:
        print_warn("GitHub token not available; PR status check skipped")
        print_warn("Only solver-level outcomes will be reported")

    metrics = compute_metrics(reports, pr_outcomes)
    report_path = generate_report(metrics, config)

    print()
    print("─" * 50)
    print(f"  Issues processed:  {metrics.issues_processed}")
    print(f"  PRs merged:        {metrics.prs_merged}")
    print(f"  Success rate:      {metrics.success_rate:.1f}%")
    print(f"  Total cost:        {format_cost(metrics.total_cost)}")
    print(f"  Total time:        {format_duration(metrics.total_time_seconds)}")
    print("─" * 50)

    return 0


def cmd_check_prs(args: argparse.Namespace) -> int:
    """Check PR merge + CI status for a previous validation run."""
    print_banner("CHECK PR STATUS")

    config = load_validation_run(args.run_id)
    if config is None:
        return 1

    config_obj = load_env()
    token = config_obj.get("GITHUB_TOKEN", "")
    owner = config.owner or args.owner or config_obj.get("GITHUB_USER", DEFAULT_OWNER)
    repo = config.repo or args.repo or DEFAULT_REPO

    if not token or token.strip().startswith("ghp_DEIN") or requests is None:
        print_err("Valid GitHub token required (install requests and set GITHUB_TOKEN)")
        return 1

    run_report_paths = [RUNS_ROOT / name for name in config.run_report_paths]

    reports = collect_run_reports(run_report_paths)
    if not reports:
        print_err("No run reports found for this validation run")
        return 1

    client = ValidationGitHubClient(token, owner)
    pr_outcomes, merged_count, ci_green_count = check_pr_statuses(
        reports, owner, repo, client,
    )

    print(f"   Validation run: {args.run_id}")
    print(f"   Owner/Repo: {owner}/{repo}")
    print()
    print(f"   PRs merged:       {merged_count}")
    print(f"   CI green:         {ci_green_count}")
    print()

    for outcome in pr_outcomes:
        issue = outcome["issue_number"]
        pr_url = outcome["pr_url"]
        merged = outcome["pr_merged"]
        ci = outcome["ci_green"]
        status = outcome["status"]

        merged_str = "✅ merged" if merged else ("❌ not merged" if merged is False else "—")
        ci_str = "✅ green" if ci else ("❌ red" if ci is False else "—")
        print(f"   #{issue}: {status}  {merged_str}  {ci_str}")
        if pr_url:
            print(f"           {pr_url}")

    return 0


def cmd_list(args: argparse.Namespace) -> int:
    """List open issues suitable for validation."""
    config_obj = load_env()
    token = config_obj.get("GITHUB_TOKEN", "")
    owner = args.owner or config_obj.get("GITHUB_USER", DEFAULT_OWNER)
    repo = args.repo or DEFAULT_REPO

    if not token or token.strip().startswith("ghp_DEIN") or requests is None:
        print_err("Valid GitHub token required")
        return 1

    client = ValidationGitHubClient(token, owner)

    issues = select_issues_by_label(
        client,
        repo,
        count=args.count,
        label=args.label,
    )

    if not issues:
        print(f"No open issues found in {owner}/{repo} with label '{args.label}'")
        return 0

    print(f"Open issues in {owner}/{repo} (label: {args.label}):")
    print()
    for iss in issues:
        labels_str = ", ".join(iss.labels) if iss.labels else "(no labels)"
        body_preview = iss.body[:60].replace("\n", " ") if iss.body else ""
        print(f"   #{iss.number}: {iss.title}")
        print(f"      Labels: {labels_str}")
        if body_preview:
            print(f"      {body_preview}...")
        print()

    print(f"Total: {len(issues)} issue(s)")
    return 0


# ── CLI ──────────────────────────────────────────────────────────

def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validation Metrics & Run (Release 0.9.0)",
    )
    subparsers = parser.add_subparsers(dest="command", help="Subcommand")

    # ── run ──
    run_parser = subparsers.add_parser(
        "run",
        help="Execute the solver pipeline on N issues and generate report",
    )
    run_parser.add_argument(
        "--count", type=int, default=DEFAULT_ISSUE_COUNT,
        help=f"Number of issues to process (default: {DEFAULT_ISSUE_COUNT})",
    )
    run_parser.add_argument(
        "--issues", type=lambda s: [int(x) for x in s.split(",")],
        help="Comma-separated issue numbers (overrides --count)",
    )
    run_parser.add_argument(
        "--model", default=DEFAULT_MODEL,
        choices=("codex", "claude", "openai", "mistral", "ollama",
                 "mistral-vibe", "opencode", "openrouter", "openrouter_direct"),
        help=f"KI-Modell (default: {DEFAULT_MODEL})",
    )
    run_parser.add_argument(
        "--model-name", default=DEFAULT_MODEL_NAME,
        help=f"Spezifischer Modellname (default: {DEFAULT_MODEL_NAME})",
    )
    run_parser.add_argument(
        "--max-run-cost-usd", type=float, default=DEFAULT_MAX_COST_USD,
        help=f"Maximale Kosten pro Run in USD (default: {DEFAULT_MAX_COST_USD})",
    )
    run_parser.add_argument(
        "--owner", default=None,
        help="GitHub owner (default: from config or SaJaToGu)",
    )
    run_parser.add_argument(
        "--repo", default=DEFAULT_REPO,
        help=f"GitHub repo (default: {DEFAULT_REPO})",
    )
    run_parser.add_argument(
        "--label", default="ai-generated",
        help="Issue label filter for auto-selection (default: ai-generated)",
    )
    run_parser.add_argument(
        "--base-branch", default=None,
        help="Zielbranch fuer Klon und PR (default: GitHub Default-Branch)",
    )
    run_parser.add_argument(
        "--run-reviewer", action="store_true",
        help="Run the reviewer on each created PR",
    )
    run_parser.add_argument(
        "--reviewer-role", default="code",
        choices=("code", "architecture", "documentation"),
        help="Reviewer role (default: code)",
    )
    run_parser.add_argument(
        "--dry-run", action="store_true",
        help="Show what would be done without running solver",
    )
    run_parser.add_argument(
        "--verbose", action="store_true",
        help="Show full solver output",
    )
    run_parser.add_argument(
        "--list-runs", action="store_true",
        help="List previous validation runs and exit",
    )

    # ── report ──
    report_parser = subparsers.add_parser(
        "report",
        help="Generate the validation report from existing run data",
    )
    report_parser.add_argument(
        "--run-id", default=None,
        help="Validation run ID (from reports/validation-runs/)",
    )
    report_parser.add_argument(
        "--report-dir", nargs="*", default=None,
        help="One or more run report directories (path relative to reports/runs/)",
    )
    report_parser.add_argument(
        "--owner", default=None,
        help="GitHub owner (default: from config)",
    )
    report_parser.add_argument(
        "--repo", default=None,
        help="GitHub repo (default: from config)",
    )

    # ── check-prs ──
    check_parser = subparsers.add_parser(
        "check-prs",
        help="Check PR merge + CI status for a previous validation run",
    )
    check_parser.add_argument(
        "--run-id", required=True,
        help="Validation run ID (from reports/validation-runs/)",
    )
    check_parser.add_argument(
        "--owner", default=None,
        help="GitHub owner override",
    )
    check_parser.add_argument(
        "--repo", default=None,
        help="GitHub repo override",
    )

    # ── list ──
    list_parser = subparsers.add_parser(
        "list",
        help="List open issues suitable for validation",
    )
    list_parser.add_argument(
        "--count", type=int, default=20,
        help="Number of issues to list (default: 20)",
    )
    list_parser.add_argument(
        "--label", default="ai-generated",
        help="Issue label filter (default: ai-generated)",
    )
    list_parser.add_argument(
        "--owner", default=None,
        help="GitHub owner (default: from config)",
    )
    list_parser.add_argument(
        "--repo", default=DEFAULT_REPO,
        help=f"GitHub repo (default: {DEFAULT_REPO})",
    )

    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        sys.exit(1)
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    if args.command == "run":
        return cmd_run(args)
    elif args.command == "report":
        return cmd_report(args)
    elif args.command == "check-prs":
        return cmd_check_prs(args)
    elif args.command == "list":
        return cmd_list(args)
    else:
        print_err(f"Unknown command: {args.command}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
