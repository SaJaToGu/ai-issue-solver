#!/usr/bin/env python3
"""
Tests for cleanup_backlog.py functionality.

Verifies that completed backlog entries are detected and removed correctly.
"""

import unittest
from pathlib import Path
from tempfile import NamedTemporaryFile
from unittest.mock import patch

from scripts.cleanup_backlog import (
    parse_backlog,
    find_completed_issues,
    remove_sections_from_backlog,
)


class TestCleanupBacklog(unittest.TestCase):
    """Test cases for backlog cleanup functionality."""

    def setUp(self):
        """Set up test backlog content."""
        self.backlog_content = """
# Next Backlog

## 1. Test Issue 1

Labels: `automation`, `quality`

Priority: `high`

Test description for issue 1.

## 2. Test Issue 2

Labels: `documentation`

Priority: `medium`

Test description for issue 2.
"""
        self.temp_file = NamedTemporaryFile(mode="w+", delete=False, suffix=".md")
        self.temp_file.write(self.backlog_content)
        self.temp_file.close()

    def tearDown(self):
        """Clean up temporary file."""
        Path(self.temp_file.name).unlink()

    def test_parse_backlog(self):
        """Test parsing of backlog file."""
        issues = parse_backlog(Path(self.temp_file.name))
        self.assertEqual(len(issues), 2)
        self.assertEqual(issues[0]["title"], "Test Issue 1")
        self.assertEqual(issues[1]["title"], "Test Issue 2")

    def test_find_completed_issues(self):
        """Test detection of completed issues."""
        issues = parse_backlog(Path(self.temp_file.name))
        github_issues = {
            "Test Issue 1": {"title": "Test Issue 1", "state": "closed", "number": 1, "html_url": "https://github.com/test/repo/issues/1"},
            "Test Issue 2": {"title": "Test Issue 2", "state": "open", "number": 2, "html_url": "https://github.com/test/repo/issues/2"},
        }
        completed = find_completed_issues(issues, github_issues)
        self.assertEqual(len(completed), 1)
        self.assertEqual(completed[0]["title"], "Test Issue 1")

    def test_remove_sections_from_backlog(self):
        """Test removal of completed sections from backlog."""
        issues = parse_backlog(Path(self.temp_file.name))
        completed = [
            {
                "title": "Test Issue 1",
                "raw_section": issues[0]["raw_section"],
            }
        ]
        new_content, removed_count = remove_sections_from_backlog(
            Path(self.temp_file.name), completed
        )
        self.assertEqual(removed_count, 1)
        self.assertNotIn("Test Issue 1", new_content)
        self.assertIn("Test Issue 2", new_content)


if __name__ == "__main__":
    unittest.main()