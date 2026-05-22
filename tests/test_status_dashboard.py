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
    enrich_runs_with_github,
    github_repo_api_path,
    github_links,
    read_runs,
    render_dashboard,
    write_dashboard,
)


class FakeLifecycleClient:
    def __init__(
        self,
        pull_requests=None,
        branch_pull_requests=None,
        issue_pull_requests=None,
        issues=None,
        main_contains=None,
        fail=False,
    ):
        self.pull_requests = pull_requests or {}
        self.branch_pull_requests = branch_pull_requests or {}
        self.issue_pull_requests = issue_pull_requests or {}
        self.issues = issues or {}
        self.main_contains = main_contains or set()
        self.fail = fail
        self.calls = 0
        self.seen_repos = []

    def _record(self, repo=None):
        self.calls += 1
        if repo:
            self.seen_repos.append(repo)
        if self.fail:
            raise RuntimeError("GitHub unavailable")

    def get_pull_request(self, repo, number):
        self._record(repo)
        return self.pull_requests.get(str(number))

    def get_pull_requests_for_branch(self, repo, branch):
        self._record(repo)
        return self.branch_pull_requests.get(branch, [])

    def get_pull_requests_for_issue(self, repo, issue_number):
        self._record(repo)
        return self.issue_pull_requests.get(str(issue_number), [])

    def get_issue(self, repo, issue_number):
        self._record(repo)
        return self.issues.get(str(issue_number))

    def branch_contains_commit(self, repo, branch, sha):
        self._record(repo)
        return (branch, sha) in self.main_contains


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
        self.assertEqual(classify_status("validation_failed"), "failed")

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
        self.assertIn("Lifecycle", html)
        self.assertIn("PR created", html)
        self.assertIn("Diff stat", html)
        self.assertIn("README.md | 1 +", html)
        self.assertIn("Recovery-Worktree", html)
        self.assertIn("reports/preserved-worktrees/run/demo", html)
        self.assertTrue(output_exists)

    def test_github_enrichment_marks_failed_preserved_run_as_recovered(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            runs_dir = Path(tmpdir) / "runs"
            self.write_summary(
                runs_dir / "20260521-090807-demo-issue-56",
                """status: rate_limit_deferred
repo: demo
issue_number: 56
branch: ai/fix-issue-56
base_branch: develop
worker_exit_code: 1
pr_url:
preserved_worktree: reports/preserved-worktrees/20260521-demo-issue-56
""",
            )
            pr = {
                "number": 61,
                "html_url": "https://github.com/test-owner/demo/pull/61",
                "state": "closed",
                "merged_at": "2026-05-21T10:00:00Z",
                "merge_commit_sha": "recover61",
                "base": {"ref": "develop"},
            }
            client = FakeLifecycleClient(
                branch_pull_requests={"ai/fix-issue-56": [pr]},
                issues={"56": {"state": "open"}},
            )

            result = enrich_runs_with_github(
                read_runs(runs_dir),
                "test-owner",
                "token",
                cache_path=Path(tmpdir) / "cache.json",
                client=client,
            )
            html = render_dashboard(result.runs, "test-owner", Path(tmpdir) / "status.html")

        self.assertTrue(result.used_github)
        self.assertEqual(result.runs[0].status, "rate_limit_deferred")
        self.assertEqual(result.runs[0].category, "recovered")
        self.assertEqual(result.runs[0].lifecycle_label, "Recovered to develop")
        self.assertIn("Original run failed; recovered via PR #61", result.runs[0].lifecycle_note)
        self.assertIn("Recovered", html)
        self.assertIn("rate_limit_deferred", html)
        self.assertIn("Original run failed; recovered via PR #61", html)
        self.assertIn("https://github.com/test-owner/demo/pull/61", html)

    def test_github_enrichment_recovers_failed_run_via_issue_pr_when_branch_lookup_misses(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            runs_dir = Path(tmpdir) / "runs"
            self.write_summary(
                runs_dir / "20260521-090807-demo-issue-62",
                """status: push_failed
repo: demo
issue_number: 62
branch: ai/fix-issue-62
worker_exit_code: 0
preserved_worktree: reports/preserved-worktrees/20260521-demo-issue-62
""",
            )
            pr = {
                "number": 63,
                "html_url": "https://github.com/test-owner/demo/pull/63",
                "state": "closed",
                "merged_at": "2026-05-21T11:00:00Z",
                "merge_commit_sha": "recover63",
                "base": {"ref": "develop"},
            }
            client = FakeLifecycleClient(
                branch_pull_requests={"ai/fix-issue-62": []},
                issue_pull_requests={"62": [pr]},
                issues={"62": {"state": "closed"}},
                main_contains={("main", "recover63")},
            )

            result = enrich_runs_with_github(
                read_runs(runs_dir),
                "test-owner",
                "token",
                cache_path=Path(tmpdir) / "cache.json",
                client=client,
            )

        self.assertEqual(result.runs[0].category, "recovered")
        self.assertEqual(result.runs[0].lifecycle_label, "Issue closed")
        self.assertFalse(result.runs[0].lifecycle_needs_attention)

    def test_github_enrichment_keeps_recoverable_failed_run_failed_when_api_fails(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            runs_dir = Path(tmpdir) / "runs"
            self.write_summary(
                runs_dir / "20260521-090807-demo-issue-56",
                """status: rate_limit_deferred
repo: demo
issue_number: 56
branch: ai/fix-issue-56
worker_exit_code: 1
preserved_worktree: reports/preserved-worktrees/20260521-demo-issue-56
""",
            )

            result = enrich_runs_with_github(
                read_runs(runs_dir),
                "test-owner",
                "token",
                cache_path=Path(tmpdir) / "cache.json",
                client=FakeLifecycleClient(fail=True),
            )
            html = render_dashboard(result.runs, "test-owner", Path(tmpdir) / "status.html")

        self.assertFalse(result.used_github)
        self.assertEqual(result.runs[0].category, "failed")
        self.assertEqual(result.runs[0].lifecycle_label, "")
        self.assertIn("Failed", html)
        self.assertNotIn("Original run failed; recovered", html)

    def test_render_dashboard_shows_lifecycle_fallback_without_github_data(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            runs_dir = Path(tmpdir) / "runs"
            self.write_summary(
                runs_dir / "20260521-090807-demo-issue-40",
                """status: pr_created
repo: demo
issue_number: 40
branch: ai/fix-issue-40
worker_exit_code: 0
pr_url: https://github.com/test-owner/demo/pull/40
""",
            )
            runs = read_runs(runs_dir)

            html = render_dashboard(runs, "test-owner", Path(tmpdir) / "status.html")

        self.assertIn("PR created", html)
        self.assertIn("GitHub-Status nicht geladen", html)
        self.assertIn("action", html)

    def test_github_enrichment_marks_open_pr_as_action_needed(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            runs_dir = Path(tmpdir) / "runs"
            self.write_summary(
                runs_dir / "20260521-090807-demo-issue-41",
                """status: pr_created
repo: demo
issue_number: 41
branch: ai/fix-issue-41
worker_exit_code: 0
pr_url: https://github.com/test-owner/demo/pull/41
""",
            )
            runs = read_runs(runs_dir)
            client = FakeLifecycleClient(
                pull_requests={
                    "41": {
                        "state": "open",
                        "merged_at": None,
                        "merge_commit_sha": "",
                    }
                },
                issues={"41": {"state": "open"}},
            )

            result = enrich_runs_with_github(
                runs,
                "test-owner",
                "token",
                cache_path=Path(tmpdir) / "cache.json",
                client=client,
            )

        self.assertTrue(result.used_github)
        self.assertEqual(result.runs[0].lifecycle_label, "PR open")
        self.assertTrue(result.runs[0].lifecycle_needs_attention)

    def test_github_enrichment_marks_merged_to_develop(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            runs_dir = Path(tmpdir) / "runs"
            self.write_summary(
                runs_dir / "20260521-090807-demo-issue-42",
                """status: pr_created
repo: demo
issue_number: 42
branch: ai/fix-issue-42
worker_exit_code: 0
pr_url: https://github.com/test-owner/demo/pull/42
""",
            )
            runs = read_runs(runs_dir)
            client = FakeLifecycleClient(
                pull_requests={
                    "42": {
                        "state": "closed",
                        "merged_at": "2026-05-21T10:00:00Z",
                        "merge_commit_sha": "abc123",
                        "base": {"ref": "develop"},
                    }
                },
                issues={"42": {"state": "open"}},
            )

            result = enrich_runs_with_github(
                runs,
                "test-owner",
                "token",
                cache_path=Path(tmpdir) / "cache.json",
                client=client,
            )

        self.assertEqual(result.runs[0].lifecycle_label, "Merged to develop")
        self.assertTrue(result.runs[0].lifecycle_needs_attention)

    def test_github_enrichment_keeps_closed_issue_action_needed_until_main_contains_merge(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            runs_dir = Path(tmpdir) / "runs"
            self.write_summary(
                runs_dir / "20260521-090807-demo-issue-48",
                """status: pr_created
repo: demo
issue_number: 48
branch: ai/fix-issue-48
worker_exit_code: 0
pr_url: https://github.com/test-owner/demo/pull/48
""",
            )
            runs = read_runs(runs_dir)
            client = FakeLifecycleClient(
                pull_requests={
                    "48": {
                        "state": "closed",
                        "merged_at": "2026-05-21T10:00:00Z",
                        "merge_commit_sha": "closed48",
                        "base": {"ref": "develop"},
                    }
                },
                issues={"48": {"state": "closed"}},
            )

            result = enrich_runs_with_github(
                runs,
                "test-owner",
                "token",
                cache_path=Path(tmpdir) / "cache.json",
                client=client,
            )

        self.assertEqual(result.runs[0].lifecycle_label, "Merged to develop")
        self.assertTrue(result.runs[0].lifecycle_needs_attention)
        self.assertIn("Issue ist geschlossen", result.runs[0].lifecycle_note)

    def test_github_enrichment_marks_main_and_closed_issue(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            runs_dir = Path(tmpdir) / "runs"
            self.write_summary(
                runs_dir / "20260521-090807-demo-issue-43",
                """status: pr_created
repo: demo
issue_number: 43
branch: ai/fix-issue-43
worker_exit_code: 0
pr_url: https://github.com/test-owner/demo/pull/43
""",
            )
            runs = read_runs(runs_dir)
            client = FakeLifecycleClient(
                pull_requests={
                    "43": {
                        "state": "closed",
                        "merged_at": "2026-05-21T10:00:00Z",
                        "merge_commit_sha": "def456",
                        "base": {"ref": "develop"},
                    }
                },
                issues={"43": {"state": "closed"}},
                main_contains={("main", "def456")},
            )

            result = enrich_runs_with_github(
                runs,
                "test-owner",
                "token",
                cache_path=Path(tmpdir) / "cache.json",
                client=client,
            )
            html = render_dashboard(result.runs, "test-owner", Path(tmpdir) / "status.html")

        self.assertEqual(result.runs[0].lifecycle_label, "Issue closed")
        self.assertFalse(result.runs[0].lifecycle_needs_attention)
        self.assertIn("Issue closed", html)

    def test_github_enrichment_marks_in_main_before_issue_is_closed(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            runs_dir = Path(tmpdir) / "runs"
            self.write_summary(
                runs_dir / "20260521-090807-demo-issue-46",
                """status: pr_created
repo: demo
issue_number: 46
branch: ai/fix-issue-46
worker_exit_code: 0
pr_url: https://github.com/test-owner/demo/pull/46
""",
            )
            runs = read_runs(runs_dir)
            client = FakeLifecycleClient(
                pull_requests={
                    "46": {
                        "state": "closed",
                        "merged_at": "2026-05-21T10:00:00Z",
                        "merge_commit_sha": "feed46",
                        "base": {"ref": "develop"},
                    }
                },
                issues={"46": {"state": "open"}},
                main_contains={("main", "feed46")},
            )

            result = enrich_runs_with_github(
                runs,
                "test-owner",
                "token",
                cache_path=Path(tmpdir) / "cache.json",
                client=client,
            )

        self.assertEqual(result.runs[0].lifecycle_label, "In main")
        self.assertTrue(result.runs[0].lifecycle_needs_attention)

    def test_github_enrichment_uses_cache_without_api_calls(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            runs_dir = Path(tmpdir) / "runs"
            cache_path = Path(tmpdir) / "cache.json"
            self.write_summary(
                runs_dir / "20260521-090807-demo-issue-44",
                """status: pr_created
repo: demo
issue_number: 44
branch: ai/fix-issue-44
worker_exit_code: 0
pr_url: https://github.com/test-owner/demo/pull/44
""",
            )
            cache_path.write_text(
                """{
  "entries": {
    "test-owner|demo|44|ai/fix-issue-44|https://github.com/test-owner/demo/pull/44": {
      "label": "In main",
      "state": "in-main",
      "needs_attention": false,
      "note": "cached"
    }
  }
}
""",
                encoding="utf-8",
            )
            client = FakeLifecycleClient(fail=True)

            result = enrich_runs_with_github(
                read_runs(runs_dir),
                "test-owner",
                "token",
                cache_path=cache_path,
                client=client,
            )

        self.assertTrue(result.used_cache)
        self.assertEqual(client.calls, 0)
        self.assertEqual(result.runs[0].lifecycle_label, "In main")

    def test_github_enrichment_falls_back_when_api_fails(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            runs_dir = Path(tmpdir) / "runs"
            self.write_summary(
                runs_dir / "20260521-090807-demo-issue-45",
                """status: pr_created
repo: demo
issue_number: 45
branch: ai/fix-issue-45
worker_exit_code: 0
pr_url: https://github.com/test-owner/demo/pull/45
""",
            )

            result = enrich_runs_with_github(
                read_runs(runs_dir),
                "test-owner",
                "token",
                cache_path=Path(tmpdir) / "cache.json",
                client=FakeLifecycleClient(fail=True),
            )

        self.assertFalse(result.used_github)
        self.assertEqual(result.runs[0].lifecycle_label, "PR created")
        self.assertIn("GitHub unavailable", result.error)

    def test_github_repo_api_path_uses_owner_from_full_repo_name(self):
        self.assertEqual(github_repo_api_path("other-owner/demo", "default-owner"), "/repos/other-owner/demo")
        self.assertEqual(github_repo_api_path("demo", "default-owner"), "/repos/default-owner/demo")

    def test_github_enrichment_preserves_full_repo_name_for_api_calls(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            runs_dir = Path(tmpdir) / "runs"
            self.write_summary(
                runs_dir / "20260521-090807-demo-issue-47",
                """status: pr_created
repo: other-owner/demo
issue_number: 47
branch: ai/fix-issue-47
worker_exit_code: 0
pr_url: https://github.com/other-owner/demo/pull/47
""",
            )
            client = FakeLifecycleClient(
                pull_requests={"47": {"state": "open", "merged_at": None, "merge_commit_sha": ""}},
                issues={"47": {"state": "open"}},
            )

            enrich_runs_with_github(
                read_runs(runs_dir),
                "default-owner",
                "token",
                cache_path=Path(tmpdir) / "cache.json",
                client=client,
            )

        self.assertIn("other-owner/demo", client.seen_repos)

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
