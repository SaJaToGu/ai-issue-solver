import argparse
from datetime import datetime
from pathlib import Path
import tempfile
import unittest

import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from run_overnight import (  # noqa: E402
    StepResult,
    build_batch_command,
    build_dashboard_command,
    build_pull_command,
    create_session_dir,
    format_duration,
    parse_args,
    write_final_summary,
)


class OvernightRunnerTests(unittest.TestCase):
    def make_args(self, **overrides):
        defaults = {
            "model": "codex",
            "model_name": "",
            "repo": None,
            "issue": None,
            "label": "ai-generated",
            "base_branch": "develop",
            "workers": 2,
            "dry_run": False,
            "close_issues": False,
            "runs_dir": Path("reports/runs"),
            "dashboard_output": Path("reports/status-dashboard.html"),
            "owner": None,
        }
        defaults.update(overrides)
        return argparse.Namespace(**defaults)

    def test_build_pull_command_uses_fast_forward_only(self):
        self.assertEqual(
            build_pull_command("develop"),
            ["git", "pull", "--ff-only", "origin", "develop"],
        )

    def test_build_batch_command_forwards_bounded_solver_flags(self):
        args = self.make_args(
            model="ollama",
            model_name="deepseek-coder:6.7b",
            repo="demo",
            issue=[7, 8],
            workers=3,
            dry_run=True,
            close_issues=True,
        )

        command = build_batch_command(args, Path("scripts/solve_issues_batch.py"))

        self.assertEqual(command[0], sys.executable)
        self.assertIn("scripts/solve_issues_batch.py", command)
        self.assertIn("--workers", command)
        self.assertIn("3", command)
        self.assertIn("--base-branch", command)
        self.assertIn("develop", command)
        self.assertEqual(command.count("--issue"), 2)
        self.assertIn("--dry-run", command)
        self.assertIn("--close-issues", command)

    def test_build_dashboard_command_uses_configured_paths_and_owner(self):
        args = self.make_args(
            runs_dir=Path("custom/runs"),
            dashboard_output=Path("custom/dashboard.html"),
            owner="test-owner",
        )

        command = build_dashboard_command(args, Path("scripts/status_dashboard.py"))

        self.assertIn("--runs-dir", command)
        self.assertIn("custom/runs", command)
        self.assertIn("--output", command)
        self.assertIn("custom/dashboard.html", command)
        self.assertIn("--owner", command)
        self.assertIn("test-owner", command)

    def test_parse_args_keeps_test_command_as_argv(self):
        args = parse_args([
            "--model",
            "codex",
            "--test-command",
            "python -m pytest tests",
        ])

        self.assertEqual(args.test_command, ["python", "-m", "pytest", "tests"])

    def test_parse_args_default_test_command_discovers_tests_directory(self):
        args = parse_args(["--model", "codex"])

        self.assertEqual(
            args.test_command,
            ["python", "-m", "unittest", "discover", "-s", "tests"],
        )

    def test_create_session_dir_adds_suffix_when_timestamp_exists(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            existing = root / "20260521-220000"
            existing.mkdir()

            session_dir = create_session_dir(
                root,
                now_fn=lambda: datetime(2026, 5, 21, 22, 0, 0),
            )

        self.assertEqual(session_dir.name, "20260521-220000-2")

    def test_write_final_summary_records_failed_step_and_logs(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            session_dir = Path(tmpdir) / "reports" / "overnight" / "run"
            session_dir.mkdir(parents=True)
            summary_path = session_dir / "summary.txt"
            args = self.make_args(repo="demo", dry_run=True)
            steps = [
                StepResult("pull", ["git", "pull"], 0, session_dir / "pull.log", 1.2),
                StepResult("tests", ["python", "-m", "unittest"], 1, session_dir / "tests.log", 2.4),
                StepResult("batch", [], 0, session_dir / "batch.log", 0.0, skipped=True),
            ]

            write_final_summary(
                summary_path,
                session_dir,
                args,
                steps,
                datetime(2026, 5, 21, 22, 0, 0),
                datetime(2026, 5, 21, 22, 0, 4),
            )
            summary = summary_path.read_text(encoding="utf-8")

        self.assertIn("status: failed", summary)
        self.assertIn("repo: demo", summary)
        self.assertIn("dry_run: True", summary)
        self.assertIn("status: skipped", summary)
        self.assertIn("failed_steps:", summary)
        self.assertIn("- tests", summary)

    def test_format_duration_uses_compact_units(self):
        self.assertEqual(format_duration(4.4), "4s")
        self.assertEqual(format_duration(64), "1m 4s")
        self.assertEqual(format_duration(3661), "1h 1m 1s")


if __name__ == "__main__":
    unittest.main()
