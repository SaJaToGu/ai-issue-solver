#!/usr/bin/env python3
"""Workflow congestion analysis for PR and issue queues."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Iterable


ISSUE_REF_RE = re.compile(
    r"(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?|ref(?:s)?|related(?:\s+to)?|parent)\s+#(\d+)|#(\d+)",
    re.IGNORECASE,
)
RED_STATES = {"error", "failure", "failed", "cancelled", "timed_out", "action_required", "dirty", "unstable"}
GREEN_STATES = {"success", "successful", "completed", "clean"}


@dataclass(frozen=True)
class WorkflowPullRequest:
    number: int
    title: str
    url: str = ""
    body: str = ""
    state: str = "open"
    draft: bool = False
    created_at: str = ""
    updated_at: str = ""
    mergeable_state: str = ""
    check_state: str = ""
    labels: tuple[str, ...] = ()


@dataclass(frozen=True)
class WorkflowIssue:
    number: int
    title: str
    url: str = ""
    state: str = "open"
    labels: tuple[str, ...] = ()


@dataclass(frozen=True)
class WorkflowCongestionFinding:
    kind: str
    severity: str
    message: str
    action: str
    pr_number: int | None = None
    issue_number: int | None = None


@dataclass(frozen=True)
class WorkflowCongestionSummary:
    open_pr_count: int
    red_pr_count: int
    green_unreviewed_pr_count: int
    stale_pr_count: int
    duplicate_issue_pr_count: int
    threshold: int
    findings: tuple[WorkflowCongestionFinding, ...] = field(default_factory=tuple)

    @property
    def needs_attention(self) -> bool:
        return bool(self.findings)

    @property
    def recommended_action(self) -> str:
        if self.red_pr_count:
            return "rerun_or_fix_red_pr"
        if self.open_pr_count > self.threshold:
            return "review_or_merge_pr_queue"
        if self.duplicate_issue_pr_count:
            return "skip_duplicate_issue_runs"
        if self.stale_pr_count:
            return "rebase_or_close_stale_pr"
        if self.green_unreviewed_pr_count:
            return "review_green_prs"
        return "continue"


def parse_issue_references(text: str) -> tuple[int, ...]:
    refs: list[int] = []
    for match in ISSUE_REF_RE.finditer(text or ""):
        value = match.group(1) or match.group(2)
        if not value:
            continue
        number = int(value)
        if number not in refs:
            refs.append(number)
    return tuple(refs)


def parse_github_datetime(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def pr_age_days(pr: WorkflowPullRequest, now: datetime) -> int:
    created = parse_github_datetime(pr.created_at)
    if created is None:
        return 0
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return max(0, (now - created).days)


def pull_request_from_github(data: dict) -> WorkflowPullRequest:
    labels = tuple(
        label.get("name", "")
        for label in data.get("labels", [])
        if isinstance(label, dict) and label.get("name")
    )
    return WorkflowPullRequest(
        number=int(data.get("number", 0)),
        title=str(data.get("title", "")),
        url=str(data.get("html_url", "")),
        body=str(data.get("body") or ""),
        state=str(data.get("state", "open")),
        draft=bool(data.get("draft", False)),
        created_at=str(data.get("created_at", "")),
        updated_at=str(data.get("updated_at", "")),
        mergeable_state=str(data.get("mergeable_state") or ""),
        check_state=str(data.get("check_state") or data.get("conclusion") or ""),
        labels=labels,
    )


def issue_from_github(data: dict) -> WorkflowIssue:
    labels = tuple(
        label.get("name", "")
        for label in data.get("labels", [])
        if isinstance(label, dict) and label.get("name")
    )
    return WorkflowIssue(
        number=int(data.get("number", 0)),
        title=str(data.get("title", "")),
        url=str(data.get("html_url", "")),
        state=str(data.get("state", "open")),
        labels=labels,
    )


def is_red_pr(pr: WorkflowPullRequest) -> bool:
    state = (pr.check_state or pr.mergeable_state or "").lower()
    return state in RED_STATES


def is_green_unreviewed_pr(pr: WorkflowPullRequest) -> bool:
    state = (pr.check_state or pr.mergeable_state or "").lower()
    return not pr.draft and state in GREEN_STATES


def analyze_workflow_congestion(
    pull_requests: Iterable[WorkflowPullRequest],
    open_issues: Iterable[WorkflowIssue],
    *,
    now: datetime | None = None,
    pr_threshold: int = 3,
    stale_days: int = 7,
) -> WorkflowCongestionSummary:
    now = now or datetime.now(timezone.utc)
    prs = [pr for pr in pull_requests if pr.state == "open"]
    issues_by_number = {issue.number: issue for issue in open_issues if issue.state == "open"}
    findings: list[WorkflowCongestionFinding] = []

    red_prs = [pr for pr in prs if is_red_pr(pr)]
    green_unreviewed = [pr for pr in prs if is_green_unreviewed_pr(pr)]
    stale_prs = [pr for pr in prs if pr_age_days(pr, now) >= stale_days]

    if len(prs) > pr_threshold:
        findings.append(WorkflowCongestionFinding(
            kind="open_pr_threshold",
            severity="warning",
            message=f"{len(prs)} open PRs exceed threshold {pr_threshold}",
            action="review_or_merge_pr_queue",
        ))

    for pr in red_prs:
        findings.append(WorkflowCongestionFinding(
            kind="red_pr",
            severity="error",
            message=f"PR #{pr.number} has unresolved red checks",
            action="rerun_or_fix_red_pr",
            pr_number=pr.number,
        ))

    for pr in stale_prs:
        findings.append(WorkflowCongestionFinding(
            kind="stale_pr",
            severity="warning",
            message=f"PR #{pr.number} is at least {stale_days} days old",
            action="rebase_or_close_stale_pr",
            pr_number=pr.number,
        ))

    duplicate_count = 0
    for pr in prs:
        refs = parse_issue_references(f"{pr.title}\n{pr.body}")
        for issue_number in refs:
            if issue_number in issues_by_number:
                duplicate_count += 1
                findings.append(WorkflowCongestionFinding(
                    kind="issue_has_open_pr",
                    severity="warning",
                    message=f"Issue #{issue_number} already has open PR #{pr.number}",
                    action="skip_duplicate_issue_runs",
                    pr_number=pr.number,
                    issue_number=issue_number,
                ))
                break

    return WorkflowCongestionSummary(
        open_pr_count=len(prs),
        red_pr_count=len(red_prs),
        green_unreviewed_pr_count=len(green_unreviewed),
        stale_pr_count=len(stale_prs),
        duplicate_issue_pr_count=duplicate_count,
        threshold=pr_threshold,
        findings=tuple(findings),
    )
