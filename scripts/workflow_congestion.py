#!/usr/bin/env python3
"""Workflow congestion analysis for PR and issue queues."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


ISSUE_REF_RE = re.compile(
    r"(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?|ref(?:s)?|related(?:\s+to)?|parent)\s+#(\d+)|#(\d+)",
    re.IGNORECASE,
)
RED_STATES = {"error", "failure", "failed", "cancelled", "timed_out", "action_required", "dirty", "unstable"}
GREEN_STATES = {"success", "successful", "completed", "clean"}

# Regex fuer generierte Branches: ai/fix-issue-<nummer>(-...)?
GENERATED_BRANCH_RE = re.compile(r"^ai/fix-issue-(\d+)(?:-|$)")
# Regex fuer Backlog-Sektionen: ## <number>. <title>
BACKLOG_SECTION_RE = re.compile(r"^##\s+(\d+)\.\s+(.+?)\s*$", re.MULTILINE)
# Regex fuer "Priority: `\d+`" in Backlog
BACKLOG_PRIORITY_RE = re.compile(r"Priority:\s*`(\d+)`")


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
class BacklogEntry:
    section_number: int
    title: str
    labels: tuple[str, ...] = ()
    priority: int = 0
    body: str = ""


@dataclass(frozen=True)
class WorkflowCongestionFinding:
    kind: str
    severity: str
    message: str
    action: str
    pr_number: int | None = None
    issue_number: int | None = None
    backlog_section: int | None = None


@dataclass(frozen=True)
class WorkflowCongestionSummary:
    open_pr_count: int
    red_pr_count: int
    green_unreviewed_pr_count: int
    stale_pr_count: int
    stale_generated_branch_count: int
    duplicate_issue_pr_count: int
    backlog_entry_with_open_issue_count: int
    backlog_entry_with_closed_issue_count: int
    superseded_approach_count: int
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
        if self.superseded_approach_count:
            return "close_superseded_pr"
        if self.duplicate_issue_pr_count:
            return "skip_duplicate_issue_runs"
        if self.stale_pr_count:
            return "rebase_or_close_stale_pr"
        if self.stale_generated_branch_count:
            return "clean_stale_generated_branches"
        if self.backlog_entry_with_closed_issue_count:
            return "clean_backlog_closed_issues"
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


def parse_backlog_entries(backlog_path: Path) -> list[BacklogEntry]:
    """Liest Backlog-Eintraege aus docs/NEXT_BACKLOG.md und gibt sie strukturiert zurueck."""
    if not backlog_path.exists():
        return []
    try:
        text = backlog_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []

    entries: list[BacklogEntry] = []
    sections = list(re.finditer(BACKLOG_SECTION_RE, text))

    for i, match in enumerate(sections):
        section_number = int(match.group(1))
        title = match.group(2).strip()
        section_start = match.start()
        section_end = sections[i + 1].start() if i + 1 < len(sections) else len(text)
        section_text = text[section_start:section_end]

        labels: list[str] = []
        priority = 0
        body_parts: list[str] = []

        for line in section_text.splitlines():
            stripped = line.strip()
            if stripped.startswith("Labels:"):
                labels = re.findall(r"`([^`]+)`", stripped)
            elif stripped.startswith("Priority:"):
                prio_match = BACKLOG_PRIORITY_RE.search(stripped)
                if prio_match:
                    priority = int(prio_match.group(1))
            elif stripped.startswith("##") and not stripped.startswith("###"):
                continue
            else:
                body_parts.append(stripped)

        entries.append(BacklogEntry(
            section_number=section_number,
            title=title,
            labels=tuple(labels),
            priority=priority,
            body="\n".join(body_parts).strip(),
        ))

    return entries


def match_backlog_to_issues(
    backlog_entries: list[BacklogEntry],
    open_issues: Iterable[WorkflowIssue],
    closed_issues: Iterable[WorkflowIssue],
) -> dict[int, tuple[WorkflowIssue | None, WorkflowIssue | None]]:
    """Ordnet Backlog-Eintraege offenen und geschlossenen GitHub Issues zu.

    Returns:
        Dict mapping backlog section number -> (open_issue_or_None, closed_issue_or_None)
    """
    open_map: dict[str, WorkflowIssue] = {}
    closed_map: dict[str, WorkflowIssue] = {}

    for issue in open_issues:
        open_map[issue.title.lower().strip()] = issue
    for issue in closed_issues:
        closed_map[issue.title.lower().strip()] = issue

    result: dict[int, tuple[WorkflowIssue | None, WorkflowIssue | None]] = {}
    for entry in backlog_entries:
        key = entry.title.lower().strip()
        open_match = open_map.get(key)
        closed_match = closed_map.get(key)
        if open_match or closed_match:
            result[entry.section_number] = (open_match, closed_match)
    return result


def analyze_workflow_congestion(
    pull_requests: Iterable[WorkflowPullRequest],
    open_issues: Iterable[WorkflowIssue],
    closed_issues: Iterable[WorkflowIssue] | None = None,
    backlog_entries: list[BacklogEntry] | None = None,
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

    # Pruefe auf stale generierte Branches (ai/fix-issue-* ohne offenen PR)
    stale_generated_branches: set[str] = set()
    pr_branch_refs: set[str] = set()
    for pr in prs:
        if pr.url:
            pr_branch_refs.add(pr.title.split(":")[-1] if ":" in pr.title else "")

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
    superseded_count = 0
    for pr in prs:
        refs = parse_issue_references(f"{pr.title}\n{pr.body}")
        has_issue_ref = False
        for issue_number in refs:
            if issue_number in issues_by_number:
                duplicate_count += 1
                has_issue_ref = True
                findings.append(WorkflowCongestionFinding(
                    kind="issue_has_open_pr",
                    severity="warning",
                    message=f"Issue #{issue_number} already has open PR #{pr.number}",
                    action="skip_duplicate_issue_runs",
                    pr_number=pr.number,
                    issue_number=issue_number,
                ))
                break

        # Erkenne superseded PRs: PRs die auf Issues verweisen, fuer die es bereits
        # einen anderen offenen PR gibt (mehrfach-Referenz)
        if not has_issue_ref and len(refs) >= 1:
            if refs[0] in issues_by_number:
                superseded_count += 1
                findings.append(WorkflowCongestionFinding(
                    kind="superseded_pr",
                    severity="info",
                    message=f"PR #{pr.number} may supersede an existing approach for issue #{refs[0]}",
                    action="close_superseded_pr",
                    pr_number=pr.number,
                    issue_number=refs[0],
                ))

    # Backlog-Analyse
    backlog_with_open = 0
    backlog_with_closed = 0
    if backlog_entries and closed_issues is not None:
        closed_issues_list = [i for i in closed_issues if i.state == "closed"]
        backlog_match = match_backlog_to_issues(
            backlog_entries, open_issues, closed_issues_list
        )
        for section_number, (open_match, closed_match) in backlog_match.items():
            if open_match and not closed_match:
                backlog_with_open += 1
                findings.append(WorkflowCongestionFinding(
                    kind="backlog_entry_has_open_issue",
                    severity="info",
                    message=(
                        f"Backlog #{section_number} already has open issue "
                        f"#{open_match.number}"
                    ),
                    action="skip_or_update_backlog",
                    issue_number=open_match.number,
                    backlog_section=section_number,
                ))
            if closed_match:
                backlog_with_closed += 1
                findings.append(WorkflowCongestionFinding(
                    kind="backlog_entry_has_closed_issue",
                    severity="warning",
                    message=(
                        f"Backlog #{section_number} has closed issue "
                        f"#{closed_match.number} - consider cleanup"
                    ),
                    action="clean_backlog_closed_issues",
                    issue_number=closed_match.number,
                    backlog_section=section_number,
                ))

    return WorkflowCongestionSummary(
        open_pr_count=len(prs),
        red_pr_count=len(red_prs),
        green_unreviewed_pr_count=len(green_unreviewed),
        stale_pr_count=len(stale_prs),
        stale_generated_branch_count=len(stale_generated_branches),
        duplicate_issue_pr_count=duplicate_count,
        backlog_entry_with_open_issue_count=backlog_with_open,
        backlog_entry_with_closed_issue_count=backlog_with_closed,
        superseded_approach_count=superseded_count,
        threshold=pr_threshold,
        findings=tuple(findings),
    )


def issue_has_open_pr(issue_number: int, prs: Iterable[WorkflowPullRequest]) -> bool:
    """Prueft ob ein Issue bereits einen offenen PR hat."""
    issue_str = f"#{issue_number}"
    for pr in prs:
        if pr.state != "open":
            continue
        if issue_str in pr.title or issue_str in pr.body:
            return True
        # Auch "closes #N", "fixes #N" erkennen
        refs = parse_issue_references(f"{pr.title}\n{pr.body}")
        if issue_number in refs:
            return True
    return False
