from __future__ import annotations

from typing import Any

from scripts.validation.github_client import ValidationGitHubClient
from scripts.validation.models import ValidationIssue


def select_issues_by_label(
    client: ValidationGitHubClient,
    repo: str,
    label: str = "ai-generated",
    max_issues: int = 10,
    state: str = "open",
    exclude_labels: tuple[str, ...] = (),
) -> list[ValidationIssue]:
    all_issues = client.get_issues_by_label(repo, label, state=state)
    filtered = [
        issue
        for issue in all_issues
        if not any(excl in issue.labels for excl in exclude_labels)
    ]
    return filtered[:max_issues]


def select_issues_by_criteria(
    issues: list[ValidationIssue],
    min_number: int | None = None,
    max_number: int | None = None,
    exclude_labels: tuple[str, ...] = (),
    max_issues: int = 10,
) -> list[ValidationIssue]:
    filtered = list(issues)
    if min_number is not None:
        filtered = [i for i in filtered if i.number >= min_number]
    if max_number is not None:
        filtered = [i for i in filtered if i.number <= max_number]
    if exclude_labels:
        filtered = [
            i for i in filtered
            if not any(excl in i.labels for excl in exclude_labels)
        ]
    return filtered[:max_issues]
