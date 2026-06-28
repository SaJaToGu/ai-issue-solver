"""ais_core.issue_resolve — locate and inspect GitHub issues.

This module is intentionally side-effect-free: it does not import any
GitHub client or perform I/O at import time. The functions below are
placeholders for the v0.10.0 implementation; they will be filled in
by subsequent work.

Public API:
    fetch_issue(owner, repo, number)         — load a single issue
    find_open_issues(owner, repo, label)     — list issues by label
    issue_is_ai_solvable(issue)              — heuristic classification
    ResolvedIssue                            — typed result
"""

from __future__ import annotations

from typing import NamedTuple


class ResolvedIssue(NamedTuple):
    """A minimal GitHub issue reference used by AIS callers.

    Attributes:
        owner: GitHub owner (user or org).
        repo: GitHub repository name.
        number: Issue number within the repo.
        title: Issue title.
        state: Issue state ('open' | 'closed').
        labels: Issue label names.
    """

    owner: str
    repo: str
    number: int
    title: str
    state: str
    labels: tuple[str, ...]


__all__ = [
    "ResolvedIssue",
    "fetch_issue",
    "find_open_issues",
    "issue_is_ai_solvable",
]


def fetch_issue(owner: str, repo: str, number: int) -> ResolvedIssue:
    """Load a single GitHub issue by (owner, repo, number)."""
    raise NotImplementedError("ais_core.issue_resolve.fetch_issue")


def find_open_issues(owner: str, repo: str, label: str) -> list[ResolvedIssue]:
    """List open issues in a repo filtered by label name."""
    raise NotImplementedError("ais_core.issue_resolve.find_open_issues")


def issue_is_ai_solvable(issue: ResolvedIssue) -> bool:
    """Heuristic: is this issue a candidate for an automated solver run?"""
    raise NotImplementedError("ais_core.issue_resolve.issue_is_ai_solvable")
