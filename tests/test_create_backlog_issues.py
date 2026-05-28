#!/usr/bin/env python3
"""
Tests for backlog issue creation and cleanup functionality.

Tests both create_backlog_issues.py and cleanup_backlog.py scripts.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

# Add scripts directory to path for imports
import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from create_backlog_issues import parse_backlog as parse_backlog_create
from cleanup_backlog import parse_backlog as parse_backlog_cleanup
from cleanup_backlog import (
    find_completed_issues,
    remove_sections_from_backlog,
)


# ── Sample backlog content for testing ──

SAMPLE_BACKLOG_CONTENT = """# Next Backlog

> **Note:** This is a test backlog.

## 1. First issue

Labels: `quality`, `workflow`

This is the first issue body.

Touches: `file1.py`, `file2.py`

## 2. Second issue

Labels: `automation`

This is the second issue body.

## 3. Third issue

Labels: `documentation`, `github`

This is the third issue body.

Checks:
- Test 1
- Test 2
"""

SAMPLE_BACKLOG_NO_LABELS = """# Next Backlog

## 1. Issue without labels

This is an issue without labels.

## 2. Another issue

This is another issue.
"""

SAMPLE_BACKLOG_EMPTY = """# Next Backlog

No issues here.
"""

SAMPLE_BACKLOG_ONLY_HEADER = """# Next Backlog
"""


class TestParseBacklogCreate(unittest.TestCase):
    """Tests for parse_backlog function in create_backlog_issues.py"""

    def setUp(self):
        """Create temporary backlog files for testing."""
        self.temp_dir = tempfile.mkdtemp()
        self.backlog_path = Path(self.temp_dir) / "backlog.md"

    def tearDown(self):
        """Clean up temporary files."""
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def write_backlog(self, content: str):
        """Write content to temp backlog file."""
        self.backlog_path.write_text(content, encoding="utf-8")

    def test_parse_sample_backlog(self):
        """Test parsing standard backlog with issues."""
        self.write_backlog(SAMPLE_BACKLOG_CONTENT)
        issues = parse_backlog_create(self.backlog_path)

        self.assertEqual(len(issues), 3)

        # Check first issue
        self.assertEqual(issues[0]["title"], "First issue")
        self.assertEqual(issues[0]["labels"], ["quality", "workflow"])
        self.assertIn("This is the first issue body.", issues[0]["body"])
        self.assertIn("Touches: `file1.py`, `file2.py`", issues[0]["body"])
        self.assertIn("Created from `", issues[0]["body"])

        # Check second issue
        self.assertEqual(issues[1]["title"], "Second issue")
        self.assertEqual(issues[1]["labels"], ["automation"])

        # Check third issue
        self.assertEqual(issues[2]["title"], "Third issue")
        self.assertEqual(issues[2]["labels"], ["documentation", "github"])

    def test_parse_backlog_no_labels(self):
        """Test parsing backlog with issues that have no labels."""
        self.write_backlog(SAMPLE_BACKLOG_NO_LABELS)
        issues = parse_backlog_create(self.backlog_path)

        self.assertEqual(len(issues), 2)
        self.assertEqual(issues[0]["title"], "Issue without labels")
        self.assertEqual(issues[0]["labels"], [])
        self.assertEqual(issues[1]["title"], "Another issue")
        self.assertEqual(issues[1]["labels"], [])

    def test_parse_empty_backlog(self):
        """Test parsing backlog with no issues."""
        self.write_backlog(SAMPLE_BACKLOG_EMPTY)
        issues = parse_backlog_create(self.backlog_path)
        self.assertEqual(len(issues), 0)

    def test_parse_only_header(self):
        """Test parsing backlog with only header."""
        self.write_backlog(SAMPLE_BACKLOG_ONLY_HEADER)
        issues = parse_backlog_create(self.backlog_path)
        self.assertEqual(len(issues), 0)

    def test_parse_nonexistent_file(self):
        """Test parsing a non-existent file raises error."""
        with self.assertRaises(FileNotFoundError):
            parse_backlog_create(Path("/nonexistent/file.md"))


class TestParseBacklogCleanup(unittest.TestCase):
    """Tests for parse_backlog function in cleanup_backlog.py"""

    def setUp(self):
        """Create temporary backlog files for testing."""
        self.temp_dir = tempfile.mkdtemp()
        self.backlog_path = Path(self.temp_dir) / "backlog.md"

    def tearDown(self):
        """Clean up temporary files."""
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def write_backlog(self, content: str):
        """Write content to temp backlog file."""
        self.backlog_path.write_text(content, encoding="utf-8")

    def test_parse_sample_backlog(self):
        """Test parsing standard backlog with issues."""
        self.write_backlog(SAMPLE_BACKLOG_CONTENT)
        issues = parse_backlog_cleanup(self.backlog_path)

        self.assertEqual(len(issues), 3)

        # Check first issue
        self.assertEqual(issues[0]["title"], "First issue")
        self.assertEqual(issues[0]["labels"], ["quality", "workflow"])
        self.assertIn("This is the first issue body.", issues[0]["body"])
        self.assertTrue(len(issues[0]["raw_section"]) > 0)

    def test_parse_backlog_preserves_raw_section(self):
        """Test that raw_section contains the original section text."""
        self.write_backlog(SAMPLE_BACKLOG_CONTENT)
        issues = parse_backlog_cleanup(self.backlog_path)

        for issue in issues:
            self.assertIn("##", issue["raw_section"])
            self.assertIn(issue["title"], issue["raw_section"])


class TestFindCompletedIssues(unittest.TestCase):
    """Tests for find_completed_issues function."""

    def test_find_completed_issues(self):
        """Test finding completed issues from GitHub issues."""
        issues = [
            {"title": "Issue 1", "labels": ["label1"], "raw_section": ""},
            {"title": "Issue 2", "labels": ["label2"], "raw_section": ""},
            {"title": "Issue 3", "labels": ["label3"], "raw_section": ""},
        ]

        github_issues = {
            "Issue 1": {"state": "closed", "number": 1, "html_url": "http://github.com/issue/1"},
            "Issue 2": {"state": "open", "number": 2, "html_url": "http://github.com/issue/2"},
            "Issue 3": {"state": "closed", "number": 3, "html_url": "http://github.com/issue/3"},
        }

        completed = find_completed_issues(issues, github_issues)

        self.assertEqual(len(completed), 2)

        titles = [c["title"] for c in completed]
        self.assertIn("Issue 1", titles)
        self.assertIn("Issue 3", titles)
        self.assertNotIn("Issue 2", titles)

        # Check that completed issues have correct data
        for c in completed:
            self.assertIn(c["title"], ["Issue 1", "Issue 3"])
            self.assertIsNotNone(c["number"])
            self.assertIsNotNone(c["html_url"])

    def test_find_completed_issues_empty(self):
        """Test finding completed issues when none are closed."""
        issues = [
            {"title": "Issue 1", "labels": ["label1"], "raw_section": ""},
        ]

        github_issues = {
            "Issue 1": {"state": "open", "number": 1, "html_url": "http://github.com/issue/1"},
        }

        completed = find_completed_issues(issues, github_issues)
        self.assertEqual(len(completed), 0)

    def test_find_completed_issues_nonexistent(self):
        """Test finding completed issues when GitHub issue doesn't exist."""
        issues = [
            {"title": "Issue 1", "labels": ["label1"], "raw_section": ""},
        ]

        github_issues = {}

        completed = find_completed_issues(issues, github_issues)
        self.assertEqual(len(completed), 0)


class TestRemoveSectionsFromBacklog(unittest.TestCase):
    """Tests for remove_sections_from_backlog function."""

    def setUp(self):
        """Create temporary backlog files for testing."""
        self.temp_dir = tempfile.mkdtemp()
        self.backlog_path = Path(self.temp_dir) / "backlog.md"

    def tearDown(self):
        """Clean up temporary files."""
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def write_backlog(self, content: str):
        """Write content to temp backlog file."""
        self.backlog_path.write_text(content, encoding="utf-8")

    def test_remove_all_sections(self):
        """Test removing all sections from backlog."""
        self.write_backlog(SAMPLE_BACKLOG_CONTENT)
        
        completed = [
            {"title": "First issue", "labels": [], "raw_section": ""},
            {"title": "Second issue", "labels": [], "raw_section": ""},
            {"title": "Third issue", "labels": [], "raw_section": ""},
        ]
        
        new_content, count = remove_sections_from_backlog(self.backlog_path, completed)
        
        self.assertEqual(count, 3)
        self.assertIn("# Next Backlog", new_content)
        self.assertNotIn("First issue", new_content)
        self.assertNotIn("Second issue", new_content)
        self.assertNotIn("Third issue", new_content)

    def test_remove_some_sections(self):
        """Test removing only some sections from backlog."""
        self.write_backlog(SAMPLE_BACKLOG_CONTENT)
        
        # Only mark second issue as completed
        completed = [
            {"title": "Second issue", "labels": [], "raw_section": ""},
        ]
        
        new_content, count = remove_sections_from_backlog(self.backlog_path, completed)
        
        self.assertEqual(count, 1)
        self.assertIn("# Next Backlog", new_content)
        self.assertIn("First issue", new_content)
        self.assertNotIn("Second issue", new_content)
        self.assertIn("Third issue", new_content)

    def test_remove_no_sections(self):
        """Test when no sections need to be removed."""
        self.write_backlog(SAMPLE_BACKLOG_CONTENT)
        
        completed = []
        
        new_content, count = remove_sections_from_backlog(self.backlog_path, completed)
        
        self.assertEqual(count, 0)
        # Content should be unchanged
        self.assertIn("First issue", new_content)
        self.assertIn("Second issue", new_content)
        self.assertIn("Third issue", new_content)

    def test_remove_preserves_header(self):
        """Test that header is preserved when removing sections."""
        content = """# Next Backlog

> **Note:** Important note here.

## 1. Issue to remove

Labels: `test`

Body here.
"""
        self.write_backlog(content)
        
        completed = [
            {"title": "Issue to remove", "labels": [], "raw_section": ""},
        ]
        
        new_content, count = remove_sections_from_backlog(self.backlog_path, completed)
        
        self.assertEqual(count, 1)
        self.assertIn("# Next Backlog", new_content)
        self.assertIn("> **Note:** Important note here.", new_content)
        self.assertNotIn("Issue to remove", new_content)


class TestBacklogIntegration(unittest.TestCase):
    """Integration tests for backlog workflow."""

    def setUp(self):
        """Create temporary backlog files for testing."""
        self.temp_dir = tempfile.mkdtemp()
        self.backlog_path = Path(self.temp_dir) / "backlog.md"

    def tearDown(self):
        """Clean up temporary files."""
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def write_backlog(self, content: str):
        """Write content to temp backlog file."""
        self.backlog_path.write_text(content, encoding="utf-8")

    def test_full_workflow(self):
        """Test full workflow: parse, identify completed, remove."""
        self.write_backlog(SAMPLE_BACKLOG_CONTENT)
        
        # Parse backlog
        issues = parse_backlog_cleanup(self.backlog_path)
        self.assertEqual(len(issues), 3)
        
        # Simulate GitHub response (2 issues closed)
        github_issues = {
            "First issue": {"state": "closed", "number": 1, "html_url": "http://github.com/issue/1"},
            "Second issue": {"state": "open", "number": 2, "html_url": "http://github.com/issue/2"},
            "Third issue": {"state": "closed", "number": 3, "html_url": "http://github.com/issue/3"},
        }
        
        # Find completed
        completed = find_completed_issues(issues, github_issues)
        self.assertEqual(len(completed), 2)
        
        # Remove completed
        new_content, count = remove_sections_from_backlog(self.backlog_path, completed)
        self.assertEqual(count, 2)
        self.assertNotIn("First issue", new_content)
        self.assertIn("Second issue", new_content)
        self.assertNotIn("Third issue", new_content)


class TestBacklogEdgeCases(unittest.TestCase):
    """Tests for edge cases in backlog handling."""

    def setUp(self):
        """Create temporary backlog files for testing."""
        self.temp_dir = tempfile.mkdtemp()
        self.backlog_path = Path(self.temp_dir) / "backlog.md"

    def tearDown(self):
        """Clean up temporary files."""
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def write_backlog(self, content: str):
        """Write content to temp backlog file."""
        self.backlog_path.write_text(content, encoding="utf-8")

    def test_backlog_with_extra_newlines(self):
        """Test parsing backlog with extra newlines."""
        content = """# Next Backlog



## 1. Issue with extra lines


Labels: `test`


Body here.


## 2. Another issue

Body.

"""
        self.write_backlog(content)
        issues = parse_backlog_cleanup(self.backlog_path)
        self.assertEqual(len(issues), 2)

    def test_backlog_with_unicode(self):
        """Test parsing backlog with unicode characters."""
        content = """# Next Backlog

## 1. Unicode issue

Labels: `test`

Body with unicode: äöü ß 中文 🎉
"""
        self.write_backlog(content)
        issues = parse_backlog_cleanup(self.backlog_path)
        self.assertEqual(len(issues), 1)
        self.assertIn("Unicode issue", issues[0]["title"])
        self.assertIn("äöü", issues[0]["body"])

    def test_backlog_with_special_formatting(self):
        """Test parsing backlog with special markdown formatting."""
        content = """# Next Backlog

## 1. Issue with `code` blocks

Labels: `test`

Body with ```code blocks``` and **bold** text.

- List item 1
- List item 2

```python
def example():
    pass
```
"""
        self.write_backlog(content)
        issues = parse_backlog_cleanup(self.backlog_path)
        self.assertEqual(len(issues), 1)
        self.assertIn("code blocks", issues[0]["body"])
        self.assertIn("bold", issues[0]["body"])
        self.assertIn("List item 1", issues[0]["body"])


if __name__ == "__main__":
    unittest.main()
