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
        self.assertEqual(classify_status("queued"), "queued")
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

    def test_read_runs_parses_diff_stat_before_output_tail(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            runs_dir = Path(tmpdir) / "reports" / "runs"
            self.write_summary(
                runs_dir / "20260521-090807-123456-demo-issue-25",
                """status: pr_created
repo: demo
issue_number: 25
worker_exit_code: 0

git_diff_stat:
Git-Änderungsübersicht:
  README.md | 1 +

output_tail:
line 1
line 2
""",
            )

            runs = read_runs(runs_dir)

        self.assertEqual(runs[0].git_diff_stat, "Git-Änderungsübersicht:\n  README.md | 1 +")
        self.assertEqual(runs[0].output_tail, "line 1\nline 2")

    def test_read_runs_parses_queued_reports(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            runs_dir = Path(tmpdir) / "runs"
            self.write_summary(
                runs_dir / "20260521-090807-123456-demo-issue-25",
                """status: queued
repo: demo
issue_number: 25
branch:
base_branch: main
model: codex
worker_exit_code:
queued_at: 2026-05-21T09:08:07

note: Batch-Job wartet auf einen freien Worker-Slot.
""",
            )

            runs = read_runs(runs_dir)

        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0].category, "queued")
        self.assertEqual(runs[0].repo, "demo")
        self.assertEqual(runs[0].issue_number, "25")
        self.assertEqual(runs[0].base_branch, "main")

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
git_diff_stat:
Git-Änderungsübersicht:
  README.md | 1 +
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
        self.assertIn("Queued", html)
        self.assertIn("No-op", html)
        self.assertIn("#25", html)
        self.assertIn("Fix &lt;unsafe&gt; &amp; &quot;quoted&quot; dashboard title", html)
        self.assertNotIn("Fix <unsafe>", html)
        self.assertIn("https://github.com/test-owner/demo/issues/26", html)
        self.assertIn("https://github.com/test-owner/demo/pull/25", html)
        self.assertIn("Diff stat", html)
        self.assertIn("README.md | 1 +", html)
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

    def test_read_runs_marks_running_run_unhealthy_after_timeout(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            runs_dir = Path(tmpdir) / "runs"
            self.write_summary(
                runs_dir / "20260521-090807-demo-issue-32",
                """status: started
repo: demo
issue_number: 32
worker_exit_code:
last_activity_at: 2026-05-21T09:00:00

output_tail:
Plan: started
""",
            )

            runs = read_runs(
                runs_dir,
                health_timeout_minutes=30,
                now_fn=lambda: datetime(2026, 5, 21, 10, 0, 0),
            )

        self.assertEqual(runs[0].category, "unhealthy")
        self.assertEqual(runs[0].health_status, "unhealthy")
        self.assertIn("Timeout 30 min", runs[0].health_reason)
        self.assertIn("worker-output.log", runs[0].recovery_hint)

    def test_read_runs_keeps_future_codex_rate_limit_wait_running(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            runs_dir = Path(tmpdir) / "runs"
            self.write_summary(
                runs_dir / "20260521-090807-demo-issue-33",
                """status: started
repo: demo
issue_number: 33
worker_exit_code:
last_activity_at: 2026-05-21T09:00:00

output_tail:
Your rate limit will be reset on May 21, 2026, at 11:00 AM.
""",
            )

            runs = read_runs(
                runs_dir,
                health_timeout_minutes=30,
                now_fn=lambda: datetime(2026, 5, 21, 10, 0, 0),
            )

        self.assertEqual(runs[0].category, "running")
        self.assertIn("Codex-Rate-Limit", runs[0].health_reason)

    def test_read_runs_marks_codex_rate_limit_without_future_reset_unhealthy(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            runs_dir = Path(tmpdir) / "runs"
            self.write_summary(
                runs_dir / "20260521-090807-demo-issue-34",
                """status: started
repo: demo
issue_number: 34
worker_exit_code:
last_activity_at: 2026-05-21T09:59:00

output_tail:
You have reached the Codex message limit.
""",
            )

            runs = read_runs(
                runs_dir,
                health_timeout_minutes=30,
                now_fn=lambda: datetime(2026, 5, 21, 10, 0, 0),
            )

        self.assertEqual(runs[0].category, "unhealthy")
        self.assertIn("ohne zukuenftige Reset-Zeit", runs[0].health_reason)

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
            queued_run = runs_dir / "20260501-090807-demo-issue-31"
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
            self.write_summary(
                queued_run,
                """status: queued
repo: demo
issue_number: 31
worker_exit_code:
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

        self.assertEqual(len(result.candidates), 2)
        self.assertEqual(len(result.changed), 2)
        self.assertEqual(runs["28"].status, "cleanup_noop")
        self.assertEqual(runs["28"].category, "noop")
        self.assertEqual(runs["29"].status, "started")
        self.assertEqual(runs["30"].status, "pr_created")
        self.assertEqual(runs["31"].status, "cleanup_noop")

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
