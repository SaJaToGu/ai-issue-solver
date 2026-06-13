from __future__ import annotations

import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from workflow_congestion import (  # noqa: E402
    WorkflowIssue,
    WorkflowPullRequest,
    analyze_workflow_congestion,
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


if __name__ == "__main__":
    unittest.main()
