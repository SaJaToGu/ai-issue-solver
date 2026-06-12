from __future__ import annotations

import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

import rework_workflow
from solver_reporting import RunReport, write_run_report
from workers.base import WorkerRunResult


class ReworkWorkflowCliTests(unittest.TestCase):
    def run_main(self, *args: str) -> tuple[int, str]:
        output = StringIO()
        with patch.object(sys, "argv", ["rework_workflow.py", *args]):
            with redirect_stdout(output):
                code = rework_workflow.main()
        return code, output.getvalue()

    def test_plain_dry_run_requires_rework_of(self):
        stderr = StringIO()
        with patch.object(sys, "argv", ["rework_workflow.py", "--dry-run"]):
            with redirect_stderr(stderr), self.assertRaises(SystemExit) as ctx:
                rework_workflow.main()
        self.assertEqual(ctx.exception.code, 2)

    def test_from_note_dry_run_infers_issue_reference_without_github_config(self):
        code, output = self.run_main(
            "--from-note",
            "tests failing after #220",
            "--dry-run",
        )

        self.assertEqual(code, 0)
        self.assertIn("Titel:  [Rework] #220", output)
        self.assertIn("Rework-Reason: tests_failed", output)

    def test_from_note_without_issue_reference_errors(self):
        stderr = StringIO()
        with patch.object(sys, "argv", ["rework_workflow.py", "--from-note", "tests failing", "--dry-run"]):
            with redirect_stderr(stderr), self.assertRaises(SystemExit) as ctx:
                rework_workflow.main()
        self.assertEqual(ctx.exception.code, 2)

    def test_from_run_dry_run_does_not_require_github_config(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            run_dir = Path(tmpdir) / "run"
            run_dir.mkdir()
            (run_dir / "metadata.json").write_text(
                json.dumps(
                    {
                        "status": "validation_failed",
                        "issue_number": 220,
                        "issue_title": "Structured rework",
                        "pr_url": "https://github.com/example/repo/pull/12",
                        "run_outcome": {"failure_class": "validation_failure"},
                    }
                ),
                encoding="utf-8",
            )

            code, output = self.run_main("--from-run", str(run_dir), "--dry-run")

        self.assertEqual(code, 0)
        self.assertIn("Titel:  [Rework] #220", output)
        self.assertIn("Rework-Reason: validation_failed", output)

    def test_unique_labels_preserves_order(self):
        labels = rework_workflow.unique_labels(["kind/rework", "theme/quality", "kind/rework"])
        self.assertEqual(labels, ["kind/rework", "theme/quality"])

    def test_pull_request_links_issue_uses_body_not_missing_api_field(self):
        pr = {
            "title": "Fix workflow",
            "body": "Refs #220\n\nImplementation details.",
        }

        self.assertTrue(rework_workflow.pull_request_links_issue(pr, 220))
        self.assertFalse(rework_workflow.pull_request_links_issue(pr, 221))


class ReworkReportFieldTests(unittest.TestCase):
    def test_write_run_report_persists_rework_fields(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            report = RunReport(
                path=Path(tmpdir),
                repo="demo",
                issue_number=220,
                issue_title="Structured rework",
                branch="ai/fix-issue-220",
                model="opencode",
            )

            write_run_report(
                report,
                "pr_created",
                worker_result=WorkerRunResult(returncode=0, output="done"),
                pr_url="https://github.com/example/repo/pull/12",
                rework_of=220,
                rework_reason="tests_failed",
                subtask_id="test-repair-1",
                supersedes_pr=11,
                follow_up_issue=221,
            )

            metadata = json.loads((Path(tmpdir) / "metadata.json").read_text(encoding="utf-8"))
            summary = (Path(tmpdir) / "summary.txt").read_text(encoding="utf-8")

        self.assertEqual(metadata["rework"]["rework_of"], 220)
        self.assertEqual(metadata["rework"]["rework_reason"], "tests_failed")
        self.assertEqual(metadata["rework"]["subtask_id"], "test-repair-1")
        self.assertEqual(metadata["rework"]["supersedes_pr"], 11)
        self.assertEqual(metadata["rework"]["follow_up_issue"], 221)
        self.assertIn("rework_of: 220", summary)
        self.assertIn("rework_reason: tests_failed", summary)
        self.assertIn("subtask_id: test-repair-1", summary)
        self.assertIn("supersedes_pr: 11", summary)
        self.assertIn("follow_up_issue: 221", summary)


if __name__ == "__main__":
    unittest.main()
