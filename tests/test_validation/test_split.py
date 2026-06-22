from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.validation.github_client import (  # noqa: E402
    PrFileInfo,
    PullRequestInfo,
    ValidationGitHubClient,
)
from scripts.validation.split import (  # noqa: E402
    SUB_ISSUE_LABELS,
    _changes_for_file,
    build_sub_issue_body,
    close_parent_with_cross_ref,
    decompose_pr_to_sub_issues,
    group_files_by_module,
)


def _mock_pr():
    return PullRequestInfo(
        number=42, title="test", state="open", merged=False,
        head_ref="ai/fix-test", base_ref="develop",
    )


def _mock_files():
    return [
        PrFileInfo(filename="scripts/validation/metrics.py", status="modified", additions=200, deletions=50, changes=250),
        PrFileInfo(filename="scripts/validation/cli.py", status="modified", additions=150, deletions=30, changes=180),
        PrFileInfo(filename="tests/test_validation/test_metrics.py", status="modified", additions=50, deletions=10, changes=60),
    ]


class GroupFilesByModuleTests(unittest.TestCase):
    def test_groups_by_top_level_directory(self):
        files = [
            {"filename": "scripts/validation/metrics.py", "changes": 250},
            {"filename": "scripts/utils.py", "changes": 50},
            {"filename": "tests/test_validation/test_metrics.py", "changes": 60},
            {"filename": "README.md", "changes": 10},
        ]
        groups = group_files_by_module(files)
        self.assertIn("scripts/validation", groups)
        self.assertIn("scripts", groups)
        self.assertEqual(groups["scripts"], ["scripts/utils.py"])
        self.assertIn("tests/test_validation", groups)
        self.assertIn("README.md", groups)

    def test_empty_files(self):
        groups = group_files_by_module([])
        self.assertEqual(groups, {})

    def test_single_file_no_directory(self):
        files = [{"filename": "README.md", "changes": 5}]
        groups = group_files_by_module(files)
        self.assertEqual(len(groups), 1)
        self.assertIn("README.md", groups)


class BuildSubIssueBodyTests(unittest.TestCase):
    def test_builds_body(self):
        body = build_sub_issue_body(42, "scripts/validation", ["a.py", "b.py"])
        self.assertIn("#42", body)
        self.assertIn("scripts/validation", body)
        self.assertIn("a.py", body)
        self.assertIn("b.py", body)
        self.assertIn(">500 LOC", body)

    def test_includes_report_path(self):
        body = build_sub_issue_body(1, "tests", ["t.py"], report_path="reports/r.md")
        self.assertIn("r.md", body)

    def test_empty_file_list(self):
        body = build_sub_issue_body(1, "empty", [])
        self.assertIn("empty", body)


class ChangesForFileTests(unittest.TestCase):
    def test_finds_changes(self):
        files = [{"filename": "a.py", "changes": 10}]
        self.assertEqual(_changes_for_file(files, "a.py"), 10)

    def test_returns_zero_for_unknown_file(self):
        files = [{"filename": "a.py", "changes": 10}]
        self.assertEqual(_changes_for_file(files, "b.py"), 0)


class DecomposePrToSubIssuesTests(unittest.TestCase):
    def test_happy_path_decomposes(self):
        client = MagicMock(spec=ValidationGitHubClient)
        client.get_pull_request.return_value = _mock_pr()
        client.get_pr_files.return_value = _mock_files()
        client.create_issue.side_effect = [
            {"number": 100, "html_url": "http://example.com/100"},
            {"number": 101, "html_url": "http://example.com/101"},
        ]

        with patch("scripts.validation.split.add_sub_issues_to_note") as mock_note:
            result = decompose_pr_to_sub_issues(
                client, "test-repo", 42,
                thresholds={"max_loc": 100, "max_files": 100, "test_ratio": 0.0},
            )

        self.assertTrue(result["is_oversized"])
        self.assertEqual(result["total_loc"], 490)
        self.assertEqual(len(result["sub_issues"]), 2)
        self.assertEqual(client.create_issue.call_count, 2)
        mock_note.assert_called_once()

    def test_not_oversized_returns_early(self):
        client = MagicMock(spec=ValidationGitHubClient)
        client.get_pull_request.return_value = _mock_pr()
        client.get_pr_files.return_value = [
            PrFileInfo(filename="README.md", status="modified", additions=1, deletions=0, changes=1),
        ]

        result = decompose_pr_to_sub_issues(
            client, "test-repo", 42,
            thresholds={"max_loc": 9999, "max_files": 9999, "test_ratio": 0.0},
        )

        self.assertFalse(result["is_oversized"])
        self.assertEqual(len(result["sub_issues"]), 0)
        client.create_issue.assert_not_called()

    def test_pr_not_found_raises(self):
        client = MagicMock(spec=ValidationGitHubClient)
        client.get_pull_request.return_value = None

        with self.assertRaises(ValueError):
            decompose_pr_to_sub_issues(client, "test-repo", 999)

    def test_api_error_raises(self):
        client = MagicMock(spec=ValidationGitHubClient)
        client.get_pull_request.side_effect = RuntimeError("API error")

        with self.assertRaises(RuntimeError):
            decompose_pr_to_sub_issues(client, "test-repo", 42)


class CloseParentWithCrossRefTests(unittest.TestCase):
    def test_closes_with_default_comment(self):
        client = MagicMock(spec=ValidationGitHubClient)
        client.get_pull_request.return_value = _mock_pr()
        client.create_comment.return_value = {}
        client.close_issue.return_value = {}

        result = close_parent_with_cross_ref(client, "test-repo", 42, [100, 101])

        client.create_comment.assert_called_once()
        client.close_issue.assert_called_once_with("test-repo", 42)
        self.assertEqual(result["pr_number"], 42)
        self.assertIn("#100", result["comment"])
        self.assertIn("#101", result["comment"])

    def test_closes_with_custom_comment(self):
        client = MagicMock(spec=ValidationGitHubClient)
        client.get_pull_request.return_value = _mock_pr()

        close_parent_with_cross_ref(
            client, "test-repo", 42, [100], comment="custom close"
        )
        client.create_comment.assert_called_once()
        call_body = client.create_comment.call_args[0][2]
        self.assertEqual(call_body, "custom close")

    def test_pr_not_found_raises(self):
        client = MagicMock(spec=ValidationGitHubClient)
        client.get_pull_request.return_value = None

        with self.assertRaises(ValueError):
            close_parent_with_cross_ref(client, "test-repo", 999, [100])


if __name__ == "__main__":
    unittest.main()
