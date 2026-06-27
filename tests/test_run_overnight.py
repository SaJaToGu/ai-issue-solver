from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from run_overnight import (  # noqa: E402
    IssueOutcome,
    StepResult,
    build_caffeinate_command,
    build_pull_command,
    can_use_caffeinate,
    collect_issue_outcomes,
    create_session_dir,
    detect_warning_markers,
    format_duration,
    main as overnight_main,
    parse_args,
    parse_run_dir_timestamp,
    parse_summary_file,
    write_final_summary,
)


class OvernightRunnerTests(unittest.TestCase):
    def make_args(self, **overrides):
        defaults = {
            "model": "codex",
            "model_name": "",
            "fallback_model": None,
            "fallback_model_name": None,
            "repo": None,
            "issue": None,
            "label": "ai-generated",
            "base_branch": "develop",
            "workers": 2,
            "dry_run": False,
            "close_issues": False,
            "worker_health_timeout_minutes": None,
            "unhealthy_action": None,
            "unhealthy_retries": None,
            "verbosity": None,
            "runs_dir": Path("reports/runs"),
            "dashboard_output": Path("reports/status-dashboard.html"),
            "owner": None,
            "allow_opencode_state_conflict": False,
        }
        defaults.update(overrides)
        return argparse.Namespace(**defaults)

    def test_build_pull_command_uses_fast_forward_only(self):
        self.assertEqual(
            build_pull_command("develop"),
            ["git", "pull", "--ff-only", "origin", "develop"],
        )

    def test_main_uses_shared_opencode_preflight_guard(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            session_dir = Path(tmpdir) / "overnight"
            session_dir.mkdir()
            with patch("run_overnight.create_session_dir", return_value=session_dir), patch(
                "run_overnight.run_opencode_preflight_guard",
                return_value=False,
            ) as preflight_guard:
                result = overnight_main([
                    "--model",
                    "opencode",
                    "--repo",
                    "demo",
                    "--issue",
                    "7",
                    "--skip-pull",
                ])

        self.assertEqual(result, 1)
        preflight_guard.assert_called_once_with(allow_conflict=False)

    def test_build_caffeinate_command_can_watch_current_process(self):
        self.assertEqual(
            build_caffeinate_command(1234),
            ["caffeinate", "-dimsu", "-w", "1234"],
        )

    def test_can_use_caffeinate_requires_macos_and_binary(self):
        self.assertTrue(can_use_caffeinate("Darwin", which_fn=lambda name: "/usr/bin/caffeinate"))
        self.assertFalse(can_use_caffeinate("Linux", which_fn=lambda name: "/usr/bin/caffeinate"))
        self.assertFalse(can_use_caffeinate("Darwin", which_fn=lambda name: None))

    def test_parse_args_keeps_test_command_as_argv(self):
        args = parse_args([
            "--model",
            "codex",
            "--test-command",
            "python -m pytest tests",
        ])

        self.assertEqual(args.test_command, ["python", "-m", "pytest", "tests"])

    def test_parse_args_accepts_caffeinate(self):
        args = parse_args(["--model", "codex", "--caffeinate"])

        self.assertTrue(args.caffeinate)

    def test_parse_args_accepts_batch_health_flags(self):
        args = parse_args([
            "--model",
            "opencode",
            "--worker-health-timeout-minutes",
            "15",
            "--unhealthy-action",
            "stop",
            "--verbosity",
            "normal",
        ])

        self.assertEqual(args.worker_health_timeout_minutes, 15)
        self.assertEqual(args.unhealthy_action, "stop")
        self.assertEqual(args.verbosity, "normal")

    def test_parse_args_default_test_command_discovers_tests_directory(self):
        args = parse_args(["--model", "codex"])

        self.assertEqual(
            args.test_command,
            [sys.executable, "-m", "unittest", "discover", "-s", "tests"],
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
                runs_dir=None,  # Keine Issue-Outcomes
            )
            summary = summary_path.read_text(encoding="utf-8")

        self.assertIn("status: failed", summary)
        self.assertIn("repo: demo", summary)
        self.assertIn("dry_run: True", summary)
        self.assertIn("workflow_congestion: see_dashboard_workflow_status", summary)
        self.assertIn("status: skipped", summary)
        self.assertIn("failed_steps:", summary)
        self.assertIn("- tests", summary)
        self.assertNotIn("issue_outcomes:", summary)

    def test_write_final_summary_includes_issue_outcomes_when_runs_dir_provided(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            session_dir = Path(tmpdir) / "reports" / "overnight" / "run"
            session_dir.mkdir(parents=True)
            runs_dir = Path(tmpdir) / "reports" / "runs"
            runs_dir.mkdir(parents=True)

            # Erstelle einen Run-Report
            run_dir = runs_dir / "20260521-220001-demo-issue-25"
            run_dir.mkdir(parents=True)
            (run_dir / "summary.txt").write_text(
                """status: pr_created
repo: demo
issue_number: 25
issue_title: Fix dashboard title
branch: ai/fix-issue-25
model: codex
worker_exit_code: 0
pr_url: https://github.com/test-owner/demo/pull/25
git_diff_stat:
  README.md | 1 +
  scripts/dashboard.py | 2 +-
""",
                encoding="utf-8",
            )

            summary_path = session_dir / "summary.txt"
            args = self.make_args(repo="demo", dry_run=False, runs_dir=runs_dir)
            steps = [
                StepResult("batch", [], 0, session_dir / "batch.log", 10.5),
            ]

            write_final_summary(
                summary_path,
                session_dir,
                args,
                steps,
                datetime(2026, 5, 21, 22, 0, 0),
                datetime(2026, 5, 21, 22, 0, 11),
                runs_dir=runs_dir,
            )
            summary = summary_path.read_text(encoding="utf-8")

        self.assertIn("status: successful", summary)
        self.assertIn("issue_outcomes:", summary)
        self.assertIn("- issue: 25", summary)
        self.assertIn("  repo: demo", summary)
        self.assertIn("  title: Fix dashboard title", summary)
        self.assertIn("  status: pr_created", summary)
        self.assertIn("  category: successful", summary)
        self.assertIn("  worker_exit_code: 0", summary)
        self.assertIn("  pr_url: https://github.com/test-owner/demo/pull/25", summary)
        self.assertIn("  changed_files:", summary)
        self.assertIn("README.md | 1 +", summary)

    def test_parse_summary_file_handles_basic_fields(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            summary_path = Path(tmpdir) / "summary.txt"
            summary_path.write_text(
                """status: pr_created
repo: demo
issue_number: 25
worker_exit_code: 0
""",
                encoding="utf-8",
            )
            fields = parse_summary_file(summary_path)

        self.assertEqual(fields["status"], "pr_created")
        self.assertEqual(fields["repo"], "demo")
        self.assertEqual(fields["issue_number"], "25")
        self.assertEqual(fields["worker_exit_code"], "0")

    def test_parse_summary_file_handles_multiline_fields(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            summary_path = Path(tmpdir) / "summary.txt"
            summary_path.write_text(
                """status: pr_created
git_diff_stat:
  README.md | 1 +
  scripts/dashboard.py | 2 +-
output_tail:
line 1
line 2
""",
                encoding="utf-8",
            )
            fields = parse_summary_file(summary_path)

        self.assertEqual(fields["status"], "pr_created")
        self.assertIn("README.md | 1 +", fields["git_diff_stat"])
        self.assertIn("scripts/dashboard.py | 2 +-", fields["git_diff_stat"])
        self.assertEqual(fields["output_tail"], "line 1\nline 2")

    def test_collect_issue_outcomes_returns_sorted_outcomes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            runs_dir = Path(tmpdir) / "runs"
            runs_dir.mkdir()

            # Erstelle zwei Run-Reports
            for issue_num in [42, 25]:
                run_dir = runs_dir / f"20260521-090807-demo-issue-{issue_num}"
                run_dir.mkdir()
                (run_dir / "summary.txt").write_text(
                    f"""status: pr_created
repo: demo
issue_number: {issue_num}
issue_title: Issue {issue_num}
worker_exit_code: 0
pr_url: https://github.com/test-owner/demo/pull/{issue_num}
""",
                    encoding="utf-8",
                )

            outcomes = collect_issue_outcomes(runs_dir)

        # Sollte nach Issue-Nummer sortiert sein
        self.assertEqual(len(outcomes), 2)
        self.assertEqual(outcomes[0].issue_number, "25")
        self.assertEqual(outcomes[1].issue_number, "42")
        self.assertEqual(outcomes[0].category, "successful")
        self.assertEqual(outcomes[1].category, "successful")

    def test_parse_run_dir_timestamp_reads_timestamp_prefix(self):
        self.assertEqual(
            parse_run_dir_timestamp(Path("20260521-220001-demo-issue-25")),
            datetime(2026, 5, 21, 22, 0, 1),
        )
        self.assertIsNone(parse_run_dir_timestamp(Path("manual-demo-issue-25")))

    def test_write_final_summary_scopes_issue_outcomes_to_current_session(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            session_dir = Path(tmpdir) / "reports" / "overnight" / "run"
            session_dir.mkdir(parents=True)
            runs_dir = Path(tmpdir) / "reports" / "runs"
            runs_dir.mkdir(parents=True)

            run_specs = [
                ("20260521-215959-demo-issue-25", "demo", 25, "Old run"),
                ("20260521-220001-demo-issue-25", "demo", 25, "Current run"),
                ("20260521-220002-other-issue-25", "other", 25, "Wrong repo"),
                ("20260521-220003-demo-issue-26", "demo", 26, "Wrong issue"),
            ]
            for run_name, repo, issue_number, title in run_specs:
                run_dir = runs_dir / run_name
                run_dir.mkdir()
                (run_dir / "summary.txt").write_text(
                    f"""status: pr_created
repo: {repo}
issue_number: {issue_number}
issue_title: {title}
worker_exit_code: 0
""",
                    encoding="utf-8",
                )

            summary_path = session_dir / "summary.txt"
            args = self.make_args(repo="demo", issue=[25], runs_dir=runs_dir)
            steps = [StepResult("batch", [], 0, session_dir / "batch.log", 1.0)]

            write_final_summary(
                summary_path,
                session_dir,
                args,
                steps,
                datetime(2026, 5, 21, 22, 0, 0),
                datetime(2026, 5, 21, 22, 0, 10),
                runs_dir=runs_dir,
            )
            summary = summary_path.read_text(encoding="utf-8")

        self.assertIn("issue_outcomes:", summary)
        self.assertIn("Current run", summary)
        self.assertNotIn("Old run", summary)
        self.assertNotIn("Wrong repo", summary)
        self.assertNotIn("Wrong issue", summary)

    def test_write_final_summary_includes_current_incomplete_outcomes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            session_dir = Path(tmpdir) / "reports" / "overnight" / "run"
            session_dir.mkdir(parents=True)
            runs_dir = Path(tmpdir) / "reports" / "runs"
            runs_dir.mkdir(parents=True)
            run_dir = runs_dir / "20260521-220001-demo-issue-189"
            run_dir.mkdir()
            (run_dir / "summary.txt").write_text(
                """status: started
repo: demo
issue_number: 189
issue_title: Long running issue
worker_exit_code:
""",
                encoding="utf-8",
            )

            summary_path = session_dir / "summary.txt"
            args = self.make_args(repo="demo", issue=[189], runs_dir=runs_dir)
            steps = [StepResult("batch", [], 1, session_dir / "batch.log", 900.0)]

            write_final_summary(
                summary_path,
                session_dir,
                args,
                steps,
                datetime(2026, 5, 21, 22, 0, 0),
                datetime(2026, 5, 21, 22, 15, 0),
                runs_dir=runs_dir,
            )
            summary = summary_path.read_text(encoding="utf-8")

        self.assertIn("issue_outcomes:", summary)
        self.assertIn("- issue: 189", summary)
        self.assertIn("  status: started", summary)
        self.assertIn("  category: running", summary)

    def test_collect_issue_outcomes_skips_queued_and_running(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            runs_dir = Path(tmpdir) / "runs"
            runs_dir.mkdir()

            # Erstelle einen queued Run (sollte ignoriert werden)
            queued_dir = runs_dir / "20260521-090807-demo-issue-99"
            queued_dir.mkdir()
            (queued_dir / "summary.txt").write_text(
                """status: queued
repo: demo
issue_number: 99
worker_exit_code:
""",
                encoding="utf-8",
            )

            # Erstelle einen erfolgreichen Run
            done_dir = runs_dir / "20260521-090807-demo-issue-25"
            done_dir.mkdir()
            (done_dir / "summary.txt").write_text(
                """status: pr_created
repo: demo
issue_number: 25
worker_exit_code: 0
""",
                encoding="utf-8",
            )

            outcomes = collect_issue_outcomes(runs_dir)

        # Nur der erfolgreiche Run sollte enthalten sein
        self.assertEqual(len(outcomes), 1)
        self.assertEqual(outcomes[0].issue_number, "25")

    def test_detect_warning_markers_finds_conflict_in_output(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            run_dir = Path(tmpdir) / "run"
            run_dir.mkdir()
            (run_dir / "summary.txt").write_text(
                """status: pr_created
output_tail:
enthaelt Git-Konfliktmarker
""",
                encoding="utf-8",
            )
            markers = detect_warning_markers(run_dir)

        self.assertIn("conflict", markers)

    def test_detect_warning_markers_finds_syntax_error_in_output(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            run_dir = Path(tmpdir) / "run"
            run_dir.mkdir()
            (run_dir / "summary.txt").write_text(
                """status: worker_finished
output_tail:
Python-Syntaxpruefung fehlgeschlagen
""",
                encoding="utf-8",
            )
            markers = detect_warning_markers(run_dir)

        self.assertIn("syntax", markers)

    def test_format_duration_uses_compact_units(self):
        self.assertEqual(format_duration(4.4), "4s")
        self.assertEqual(format_duration(64), "1m 4s")
        self.assertEqual(format_duration(3661), "1h 1m 1s")


# ── Cost-limit / runtime flag forwarding ──────────────────────────────────

def _has_pair(cmd: list[str], flag: str, value: str) -> bool:
    for i, token in enumerate(cmd):
        if token == flag and i + 1 < len(cmd) and cmd[i + 1] == value:
            return True
    return False


class OvernightCostLimitForwardingTests(unittest.TestCase):
    """Verify that run_overnight's parse_args accepts budget/runtime limits
    and forwards them through solver_commands.build_batch_command."""

    def test_parse_args_accepts_budget_flags(self):
        args = parse_args([
            "--model", "opencode",
            "--max-run-cost-usd", "5.0",
            "--max-run-input-tokens", "100000",
            "--max-run-output-tokens", "20000",
            "--skip-pull",
        ])
        self.assertEqual(args.max_run_cost_usd, 5.0)
        self.assertEqual(args.max_run_input_tokens, 100000)
        self.assertEqual(args.max_run_output_tokens, 20000)

    def test_parse_args_accepts_runtime_flags(self):
        args = parse_args([
            "--model", "opencode",
            "--max-run-runtime-seconds", "600",
            "--max-post-worker-runtime-seconds", "120",
            "--skip-pull",
        ])
        self.assertEqual(args.max_run_runtime_seconds, 600.0)
        self.assertEqual(args.max_post_worker_runtime_seconds, 120.0)

    def test_parse_args_omits_budget_flags_by_default(self):
        args = parse_args(["--model", "opencode", "--skip-pull"])
        self.assertIsNone(args.max_run_cost_usd)
        self.assertIsNone(args.max_run_input_tokens)
        self.assertIsNone(args.max_run_output_tokens)

    def test_parse_args_omits_runtime_flags_by_default(self):
        args = parse_args(["--model", "opencode", "--skip-pull"])
        self.assertIsNone(args.max_run_runtime_seconds)
        self.assertIsNone(args.max_post_worker_runtime_seconds)

    def test_build_batch_command_forwards_budget_flags(self):
        from solver_commands import build_batch_command

        args = parse_args([
            "--model", "opencode",
            "--max-run-cost-usd", "2.5",
            "--max-run-input-tokens", "50000",
            "--max-run-output-tokens", "10000",
            "--skip-pull",
        ])
        cmd = build_batch_command(args, Path("scripts/solve_issues_batch.py"))
        self.assertTrue(_has_pair(cmd, "--max-run-cost-usd", "2.5"))
        self.assertTrue(_has_pair(cmd, "--max-run-input-tokens", "50000"))
        self.assertTrue(_has_pair(cmd, "--max-run-output-tokens", "10000"))

    def test_build_batch_command_forwards_runtime_flags(self):
        from solver_commands import build_batch_command

        args = parse_args([
            "--model", "opencode",
            "--max-run-runtime-seconds", "900",
            "--max-post-worker-runtime-seconds", "180",
            "--skip-pull",
        ])
        cmd = build_batch_command(args, Path("scripts/solve_issues_batch.py"))
        self.assertTrue(_has_pair(cmd, "--max-run-runtime-seconds", "900.0"))
        self.assertTrue(_has_pair(cmd, "--max-post-worker-runtime-seconds", "180.0"))

    def test_build_batch_command_omits_limits_when_not_set(self):
        from solver_commands import build_batch_command

        args = parse_args(["--model", "opencode", "--skip-pull"])
        cmd = build_batch_command(args, Path("scripts/solve_issues_batch.py"))
        self.assertNotIn("--max-run-cost-usd", cmd)
        self.assertNotIn("--max-run-input-tokens", cmd)
        self.assertNotIn("--max-run-output-tokens", cmd)
        self.assertNotIn("--max-run-runtime-seconds", cmd)
        self.assertNotIn("--max-post-worker-runtime-seconds", cmd)


if __name__ == "__main__":
    unittest.main()
