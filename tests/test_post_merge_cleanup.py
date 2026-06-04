import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from post_merge_cleanup import (  # noqa: E402
    CleanupResult,
    ReferencedIssue,
    can_close_issue,
    cleanup_backlog_entries,
    cleanup_repo,
    referenced_issues_from_pr,
)


class FakeCleanupClient:
    owner = "test-owner"

    def __init__(self):
        self.closed = []
        self.deleted = []
        self.pulls = [
            {
                "number": 12,
                "title": "Fix dashboard cleanup",
                "body": "Fixes #41",
                "html_url": "https://github.com/test-owner/demo/pull/12",
                "merged_at": "2026-05-20T12:00:00Z",
                "updated_at": "2026-05-20T12:00:00Z",
                "labels": [{"name": "ai-generated"}],
                "head": {
                    "ref": "ai/fix-issue-41",
                    "repo": {"owner": {"login": "test-owner"}},
                },
            }
        ]

    def get_merged_pulls(self, repo, since):
        return self.pulls

    def get_issue(self, repo, number):
        if number == 41:
            return {"number": 41, "state": "open", "labels": [{"name": "ai-generated"}]}
        return None

    def get_issues_by_title(self, repo, titles):
        return {
            "Fix dashboard cleanup": {
                "number": 41,
                "state": "closed",
                "html_url": "https://github.com/test-owner/demo/issues/41",
            }
        }

    def get_open_prs_for_branch(self, repo, branch):
        return []

    def branch_exists(self, repo, branch):
        return branch == "ai/fix-issue-41"

    def close_issue(self, repo, number, comment):
        self.closed.append((repo, number, comment))

    def delete_branch(self, repo, branch):
        self.deleted.append((repo, branch))

    def get_branches(self, repo):
        return []


class FakeStaleBranchClient(FakeCleanupClient):
    def __init__(self):
        super().__init__()
        self.pulls = []

    def get_branches(self, repo):
        return [
            {
                "name": "ai/fix-issue-30",
                "commit": {
                    "sha": "abc123",
                    "commit": {"committer": {"date": "2026-03-01T12:00:00Z"}},
                },
            }
        ]

    def branch_exists(self, repo, branch):
        return True

    def get_pulls_for_branch(self, repo, branch):
        return [{"number": 9, "merged_at": "2026-03-02T12:00:00Z"}]


class PostMergeCleanupTests(unittest.TestCase):
    def test_referenced_issues_prefers_closing_keyword_and_branch(self):
        refs = referenced_issues_from_pr({
            "title": "Fix #7",
            "body": "Related to #8",
            "head": {"ref": "ai/fix-issue-9"},
        })

        self.assertEqual(
            [(ref.number, ref.source) for ref in refs],
            [(7, "closing-keyword"), (8, "reference"), (9, "branch-name")],
        )

    def test_can_close_issue_rejects_loose_reference(self):
        issue = {"number": 7, "state": "open", "labels": [{"name": "ai-generated"}]}

        can_close, reason = can_close_issue(issue, [ReferencedIssue(7, "reference")])

        self.assertFalse(can_close)
        self.assertIn("lose referenziert", reason)

    def test_can_close_issue_rejects_manual_review_labels(self):
        issue = {"number": 7, "state": "open", "labels": [{"name": "needs-review"}]}

        can_close, reason = can_close_issue(issue, [ReferencedIssue(7, "closing-keyword")])

        self.assertFalse(can_close)
        self.assertIn("manuelles Review-Label", reason)

    def test_cleanup_repo_dry_run_plans_safe_changes_without_mutation(self):
        client = FakeCleanupClient()

        result = cleanup_repo(
            client,
            "demo",
            datetime(2026, 5, 1, tzinfo=timezone.utc),
            datetime(2026, 4, 1, tzinfo=timezone.utc),
            "ai/",
            dry_run=True,
        )

        self.assertIsInstance(result, CleanupResult)
        self.assertEqual(result.closed_issue_count, 1)
        self.assertEqual(result.deleted_branch_count, 1)
        self.assertEqual(client.closed, [])
        self.assertEqual(client.deleted, [])

    def test_cleanup_repo_apply_closes_issue_and_deletes_branch(self):
        client = FakeCleanupClient()

        result = cleanup_repo(
            client,
            "demo",
            datetime(2026, 5, 1, tzinfo=timezone.utc),
            datetime(2026, 4, 1, tzinfo=timezone.utc),
            "ai/",
            dry_run=False,
        )

        self.assertEqual(result.closed_issue_count, 1)
        self.assertEqual(result.deleted_branch_count, 1)
        self.assertEqual(client.closed[0][0:2], ("demo", 41))
        self.assertEqual(client.deleted, [("demo", "ai/fix-issue-41")])

    def test_cleanup_repo_deletes_stale_branch_with_merged_pr(self):
        client = FakeStaleBranchClient()

        result = cleanup_repo(
            client,
            "demo",
            datetime(2026, 5, 1, tzinfo=timezone.utc),
            datetime(2026, 4, 1, tzinfo=timezone.utc),
            "ai/",
            dry_run=False,
        )

        self.assertEqual(result.deleted_branch_count, 1)
        self.assertEqual(result.stale_deleted_branches, ["ai/fix-issue-30"])
        self.assertEqual(client.deleted, [("demo", "ai/fix-issue-30")])

    def test_cleanup_backlog_entries_dry_run_does_not_edit_file(self):
        client = FakeCleanupClient()
        content = """# Next Backlog

## 1. Fix dashboard cleanup

Labels: `automation`

Remove this after the issue closes.

## 2. Keep open item

Labels: `quality`

Keep this entry.
"""
        with tempfile.TemporaryDirectory() as tmpdir:
            backlog_path = Path(tmpdir) / "NEXT_BACKLOG.md"
            backlog_path.write_text(content, encoding="utf-8")

            result = cleanup_backlog_entries(client, "demo", backlog_path, dry_run=True)

            self.assertEqual(result.completed_titles, ["Fix dashboard cleanup"])
            self.assertEqual(result.removed_count, 0)
            self.assertEqual(backlog_path.read_text(encoding="utf-8"), content)

    def test_cleanup_backlog_entries_apply_removes_closed_issue_section(self):
        client = FakeCleanupClient()
        content = """# Next Backlog

## 1. Fix dashboard cleanup

Labels: `automation`

Remove this after the issue closes.

## 2. Keep open item

Labels: `quality`

Keep this entry.
"""
        with tempfile.TemporaryDirectory() as tmpdir:
            backlog_path = Path(tmpdir) / "NEXT_BACKLOG.md"
            backlog_path.write_text(content, encoding="utf-8")

            result = cleanup_backlog_entries(client, "demo", backlog_path, dry_run=False)

            updated = backlog_path.read_text(encoding="utf-8")
            self.assertEqual(result.completed_titles, ["Fix dashboard cleanup"])
            self.assertEqual(result.removed_count, 1)
            self.assertNotIn("Fix dashboard cleanup", updated)
            self.assertIn("Keep open item", updated)


if __name__ == "__main__":
    unittest.main()
