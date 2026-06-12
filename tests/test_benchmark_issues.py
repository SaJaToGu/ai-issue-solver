import json
import tempfile
import unittest
from pathlib import Path

from scripts.benchmark_issues import extract_run_report_path, load_run_outcome


class BenchmarkIssueTests(unittest.TestCase):
    def test_extract_run_report_path_from_solver_output(self):
        output = "foo\n      Run-Report: reports/runs/20260607-demo\nbar"

        self.assertEqual(
            extract_run_report_path(output),
            Path("reports/runs/20260607-demo"),
        )

    def test_load_run_outcome_from_metadata(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            run_dir = Path(tmpdir) / "run"
            run_dir.mkdir()
            (run_dir / "metadata.json").write_text(
                json.dumps(
                    {
                        "run_outcome": {
                            "worker_status": "succeeded",
                            "has_changes": True,
                            "test_status": "passed",
                            "delivery_status": "push_failed",
                            "failure_class": "pipeline_failure",
                            "recovery_status": "preserved_worktree",
                        }
                    }
                ),
                encoding="utf-8",
            )

            outcome = load_run_outcome(run_dir)

        self.assertEqual(outcome["failure_class"], "pipeline_failure")
        self.assertTrue(outcome["has_changes"])

    def test_load_run_outcome_returns_empty_dict_when_missing(self):
        self.assertEqual(load_run_outcome(None), {})
        self.assertEqual(load_run_outcome(Path("does-not-exist")), {})


if __name__ == "__main__":
    unittest.main()
