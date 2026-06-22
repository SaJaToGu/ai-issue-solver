from __future__ import annotations

from typing import Any

from scripts.validation.github_client import (
    CiStatus,
    PullRequestInfo,
    ValidationGitHubClient,
)
from scripts.validation.models import RunReportData


def check_pr_statuses(
    client: ValidationGitHubClient,
    repo: str,
    report: RunReportData,
) -> RunReportData:
    if report.pr_number is None:
        return RunReportData(
            issue_number=report.issue_number,
            issue_title=report.issue_title,
            status=report.status,
            pr_number=report.pr_number,
            pr_url=report.pr_url,
            pr_merged=False,
            ci_green=None,
            duration_seconds=report.duration_seconds,
            cost_usd=report.cost_usd,
            model=report.model,
            error_class=report.error_class,
            error_detail=report.error_detail,
            started_at=report.started_at,
            finished_at=report.finished_at,
            run_id=report.run_id,
        )

    pr_info = client.get_pull_request(repo, report.pr_number)
    if pr_info is None:
        return report

    merged = pr_info.merged
    ci_green: bool | None = None

    if merged and pr_info.merge_commit_sha:
        ci_status = client.get_combined_ci_status(repo, pr_info.merge_commit_sha)
        ci_green = ci_status.state == "success"

    return RunReportData(
        issue_number=report.issue_number,
        issue_title=report.issue_title,
        status=report.status,
        pr_number=report.pr_number,
        pr_url=report.pr_url,
        pr_merged=merged,
        ci_green=ci_green,
        duration_seconds=report.duration_seconds,
        cost_usd=report.cost_usd,
        model=report.model,
        error_class=report.error_class,
        error_detail=report.error_detail,
        started_at=report.started_at,
        finished_at=report.finished_at,
        run_id=report.run_id,
    )


def is_pr_merged_and_green(
    client: ValidationGitHubClient,
    repo: str,
    pr_number: int,
) -> bool:
    pr_info = client.get_pull_request(repo, pr_number)
    if pr_info is None or not pr_info.merged:
        return False
    if pr_info.merge_commit_sha:
        ci_status = client.get_combined_ci_status(repo, pr_info.merge_commit_sha)
        return ci_status.state == "success"
    return False
