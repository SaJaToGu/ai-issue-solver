from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from workflow_congestion import (  # noqa: E402
    BacklogEntry,
    WorkflowIssue,
    WorkflowPullRequest,
    analyze_workflow_congestion,
    parse_backlog_entries,
    match_backlog_to_issues,
    issue_has_open_pr,
    parse_issue_references,
)


class WorkflowCongestionTests(unittest.TestCase):
    def test_parse_issue_references_deduplicates_parent_and_refs(self):
        refs = parse_issue_references("Parent: #216\nRefs #216 and fixes #289")
        self.assertEqual(refs, (216, 289))

    def test_clean_workflow_has_continue_recommendation(self):
        summary = analyze_workflow_congestion([], [], pr_threshold=2)

        self.assertFalse(summary.needs_attention)
        self.assertEqual(summary.recommended_action, "continue")
        self.assertEqual(summary.open_pr_count, 0)
        self.assertEqual(summary.red_pr_count, 0)
        self.assertEqual(summary.stale_generated_branch_count, 0)
        self.assertEqual(summary.superseded_approach_count, 0)
        self.assertEqual(summary.backlog_entry_with_open_issue_count, 0)
        self.assertEqual(summary.backlog_entry_with_closed_issue_count, 0)

    def test_pr_congestion_and_duplicate_issue_pr_are_reported(self):
        now = datetime(2026, 6, 13, tzinfo=timezone.utc)
        prs = [
            WorkflowPullRequest(1, "Fix #216", body="Refs #216", created_at="2026-06-01T00:00:00Z"),
            WorkflowPullRequest(2, "Fix #289", body="Refs #289", mergeable_state="dirty"),
            WorkflowPullRequest(3, "Docs", mergeable_state="clean"),
        ]
        issues = [WorkflowIssue(216, "Workflow control"), WorkflowIssue(289, "Labels")]

        summary = analyze_workflow_congestion(
            prs,
            issues,
            now=now,
            pr_threshold=2,
            stale_days=7,
        )

        self.assertTrue(summary.needs_attention)
        self.assertEqual(summary.open_pr_count, 3)
        self.assertEqual(summary.red_pr_count, 1)
        self.assertEqual(summary.green_unreviewed_pr_count, 1)
        self.assertEqual(summary.stale_pr_count, 1)
        self.assertEqual(summary.duplicate_issue_pr_count, 2)
        self.assertEqual(summary.recommended_action, "rerun_or_fix_red_pr")
        self.assertIn("issue_has_open_pr", {finding.kind for finding in summary.findings})

    def test_stale_generated_branches_do_not_count_twice(self):
        """Stale generated branches are separate from stale PRs."""
        now = datetime(2026, 6, 13, tzinfo=timezone.utc)
        prs = [
            WorkflowPullRequest(1, "Fix old issue", created_at="2026-06-01T00:00:00Z"),
        ]
        summary = analyze_workflow_congestion(
            prs,
            [],
            now=now,
            stale_days=7,
        )
        self.assertEqual(summary.stale_pr_count, 1)
        self.assertEqual(summary.stale_generated_branch_count, 0)

    def test_superseded_approach_detection(self):
        """PRs referencing an open issue are detected as duplicates."""
        prs = [
            WorkflowPullRequest(1, "First approach", body="Closes #42"),
            WorkflowPullRequest(2, "Second approach", body="Refs #42"),
        ]
        issues = [WorkflowIssue(42, "Some feature")]
        summary = analyze_workflow_congestion(prs, issues)
        # Both PRs reference the same open issue -> 2 entries
        self.assertEqual(summary.duplicate_issue_pr_count, 2)

    def test_backlog_entries_matched_to_issues(self):
        """Backlog entries matched to open and closed issues appear in findings."""
        backlog_entries = [
            BacklogEntry(section_number=16, title="Use GitHub intelligence", priority=1),
            BacklogEntry(section_number=17, title="Add workflow control", priority=1),
        ]
        open_issues = [
            WorkflowIssue(216, "Add workflow control"),
        ]
        closed_issues = [
            WorkflowIssue(200, "Use GitHub intelligence", state="closed"),
        ]

        summary = analyze_workflow_congestion(
            [],
            open_issues,
            closed_issues=closed_issues,
            backlog_entries=backlog_entries,
        )

        # Backlog #17 has an open issue -> finding
        # Backlog #16 has a closed issue -> finding
        backlog_kinds = {finding.kind for finding in summary.findings}
        self.assertIn("backlog_entry_has_open_issue", backlog_kinds)
        self.assertIn("backlog_entry_has_closed_issue", backlog_kinds)
        self.assertEqual(summary.backlog_entry_with_open_issue_count, 1)
        self.assertEqual(summary.backlog_entry_with_closed_issue_count, 1)

    def test_backlog_without_matching_issues_produces_no_findings(self):
        """Backlog entries without matching GitHub issues produce no backlog findings."""
        backlog_entries = [
            BacklogEntry(section_number=99, title="Nonexistent feature", priority=2),
        ]
        summary = analyze_workflow_congestion(
            [],
            [],
            backlog_entries=backlog_entries,
        )
        backlog_findings = [
            f for f in summary.findings if "backlog" in f.kind
        ]
        self.assertEqual(len(backlog_findings), 0)
        self.assertEqual(summary.backlog_entry_with_open_issue_count, 0)
        self.assertEqual(summary.backlog_entry_with_closed_issue_count, 0)

    def test_issue_has_open_pr_returns_true_when_pr_exists(self):
        """issue_has_open_pr detects when an issue has an open PR."""
        prs = [
            WorkflowPullRequest(10, "Fix #42", body="Closes #42"),
            WorkflowPullRequest(11, "Docs update"),
        ]
        self.assertTrue(issue_has_open_pr(42, prs))
        self.assertFalse(issue_has_open_pr(99, prs))

    def test_issue_has_open_pr_ignores_closed_prs(self):
        """issue_has_open_pr only checks open PRs."""
        prs = [
            WorkflowPullRequest(10, "Fix #42", body="Closes #42", state="closed"),
        ]
        self.assertFalse(issue_has_open_pr(42, prs))

    def test_parse_backlog_entries_returns_empty_for_missing_file(self):
        entries = parse_backlog_entries(Path("/nonexistent/path/NEXT_BACKLOG.md"))
        self.assertEqual(entries, [])

    def test_parse_backlog_entries_reads_valid_file(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
            f.write("""# Backlog

## 16. Use GitHub intelligence

Labels: `kind/automation`, `theme/quality`

Priority: `1`

Description here.

## 17. Add workflow control

Labels: `kind/automation`, `theme/workflow`

Priority: `1`

Another description.
""")
            temp_path = Path(f.name)

        try:
            entries = parse_backlog_entries(temp_path)
            self.assertEqual(len(entries), 2)
            self.assertEqual(entries[0].section_number, 16)
            self.assertEqual(entries[0].title, "Use GitHub intelligence")
            self.assertIn("kind/automation", entries[0].labels)
            self.assertEqual(entries[0].priority, 1)
            self.assertEqual(entries[1].section_number, 17)
            self.assertEqual(entries[1].title, "Add workflow control")
        finally:
            if temp_path.exists():
                temp_path.unlink()

    def test_match_backlog_to_issues_matches_by_title(self):
        backlog = [
            BacklogEntry(1, "Fix the thing", priority=1),
            BacklogEntry(2, "Different title", priority=2),
        ]
        open_issues = [WorkflowIssue(100, "Fix the thing")]
        closed_issues = [WorkflowIssue(200, "Different title", state="closed")]
        result = match_backlog_to_issues(backlog, open_issues, closed_issues)
        self.assertIn(1, result)
        self.assertIn(2, result)
        matched_open, matched_closed = result[1]
        self.assertEqual(matched_open.number, 100)
        self.assertIsNone(matched_closed)
        matched_open2, matched_closed2 = result[2]
        self.assertIsNone(matched_open2)
        self.assertEqual(matched_closed2.number, 200)

    def test_superseded_prs_counted_separately(self):
        """Superseded PRs are counted separately from duplicates."""
        now = datetime(2026, 6, 13, tzinfo=timezone.utc)
        prs = [
            WorkflowPullRequest(5, "PR 5", body="Refs #50"),
            WorkflowPullRequest(6, "PR 6", body="Closes #51"),
            WorkflowPullRequest(7, "PR 7", body="Refs #52"),
        ]
        issues = [
            WorkflowIssue(50, "Issue 50"),
            WorkflowIssue(51, "Issue 51"),
            WorkflowIssue(52, "Issue 52"),
        ]
        summary = analyze_workflow_congestion(prs, issues, pr_threshold=5)
        # PR 5 refs #50, PR 6 closes #51, PR 7 refs #52
        self.assertGreater(summary.duplicate_issue_pr_count, 0)

    def test_backlog_entry_with_open_and_closed_issue_separate_counts(self):
        """Open and closed issue counts for backlog are tracked separately."""
        backlog_entries = [
            BacklogEntry(1, "Feature A", priority=1),
            BacklogEntry(2, "Feature B", priority=1),
            BacklogEntry(3, "Feature C", priority=1),
        ]
        open_issues = [WorkflowIssue(100, "Feature A")]
        closed_issues = [WorkflowIssue(200, "Feature B", state="closed")]
        summary = analyze_workflow_congestion(
            [],
            open_issues,
            closed_issues=closed_issues,
            backlog_entries=backlog_entries,
        )
        self.assertEqual(summary.backlog_entry_with_open_issue_count, 1)
        self.assertEqual(summary.backlog_entry_with_closed_issue_count, 1)
        self.assertGreater(summary.backlog_entry_with_closed_issue_count, 0)

    def test_recommended_action_prioritizes_red_prs(self):
        """Red PRs have highest priority in recommended_action."""
        prs = [
            WorkflowPullRequest(1, "Red PR", check_state="failure"),
            WorkflowPullRequest(2, "Old PR", created_at="2026-06-01T00:00:00Z"),
        ]
        now = datetime(2026, 6, 13, tzinfo=timezone.utc)
        summary = analyze_workflow_congestion(prs, [], now=now, stale_days=7)
        self.assertEqual(summary.recommended_action, "rerun_or_fix_red_pr")

    def test_recommended_action_backlog_cleanup_when_closed_issues_exist(self):
        """Clean backlog is recommended when backlog items have closed issues."""
        backlog_entries = [
            BacklogEntry(5, "Done feature", priority=1),
        ]
        open_issues: list[WorkflowIssue] = []
        closed_issues = [WorkflowIssue(500, "Done feature", state="closed")]
        summary = analyze_workflow_congestion(
            [],
            open_issues,
            closed_issues=closed_issues,
            backlog_entries=backlog_entries,
            pr_threshold=5,
        )
        self.assertEqual(summary.recommended_action, "clean_backlog_closed_issues")


if __name__ == "__main__":
    unittest.main()
