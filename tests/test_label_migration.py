#!/usr/bin/env python3
"""
Unit tests for label_migration.py
"""

import unittest
from scripts.label_migration import migrate_issue_labels, LABEL_MAPPING, UNLABELED_ISSUE_MAPPING


class TestLabelMigration(unittest.TestCase):
    """Test cases for label migration functionality."""

    def test_migrate_existing_labels(self):
        """Test migration of existing labels using LABEL_MAPPING."""
        issue = {
            "number": 123,
            "labels": [{"name": "github"}, {"name": "quality"}],
        }
        new_labels = migrate_issue_labels(issue, LABEL_MAPPING, UNLABELED_ISSUE_MAPPING)
        expected = [
            "theme/github",
            "area/prs",
            "area/issues",
            "theme/quality",
            "kind/test",
        ]
        self.assertEqual(set(new_labels), set(expected))

    def test_migrate_unlabeled_issue_213(self):
        """Test migration of unlabeled issue #213 using UNLABELED_ISSUE_MAPPING."""
        issue = {
            "number": 213,
            "labels": [],
        }
        new_labels = migrate_issue_labels(issue, LABEL_MAPPING, UNLABELED_ISSUE_MAPPING)
        expected = [
            "theme/github",
            "theme/workflow",
            "area/issues",
            "kind/feature",
            "agent/triage",
        ]
        self.assertEqual(set(new_labels), set(expected))

    def test_migrate_unlabeled_issue_unknown(self):
        """Test that unlabeled issues without explicit mapping remain unchanged."""
        issue = {
            "number": 9999,
            "labels": [],
        }
        new_labels = migrate_issue_labels(issue, LABEL_MAPPING, UNLABELED_ISSUE_MAPPING)
        self.assertEqual(new_labels, [])

    def test_migrate_unmapped_labels(self):
        """Test that unmapped labels are preserved."""
        issue = {
            "number": 456,
            "labels": [{"name": "unknown-label"}],
        }
        new_labels = migrate_issue_labels(issue, LABEL_MAPPING, UNLABELED_ISSUE_MAPPING)
        self.assertEqual(new_labels, ["unknown-label"])

    def test_migrate_mixed_labels(self):
        """Test migration of a mix of mapped and unmapped labels."""
        issue = {
            "number": 789,
            "labels": [{"name": "github"}, {"name": "unknown-label"}],
        }
        new_labels = migrate_issue_labels(issue, LABEL_MAPPING, UNLABELED_ISSUE_MAPPING)
        expected = [
            "theme/github",
            "area/prs",
            "area/issues",
            "unknown-label",
        ]
        self.assertEqual(set(new_labels), set(expected))

    def test_deduplication(self):
        """Test that duplicate labels are removed while preserving order."""
        issue = {
            "number": 101,
            "labels": [{"name": "github"}, {"name": "github"}],
        }
        new_labels = migrate_issue_labels(issue, LABEL_MAPPING, UNLABELED_ISSUE_MAPPING)
        expected = [
            "theme/github",
            "area/prs",
            "area/issues",
        ]
        self.assertEqual(new_labels, expected)

    def test_new_legacy_mappings(self):
        """Test migration of new legacy labels from PR #233."""
        test_cases = [
            ("dashboard", ["theme/dashboard"]),
            ("provider", ["theme/provider"]),
            ("research", ["theme/research"]),
            ("opencode", ["area/opencode"]),
            ("sandbox", ["theme/codex"]),
        ]
        
        for old_label, expected in test_cases:
            issue = {
                "number": 1,
                "labels": [{"name": old_label}],
            }
            new_labels = migrate_issue_labels(issue, LABEL_MAPPING, UNLABELED_ISSUE_MAPPING)
            self.assertEqual(set(new_labels), set(expected))


if __name__ == "__main__":
    unittest.main()