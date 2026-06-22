from __future__ import annotations

import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from scripts.validation.models import RunReportData


SOLVE_ISSUES_SCRIPT = Path("scripts/solve_issues.py")
REVIEW_PR_SCRIPT = Path("scripts/review_pr.py")


def run_solver_for_issue(
    repo: str,
    issue_number: int,
    model: str = "opencode",
    model_name: str = "opencode/deepseek-v4-flash-free",
    max_run_cost_usd: float = 5.0,
    dry_run: bool = False,
    base_branch: str | None = None,
    timeout_seconds: int = 1800,
) -> RunReportData:
    script = SOLVE_ISSUES_SCRIPT
    cmd = [
        sys.executable, str(script),
        "--model", model,
        "--model-name", model_name,
        "--repo", repo,
        "--issue", str(issue_number),
        "--no-close",
    ]
    if base_branch:
        cmd.extend(["--base-branch", base_branch])
    if max_run_cost_usd is not None:
        cmd.extend(["--max-run-cost-usd", str(max_run_cost_usd)])
    if dry_run:
        cmd.append("--dry-run")

    started_at = datetime.utcnow().isoformat()
    start_wall = time.monotonic()

    if dry_run:
        finished_at = datetime.utcnow().isoformat()
        return RunReportData(
            issue_number=issue_number,
            issue_title="",
            status="dry_run",
            pr_number=None,
            pr_url=None,
            pr_merged=None,
            ci_green=None,
            duration_seconds=0.0,
            cost_usd=0.0,
            model=model_name,
            error_class=None,
            error_detail=None,
            started_at=started_at,
            finished_at=finished_at,
            run_id=None,
        )

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired:
        finished_at = datetime.utcnow().isoformat()
        return RunReportData(
            issue_number=issue_number,
            issue_title="",
            status="timeout",
            pr_number=None,
            pr_url=None,
            pr_merged=None,
            ci_green=None,
            duration_seconds=time.monotonic() - start_wall,
            cost_usd=None,
            model=model_name,
            error_class="timeout",
            error_detail=f"subprocess timed out after {timeout_seconds}s",
            started_at=started_at,
            finished_at=finished_at,
            run_id=None,
        )

    finished_at = datetime.utcnow().isoformat()
    duration = time.monotonic() - start_wall
    status = "success" if result.returncode == 0 else "failed"

    error_class = None
    error_detail = None
    if result.returncode != 0:
        stderr = (result.stderr or "").strip()
        stdout = (result.stdout or "").strip()
        combined = stderr or stdout
        if "timeout" in combined.lower():
            error_class = "timeout"
        elif "rate limit" in combined.lower():
            error_class = "rate_limit"
        elif "permission" in combined.lower():
            error_class = "permission"
        elif "not found" in combined.lower():
            error_class = "not_found"
        else:
            error_class = "unknown_error"
        error_detail = combined[:500] if combined else None

    return RunReportData(
        issue_number=issue_number,
        issue_title="",
        status=status,
        pr_number=None,
        pr_url=None,
        pr_merged=None,
        ci_green=None,
        duration_seconds=duration,
        cost_usd=None,
        model=model_name,
        error_class=error_class,
        error_detail=error_detail,
        started_at=started_at,
        finished_at=finished_at,
        run_id=None,
    )


def run_reviewer_for_pr(
    pr_number: int,
    role: str = "code",
    owner: str = "SaJaToGu",
    repo: str = "ai-issue-solver",
    dry_run: bool = False,
    timeout_seconds: int = 300,
) -> dict[str, Any]:
    script = REVIEW_PR_SCRIPT
    cmd = [
        sys.executable, str(script),
        "--pr", str(pr_number),
        "--role", role,
        "--owner", owner,
        "--repo", repo,
    ]
    if dry_run:
        cmd.append("--dry-run")

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired:
        return {"status": "timeout", "error": f"reviewer timeout after {timeout_seconds}s"}

    return {
        "status": "success" if result.returncode == 0 else "failed",
        "returncode": result.returncode,
        "stdout": (result.stdout or ""),
        "stderr": (result.stderr or ""),
    }
