import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.benchmark_issues import (
    build_benchmark_command,
    extract_run_report_path,
    load_run_outcome,
    run_benchmark,
)


class BenchmarkIssueTests(unittest.TestCase):
    def test_build_benchmark_command_uses_shared_single_solver_spec(self):
        command = build_benchmark_command(
            380,
            repo="ai-issue-solver",
            dry_run=True,
            model_name="minimax/minimax-m3",
            branch_suffix="bench/123/minimax",
        )

        self.assertIn("scripts/solve_issues.py", command[1])
        self.assertIn("--model", command)
        self.assertIn("opencode", command)
        self.assertIn("--model-name", command)
        self.assertIn("minimax/minimax-m3", command)
        self.assertIn("--repo", command)
        self.assertIn("ai-issue-solver", command)
        self.assertIn("--issue", command)
        self.assertIn("380", command)
        self.assertIn("--skip-pr", command)
        self.assertIn("--dry-run", command)
        self.assertIn("--branch-suffix", command)
        self.assertNotIn("--label", command)

    def test_build_benchmark_ensemble_command_uses_shared_single_solver_spec(self):
        command = build_benchmark_command(
            380,
            repo="ai-issue-solver",
            ensemble=3,
        )

        self.assertIn("--skip-pr", command)
        self.assertIn("--ensemble", command)
        self.assertIn("3", command)
        self.assertNotIn("--model-name", command)

    def test_build_benchmark_command_omits_dry_run_when_disabled(self):
        command = build_benchmark_command(
            380,
            repo="ai-issue-solver",
            dry_run=False,
            model_name="minimax/minimax-m3",
        )

        self.assertNotIn("--dry-run", command)

    def test_build_benchmark_command_forwards_opencode_state_override(self):
        command = build_benchmark_command(
            381,
            repo="ai-issue-solver",
            allow_opencode_state_conflict=True,
        )

        self.assertIn("--allow-opencode-state-conflict", command)

    def test_run_benchmark_uses_shared_opencode_preflight_guard(self):
        with patch(
            "scripts.benchmark_issues.run_opencode_preflight_guard",
            return_value=False,
        ) as preflight_guard:
            result = run_benchmark(
                381,
                ["minimax/minimax-m3"],
                dry_run=False,
                allow_opencode_state_conflict=True,
            )

        self.assertEqual(result["error"], "opencode_state_preflight_failed")
        self.assertEqual(result["models_tested"], 0)
        preflight_guard.assert_called_once_with(allow_conflict=True)

    def test_run_benchmark_skips_opencode_preflight_for_dry_run(self):
        with patch(
            "scripts.benchmark_issues.run_opencode_preflight_guard",
            return_value=False,
        ) as preflight_guard, patch(
            "scripts.benchmark_issues.subprocess.run"
        ) as subprocess_run:
            subprocess_run.return_value.returncode = 0
            subprocess_run.return_value.stdout = "no_changes"
            subprocess_run.return_value.stderr = ""

            result = run_benchmark(381, ["minimax/minimax-m3"], dry_run=True)

        self.assertFalse(preflight_guard.called)
        self.assertIn("minimax/minimax-m3", result)

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
