#!/usr/bin/env python3
"""
Unit tests for label_migration.py
"""

import unittest
from scripts.label_migration import migrate_issue_labels, LABEL_MAPPING, UNLABELED_ISSUE_MAPPING


class TestLabelMigration(unittest.TestCase):
    """Test cases for label migration functionality."""

    def test_legacy_label_mapping(self):
        """Test that legacy labels are correctly mapped to new taxonomy."""
        test_issue = {
            "number": 123,
            "labels": [{"name": "dashboard"}, {"name": "provider"}]
        }
        result = migrate_issue_labels(test_issue, LABEL_MAPPING, {})
        self.assertIn("theme/dashboard", result)
        self.assertIn("theme/provider", result)

    def test_unlabeled_issue_213(self):
        """Test that issue #213 gets correct labels when unlabeled."""
        test_issue = {
            "number": 213,
            "labels": []
        }
        result = migrate_issue_labels(test_issue, LABEL_MAPPING, UNLABELED_ISSUE_MAPPING)
        expected_labels = UNLABELED_ISSUE_MAPPING[213]
        for label in expected_labels:
            self.assertIn(label, result)

    def test_unlabeled_issue_unknown(self):
        """Test that unknown unlabeled issues remain unchanged."""
        test_issue = {
            "number": 9999,
            "labels": []
        }
        result = migrate_issue_labels(test_issue, LABEL_MAPPING, UNLABELED_ISSUE_MAPPING)
        self.assertEqual(result, [])

    def test_mixed_labels(self):
        """Test that existing labels are preserved and new labels are added."""
        test_issue = {
            "number": 213,
            "labels": [{"name": "github"}]
        }
        result = migrate_issue_labels(test_issue, LABEL_MAPPING, UNLABELED_ISSUE_MAPPING)
        # Should have both mapped github labels and unlabeled issue labels
        self.assertIn("theme/github", result)
        self.assertIn("area/prs", result)
        self.assertIn("area/issues", result)
        self.assertIn("kind/feature", result)
        self.assertIn("agent/triage", result)

    def test_label_deduplication(self):
        """Test that duplicate labels are removed while preserving order."""
        test_issue = {
            "number": 123,
            "labels": [{"name": "github"}, {"name": "github"}]
        }
        result = migrate_issue_labels(test_issue, LABEL_MAPPING, {})
        # Should only appear once
        self.assertEqual(result.count("theme/github"), 1)
        self.assertEqual(result.count("area/prs"), 1)
        self.assertEqual(result.count("area/issues"), 1)


if __name__ == "__main__":
    unittest.main()