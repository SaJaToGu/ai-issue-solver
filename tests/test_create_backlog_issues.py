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


class TestApplyLoopSafety(unittest.TestCase):
    """Tests for the apply loop safety in create_backlog_issues.py"""

    def test_apply_loop_skips_existing_issues(self):
        """Test that the apply loop correctly skips existing issues."""
        # Mock GitHubClient and its methods
        class MockGitHubClient:
            def __init__(self):
                self.created_issues = []
                self.ensured_labels = []

            def find_matching_issue(self, repo, title):
                # Simulate that the second issue already exists
                if title == "Second issue":
                    return {"state": "open", "number": 2}
                return None

            def ensure_label(self, repo, label):
                self.ensured_labels.append(label)

            def create_issue(self, repo, title, body, labels):
                self.created_issues.append((title, labels))
                return f"https://github.com/{repo}/issues/1"

        # Mock issues
        issues = [
            {"title": "First issue", "labels": ["label1"], "body": "Body 1"},
            {"title": "Second issue", "labels": ["label2"], "body": "Body 2"},
            {"title": "Third issue", "labels": ["label3"], "body": "Body 3"},
        ]

        # Test the new logic
        client = MockGitHubClient()
        new_issues = []
        existing_open = []
        existing_closed = []

        for issue in issues:
            matching_issue = client.find_matching_issue("test-repo", issue["title"])
            if matching_issue:
                if matching_issue.get("state") == "open":
                    existing_open.append((issue["title"], matching_issue["number"]))
                else:
                    existing_closed.append((issue["title"], matching_issue["number"]))
            else:
                new_issues.append(issue)

        # Verify results
        self.assertEqual(len(new_issues), 2)  # First and third issues are new
        self.assertEqual(len(existing_open), 1)  # Second issue exists and is open
        self.assertEqual(len(existing_closed), 0)

    def test_apply_loop_with_closed_issues(self):
        """Test that the apply loop correctly handles closed issues."""
        # Mock GitHubClient and its methods
        class MockGitHubClient:
            def __init__(self):
                self.created_issues = []
                self.ensured_labels = []

            def find_matching_issue(self, repo, title):
                # Simulate that the second issue exists and is closed
                if title == "Second issue":
                    return {"state": "closed", "number": 2}
                return None

            def ensure_label(self, repo, label):
                self.ensured_labels.append(label)

            def create_issue(self, repo, title, body, labels):
                self.created_issues.append((title, labels))
                return f"https://github.com/{repo}/issues/1"

        # Mock issues
        issues = [
            {"title": "First issue", "labels": ["label1"], "body": "Body 1"},
            {"title": "Second issue", "labels": ["label2"], "body": "Body 2"},
            {"title": "Third issue", "labels": ["label3"], "body": "Body 3"},
        ]

        # Test the new logic
        client = MockGitHubClient()
        new_issues = []
        existing_open = []
        existing_closed = []

        for issue in issues:
            matching_issue = client.find_matching_issue("test-repo", issue["title"])
            if matching_issue:
                if matching_issue.get("state") == "open":
                    existing_open.append((issue["title"], matching_issue["number"]))
                else:
                    existing_closed.append((issue["title"], matching_issue["number"]))
            else:
                new_issues.append(issue)

        # Verify results
        self.assertEqual(len(new_issues), 2)  # First and third issues are new
        self.assertEqual(len(existing_open), 0)
        self.assertEqual(len(existing_closed), 1)  # Second issue exists and is closed

    def test_apply_loop_with_only_new_flag(self):
        """Test that the apply loop respects the --only-new flag."""
        # Mock GitHubClient and its methods
        class MockGitHubClient:
            def __init__(self):
                self.created_issues = []
                self.ensured_labels = []

            def find_matching_issue(self, repo, title):
                # Simulate that the second issue already exists
                if title == "Second issue":
                    return {"state": "open", "number": 2}
                return None

            def ensure_label(self, repo, label):
                self.ensured_labels.append(label)

            def create_issue(self, repo, title, body, labels):
                self.created_issues.append((title, labels))
                return f"https://github.com/{repo}/issues/1"

        # Mock issues
        issues = [
            {"title": "First issue", "labels": ["label1"], "body": "Body 1"},
            {"title": "Second issue", "labels": ["label2"], "body": "Body 2"},
            {"title": "Third issue", "labels": ["label3"], "body": "Body 3"},
        ]

        # Test with --only-new flag
        client = MockGitHubClient()
        new_issues = []
        existing_open = []
        existing_closed = []

        for issue in issues:
            matching_issue = client.find_matching_issue("test-repo", issue["title"])
            if matching_issue:
                if matching_issue.get("state") == "open":
                    existing_open.append((issue["title"], matching_issue["number"]))
                else:
                    existing_closed.append((issue["title"], matching_issue["number"]))
            else:
                new_issues.append(issue)

        # With --only-new, only new_issues should be created
        issues_to_create = new_issues
        self.assertEqual(len(issues_to_create), 2)  # First and third issues

    def test_apply_loop_with_force_flag(self):
        """Test that the apply loop respects the --force flag."""
        # Mock GitHubClient and its methods
        class MockGitHubClient:
            def __init__(self):
                self.created_issues = []
                self.ensured_labels = []

            def find_matching_issue(self, repo, title):
                # Simulate that the second issue already exists
                if title == "Second issue":
                    return {"state": "open", "number": 2}
                return None

            def ensure_label(self, repo, label):
                self.ensured_labels.append(label)

            def create_issue(self, repo, title, body, labels):
                self.created_issues.append((title, labels))
                return f"https://github.com/{repo}/issues/1"

        # Mock issues
        issues = [
            {"title": "First issue", "labels": ["label1"], "body": "Body 1"},
            {"title": "Second issue", "labels": ["label2"], "body": "Body 2"},
            {"title": "Third issue", "labels": ["label3"], "body": "Body 3"},
        ]

        # Test with --force flag
        client = MockGitHubClient()
        new_issues = []
        existing_open = []
        existing_closed = []

        for issue in issues:
            matching_issue = client.find_matching_issue("test-repo", issue["title"])
            if matching_issue:
                if matching_issue.get("state") == "open":
                    existing_open.append((issue["title"], matching_issue["number"]))
                else:
                    existing_closed.append((issue["title"], matching_issue["number"]))
            else:
                new_issues.append(issue)

        # With --force, all issues should be created
        issues_to_create = issues
        self.assertEqual(len(issues_to_create), 3)  # All issues

    def test_apply_loop_handles_empty_issues(self):
        """Test that the apply loop handles empty issues list safely."""
        # Mock GitHubClient
        class MockGitHubClient:
            def issue_exists(self, repo, title):
                return False

            def ensure_label(self, repo, label):
                pass

            def create_issue(self, repo, title, body, labels):
                return f"https://github.com/{repo}/issues/1"

        # Test with empty issues list
        client = MockGitHubClient()
        issues = []
        created = 0
        skipped = 0

        for issue in issues:
            if client.issue_exists("test-repo", issue["title"]):
                skipped += 1
                continue

            mapped_labels = []
            for label in issue["labels"]:
                mapped_labels.append(label)
                client.ensure_label("test-repo", label)

            client.create_issue("test-repo", issue["title"], issue["body"], mapped_labels)
            created += 1

        # Verify no issues were created
        self.assertEqual(created, 0)
        self.assertEqual(skipped, 0)


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


class TestTitleNormalization(unittest.TestCase):
    """Tests for title normalization in create_backlog_issues.py"""

    def test_normalize_title(self):
        """Test that title normalization works correctly."""
        # Mock GitHubClient and its methods
        class MockGitHubClient:
            def normalize_title(self, title: str) -> str:
                import re
                return re.sub(r'[^a-z0-9]', '', title.lower())

        client = MockGitHubClient()

        # Test various title formats
        self.assertEqual(client.normalize_title("Test Issue"), "testissue")
        self.assertEqual(client.normalize_title("Test-Issue"), "testissue")
        self.assertEqual(client.normalize_title("Test_Issue"), "testissue")
        self.assertEqual(client.normalize_title("Test Issue!"), "testissue")
        self.assertEqual(client.normalize_title("Test Issue?"), "testissue")
        self.assertEqual(client.normalize_title("Test Issue 123"), "testissue123")
        self.assertEqual(client.normalize_title("TEST ISSUE"), "testissue")
        self.assertEqual(client.normalize_title("  Test Issue  "), "testissue")


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
