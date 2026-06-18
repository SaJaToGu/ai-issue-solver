import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from post_merge_cleanup import (  # noqa: E402
    CleanupResult,
    LocalBranchEntry,
    LocalBranchReport,
    ReferencedIssue,
    apply_local_branch_cleanup,
    can_close_issue,
    cleanup_backlog_entries,
    cleanup_local_branches,
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


# ── Local branch cleanup (Issue #331) ────────────────────────────
#
# Safety rule pinned by these tests:
#   - main, develop, and the current branch are NEVER deletable.
#   - A branch becomes a deletion candidate ONLY when it is merged into
#     the configured base AND not protected.
#   - "gone upstream" is a manual-review signal, NOT a deletion approval.
#   - Unmerged branches are never deleted, regardless of upstream state.
#   - The git_runner parameter is the seam: tests pass a fake runner
#     that records every call and returns a pre-configured response
#     per (args) pattern. This is the same injection pattern used by
#     scripts/review_pr.py for the OpenRouter call.


class FakeGitRunner:
    """Records every call and returns a pre-configured response per args pattern.

    The matcher is a list of substrings: a configured response applies
    when the git args contain ALL of its substrings. The first matching
    configured response wins.
    """

    def __init__(self):
        self.calls: list[list[str]] = []
        # Ordered list of (matcher_substrings, returncode, stdout, stderr)
        self.responses: list[tuple[list[str], int, str, str]] = []
        # Counters
        self.deleted_branches: list[str] = []

    def add_response(self, substrings: list[str], returncode: int = 0, stdout: str = "", stderr: str = "") -> None:
        self.responses.append((list(substrings), returncode, stdout, stderr))

    def __call__(self, args, cwd=None):
        self.calls.append(list(args))
        for substrings, rc, out, err in self.responses:
            if all(s in args for s in substrings):
                return subprocess.CompletedProcess(
                    args=["git", *args],
                    returncode=rc,
                    stdout=out,
                    stderr=err,
                )
        # Default: empty success.
        return subprocess.CompletedProcess(
            args=["git", *args],
            returncode=0,
            stdout="",
            stderr="",
        )


class LocalBranchSafetyTests(unittest.TestCase):
    """Protected branches are never deletable."""

    def test_main_and_develop_never_deletable(self):
        runner = FakeGitRunner()
        runner.add_response(["rev-parse", "--abbrev-ref", "HEAD"],
                            stdout="feature/working")
        runner.add_response(["for-each-ref"],
                            stdout="main\ndevelop\nfeature/working\nmerged-branch")
        runner.add_response(["branch", "--list", "--merged"],
                            stdout="  feature/working\n  merged-branch")

        report = cleanup_local_branches(
            base="develop",
            show_unmerged=False,
            dry_run=True,
            git_runner=runner,
        )

        # main, develop, and the current branch are protected
        protected_names = {e.name for e in report.protected}
        self.assertIn("main", protected_names)
        self.assertIn("develop", protected_names)
        self.assertIn("feature/working", protected_names)

        # None of the protected names appear in to_delete
        to_delete_names = {e.name for e in report.to_delete}
        self.assertNotIn("main", to_delete_names)
        self.assertNotIn("develop", to_delete_names)
        self.assertNotIn("feature/working", to_delete_names)

    def test_protection_holds_even_with_apply(self):
        """--apply must never delete main/develop/current."""
        runner = FakeGitRunner()
        runner.add_response(["rev-parse", "--abbrev-ref", "HEAD"],
                            stdout="develop")
        runner.add_response(["for-each-ref"],
                            stdout="main\ndevelop\nfeature/merged")
        runner.add_response(["branch", "--list", "--merged"],
                            stdout="  develop\n  feature/merged")
        report = cleanup_local_branches(
            base="develop",
            show_unmerged=False,
            dry_run=False,  # apply mode
            git_runner=runner,
        )
        actions = apply_local_branch_cleanup(report, dry_run=False, git_runner=runner)
        # Even in apply mode, the script never asks git to delete
        # a protected branch. The git_runner would record such a call
        # in its calls list; we assert no such call was made.
        delete_args = [c for c in runner.calls if c and c[0] == "branch" and c[1] == "-d"]
        for args in delete_args:
            self.assertNotIn("main", args)
            self.assertNotIn("develop", args)
            # Current branch was "develop", so it must not appear either
            self.assertNotIn("develop", args[2:])

        # The only deletable branch was "feature/merged"
        self.assertTrue(any("feature/merged" in a for a in actions))

    def test_current_branch_never_deletable_when_it_is_a_feature_branch(self):
        runner = FakeGitRunner()
        runner.add_response(["rev-parse", "--abbrev-ref", "HEAD"],
                            stdout="feature/wip")
        runner.add_response(["for-each-ref"],
                            stdout="main\ndevelop\nfeature/wip")
        runner.add_response(["branch", "--list", "--merged"],
                            stdout="  develop\n  feature/wip")
        report = cleanup_local_branches(
            base="develop",
            show_unmerged=False,
            dry_run=False,
            git_runner=runner,
        )
        protected_names = {e.name for e in report.protected}
        self.assertIn("feature/wip", protected_names)
        # Even though feature/wip is "merged" in git's view, it is the
        # current branch and must not be in to_delete.
        to_delete_names = {e.name for e in report.to_delete}
        self.assertNotIn("feature/wip", to_delete_names)


class LocalBranchDeletionTests(unittest.TestCase):
    """Only merged-into-base + not-protected becomes a deletion candidate."""

    def test_merged_branch_is_deletable(self):
        runner = FakeGitRunner()
        runner.add_response(["rev-parse", "--abbrev-ref", "HEAD"],
                            stdout="develop")
        runner.add_response(["for-each-ref"],
                            stdout="main\ndevelop\nfeature/merged")
        runner.add_response(["branch", "--list", "--merged"],
                            stdout="  develop\n  feature/merged")
        report = cleanup_local_branches(
            base="develop", show_unmerged=False, dry_run=True, git_runner=runner
        )
        to_delete_names = {e.name for e in report.to_delete}
        self.assertIn("feature/merged", to_delete_names)
        for entry in report.to_delete:
            if entry.name == "feature/merged":
                self.assertEqual(entry.category, "merged")
                self.assertIn("develop", entry.reason)

    def test_unmerged_branch_is_not_deletable_even_with_show_unmerged(self):
        runner = FakeGitRunner()
        runner.add_response(["rev-parse", "--abbrev-ref", "HEAD"],
                            stdout="develop")
        runner.add_response(["for-each-ref"],
                            stdout="main\ndevelop\nfeature/wip")
        runner.add_response(["branch", "--list", "--merged"],
                            stdout="  develop")
        # feature/wip has its upstream still alive
        runner.add_response(["rev-parse", "--verify", "refs/remotes/origin/feature/wip"],
                            stdout="abc123")
        report = cleanup_local_branches(
            base="develop",
            show_unmerged=True,  # explicit
            dry_run=False,        # apply mode
            git_runner=runner,
        )
        to_delete_names = {e.name for e in report.to_delete}
        self.assertNotIn("feature/wip", to_delete_names)
        # The branch shows up in manual_review because --show-unmerged
        review_names = {e.name for e in report.manual_review}
        self.assertIn("feature/wip", review_names)

        # And the apply call must NOT ask git to delete it.
        apply_local_branch_cleanup(report, dry_run=False, git_runner=runner)
        delete_calls = [
            c for c in runner.calls
            if c and c[0] == "branch" and c[1] == "-d"
        ]
        for call in delete_calls:
            self.assertNotIn("feature/wip", call)

    def test_unmerged_branch_hidden_without_show_unmerged(self):
        runner = FakeGitRunner()
        runner.add_response(["rev-parse", "--abbrev-ref", "HEAD"],
                            stdout="develop")
        runner.add_response(["for-each-ref"],
                            stdout="main\ndevelop\nfeature/wip")
        runner.add_response(["branch", "--list", "--merged"],
                            stdout="  develop")
        runner.add_response(["rev-parse", "--verify", "refs/remotes/origin/feature/wip"],
                            stdout="abc123")
        report = cleanup_local_branches(
            base="develop",
            show_unmerged=False,  # default
            dry_run=True,
            git_runner=runner,
        )
        # Without --show-unmerged, the unmerged branch is in the
        # report but filtered out of the visible list.
        self.assertEqual(report.manual_review, [])

    def test_gone_upstream_merged_branch_is_still_deletable(self):
        """Merged-and-gone: the commits are on base, deletion is safe."""
        runner = FakeGitRunner()
        runner.add_response(["rev-parse", "--abbrev-ref", "HEAD"],
                            stdout="develop")
        runner.add_response(["for-each-ref"],
                            stdout="main\ndevelop\nfeature/merged-and-gone")
        runner.add_response(["branch", "--list", "--merged"],
                            stdout="  develop\n  feature/merged-and-gone")
        # Upstream gone: rev-parse --verify returns non-zero
        runner.add_response(
            ["rev-parse", "--verify", "refs/remotes/origin/feature/merged-and-gone"],
            returncode=1, stderr="unknown revision",
        )
        report = cleanup_local_branches(
            base="develop", show_unmerged=False, dry_run=True, git_runner=runner
        )
        to_delete_names = {e.name for e in report.to_delete}
        self.assertIn("feature/merged-and-gone", to_delete_names)
        for entry in report.to_delete:
            if entry.name == "feature/merged-and-gone":
                self.assertEqual(entry.category, "merged")
                self.assertIn("Upstream", entry.reason)

    def test_gone_upstream_unmerged_branch_is_manual_review_not_deletion(self):
        """The safety rule: gone-upstream alone is never a deletion approval."""
        runner = FakeGitRunner()
        runner.add_response(["rev-parse", "--abbrev-ref", "HEAD"],
                            stdout="develop")
        runner.add_response(["for-each-ref"],
                            stdout="main\ndevelop\nfeature/lost-work")
        runner.add_response(["branch", "--list", "--merged"],
                            stdout="  develop")
        runner.add_response(
            ["rev-parse", "--verify", "refs/remotes/origin/feature/lost-work"],
            returncode=1, stderr="unknown revision",
        )
        report = cleanup_local_branches(
            base="develop", show_unmerged=True, dry_run=False, git_runner=runner
        )
        # feature/lost-work must NEVER be in to_delete, even in apply
        # mode and even with show_unmerged
        to_delete_names = {e.name for e in report.to_delete}
        self.assertNotIn("feature/lost-work", to_delete_names)
        # It must be in the manual-review list
        review_names = {e.name for e in report.manual_review}
        self.assertIn("feature/lost-work", review_names)
        # Category is unmerged-gone
        for entry in report.manual_review:
            if entry.name == "feature/lost-work":
                self.assertEqual(entry.category, "unmerged-gone")

        # And the apply call must not ask git to delete it
        apply_local_branch_cleanup(report, dry_run=False, git_runner=runner)
        delete_calls = [
            c for c in runner.calls
            if c and c[0] == "branch" and c[1] == "-d"
        ]
        for call in delete_calls:
            self.assertNotIn("feature/lost-work", call)


class LocalBranchFetchAndErrorsTests(unittest.TestCase):
    """git fetch --prune is invoked, and failures are reported."""

    def test_fetch_prune_is_called(self):
        runner = FakeGitRunner()
        runner.add_response(["rev-parse", "--abbrev-ref", "HEAD"],
                            stdout="develop")
        runner.add_response(["for-each-ref"], stdout="develop")
        runner.add_response(["branch", "--list", "--merged"], stdout="  develop")
        cleanup_local_branches(
            base="develop", show_unmerged=False, dry_run=True, git_runner=runner
        )
        fetch_calls = [c for c in runner.calls if c and c[0] == "fetch"]
        self.assertEqual(len(fetch_calls), 1)
        self.assertIn("--prune", fetch_calls[0])
        self.assertIn("origin", fetch_calls[0])

    def test_fetch_failure_does_not_block_classification(self):
        runner = FakeGitRunner()
        runner.add_response(
            ["fetch", "--prune", "origin"],
            returncode=1, stderr="network down",
        )
        runner.add_response(["rev-parse", "--abbrev-ref", "HEAD"], stdout="develop")
        runner.add_response(["for-each-ref"], stdout="develop")
        runner.add_response(["branch", "--list", "--merged"], stdout="  develop")
        report = cleanup_local_branches(
            base="develop", show_unmerged=False, dry_run=True, git_runner=runner
        )
        # Classification still works; the report flags the fetch failure
        # but does not raise.
        self.assertFalse(report.fetch_ok)
        self.assertIn("network down", report.fetch_error)
        # No errors propagating to the caller
        self.assertEqual(report.errors, [])

    def test_list_branches_failure_returns_error(self):
        runner = FakeGitRunner()
        runner.add_response(["rev-parse", "--abbrev-ref", "HEAD"], stdout="develop")
        runner.add_response(
            ["for-each-ref"],
            returncode=128, stderr="fatal: bad ref",
        )
        report = cleanup_local_branches(
            base="develop", show_unmerged=False, dry_run=True, git_runner=runner
        )
        self.assertEqual(len(report.errors), 1)
        self.assertIn("bad ref", report.errors[0])
        # No classifications possible
        self.assertEqual(report.to_delete, [])
        self.assertEqual(report.manual_review, [])
        self.assertEqual(report.protected, [])

    def test_delete_failure_is_reported_not_raised(self):
        """If git branch -d fails on a merged branch, surface the error in actions."""
        runner = FakeGitRunner()
        runner.add_response(["rev-parse", "--abbrev-ref", "HEAD"], stdout="develop")
        runner.add_response(["for-each-ref"],
                            stdout="develop\nfeature/merged")
        runner.add_response(["branch", "--list", "--merged"],
                            stdout="  develop\n  feature/merged")
        # Make the delete fail
        runner.add_response(
            ["branch", "-d", "feature/merged"],
            returncode=1, stderr="error: not fully merged",
        )
        report = cleanup_local_branches(
            base="develop", show_unmerged=False, dry_run=False, git_runner=runner
        )
        actions = apply_local_branch_cleanup(report, dry_run=False, git_runner=runner)
        self.assertEqual(len(actions), 1)
        self.assertIn("FEHLGESCHLAGEN", actions[0])
        self.assertIn("feature/merged", actions[0])
        self.assertIn("not fully merged", actions[0])

    def test_no_local_branches_returns_empty_lists(self):
        runner = FakeGitRunner()
        runner.add_response(["rev-parse", "--abbrev-ref", "HEAD"], stdout="develop")
        runner.add_response(["for-each-ref"], stdout="develop")
        runner.add_response(["branch", "--list", "--merged"], stdout="  develop")
        report = cleanup_local_branches(
            base="develop", show_unmerged=False, dry_run=True, git_runner=runner
        )
        self.assertEqual(report.to_delete, [])
        self.assertEqual(report.manual_review, [])
        # develop is in the protected set as the current branch
        protected_names = {e.name for e in report.protected}
        self.assertIn("develop", protected_names)
        self.assertNotIn("main", protected_names)


class LocalBranchDryRunVsApplyTests(unittest.TestCase):
    """dry_run gates all destructive operations."""

    def test_dry_run_does_not_call_git_branch_delete(self):
        runner = FakeGitRunner()
        runner.add_response(["rev-parse", "--abbrev-ref", "HEAD"], stdout="develop")
        runner.add_response(["for-each-ref"],
                            stdout="develop\nfeature/merged")
        runner.add_response(["branch", "--list", "--merged"],
                            stdout="  develop\n  feature/merged")
        report = cleanup_local_branches(
            base="develop", show_unmerged=False, dry_run=True, git_runner=runner
        )
        actions = apply_local_branch_cleanup(report, dry_run=True, git_runner=runner)
        # dry_run=True means no actions
        self.assertEqual(actions, [])
        # And no `git branch -d` was issued
        delete_calls = [
            c for c in runner.calls
            if c and c[0] == "branch" and c[1] == "-d"
        ]
        self.assertEqual(delete_calls, [])

    def test_apply_calls_git_branch_d_for_each_deletable(self):
        runner = FakeGitRunner()
        runner.add_response(["rev-parse", "--abbrev-ref", "HEAD"], stdout="develop")
        runner.add_response(["for-each-ref"],
                            stdout="develop\nfeature/one\nfeature/two")
        runner.add_response(["branch", "--list", "--merged"],
                            stdout="  develop\n  feature/one\n  feature/two")
        report = cleanup_local_branches(
            base="develop", show_unmerged=False, dry_run=False, git_runner=runner
        )
        actions = apply_local_branch_cleanup(report, dry_run=False, git_runner=runner)
        self.assertEqual(len(actions), 2)
        # Both branches were deleted
        delete_calls = [
            c for c in runner.calls
            if c and c[0] == "branch" and c[1] == "-d"
        ]
        delete_targets = sorted(c[2] for c in delete_calls)
        self.assertEqual(delete_targets, ["feature/one", "feature/two"])


class LocalBranchDataclassTests(unittest.TestCase):
    def test_local_branch_entry_is_frozen(self):
        entry = LocalBranchEntry(name="x", category="merged", reason="r")
        with self.assertRaises(Exception):  # FrozenInstanceError
            entry.name = "y"  # type: ignore[misc]

    def test_local_branch_report_has_expected_fields(self):
        report = LocalBranchReport(
            fetch_ok=True,
            fetch_error="",
            current_branch="develop",
            base="develop",
        )
        self.assertTrue(report.fetch_ok)
        self.assertEqual(report.current_branch, "develop")
        self.assertEqual(report.base, "develop")
        self.assertEqual(report.to_delete, [])
        self.assertEqual(report.manual_review, [])
        self.assertEqual(report.protected, [])
        self.assertEqual(report.errors, [])
        self.assertFalse(report.has_deletable)


if __name__ == "__main__":
    unittest.main()
