from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from validation.github_client import (  # noqa: E402
    CiStatus,
    PullRequestInfo,
    ValidationGitHubClient,
)
from validation.models import RunReportData  # noqa: E402
from validation.pr_checks import (  # noqa: E402
    check_pr_statuses,
    is_pr_merged_and_green,
)


class CheckPrStatusesTests(unittest.TestCase):
    def setUp(self):
        self.client = MagicMock(spec=ValidationGitHubClient)

    def test_returns_report_with_pr_merged_false_when_no_pr_number(self):
        report = RunReportData(issue_number=1, issue_title="Test", status="success", pr_number=None)
        result = check_pr_statuses(self.client, "repo", report)
        self.assertFalse(result.pr_merged)

    def test_enriches_with_pr_merged_true_and_ci_green(self):
        self.client.get_pull_request.return_value = PullRequestInfo(
            number=10, title="PR", state="merged", merged=True,
            merge_commit_sha="abc123", html_url="url", head_ref="br", base_ref="main",
        )
        self.client.get_combined_ci_status.return_value = CiStatus(state="success", total_count=2, successful_count=2)
        report = RunReportData(issue_number=1, issue_title="Test", status="pr_created", pr_number=10, pr_url="url")
        result = check_pr_statuses(self.client, "repo", report)
        self.assertTrue(result.pr_merged)
        self.assertTrue(result.ci_green)

    def test_ci_green_false_when_ci_fails(self):
        self.client.get_pull_request.return_value = PullRequestInfo(
            number=10, title="PR", state="merged", merged=True,
            merge_commit_sha="abc123", html_url="url", head_ref="br", base_ref="main",
        )
        self.client.get_combined_ci_status.return_value = CiStatus(state="failure", total_count=1, successful_count=0)
        report = RunReportData(issue_number=1, issue_title="Test", status="pr_created", pr_number=10)
        result = check_pr_statuses(self.client, "repo", report)
        self.assertTrue(result.pr_merged)
        self.assertFalse(result.ci_green)

    def test_ci_green_none_when_no_merge_commit_sha(self):
        self.client.get_pull_request.return_value = PullRequestInfo(
            number=10, title="PR", state="merged", merged=True,
            merge_commit_sha=None, html_url="url", head_ref="br", base_ref="main",
        )
        report = RunReportData(issue_number=1, issue_title="Test", status="pr_created", pr_number=10)
        result = check_pr_statuses(self.client, "repo", report)
        self.assertTrue(result.pr_merged)
        self.assertIsNone(result.ci_green)

    def test_pull_request_not_found_returns_original_report(self):
        self.client.get_pull_request.return_value = None
        report = RunReportData(issue_number=1, issue_title="Test", status="pr_created", pr_number=999)
        result = check_pr_statuses(self.client, "repo", report)
        self.assertEqual(result.pr_number, 999)
        self.assertIsNone(result.pr_merged)


class IsPrMergedAndGreenTests(unittest.TestCase):
    def setUp(self):
        self.client = MagicMock(spec=ValidationGitHubClient)

    def test_returns_true_when_merged_and_ci_green(self):
        self.client.get_pull_request.return_value = PullRequestInfo(
            number=1, title="PR", state="merged", merged=True,
            merge_commit_sha="abc", html_url="url", head_ref="br", base_ref="main",
        )
        self.client.get_combined_ci_status.return_value = CiStatus(state="success")
        self.assertTrue(is_pr_merged_and_green(self.client, "repo", 1))

    def test_returns_false_when_not_merged(self):
        self.client.get_pull_request.return_value = PullRequestInfo(
            number=2, title="PR", state="open", merged=False,
            html_url="url", head_ref="br", base_ref="main",
        )
        self.assertFalse(is_pr_merged_and_green(self.client, "repo", 2))

    def test_returns_false_when_pr_not_found(self):
        self.client.get_pull_request.return_value = None
        self.assertFalse(is_pr_merged_and_green(self.client, "repo", 999))

    def test_returns_false_when_ci_red(self):
        self.client.get_pull_request.return_value = PullRequestInfo(
            number=3, title="PR", state="merged", merged=True,
            merge_commit_sha="abc", html_url="url", head_ref="br", base_ref="main",
        )
        self.client.get_combined_ci_status.return_value = CiStatus(state="failure")
        self.assertFalse(is_pr_merged_and_green(self.client, "repo", 3))


if __name__ == "__main__":
    unittest.main()
