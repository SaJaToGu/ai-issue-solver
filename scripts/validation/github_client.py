from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

import requests

from validation.models import ValidationIssue


@dataclass(frozen=True)
class PullRequestInfo:
    number: int
    title: str
    state: str
    merged: bool
    merged_at: str | None = None
    html_url: str = ""
    head_ref: str = ""
    head_sha: str = ""
    base_ref: str = ""
    merge_commit_sha: str | None = None


@dataclass(frozen=True)
class CiStatus:
    state: str
    conclusion: str | None = None
    total_count: int = 0
    successful_count: int = 0


@dataclass(frozen=True)
class ReviewThread:
    """A single review comment thread on a PR."""
    id: int
    body: str
    user: str
    path: str | None = None
    position: int | None = None
    commit_id: str | None = None
    state: str = "pending"


class ValidationGitHubClient:
    BASE = "https://api.github.com"

    def __init__(self, token: str, owner: str):
        self.owner = owner
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        })

    def get_repo(self, repo: str) -> dict[str, Any] | None:
        resp = self.session.get(f"{self.BASE}/repos/{self.owner}/{repo}")
        if resp.status_code == 404:
            return None
        self._raise_for_status(resp, f"get repo: {repo}")
        return resp.json()

    def get_issues_by_label(self, repo: str, label: str, state: str = "open") -> list[ValidationIssue]:
        results: list[ValidationIssue] = []
        page = 1
        while True:
            resp = self.session.get(
                f"{self.BASE}/repos/{self.owner}/{repo}/issues",
                params={"state": state, "labels": label, "per_page": 100, "page": page},
            )
            if resp.status_code == 404:
                return results
            self._raise_for_status(resp, f"get issues: {repo}")
            page_issues = resp.json()
            for item in page_issues:
                if "pull_request" in item:
                    continue
                labels = tuple(lb["name"] for lb in item.get("labels", []))
                results.append(ValidationIssue(
                    number=item["number"],
                    title=item.get("title", ""),
                    body=item.get("body", ""),
                    labels=labels,
                    state=item.get("state", "open"),
                    html_url=item.get("html_url", ""),
                    repo=repo,
                ))
            if len(page_issues) < 100:
                break
            page += 1
        return results

    def get_issue(self, repo: str, number: int) -> ValidationIssue | None:
        resp = self.session.get(f"{self.BASE}/repos/{self.owner}/{repo}/issues/{number}")
        if resp.status_code == 404:
            return None
        self._raise_for_status(resp, f"get issue: {repo}#{number}")
        item = resp.json()
        if "pull_request" in item:
            return None
        labels = tuple(lb["name"] for lb in item.get("labels", []))
        return ValidationIssue(
            number=item["number"],
            title=item.get("title", ""),
            body=item.get("body", ""),
            labels=labels,
            state=item.get("state", "open"),
            html_url=item.get("html_url", ""),
            repo=repo,
        )

    def get_pull_requests(self, repo: str, state: str = "all", head: str | None = None) -> list[PullRequestInfo]:
        params: dict[str, Any] = {"state": state, "per_page": 100}
        if head:
            params["head"] = head
        resp = self.session.get(
            f"{self.BASE}/repos/{self.owner}/{repo}/pulls",
            params=params,
        )
        if resp.status_code == 404:
            return []
        self._raise_for_status(resp, f"get PRs: {repo}")
        prs = []
        for pr in resp.json():
            prs.append(PullRequestInfo(
                number=pr["number"],
                title=pr.get("title", ""),
                state=pr.get("state", ""),
                merged=bool(pr.get("merged_at")),
                merged_at=pr.get("merged_at"),
                html_url=pr.get("html_url", ""),
                head_ref=(pr.get("head") or {}).get("ref", ""),
                head_sha=(pr.get("head") or {}).get("sha", ""),
                base_ref=(pr.get("base") or {}).get("ref", ""),
                merge_commit_sha=(pr.get("merge_commit_sha") or None),
            ))
        return prs

    def get_pull_request(self, repo: str, number: int) -> PullRequestInfo | None:
        resp = self.session.get(f"{self.BASE}/repos/{self.owner}/{repo}/pulls/{number}")
        if resp.status_code == 404:
            return None
        self._raise_for_status(resp, f"get PR: {repo}#{number}")
        pr = resp.json()
        return PullRequestInfo(
            number=pr["number"],
            title=pr.get("title", ""),
            state=pr.get("state", ""),
            merged=bool(pr.get("merged_at")),
            merged_at=pr.get("merged_at"),
            html_url=pr.get("html_url", ""),
            head_ref=(pr.get("head") or {}).get("ref", ""),
            head_sha=(pr.get("head") or {}).get("sha", ""),
            base_ref=(pr.get("base") or {}).get("ref", ""),
            merge_commit_sha=(pr.get("merge_commit_sha") or None),
        )

    def get_ci_status(self, repo: str, ref: str) -> CiStatus:
        resp = self.session.get(
            f"{self.BASE}/repos/{self.owner}/{repo}/commits/{ref}/status",
        )
        if resp.status_code == 404:
            return CiStatus(state="missing")
        self._raise_for_status(resp, f"get CI status: {repo}@{ref}")
        data = resp.json()
        total = data.get("total_count", 0)
        statuses = data.get("statuses", [])
        successful = sum(1 for s in statuses if s.get("state") == "success")
        # GitHub returns state="pending" for commits with zero legacy
        # commit statuses (e.g. PRs that only use the Check Runs API).
        # Normalize: if no statuses exist, treat as "missing" so the
        # combined check correctly attributes the result to Check Runs.
        if not statuses:
            state = "missing"
        else:
            state = data.get("state", "unknown")
        return CiStatus(
            state=state,
            conclusion=None,
            total_count=total,
            successful_count=successful,
        )

    def get_check_runs(self, repo: str, ref: str) -> CiStatus:
        resp = self.session.get(
            f"{self.BASE}/repos/{self.owner}/{repo}/commits/{ref}/check-runs",
        )
        if resp.status_code == 404:
            return CiStatus(state="missing")
        self._raise_for_status(resp, f"get check runs: {repo}@{ref}")
        data = resp.json()
        check_runs = data.get("check_runs", [])
        total = len(check_runs)
        successful = sum(1 for r in check_runs if r.get("conclusion") == "success")
        return CiStatus(
            state="completed" if all(r.get("status") == "completed" for r in check_runs) else "pending",
            total_count=total,
            successful_count=successful,
        )

    def get_combined_ci_status(self, repo: str, ref: str) -> CiStatus:
        status = self.get_ci_status(repo, ref)
        checks = self.get_check_runs(repo, ref)
        total = status.total_count + checks.total_count
        successful = status.successful_count + checks.successful_count
        all_success = (
            status.state in ("success", "missing")
            and checks.state in ("completed", "missing")
            and total == successful
        )
        return CiStatus(
            state="success" if all_success else "failure",
            total_count=total,
            successful_count=successful,
        )

    def get_repo_issues(self, repo: str, state: str = "open") -> list[ValidationIssue]:
        results: list[ValidationIssue] = []
        page = 1
        while True:
            resp = self.session.get(
                f"{self.BASE}/repos/{self.owner}/{repo}/issues",
                params={"state": state, "per_page": 100, "page": page},
            )
            if resp.status_code == 404:
                return results
            self._raise_for_status(resp, f"get repo issues: {repo}")
            page_issues = resp.json()
            for item in page_issues:
                if "pull_request" in item:
                    continue
                labels = tuple(lb["name"] for lb in item.get("labels", []))
                results.append(ValidationIssue(
                    number=item["number"],
                    title=item.get("title", ""),
                    body=item.get("body", ""),
                    labels=labels,
                    state=item.get("state", "open"),
                    html_url=item.get("html_url", ""),
                    repo=repo,
                ))
            if len(page_issues) < 100:
                break
            page += 1
        return results

    def get_pr_review_threads(
        self,
        repo: str,
        pr_number: int,
    ) -> list[ReviewThread]:
        """Fetch all review comments on a PR (inline diff comments).

        Returns list of ReviewThread objects. Raises RuntimeError on API error.
        """
        results: list[ReviewThread] = []
        page = 1
        while True:
            resp = self.session.get(
                f"{self.BASE}/repos/{self.owner}/{repo}/pulls/{pr_number}/comments",
                params={"per_page": 100, "page": page},
            )
            if resp.status_code == 404:
                return results
            self._raise_for_status(resp, f"get PR review threads: {repo}#{pr_number}")
            page_threads = resp.json()
            for item in page_threads:
                results.append(ReviewThread(
                    id=item.get("id", 0),
                    body=item.get("body", ""),
                    user=item.get("user", {}).get("login", "unknown"),
                    path=item.get("path"),
                    position=item.get("position"),
                    commit_id=item.get("commit_id"),
                    state=item.get("state", "pending"),
                ))
            if len(page_threads) < 100:
                break
            page += 1
        return results

    def get_pr_diff(
        self,
        repo: str,
        pr_number: int,
        *,
        max_chars: int = 200_000,
    ) -> str:
        """Fetch the unified diff of a pull request via the GitHub API.

        Uses the ``application/vnd.github.v3.diff`` media type. Returns the
        diff text, truncated to ``max_chars`` with a clear marker if larger.

        Raises RuntimeError on non-2xx responses.
        """
        url = f"{self.BASE}/repos/{self.owner}/{repo}/pulls/{pr_number}"
        resp = self.session.get(
            url,
            headers={"Accept": "application/vnd.github.v3.diff"},
        )
        if resp.status_code == 404:
            raise RuntimeError(f"PR #{pr_number} not found in {self.owner}/{repo}")
        self._raise_for_status(resp, f"get PR diff: {repo}#{pr_number}")
        diff = resp.text
        if len(diff) > max_chars:
            diff = (
                diff[:max_chars]
                + f"\n\n... [truncated, original diff was {len(resp.text)} chars] ...\n"
            )
        return diff

    @staticmethod
    def _raise_for_status(resp: requests.Response, context: str) -> None:
        try:
            resp.raise_for_status()
        except requests.HTTPError as exc:
            raise RuntimeError(f"GitHub API error ({context}): {exc}") from exc
