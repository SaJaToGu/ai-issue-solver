import tempfile
import unittest
from datetime import datetime
from pathlib import Path

import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from status_dashboard import (  # noqa: E402
    classify_status,
    cleanup_stale_runs,
    github_links,
    read_runs,
    render_dashboard,
    write_dashboard,
)


class StatusDashboardTests(unittest.TestCase):
    def write_summary(self, run_dir: Path, content: str) -> None:
        run_dir.mkdir(parents=True)
        (run_dir / "summary.txt").write_text(content, encoding="utf-8")

    def test_classify_status_groups_known_solver_states(self):
        self.assertEqual(classify_status(""), "unknown")
        self.assertEqual(classify_status("started"), "running")
        self.assertEqual(classify_status("pr_created"), "successful")
        self.assertEqual(classify_status("pr_created_from_existing_branch"), "successful")
        self.assertEqual(classify_status("no_changes"), "noop")
        self.assertEqual(classify_status("skip_existing_pr"), "noop")
        self.assertEqual(classify_status("clone_failed"), "failed")
        self.assertEqual(classify_status("worker_finished", "2"), "failed")
        self.assertEqual(classify_status("archived"), "archived")
        self.assertEqual(classify_status("cleanup_successful"), "successful")
        self.assertEqual(classify_status("cleanup_noop"), "noop")
        self.assertEqual(classify_status("rate_limit_deferred"), "failed")

    def test_legacy_summary_without_status_is_unknown_not_running(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            runs_dir = Path(tmpdir) / "runs"
            self.write_summary(
                runs_dir / "20260521-004025-demo-issue-24",
                """repo: demo
issue: 24
model: codex
worker_exit_code: 0
""",
            )

            runs = read_runs(runs_dir)

        self.assertEqual(runs[0].status, "")
        self.assertEqual(runs[0].category, "unknown")

    def test_read_runs_parses_summary_and_multiline_output_tail(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            runs_dir = Path(tmpdir) / "reports" / "runs"
            self.write_summary(
                runs_dir / "20260521-090807-123456-demo-issue-25",
                """status: pr_created
repo: demo
issue_number: 25
issue_title: Show issue titles in the status dashboard
branch: ai/fix-issue-25
model: codex
worker_exit_code: 0
pr_url: https://github.com/test-owner/demo/pull/25

output_tail:
line 1
line 2
""",
            )

            runs = read_runs(runs_dir)

        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0].category, "successful")
        self.assertEqual(runs[0].created_at, datetime(2026, 5, 21, 9, 8, 7, 123456))
        self.assertEqual(runs[0].repo, "demo")
        self.assertEqual(runs[0].issue_number, "25")
        self.assertEqual(runs[0].issue_title, "Show issue titles in the status dashboard")
        self.assertEqual(runs[0].output_tail, "line 1\nline 2")

    def test_read_runs_keeps_legacy_reports_without_issue_title_compatible(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            runs_dir = Path(tmpdir) / "runs"
            self.write_summary(
                runs_dir / "20260521-090807-demo-issue-25",
                """status: pr_created
repo: demo
issue_number: 25
branch: ai/fix-issue-25
model: codex
worker_exit_code: 0
""",
            )

            runs = read_runs(runs_dir)

        self.assertEqual(runs[0].issue_number, "25")
        self.assertEqual(runs[0].issue_title, "")

    def test_github_links_use_owner_and_encode_branch_slashes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            runs_dir = Path(tmpdir) / "runs"
            self.write_summary(
                runs_dir / "20260521-090807-demo-issue-7",
                """status: started
repo: demo
issue_number: 7
branch: ai/fix-issue-7
model: claude
worker_exit_code:
pr_url:
""",
            )
            run = read_runs(runs_dir)[0]

        links = github_links(run, "test-owner")

        self.assertEqual(links["issue"], "https://github.com/test-owner/demo/issues/7")
        self.assertEqual(
            links["branch"],
            "https://github.com/test-owner/demo/tree/ai%2Ffix-issue-7",
        )

    def test_render_dashboard_contains_counts_and_available_links(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            runs_dir = Path(tmpdir) / "runs"
            output_path = Path(tmpdir) / "reports" / "status-dashboard.html"
            self.write_summary(
                runs_dir / "20260521-090807-demo-issue-25",
                """status: pr_created
repo: demo
issue_number: 25
issue_title: Fix <unsafe> & "quoted" dashboard title
branch: ai/fix-issue-25
model: codex
worker_exit_code: 0
pr_url: https://github.com/test-owner/demo/pull/25
""",
            )
            self.write_summary(
                runs_dir / "20260521-090908-demo-issue-26",
                """status: no_changes
repo: demo
issue_number: 26
branch: ai/fix-issue-26
model: codex
worker_exit_code: 0
pr_url:
""",
            )
            self.write_summary(
                runs_dir / "20260521-091009-demo-issue-27",
                """status: push_failed
repo: demo
issue_number: 27
branch: ai/fix-issue-27
model: codex
worker_exit_code: 0
pr_url:
preserved_worktree: reports/preserved-worktrees/run/demo
""",
            )
            runs = read_runs(runs_dir)

            html = render_dashboard(runs, "test-owner", output_path)
            write_dashboard(runs, output_path, owner="test-owner")
            output_exists = output_path.exists()

        self.assertIn("Successful", html)
        self.assertIn("No-op", html)
        self.assertIn("#25", html)
        self.assertIn("Fix &lt;unsafe&gt; &amp; &quot;quoted&quot; dashboard title", html)
        self.assertNotIn("Fix <unsafe>", html)
        self.assertIn("https://github.com/test-owner/demo/issues/26", html)
        self.assertIn("https://github.com/test-owner/demo/pull/25", html)
        self.assertIn("Recovery-Worktree", html)
        self.assertIn("reports/preserved-worktrees/run/demo", html)
        self.assertTrue(output_exists)

    def test_render_dashboard_can_include_shutdown_button(self):
        html = render_dashboard([], None, Path("reports/status-dashboard.html"), allow_shutdown=True)

        self.assertIn("Dashboard-Server beenden", html)
        self.assertIn("/__shutdown__", html)

    def test_render_dashboard_can_include_auto_refresh(self):
        html = render_dashboard(
            [],
            None,
            Path("reports/status-dashboard.html"),
            refresh_seconds=10,
        )

        self.assertIn('http-equiv="refresh"', html)
        self.assertIn('content="10"', html)
        self.assertIn("Auto-refresh: 10s", html)

    def test_cleanup_stale_runs_dry_run_does_not_edit_candidates(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            runs_dir = Path(tmpdir) / "runs"
            run_dir = runs_dir / "20260501-090807-demo-issue-27"
            self.write_summary(
                run_dir,
                """repo: demo
issue: 27
worker_exit_code:
""",
            )

            result = cleanup_stale_runs(
                runs_dir,
                mark="archived",
                older_than_days=7,
                apply=False,
                now_fn=lambda: datetime(2026, 5, 21, 12, 0, 0),
            )
            summary = (run_dir / "summary.txt").read_text(encoding="utf-8")

        self.assertEqual(len(result.candidates), 1)
        self.assertEqual(result.changed, [])
        self.assertNotIn("status: archived", summary)

    def test_cleanup_stale_runs_apply_marks_only_old_active_reports(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            runs_dir = Path(tmpdir) / "runs"
            old_run = runs_dir / "20260501-090807-demo-issue-28"
            fresh_run = runs_dir / "20260521-090807-demo-issue-29"
            done_run = runs_dir / "20260501-090807-demo-issue-30"
            self.write_summary(
                old_run,
                """status: started
repo: demo
issue_number: 28
worker_exit_code:
""",
            )
            self.write_summary(
                fresh_run,
                """status: started
repo: demo
issue_number: 29
worker_exit_code:
""",
            )
            self.write_summary(
                done_run,
                """status: pr_created
repo: demo
issue_number: 30
worker_exit_code: 0
""",
            )

            result = cleanup_stale_runs(
                runs_dir,
                mark="noop",
                older_than_days=7,
                apply=True,
                now_fn=lambda: datetime(2026, 5, 21, 12, 0, 0),
            )
            runs = {run.issue_number: run for run in read_runs(runs_dir)}

        self.assertEqual(len(result.candidates), 1)
        self.assertEqual(len(result.changed), 1)
        self.assertEqual(runs["28"].status, "cleanup_noop")
        self.assertEqual(runs["28"].category, "noop")
        self.assertEqual(runs["29"].status, "started")
        self.assertEqual(runs["30"].status, "pr_created")

    def test_cleanup_stale_runs_can_include_undated_reports_explicitly(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            runs_dir = Path(tmpdir) / "runs"
            undated_run = runs_dir / "legacy-demo-issue-31"
            self.write_summary(
                undated_run,
                """repo: demo
issue: 31
worker_exit_code:
""",
            )

            default_result = cleanup_stale_runs(
                runs_dir,
                now_fn=lambda: datetime(2026, 5, 21, 12, 0, 0),
            )
            explicit_result = cleanup_stale_runs(
                runs_dir,
                include_undated=True,
                now_fn=lambda: datetime(2026, 5, 21, 12, 0, 0),
            )

        self.assertEqual(default_result.candidates, [])
        self.assertEqual(len(explicit_result.candidates), 1)


if __name__ == "__main__":
    unittest.main()
