"""split_client.py — GitHub API helpers used by the backward-split loop.

Split from scripts/validation/github_client.py (was 277 LOC) to keep the
core client under its 250-LOC line cap. These methods are only used by
`scripts/validation/split.py` (the backward-split loop, see #402).

Why a separate class: keeping the split-loop's helper surface (PR file
listing, sub-issue creation, comment/close) out of the core
`ValidationGitHubClient` keeps the core client focused on
issue/PR/CI read paths and makes it easier to swap or mock the
split-loop surface in isolation.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import requests

from validation.github_client import ValidationGitHubClient
from validation.models import ValidationIssue


@dataclass(frozen=True)
class PrFileInfo:
    """One file changed in a PR (per GitHub REST API /pulls/{n}/files)."""

    filename: str
    status: str = ""
    additions: int = 0
    deletions: int = 0
    changes: int = 0


class SplitGitHubClient:
    """GitHub API surface used by the backward-split loop.

    Composition over inheritance: holds a `ValidationGitHubClient` and
    reuses its `BASE` + session. Constructed with an existing client so
    callers don't need to juggle two auth surfaces.
    """

    BASE = ValidationGitHubClient.BASE

    def __init__(self, client: ValidationGitHubClient) -> None:
        self._client = client
        self.session = client.session
        self.owner = client.owner

    # ----- Delegating read methods (so the surface used by split.py
    #       stays self-contained for mocking with spec=SplitGitHubClient) -----

    def get_pull_request(self, repo: str, number: int):
        return self._client.get_pull_request(repo, number)

    # ----- PR file listing -----

    def get_pr_files(self, repo: str, number: int) -> list[PrFileInfo]:
        resp = self.session.get(
            f"{self.BASE}/repos/{self.owner}/{repo}/pulls/{number}/files",
            params={"per_page": 100},
        )
        if resp.status_code == 404:
            return []
        self._client._raise_for_status(resp, f"get PR files: {repo}#{number}")
        return [
            PrFileInfo(
                filename=f["filename"],
                status=f.get("status", ""),
                additions=f.get("additions", 0),
                deletions=f.get("deletions", 0),
                changes=f.get("changes", 0),
            )
            for f in resp.json()
        ]

    # ----- Sub-issue creation -----

    def create_issue(self, repo: str, title: str, body: str, labels: list[str]) -> dict:
        url = f"{self.BASE}/repos/{self.owner}/{repo}/issues"
        resp = self.session.post(url, json={"title": title, "body": body, "labels": labels})
        self._client._raise_for_status(resp, f"create issue: {title}")
        return resp.json()

    def create_comment(self, repo: str, issue_number: int, body: str) -> dict:
        url = f"{self.BASE}/repos/{self.owner}/{repo}/issues/{issue_number}/comments"
        resp = self.session.post(url, json={"body": body})
        self._client._raise_for_status(resp, f"create comment on #{issue_number}")
        return resp.json()

    def close_issue(self, repo: str, issue_number: int) -> dict:
        url = f"{self.BASE}/repos/{self.owner}/{repo}/issues/{issue_number}"
        resp = self.session.patch(url, json={"state": "closed"})
        self._client._raise_for_status(resp, f"close issue: #{issue_number}")
        return resp.json()


__all__ = [
    "PrFileInfo",
    "SplitGitHubClient",
    # re-export so callers don't need both imports
    "ValidationIssue",
    "requests",
    "Any",
]
