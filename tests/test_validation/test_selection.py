from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.validation.github_client import ValidationGitHubClient  # noqa: E402
from scripts.validation.models import ValidationIssue  # noqa: E402
from scripts.validation.selection import (  # noqa: E402
    select_issues_by_criteria,
    select_issues_by_label,
)


class SelectIssuesByLabelTests(unittest.TestCase):
    def setUp(self):
        self.client = MagicMock(spec=ValidationGitHubClient)

    def test_returns_filtered_issues(self):
        self.client.get_issues_by_label.return_value = [
            ValidationIssue(number=1, title="A", body="", labels=("ai-generated",)),
            ValidationIssue(number=2, title="B", body="", labels=("ai-generated", "bug")),
        ]
        issues = select_issues_by_label(self.client, "repo", label="ai-generated", max_issues=5)
        self.assertEqual(len(issues), 2)

    def test_respects_max_issues(self):
        self.client.get_issues_by_label.return_value = [
            ValidationIssue(number=i, title=str(i), body="") for i in range(1, 11)
        ]
        issues = select_issues_by_label(self.client, "repo", label="ai-generated", max_issues=3)
        self.assertEqual(len(issues), 3)

    def test_excludes_issues_with_exclude_labels(self):
        issues = [
            ValidationIssue(number=1, title="A", body="", labels=("ai-generated",)),
            ValidationIssue(number=2, title="B", body="", labels=("ai-generated", "wontfix")),
        ]
        self.client.get_issues_by_label.return_value = issues
        result = select_issues_by_label(self.client, "repo", label="ai-generated", exclude_labels=("wontfix",))
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].number, 1)

    def test_returns_empty_list_when_no_issues(self):
        self.client.get_issues_by_label.return_value = []
        issues = select_issues_by_label(self.client, "repo", label="ai-generated")
        self.assertEqual(issues, [])


class SelectIssuesByCriteriaTests(unittest.TestCase):
    def setUp(self):
        self.issues = [
            ValidationIssue(number=1, title="A", body="", labels=("bug",)),
            ValidationIssue(number=2, title="B", body="", labels=("feature",)),
            ValidationIssue(number=3, title="C", body="", labels=("bug", "ai-generated")),
            ValidationIssue(number=4, title="D", body="", labels=("ai-generated",)),
        ]

    def test_returns_all_without_filters(self):
        result = select_issues_by_criteria(self.issues, max_issues=10)
        self.assertEqual(len(result), 4)

    def test_filters_by_min_number(self):
        result = select_issues_by_criteria(self.issues, min_number=3, max_issues=10)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0].number, 3)

    def test_filters_by_max_number(self):
        result = select_issues_by_criteria(self.issues, max_number=2, max_issues=10)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0].number, 1)

    def test_excludes_labels(self):
        result = select_issues_by_criteria(self.issues, exclude_labels=("bug",), max_issues=10)
        self.assertEqual(len(result), 2)
        for issue in result:
            self.assertNotIn("bug", issue.labels)

    def test_respects_max_issues(self):
        result = select_issues_by_criteria(self.issues, max_issues=2)
        self.assertEqual(len(result), 2)

    def test_returns_empty_with_no_matches(self):
        result = select_issues_by_criteria(self.issues, min_number=100, max_issues=10)
        self.assertEqual(result, [])

    def test_returns_empty_from_empty_input(self):
        result = select_issues_by_criteria([], max_issues=10)
        self.assertEqual(result, [])


if __name__ == "__main__":
    unittest.main()
