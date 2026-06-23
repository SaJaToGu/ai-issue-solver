from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.validation.github_client import (  # noqa: E402
    CiStatus,
    PullRequestInfo,
    ValidationGitHubClient,
)


class ValidationGitHubClientTests(unittest.TestCase):
    def setUp(self):
        self.client = ValidationGitHubClient(token="test-token", owner="test-owner")
        self.session = MagicMock()
        self.client.session = self.session

    def _mock_response(self, status_code: int, json_data: object = None):
        resp = MagicMock()
        resp.status_code = status_code
        resp.json.return_value = json_data or {}
        if status_code >= 400:
            resp.raise_for_status.side_effect = RuntimeError(f"HTTP {status_code}")
        return resp

    def test_get_repo_returns_data_on_200(self):
        self.session.get.return_value = self._mock_response(200, {"id": 1, "name": "repo"})
        result = self.client.get_repo("test-repo")
        self.assertEqual(result["name"], "repo")

    def test_get_repo_returns_none_on_404(self):
        self.session.get.return_value = self._mock_response(404)
        result = self.client.get_repo("test-repo")
        self.assertIsNone(result)

    def test_get_repo_raises_on_500(self):
        self.session.get.return_value = self._mock_response(500)
        with self.assertRaises(RuntimeError):
            self.client.get_repo("test-repo")

    def test_get_issues_by_label_returns_list(self):
        self.session.get.return_value = self._mock_response(200, [
            {"number": 1, "title": "Issue 1", "body": "body", "state": "open", "html_url": "url1", "labels": [{"name": "ai-generated"}]},
        ])
        issues = self.client.get_issues_by_label("repo", "ai-generated")
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0].number, 1)

    def test_get_issues_by_label_skips_pull_requests(self):
        self.session.get.return_value = self._mock_response(200, [
            {"number": 2, "title": "PR", "body": "", "pull_request": {}, "labels": []},
        ])
        issues = self.client.get_issues_by_label("repo", "ai-generated")
        self.assertEqual(len(issues), 0)

    def test_get_issues_by_label_returns_empty_on_404(self):
        self.session.get.return_value = self._mock_response(404)
        issues = self.client.get_issues_by_label("repo", "ai-generated")
        self.assertEqual(issues, [])

    def test_get_issue_returns_issue(self):
        self.session.get.return_value = self._mock_response(200, {
            "number": 5, "title": "Bug", "body": "desc", "state": "open", "html_url": "url", "labels": [],
        })
        issue = self.client.get_issue("repo", 5)
        self.assertIsNotNone(issue)
        self.assertEqual(issue.number, 5)

    def test_get_issue_returns_none_on_404(self):
        self.session.get.return_value = self._mock_response(404)
        issue = self.client.get_issue("repo", 999)
        self.assertIsNone(issue)

    def test_get_issue_returns_none_for_pull_request(self):
        self.session.get.return_value = self._mock_response(200, {
            "number": 5, "pull_request": {}, "labels": [],
        })
        issue = self.client.get_issue("repo", 5)
        self.assertIsNone(issue)

    def test_get_pull_requests_returns_list(self):
        self.session.get.return_value = self._mock_response(200, [
            {"number": 10, "title": "PR 1", "state": "open", "merged_at": None, "html_url": "url", "head": {"ref": "br"}, "base": {"ref": "main"}, "merge_commit_sha": None},
        ])
        prs = self.client.get_pull_requests("repo")
        self.assertEqual(len(prs), 1)
        self.assertEqual(prs[0].number, 10)

    def test_get_pull_requests_returns_empty_on_404(self):
        self.session.get.return_value = self._mock_response(404)
        prs = self.client.get_pull_requests("repo")
        self.assertEqual(prs, [])

    def test_get_pull_request_returns_pr(self):
        self.session.get.return_value = self._mock_response(200, {
            "number": 10, "title": "PR", "state": "merged", "merged_at": "2024-01-01T00:00:00Z",
            "html_url": "url", "head": {"ref": "b"}, "base": {"ref": "m"}, "merge_commit_sha": "abc123",
        })
        pr = self.client.get_pull_request("repo", 10)
        self.assertIsNotNone(pr)
        self.assertTrue(pr.merged)

    def test_get_pull_request_returns_none_on_404(self):
        self.session.get.return_value = self._mock_response(404)
        pr = self.client.get_pull_request("repo", 999)
        self.assertIsNone(pr)

    def test_get_ci_status_returns_status(self):
        self.session.get.return_value = self._mock_response(200, {
            "state": "success", "total_count": 3, "statuses": [
                {"state": "success"}, {"state": "success"}, {"state": "success"},
            ],
        })
        status = self.client.get_ci_status("repo", "abc123")
        self.assertEqual(status.state, "success")
        self.assertEqual(status.total_count, 3)

    def test_get_ci_status_returns_missing_on_404(self):
        self.session.get.return_value = self._mock_response(404)
        status = self.client.get_ci_status("repo", "abc123")
        self.assertEqual(status.state, "missing")

    def test_get_ci_status_normalizes_empty_statuses_to_missing(self):
        """GitHub returns state='pending' for commits with zero legacy
        commit statuses (PRs that only use the Check Runs API). The
        client must normalize that to 'missing' so the combined
        check correctly attributes CI to Check Runs only."""
        self.session.get.return_value = self._mock_response(200, {
            "state": "pending", "total_count": 0, "statuses": [],
        })
        status = self.client.get_ci_status("repo", "abc123")
        self.assertEqual(status.state, "missing")
        self.assertEqual(status.total_count, 0)
        self.assertEqual(status.successful_count, 0)

    def test_get_check_runs_returns_status(self):
        self.session.get.return_value = self._mock_response(200, {
            "check_runs": [
                {"status": "completed", "conclusion": "success"},
                {"status": "completed", "conclusion": "success"},
            ],
        })
        status = self.client.get_check_runs("repo", "abc123")
        self.assertEqual(status.state, "completed")
        self.assertEqual(status.total_count, 2)

    def test_get_check_runs_returns_missing_on_404(self):
        self.session.get.return_value = self._mock_response(404)
        status = self.client.get_check_runs("repo", "abc123")
        self.assertEqual(status.state, "missing")

    def test_get_combined_ci_status_success(self):
        def mock_get(url, **kw):
            if "status" in url:
                return self._mock_response(200, {"state": "success", "total_count": 1, "statuses": [{"state": "success"}]})
            return self._mock_response(200, {"check_runs": [{"status": "completed", "conclusion": "success"}]})

        self.session.get.side_effect = mock_get
        status = self.client.get_combined_ci_status("repo", "abc")
        self.assertEqual(status.state, "success")

    def test_get_combined_ci_status_failure(self):
        def mock_get(url, **kw):
            if "status" in url:
                return self._mock_response(200, {"state": "pending", "total_count": 1, "statuses": [{"state": "pending"}]})
            return self._mock_response(200, {"check_runs": []})

        self.session.get.side_effect = mock_get
        status = self.client.get_combined_ci_status("repo", "abc")
        self.assertEqual(status.state, "failure")


class PullRequestInfoTests(unittest.TestCase):
    def test_constructs_with_all_fields(self):
        pr = PullRequestInfo(
            number=1, title="PR", state="merged", merged=True,
            html_url="url", head_ref="br", base_ref="main",
        )
        self.assertEqual(pr.number, 1)
        self.assertTrue(pr.merged)


class CiStatusTests(unittest.TestCase):
    def test_default_values(self):
        status = CiStatus(state="success")
        self.assertEqual(status.state, "success")
        self.assertIsNone(status.conclusion)
        self.assertEqual(status.total_count, 0)


if __name__ == "__main__":
    unittest.main()
