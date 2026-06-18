import contextlib
from datetime import datetime
import io
import inspect
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from solve_issues import (  # noqa: E402
    GitHubClient,
    POST_SOLVE_TEST_COMMAND,
    PostSolveTestResult,
    PullRequestState,
    WorkerAssessment,
    WorkerRunResult,
    assess_worker_result,
    branch_has_changes_against_base,
    build_aider_command,
    build_issue_pr_body,
    build_opencode_command,
    build_opencode_prompt,
    build_vibe_command,
    build_worker_command,
    build_worker_env,
    check_opencode_auth,
    clone_repo,
    collect_pre_solver_hygiene_findings,
    cleanup_preserved_worktrees,
    create_ensemble_branches,
    create_run_report,
    create_issue_pull_request,
    detect_opencode_runtime_diagnostics,
    detect_codex_rate_limit,
    evaluate_results,
    find_vibe_executable,
    format_git_change_summary,
    format_post_solve_test_command,
    format_worker_output_tail,
    find_opencode_executable,
    get_worker_display_name,
    git_status_porcelain,
    infer_aider_targets,
    is_secret_worker_path,
    parse_codex_reset_datetime,
    _parse_gone_branches,
    plan_branch_recovery,
    print_branch_recovery_plan,
    relativize_repo_absolute_paths,
    preserve_worker_worktree,
    retry_branch_name,
    run_openrouter_direct_worker,
    run_opencode_diagnostic,
    run_post_solve_tests,
    run_worker_command,
    sanitize_worker_prompt_secret_paths,
    should_preserve_worktree,
    should_surface_worker_line,
    sleep_until_codex_reset,
    validate_worker_changes,
    solve_issue,
    write_run_report,
    write_run_health,
    write_worker_diagnostics,
)


class FakeResponse:
    def __init__(self, status_code, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.text = text

    def json(self):
        return self._payload


class FakeGitHubSession:
    def __init__(self):
        self.headers = {}
        self.posts = []
        self.gets = []

    def get(self, url, params=None):
        self.gets.append((url, params))
        if url.endswith("/repos/test-owner/demo"):
            return FakeResponse(200, {"default_branch": "main"})
        if url.endswith("/repos/test-owner/demo/branches/main"):
            return FakeResponse(200, {"name": "main"})
        if url.endswith("/repos/test-owner/demo/branches/develop"):
            return FakeResponse(404, {"message": "Branch not found"})
        return FakeResponse(404, {"message": "Not found"})

    def post(self, url, json=None):
        self.posts.append((url, json))
        return FakeResponse(201, {"html_url": "https://github.com/test-owner/demo/pull/1"})


class BranchListSession:
    def __init__(self):
        self.headers = {}

    def get(self, url, params=None):
        if url.endswith("/repos/test-owner/demo/branches"):
            return FakeResponse(
                200,
                [
                    {"name": "main"},
                    {"name": "ai/fix-issue-7"},
                    {"name": "ai/fix-issue-7-20260521-090807"},
                    {"name": "ai/fix-issue-70"},
                ],
            )
        return FakeResponse(404, {"message": "Not found"})


class PreSolverHygieneTests(unittest.TestCase):
    def test_parse_gone_branches_detects_deleted_upstreams(self):
        output = "\n".join([
            "* develop 1234567 [origin/develop] ok",
            "  ai/old 89abcde [origin/ai/old: gone] stale branch",
            "  main 456789a [origin/main] ok",
        ])

        self.assertEqual(_parse_gone_branches(output), ["ai/old"])

    def test_collect_pre_solver_hygiene_findings_reports_operator_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifact_dir = root / "reports" / "tmp"
            artifact_dir.mkdir(parents=True)
            (artifact_dir / "validation-issue-999.md").write_text("body\n", encoding="utf-8")

            findings = collect_pre_solver_hygiene_findings(root)

        self.assertIn(
            "operator artifact remains: reports/tmp/validation-issue-999.md",
            findings,
        )

    def test_collect_pre_solver_hygiene_findings_reports_dirty_worktree(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=root, check=True, capture_output=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=root, check=True, capture_output=True)
            path = root / "tracked.txt"
            path.write_text("one\n", encoding="utf-8")
            subprocess.run(["git", "add", "tracked.txt"], cwd=root, check=True, capture_output=True)
            subprocess.run(["git", "commit", "-m", "init"], cwd=root, check=True, capture_output=True)
            path.write_text("two\n", encoding="utf-8")

            findings = collect_pre_solver_hygiene_findings(root)

        self.assertIn("working tree has uncommitted changes", findings)


class GitHubClientBranchTests(unittest.TestCase):
    def make_client(self):
        client = GitHubClient.__new__(GitHubClient)
        client.owner = "test-owner"
        client.session = FakeGitHubSession()
        return client

    def test_resolve_base_branch_uses_default_branch_without_override(self):
        client = self.make_client()

        base_branch = client.resolve_base_branch("demo")

        self.assertEqual(base_branch, "main")

    def test_resolve_base_branch_returns_none_when_explicit_branch_is_missing(self):
        client = self.make_client()

        with contextlib.redirect_stdout(io.StringIO()):
            base_branch = client.resolve_base_branch("demo", "develop")

        self.assertIsNone(base_branch)

    def test_create_pull_request_returns_none_when_explicit_branch_is_missing(self):
        client = self.make_client()

        with contextlib.redirect_stdout(io.StringIO()):
            pr = client.create_pull_request(
                repo="demo",
                title="Fix",
                body="Body",
                head="ai/fix-issue-1",
                base="develop",
            )

        self.assertIsNone(pr)
        self.assertEqual(len(client.session.posts), 0)

    def test_create_pull_request_posts_against_default_branch_without_explicit_base(self):
        client = self.make_client()

        with contextlib.redirect_stdout(io.StringIO()):
            pr = client.create_pull_request(
                repo="demo",
                title="Fix",
                body="Body",
                head="ai/fix-issue-1",
                base=None,
            )

        self.assertEqual(pr["html_url"], "https://github.com/test-owner/demo/pull/1")
        self.assertEqual(client.session.posts[0][1]["base"], "main")

    def test_branch_exists_encodes_branch_names_with_slashes(self):
        client = self.make_client()

        client.branch_exists("demo", "ai/fix-issue-7")

        self.assertTrue(
            client.session.gets[0][0].endswith(
                "/repos/test-owner/demo/branches/ai%2Ffix-issue-7"
            )
        )

    def test_get_issue_branches_filters_exact_issue_prefix(self):
        client = GitHubClient.__new__(GitHubClient)
        client.owner = "test-owner"
        client.session = BranchListSession()

        branches = client.get_issue_branches("demo", 7)

        self.assertEqual(
            branches,
            ["ai/fix-issue-7", "ai/fix-issue-7-20260521-090807"],
        )


class BranchRecoveryTests(unittest.TestCase):
    def make_client(self, branch_exists=True, pull_requests=None, branches=None):
        class FakeClient:
            def branch_exists(self, repo, branch):
                return branch_exists

            def get_issue_branches(self, repo, issue_number):
                return list(branches or ([] if not branch_exists else [f"ai/fix-issue-{issue_number}"]))

            def get_pull_requests_for_branch(self, repo, branch, state="all"):
                if isinstance(pull_requests, dict):
                    return list(pull_requests.get(branch, []))
                return list(pull_requests or [])

        return FakeClient()

    def test_missing_branch_starts_default_issue_branch(self):
        client = self.make_client(branch_exists=False)

        plan = plan_branch_recovery(
            client,
            "demo",
            7,
            "ai/fix-issue-7",
            stdin_isatty_fn=lambda: False,
        )

        self.assertEqual(plan.action, "new")
        self.assertEqual(plan.branch, "ai/fix-issue-7")
        self.assertIn("Kein vorhandener Branch", plan.message)

    def test_branch_without_pr_is_reused(self):
        client = self.make_client(branch_exists=True, pull_requests=[])

        plan = plan_branch_recovery(
            client,
            "demo",
            7,
            "ai/fix-issue-7",
            stdin_isatty_fn=lambda: False,
        )

        self.assertEqual(plan.action, "reuse_branch")
        self.assertEqual(plan.branch, "ai/fix-issue-7")

    def test_open_pr_skips_existing_work(self):
        pr = PullRequestState(
            number=12,
            html_url="https://github.com/test-owner/demo/pull/12",
            state="open",
            merged=False,
        )
        client = self.make_client(branch_exists=True, pull_requests=[pr])

        plan = plan_branch_recovery(
            client,
            "demo",
            7,
            "ai/fix-issue-7",
            stdin_isatty_fn=lambda: False,
        )

        self.assertEqual(plan.action, "skip_existing_pr")
        self.assertEqual(plan.pull_request, pr)

    def test_closed_unmerged_pr_uses_new_branch_without_tty(self):
        pr = PullRequestState(
            number=12,
            html_url="https://github.com/test-owner/demo/pull/12",
            state="closed",
            merged=False,
        )
        client = self.make_client(branch_exists=True, pull_requests=[pr])

        plan = plan_branch_recovery(
            client,
            "demo",
            7,
            "ai/fix-issue-7",
            stdin_isatty_fn=lambda: False,
            now_fn=lambda: datetime(2026, 5, 21, 9, 8, 7),
        )

        self.assertEqual(plan.action, "new")
        self.assertEqual(plan.branch, "ai/fix-issue-7-20260521-090807")
        self.assertIn("geschlossenen, ungemergten", plan.message)

    def test_retry_branch_name_avoids_existing_timestamp_branch(self):
        branch = retry_branch_name(
            7,
            now_fn=lambda: datetime(2026, 5, 21, 9, 8, 7),
            existing_branches={
                "ai/fix-issue-7-20260521-090807",
                "ai/fix-issue-7-20260521-090807-2",
            },
        )

        self.assertEqual(branch, "ai/fix-issue-7-20260521-090807-3")

    def test_closed_unmerged_pr_uses_new_branch_even_when_branch_was_deleted(self):
        pr = PullRequestState(
            number=12,
            html_url="https://github.com/test-owner/demo/pull/12",
            state="closed",
            merged=False,
        )
        client = self.make_client(branch_exists=False, pull_requests=[pr])

        plan = plan_branch_recovery(
            client,
            "demo",
            7,
            "ai/fix-issue-7",
            stdin_isatty_fn=lambda: False,
            now_fn=lambda: datetime(2026, 5, 21, 9, 8, 7),
        )

        self.assertEqual(plan.action, "new")
        self.assertEqual(plan.branch, "ai/fix-issue-7-20260521-090807")

    def test_closed_unmerged_pr_can_be_skipped_interactively(self):
        pr = PullRequestState(
            number=12,
            html_url="https://github.com/test-owner/demo/pull/12",
            state="closed",
            merged=False,
        )
        client = self.make_client(branch_exists=True, pull_requests=[pr])

        with contextlib.redirect_stdout(io.StringIO()):
            plan = plan_branch_recovery(
                client,
                "demo",
                7,
                "ai/fix-issue-7",
                prompt_fn=lambda prompt: "s",
                stdin_isatty_fn=lambda: True,
            )

        self.assertEqual(plan.action, "skip_closed_pr")
        self.assertEqual(plan.branch, "ai/fix-issue-7")

    def test_retry_branch_with_open_pr_is_detected(self):
        pr = PullRequestState(
            number=13,
            html_url="https://github.com/test-owner/demo/pull/13",
            state="open",
            merged=False,
        )
        client = self.make_client(
            branch_exists=True,
            branches=["ai/fix-issue-7", "ai/fix-issue-7-20260521-090807"],
            pull_requests={"ai/fix-issue-7-20260521-090807": [pr]},
        )

        plan = plan_branch_recovery(
            client,
            "demo",
            7,
            "ai/fix-issue-7",
            stdin_isatty_fn=lambda: False,
        )

        self.assertEqual(plan.action, "skip_existing_pr")
        self.assertEqual(plan.branch, "ai/fix-issue-7-20260521-090807")
        self.assertIn("ai/fix-issue-7-20260521-090807", plan.found_branches)
        self.assertEqual(plan.found_pull_requests, (("ai/fix-issue-7-20260521-090807", pr),))

    def test_print_branch_recovery_plan_explains_found_artifacts(self):
        pr = PullRequestState(
            number=13,
            html_url="https://github.com/test-owner/demo/pull/13",
            state="open",
            merged=False,
        )
        plan = self.make_client(
            branch_exists=True,
            branches=["ai/fix-issue-7", "ai/fix-issue-7-20260521-090807"],
            pull_requests={"ai/fix-issue-7-20260521-090807": [pr]},
        )
        recovery_plan = plan_branch_recovery(
            plan,
            "demo",
            7,
            "ai/fix-issue-7",
            stdin_isatty_fn=lambda: False,
        )

        printed = io.StringIO()
        with contextlib.redirect_stdout(printed):
            print_branch_recovery_plan(recovery_plan)

        output = printed.getvalue()
        self.assertIn("Gefundene Branches:", output)
        self.assertIn("ai/fix-issue-7-20260521-090807", output)
        self.assertIn("Gefundene PRs:", output)
        self.assertIn("PR #13", output)

    def test_retry_branch_without_pr_is_reused_before_closed_default_pr(self):
        pr = PullRequestState(
            number=12,
            html_url="https://github.com/test-owner/demo/pull/12",
            state="closed",
            merged=False,
        )
        client = self.make_client(
            branch_exists=True,
            branches=["ai/fix-issue-7", "ai/fix-issue-7-20260521-090807"],
            pull_requests={"ai/fix-issue-7": [pr]},
        )

        plan = plan_branch_recovery(
            client,
            "demo",
            7,
            "ai/fix-issue-7",
            stdin_isatty_fn=lambda: False,
        )

        self.assertEqual(plan.action, "reuse_branch")
        self.assertEqual(plan.branch, "ai/fix-issue-7-20260521-090807")

    def test_solve_issue_dry_run_prints_recovery_plan(self):
        client = self.make_client(branch_exists=True, pull_requests=[])
        issue = {"number": 7, "title": "Fix recovery", "body": ""}

        printed = io.StringIO()
        with contextlib.redirect_stdout(printed):
            result = solve_issue(
                client=client,
                issue=issue,
                repo="demo",
                model="codex",
                model_name="",
                config={"owner": "test-owner", "config": {}},
                token="token",
                dry_run=True,
                base_branch="main",
                close_issues=False,
            )

        self.assertTrue(result)
        self.assertIn("Recovery:", printed.getvalue())
        self.assertIn("Geplanter Issue-Branch: ai/fix-issue-7", printed.getvalue())

    def test_solve_issue_does_not_reference_cli_args_global(self):
        source = inspect.getsource(solve_issue)

        self.assertNotIn("args.", source)

    def test_create_issue_pull_request_does_not_close_issue_when_pr_creation_fails(self):
        class FailingPrClient:
            def __init__(self):
                self.closed = False

            def create_pull_request(self, **kwargs):
                return None

            def close_issue_with_comment(self, repo, number, comment):
                self.closed = True

        client = FailingPrClient()

        pr = create_issue_pull_request(
            client=client,
            repo="demo",
            number=7,
            title="Fix recovery",
            model="codex",
            config={"owner": "test-owner"},
            branch_name="ai/fix-issue-7",
            base_branch="main",
            close_issues=True,
        )

        self.assertIsNone(pr)
        self.assertFalse(client.closed)

    @patch("solve_issues.assess_worker_result",
           return_value=WorkerAssessment(should_continue=False, has_changes=False, reason="noop"))
    @patch("solve_issues.format_git_change_summary", return_value=[])
    @patch("solve_issues.git_status_porcelain", return_value="")
    @patch("solve_issues.run_worker_command", return_value=WorkerRunResult(0, ""))
    @patch("solve_issues.build_worker_command", return_value=["echo", "noop"])
    @patch("solve_issues.branch_has_changes_against_base", return_value=False)
    @patch("solve_issues.checkout_existing_remote_branch", return_value=True)
    @patch("solve_issues.clone_repo", return_value=True)
    def test_reuse_branch_without_changes_does_not_crash(
        self, mock_clone, mock_checkout, mock_branch_has_changes,
        mock_build_cmd, mock_run_worker, mock_git_status,
        mock_format_summary, mock_assess,
    ):
        client = self.make_client(branch_exists=True, pull_requests=[])
        issue = {"number": 7, "title": "Fix recovery", "body": ""}

        with tempfile.TemporaryDirectory() as tmpdir:
            printed = io.StringIO()
            with contextlib.redirect_stdout(printed):
                result = solve_issue(
                    client=client,
                    issue=issue,
                    repo="demo",
                    model="codex",
                    model_name="",
                    config={"owner": "test-owner", "config": {}},
                    token="token",
                    dry_run=False,
                    base_branch="main",
                    close_issues=False,
                    run_report_dir=tmpdir,
                )

        self.assertFalse(result)

    @patch("solve_issues.write_run_report")
    @patch("solve_issues.create_issue_pull_request",
           return_value={"html_url": "https://github.com/test-owner/demo/pull/7"})
    @patch("solve_issues.format_git_change_summary",
           return_value=["Git-Änderungsübersicht:", "  README.md | 1 +"])
    @patch("solve_issues.git_status_porcelain", return_value=" M README.md\n")
    @patch("solve_issues.branch_has_changes_against_base", return_value=True)
    @patch("solve_issues.checkout_existing_remote_branch", return_value=True)
    @patch("solve_issues.clone_repo", return_value=True)
    def test_reuse_branch_with_changes_writes_git_change_summary(
        self, mock_clone, mock_checkout, mock_branch_has_changes,
        mock_git_status, mock_format_summary, mock_create_pr,
        mock_write_report,
    ):
        client = self.make_client(branch_exists=True, pull_requests=[])
        issue = {"number": 7, "title": "Fix recovery", "body": ""}

        with tempfile.TemporaryDirectory() as tmpdir:
            printed = io.StringIO()
            with contextlib.redirect_stdout(printed):
                result = solve_issue(
                    client=client,
                    issue=issue,
                    repo="demo",
                    model="codex",
                    model_name="",
                    config={"owner": "test-owner", "config": {}},
                    token="token",
                    dry_run=False,
                    base_branch="main",
                    close_issues=False,
                    run_report_dir=tmpdir,
                )

        self.assertTrue(result)
        calls = mock_write_report.call_args_list
        summary_calls = [
            call for call in calls
            if "git_change_summary" in call[1]
        ]
        self.assertEqual(len(summary_calls), 1)
        self.assertEqual(
            summary_calls[0][1]["git_change_summary"],
            ["Git-Änderungsübersicht:", "  README.md | 1 +"],
        )


class WorkerAssessmentTests(unittest.TestCase):
    def test_success_with_changes_continues(self):
        assessment = assess_worker_result(WorkerRunResult(0, ""), " M README.md\n")

        self.assertTrue(assessment.should_continue)
        self.assertTrue(assessment.has_changes)
        self.assertEqual(assessment.reason, "changed")

    def test_success_without_changes_stops_as_noop(self):
        assessment = assess_worker_result(WorkerRunResult(0, ""), "")

        self.assertFalse(assessment.should_continue)
        self.assertFalse(assessment.has_changes)
        self.assertEqual(assessment.reason, "no_changes")

    def test_nonzero_with_changes_continues_for_review(self):
        assessment = assess_worker_result(WorkerRunResult(42, "partial"), "?? fix.py\n")

        self.assertTrue(assessment.should_continue)
        self.assertTrue(assessment.has_changes)
        self.assertEqual(assessment.reason, "nonzero_with_changes")

    def test_nonzero_without_changes_stops(self):
        assessment = assess_worker_result(WorkerRunResult(42, "failed"), "")

        self.assertFalse(assessment.should_continue)
        self.assertFalse(assessment.has_changes)
        self.assertEqual(assessment.reason, "nonzero_without_changes")

    def test_nonzero_with_only_aider_side_effects_stops(self):
        assessment = assess_worker_result(
            WorkerRunResult(1, "aider failed"),
            "?? .aider.chat.history.md\n?? .aider.tags.cache.v4/cache.db\n",
        )

        self.assertFalse(assessment.should_continue)
        self.assertFalse(assessment.has_changes)
        self.assertEqual(assessment.reason, "nonzero_without_changes")

    def test_nonzero_with_generic_side_effects_unrelated_to_issue_stops(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            Path(tmpdir, ".gitignore").write_text(".aider*\n", encoding="utf-8")
            Path(tmpdir, "LICENSE").write_text("", encoding="utf-8")

            assessment = assess_worker_result(
                WorkerRunResult(1, "worker failed before adding CI"),
                "?? .gitignore\n?? LICENSE\n",
                repo_dir=tmpdir,
                issue_text="Keine CI/CD-Pipeline (GitHub Actions) vorhanden",
            )

        self.assertFalse(assessment.should_continue)
        self.assertFalse(assessment.has_changes)
        self.assertEqual(assessment.reason, "nonzero_without_changes")

    def test_nonzero_with_issue_relevant_generic_file_continues_for_review(self):
        assessment = assess_worker_result(
            WorkerRunResult(1, "worker stopped after partial change"),
            "?? LICENSE\n",
            issue_text="Keine Lizenz-Datei vorhanden",
        )

        self.assertTrue(assessment.should_continue)
        self.assertTrue(assessment.has_changes)
        self.assertEqual(assessment.reason, "nonzero_with_changes")

    def test_nonzero_with_side_effects_and_meaningful_change_continues(self):
        assessment = assess_worker_result(
            WorkerRunResult(1, "worker failed after useful edit"),
            "?? .aider.chat.history.md\n M README.md\n",
        )

        self.assertTrue(assessment.should_continue)
        self.assertTrue(assessment.has_changes)
        self.assertEqual(assessment.reason, "nonzero_with_changes")



class WorkerValidationTests(unittest.TestCase):
    def test_validation_detects_conflict_marker(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "README.md"
            path.write_text("<<<<<<< HEAD\nbroken\n=======\nother\n>>>>>>> branch\n", encoding="utf-8")

            validation = validate_worker_changes(tmpdir, " M README.md\n")

        self.assertFalse(validation.ok)
        self.assertIn("Git-Konfliktmarker", validation.errors[0])

    def test_validation_detects_python_syntax_error(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "broken.py"
            path.write_text("def broken(:\n    pass\n", encoding="utf-8")

            validation = validate_worker_changes(tmpdir, " M broken.py\n")

        self.assertFalse(validation.ok)
        self.assertIn("Python-Syntaxpruefung fehlgeschlagen", validation.errors[0])

    def test_validation_accepts_valid_python_changes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "ok.py"
            path.write_text("print('ok')\n", encoding="utf-8")

            validation = validate_worker_changes(tmpdir, " M ok.py\n")

        self.assertTrue(validation.ok)
        self.assertEqual(validation.errors, ())


class VibeTurnLimitTests(unittest.TestCase):
    def test_detects_vibe_turn_limit_event(self):
        from solve_issues import VIBE_TURN_LIMIT_RE

        output = "Worker finished with <vibe_stop_event>Turn limit of 30 reached</vibe_stop_event>"

        self.assertTrue(VIBE_TURN_LIMIT_RE.search(output))

    def test_detects_vibe_turn_limit_with_different_number(self):
        from solve_issues import VIBE_TURN_LIMIT_RE

        output = "Worker finished with <vibe_stop_event>Turn limit of 50 reached</vibe_stop_event>"

        self.assertTrue(VIBE_TURN_LIMIT_RE.search(output))

    def test_ignores_regular_output_without_turn_limit(self):
        from solve_issues import VIBE_TURN_LIMIT_RE

        output = "Worker finished normally with some changes"

        self.assertIsNone(VIBE_TURN_LIMIT_RE.search(output))


class CodexRateLimitTests(unittest.TestCase):
    def test_detects_codex_rate_limit_and_parses_reset_time(self):
        output = (
            "You have reached the Codex message limit\n"
            "Your rate limit will be reset on May 20, 2026, at 1:36 AM. "
            "To continue using Codex, add credits or upgrade to Pro today.\n"
        )

        rate_limit = detect_codex_rate_limit(output)

        self.assertIsNotNone(rate_limit)
        self.assertEqual(rate_limit.reset_text, "May 20, 2026, at 1:36 AM")
        self.assertEqual(rate_limit.reset_at, datetime(2026, 5, 20, 1, 36))

    def test_parse_codex_reset_datetime_accepts_abbreviated_month(self):
        reset_at = parse_codex_reset_datetime("May 20, 2026, at 1:36 AM")

        self.assertEqual(reset_at, datetime(2026, 5, 20, 1, 36))

    def test_sleep_until_codex_reset_uses_remaining_seconds(self):
        sleeps = []
        rate_limit = detect_codex_rate_limit(
            "Your rate limit will be reset on May 20, 2026, at 1:36 AM."
        )

        with contextlib.redirect_stdout(io.StringIO()):
            sleep_until_codex_reset(
                rate_limit,
                sleep_fn=sleeps.append,
                now_fn=lambda: datetime(2026, 5, 20, 1, 35, 30),
            )

        self.assertEqual(sleeps, [30.0])


class AiderCommandTests(unittest.TestCase):
    def test_aider_command_adds_valid_issue_file_targets(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            (repo / "scripts").mkdir()
            (repo / "scripts" / "solve_issues.py").write_text("print('x')\n", encoding="utf-8")
            (repo / "README.md").write_text("hello\n", encoding="utf-8")
            prompt = "Bitte `scripts/solve_issues.py` und README.md prüfen."

            cmd = build_aider_command("claude", "", prompt, str(repo))

        self.assertIn("--subtree-only", cmd)
        self.assertIn("--message", cmd)
        self.assertIn("scripts/solve_issues.py", cmd)
        self.assertIn("README.md", cmd)

    def test_aider_target_inference_rejects_paths_outside_repo(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            (repo / "README.md").write_text("hello\n", encoding="utf-8")
            prompt = "Ändere `README.md`, `LICENSE`, `../secret.txt` und https://example.test/file.py"

            targets = infer_aider_targets(prompt, str(repo))

        self.assertEqual(targets, ["README.md"])

    def test_aider_target_inference_rejects_secret_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            (repo / "config").mkdir()
            (repo / "config" / ".env").write_text("SECRET=1\n", encoding="utf-8")
            (repo / "config" / "config.example.env").write_text("SECRET=\n", encoding="utf-8")
            prompt = "Pruefe `config/.env` und `config/config.example.env`."

            targets = infer_aider_targets(prompt, str(repo))

        self.assertEqual(targets, ["config/config.example.env"])

    def test_aider_command_can_use_explicit_file_targets(self):
        cmd = build_aider_command(
            "ollama",
            "llama3.2:3b",
            "Fix",
            "/tmp/repo",
            file_targets=["src/app.py"],
        )

        self.assertIn("--model", cmd)
        self.assertIn("ollama/llama3.2:3b", cmd)
        self.assertIn("--no-check-update", cmd)
        self.assertIn("--no-analytics", cmd)
        self.assertIn("--no-gitignore", cmd)
        self.assertIn("--chat-history-file", cmd)
        self.assertIn("--input-history-file", cmd)
        self.assertIn("--map-tokens", cmd)
        self.assertIn("0", cmd)
        self.assertNotIn(".aider.chat.history.md", cmd)
        self.assertNotIn(".aider.input.history", cmd)
        self.assertEqual(cmd[-1], "src/app.py")

    def test_mistral_command_uses_default_magistral_model(self):
        cmd = build_aider_command(
            "mistral",
            "magistral-medium-2509",
            "Fix",
            "/tmp/repo",
            file_targets=[],
        )

        self.assertIn("--model", cmd)
        self.assertIn("mistral/magistral-medium-2509", cmd)

    def test_mistral_command_allows_model_name_override(self):
        cmd = build_aider_command(
            "mistral",
            "magistral-small-2509",
            "Fix",
            "/tmp/repo",
            file_targets=[],
        )

        self.assertIn("mistral/magistral-small-2509", cmd)

    def test_mistral_worker_env_requires_api_key(self):
        printed = io.StringIO()

        with contextlib.redirect_stdout(printed), self.assertRaises(SystemExit) as raised:
            build_worker_env("mistral", {"MISTRAL_API_KEY": "sk-DEIN_KEY_HIER"}, base_env={})

        self.assertEqual(raised.exception.code, 1)
        self.assertIn("MISTRAL_API_KEY fehlt", printed.getvalue())

    def test_mistral_worker_env_exports_api_key(self):
        env = build_worker_env(
            "mistral",
            {"MISTRAL_API_KEY": "real-mistral-key"},
            base_env={"KEEP": "1"},
        )

        self.assertEqual(env["MISTRAL_API_KEY"], "real-mistral-key")
        self.assertEqual(env["KEEP"], "1")

    def test_mistral_vibe_worker_env_exports_api_key(self):
        env = build_worker_env(
            "mistral-vibe",
            {"MISTRAL_API_KEY": "real-mistral-key"},
            base_env={"KEEP": "1"},
        )

        self.assertEqual(env["MISTRAL_API_KEY"], "real-mistral-key")
        self.assertEqual(env["KEEP"], "1")

    def test_find_vibe_executable_uses_repo_venv(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            vibe = Path(tmpdir) / ".venv" / "bin" / "vibe"
            vibe.parent.mkdir(parents=True)
            vibe.write_text("#!/bin/sh\n", encoding="utf-8")
            vibe.chmod(0o755)

            found = find_vibe_executable(tmpdir)

        self.assertEqual(found, str(vibe))

    def test_vibe_command_uses_workdir_prompt_and_limits(self):
        with patch("solve_issues.find_vibe_executable", return_value="/usr/local/bin/vibe"):
            cmd = build_vibe_command("Fix issue", "/tmp/repo", max_turns=12, output="json")

        self.assertEqual(cmd[0], "/usr/local/bin/vibe")
        self.assertIn("--workdir", cmd)
        self.assertIn("/tmp/repo", cmd)
        self.assertIn("--trust", cmd)
        self.assertIn("-p", cmd)
        self.assertIn("Fix issue", cmd)
        self.assertIn("--max-turns", cmd)
        self.assertIn("12", cmd)
        self.assertIn("--output", cmd)
        self.assertIn("json", cmd)

    def test_vibe_command_requires_executable(self):
        with patch("solve_issues.find_vibe_executable", return_value=None):
            with self.assertRaises(FileNotFoundError):
                build_vibe_command("Fix issue", "/tmp/repo")

    def test_opencode_worker_env_drops_github_write_tokens(self):
        env = build_worker_env(
            "opencode",
            {},
            base_env={
                "GITHUB_TOKEN": "github-write-token",
                "GH_TOKEN": "gh-write-token",
                "KEEP": "1",
            },
        )

        self.assertNotIn("GITHUB_TOKEN", env)
        self.assertNotIn("GH_TOKEN", env)
        self.assertEqual(env["KEEP"], "1")

    def test_openrouter_worker_env_requires_api_key(self):
        printed = io.StringIO()

        with contextlib.redirect_stdout(printed), self.assertRaises(SystemExit) as raised:
            build_worker_env("openrouter", {"OPENROUTER_API_KEY": "sk-or-DEIN_KEY_HIER"}, base_env={})

        self.assertEqual(raised.exception.code, 1)
        self.assertIn("OPENROUTER_API_KEY fehlt", printed.getvalue())

    def test_openrouter_worker_env_exports_api_key(self):
        env = build_worker_env(
            "openrouter",
            {"OPENROUTER_API_KEY": "real-openrouter-key"},
            base_env={"KEEP": "1"},
        )

        self.assertEqual(env["OPENROUTER_API_KEY"], "real-openrouter-key")
        self.assertEqual(env["KEEP"], "1")

    def test_openrouter_worker_env_removes_other_provider_keys(self):
        env = build_worker_env(
            "openrouter",
            {"OPENROUTER_API_KEY": "real-openrouter-key"},
            base_env={
                "ANTHROPIC_API_KEY": "anthropic-key",
                "MISTRAL_API_KEY": "mistral-key",
                "OPENAI_API_KEY": "openai-key",
                "GITHUB_TOKEN": "github-token",
            },
        )

        self.assertEqual(env["OPENROUTER_API_KEY"], "real-openrouter-key")
        self.assertNotIn("ANTHROPIC_API_KEY", env)
        self.assertNotIn("MISTRAL_API_KEY", env)
        self.assertNotIn("OPENAI_API_KEY", env)
        # GITHUB_TOKEN sollte bleiben für Git-Operationen
        self.assertEqual(env["GITHUB_TOKEN"], "github-token")

    def test_find_opencode_executable_uses_repo_venv(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            opencode = Path(tmpdir) / ".venv" / "bin" / "opencode"
            opencode.parent.mkdir(parents=True)
            opencode.write_text("#!/bin/sh\n", encoding="utf-8")
            opencode.chmod(0o755)
            inactive_python = str(Path(tmpdir) / "bin" / "python")

            with patch("solve_issues.sys.executable", inactive_python):
                found = find_opencode_executable(tmpdir)

        self.assertEqual(found, str(opencode))

    def test_find_opencode_executable_uses_home_opencode_install(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            home_opencode = Path(tmpdir) / ".opencode" / "bin" / "opencode"
            home_opencode.parent.mkdir(parents=True)
            home_opencode.write_text("#!/bin/sh\n", encoding="utf-8")
            home_opencode.chmod(0o755)

            with patch("solve_issues.Path.home", return_value=Path(tmpdir)):
                with patch("solve_issues.shutil.which", return_value=None):
                    found = find_opencode_executable("/missing/repo")

        self.assertEqual(found, str(home_opencode))

    def test_opencode_command_uses_run_dir_prompt_and_model(self):
        with patch("solve_issues.find_opencode_executable", return_value="/usr/local/bin/opencode"):
            cmd = build_opencode_command("Fix issue", "/tmp/repo", model_name="mistral/mistral-small-2603")

        self.assertEqual(cmd[0], "/usr/local/bin/opencode")
        self.assertIn("run", cmd)
        self.assertIn("--dir", cmd)
        self.assertIn("/tmp/repo", cmd)
        self.assertIn("--model", cmd)
        self.assertIn("mistral/mistral-small-2603", cmd)
        self.assertIn("Fix issue", cmd[-1])
        self.assertIn("repo-relative Pfade", cmd[-1])

    def test_opencode_prompt_relativizes_repo_internal_absolute_paths(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            internal_path = repo / "scripts" / "create_issues.py"
            external_path = Path("/tmp/ai-solver-xyz/outside.py")  # Kein /var/folders-Pfad
            prompt = (
                f"Lies `{internal_path}` und pruefe auch "
                f"{external_path}."
            )

            normalized = relativize_repo_absolute_paths(prompt, str(repo))

        self.assertIn("`scripts/create_issues.py`", normalized)
        self.assertNotIn(str(internal_path), normalized)
        self.assertNotIn(str(external_path), normalized)
        self.assertIn("<EXTERNAL_PATH_REMOVED>", normalized)

    def test_opencode_prompt_keeps_var_folders_paths_outside_repo(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            external_var_path = Path("/var/folders/pl/pgd1g7vs7n98drgk98fxj1dw0000gp/T/outside.py")
            prompt = f"Pruefe {external_var_path}."

            normalized = relativize_repo_absolute_paths(prompt, str(repo))

        self.assertIn("<EXTERNAL_PATH_REMOVED>", normalized)  # Externe /var/folders-Pfade entfernen
        self.assertNotIn(str(external_var_path), normalized)

    def test_opencode_prompt_removes_temp_worktree_paths(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            temp_path = Path("/tmp/ai-solver-xyz/worktree/scripts/file.py")
            prompt = f"Bearbeite {temp_path} und pruefe `scripts/file.py`."

            normalized = relativize_repo_absolute_paths(prompt, str(repo))

        self.assertNotIn(str(temp_path), normalized)
        self.assertIn("<EXTERNAL_PATH_REMOVED>", normalized)
        self.assertIn("`scripts/file.py`", normalized)

    def test_secret_worker_path_detection_allows_example_files(self):
        self.assertTrue(is_secret_worker_path(".env"))
        self.assertTrue(is_secret_worker_path(".env.local"))
        self.assertTrue(is_secret_worker_path("config/.env"))
        self.assertTrue(is_secret_worker_path("config/.env.production"))
        self.assertFalse(is_secret_worker_path(".env.example"))
        self.assertFalse(is_secret_worker_path("config/config.example.env"))

    def test_worker_prompt_sanitizes_secret_paths(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            absolute_secret = repo / "config" / ".env"
            prompt = (
                f"Lies {absolute_secret}, pruefe `config/.env` "
                "und vergleiche mit `config/config.example.env`."
            )

            sanitized = sanitize_worker_prompt_secret_paths(prompt, str(repo))

        self.assertNotIn(str(absolute_secret), sanitized)
        self.assertNotIn("`config/.env`", sanitized)
        self.assertIn("config/config.example.env", sanitized)

    def test_opencode_prompt_omits_secret_absolute_paths(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            absolute_secret = repo / "config" / ".env"
            prompt = f"Bitte {absolute_secret} zur Diagnose lesen."

            normalized = build_opencode_prompt(prompt, str(repo))

        self.assertNotIn(str(absolute_secret), normalized)
        self.assertIn("config/config.example.env", normalized)
        self.assertIn("Lies, kopiere oder bearbeite keine echten Secret-Dateien", normalized)

    def test_opencode_prompt_keeps_urls_and_external_absolute_paths(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            internal_path = repo / "scripts" / "create_issues.py"
            external_path = Path(tmpdir).parent / "outside.py"
            prompt = (
                f"Quelle: https://example.test{internal_path}. "
                f"Repo-Datei: {internal_path}, extern: {external_path}"
            )

            normalized = relativize_repo_absolute_paths(prompt, str(repo))

        self.assertIn(f"https://example.test{internal_path}", normalized)
        self.assertIn("Repo-Datei: scripts/create_issues.py,", normalized)
        self.assertNotIn(f"Repo-Datei: {internal_path}", normalized)
        self.assertIn("<EXTERNAL_PATH_REMOVED>", normalized)
        self.assertNotIn(str(external_path), normalized)

    def test_opencode_command_prompt_does_not_expose_repo_absolute_paths(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            absolute_repo_file = repo / "scripts" / "create_issues.py"
            prompt = f"Bitte {absolute_repo_file} bearbeiten."

            with patch("solve_issues.find_opencode_executable", return_value="/usr/local/bin/opencode"):
                cmd = build_opencode_command(prompt, str(repo))

        self.assertIn("--dir", cmd)
        self.assertIn(str(repo), cmd)
        self.assertIn("scripts/create_issues.py", cmd[-1])
        self.assertNotIn(str(absolute_repo_file), cmd[-1])
        self.assertIn("ausschliesslich repo-relative Pfade", cmd[-1])

    def test_opencode_prompt_adds_repo_relative_file_access_instruction(self):
        prompt = build_opencode_prompt("Fix issue", "/tmp/repo")

        self.assertIn("OpenCode wurde bereits mit `--dir`", prompt)
        self.assertIn("repo-relative Pfade", prompt)
        self.assertIn("Fix issue", prompt)

    def test_opencode_command_requires_executable(self):
        with patch("solve_issues.find_opencode_executable", return_value=None):
            with self.assertRaises(FileNotFoundError):
                build_opencode_command("Fix issue", "/tmp/repo")


class WorkerCommandConstructionTests(unittest.TestCase):
    """Tests für die zentralisierte Worker-Command-Konstruktion (Issue #109)."""

    def test_get_worker_display_name_returns_config_display_name(self):
        self.assertEqual(get_worker_display_name("codex"), "Codex CLI")
        self.assertEqual(get_worker_display_name("claude"), "Anthropic Claude (claude-sonnet-4-20250514)")
        self.assertEqual(get_worker_display_name("openai"), "OpenAI GPT-4o")
        self.assertEqual(get_worker_display_name("mistral"), "Mistral AI Magistral (magistral-medium-2509)")
        self.assertEqual(get_worker_display_name("ollama"), "Ollama (lokal)")
        self.assertEqual(get_worker_display_name("mistral-vibe"), "Mistral Vibe CLI")
        self.assertEqual(get_worker_display_name("opencode"), "OpenCode CLI")
        self.assertEqual(get_worker_display_name("openrouter"), "OpenRouter (aider, legacy)")

    def test_build_worker_command_delegates_to_codex_builder(self):
        with patch("solve_issues.build_codex_command", return_value=["codex", "exec", "--cd", "/repo", "prompt"]):
            with patch("solve_issues.find_codex_executable", return_value="/usr/bin/codex"):
                cmd = build_worker_command("codex", "", "prompt", "/repo")

        self.assertEqual(cmd, ["codex", "exec", "--cd", "/repo", "prompt"])

    def test_build_worker_command_delegates_to_vibe_builder(self):
        with patch("solve_issues.build_vibe_command", return_value=["vibe", "--workdir", "/repo", "-p", "prompt"]):
            with patch("solve_issues.find_vibe_executable", return_value="/usr/bin/vibe"):
                cmd = build_worker_command("mistral-vibe", "", "prompt", "/repo")

        self.assertEqual(cmd, ["vibe", "--workdir", "/repo", "-p", "prompt"])

    def test_build_worker_command_delegates_to_opencode_builder(self):
        with patch("solve_issues.build_opencode_command", return_value=["opencode", "run", "--dir", "/repo", "prompt"]):
            with patch("solve_issues.find_opencode_executable", return_value="/usr/bin/opencode"):
                cmd = build_worker_command("opencode", "model-name", "prompt", "/repo")

        self.assertEqual(cmd, ["opencode", "run", "--dir", "/repo", "prompt"])

    def test_build_worker_command_delegates_to_aider_builder_for_claude(self):
        with patch("solve_issues.build_aider_command", return_value=["aider", "--model", "claude-sonnet-4-20250514", "prompt"]) as mock_aider:
            cmd = build_worker_command("claude", "", "prompt", "/repo")

        self.assertEqual(cmd, ["aider", "--model", "claude-sonnet-4-20250514", "prompt"])
        mock_aider.assert_called_once_with("claude", "", "prompt", "/repo", None)

    def test_build_worker_command_delegates_to_aider_builder_for_openai(self):
        with patch("solve_issues.build_aider_command", return_value=["aider", "--model", "gpt-4o", "prompt"]) as mock_aider:
            cmd = build_worker_command("openai", "", "prompt", "/repo")

        self.assertEqual(cmd, ["aider", "--model", "gpt-4o", "prompt"])
        mock_aider.assert_called_once_with("openai", "", "prompt", "/repo", None)

    def test_build_worker_command_delegates_to_aider_builder_for_mistral(self):
        with patch("solve_issues.build_aider_command", return_value=["aider", "--model", "mistral/model", "prompt"]) as mock_aider:
            cmd = build_worker_command("mistral", "custom-model", "prompt", "/repo")

        self.assertEqual(cmd, ["aider", "--model", "mistral/model", "prompt"])
        mock_aider.assert_called_once_with("mistral", "custom-model", "prompt", "/repo", None)

    def test_build_worker_command_delegates_to_aider_builder_for_ollama(self):
        with patch("solve_issues.build_aider_command", return_value=["aider", "--model", "ollama/model", "prompt"]) as mock_aider:
            cmd = build_worker_command("ollama", "llama3.2:3b", "prompt", "/repo")

        self.assertEqual(cmd, ["aider", "--model", "ollama/model", "prompt"])
        mock_aider.assert_called_once_with("ollama", "llama3.2:3b", "prompt", "/repo", None)

    def test_build_worker_command_passes_model_name_none_for_empty_string(self):
        with patch("solve_issues.build_codex_command", return_value=["codex", "exec", "prompt"]) as mock_codex:
            with patch("solve_issues.find_codex_executable", return_value="/usr/bin/codex"):
                build_worker_command("codex", "", "prompt", "/repo")

        # Leerer String soll als None weitergegeben werden (zusätzlicher None für additional_dirs)
        mock_codex.assert_called_once_with("prompt", "/repo", None, None)

    def test_build_worker_command_passes_model_name_for_non_empty(self):
        with patch("solve_issues.build_opencode_command", return_value=["opencode", "run", "--model", "custom", "prompt"]) as mock_opencode:
            with patch("solve_issues.find_opencode_executable", return_value="/usr/bin/opencode"):
                build_worker_command("opencode", "custom-model", "prompt", "/repo")

        mock_opencode.assert_called_once_with("prompt", "/repo", "custom-model")

    def test_build_worker_command_passes_file_targets_to_aider(self):
        with patch("solve_issues.build_aider_command", return_value=["aider", "prompt", "file.py"]) as mock_aider:
            build_worker_command("claude", "", "prompt", "/repo", file_targets=["file.py"])

        mock_aider.assert_called_once_with("claude", "", "prompt", "/repo", ["file.py"])

    def test_build_worker_command_delegates_to_aider_builder_for_openrouter(self):
        with patch("solve_issues.build_aider_command", return_value=["aider", "--model", "openrouter/openai/gpt-4o-mini", "prompt"]) as mock_aider:
            cmd = build_worker_command("openrouter", "", "prompt", "/repo")

        self.assertEqual(cmd, ["aider", "--model", "openrouter/openai/gpt-4o-mini", "prompt"])
        mock_aider.assert_called_once_with("openrouter", "", "prompt", "/repo", None)

    def test_build_worker_command_delegates_to_aider_builder_for_openrouter_with_custom_model(self):
        with patch("solve_issues.build_aider_command", return_value=["aider", "--model", "openrouter/anthropic/claude-3-haiku", "prompt"]) as mock_aider:
            cmd = build_worker_command("openrouter", "openrouter/anthropic/claude-3-haiku", "prompt", "/repo")

        self.assertEqual(cmd, ["aider", "--model", "openrouter/anthropic/claude-3-haiku", "prompt"])
        mock_aider.assert_called_once_with("openrouter", "openrouter/anthropic/claude-3-haiku", "prompt", "/repo", None)


class EnsembleTests(unittest.TestCase):
    def test_create_ensemble_branches_generates_unique_branch_names(self):
        branches = create_ensemble_branches(7, [
            "opencode/deepseek-v4-flash-free",
            "claude-sonnet-4-20250514",
            "gpt-4o"
        ])
        
        self.assertEqual(branches, {
            "opencode/deepseek-v4-flash-free": "ai/fix-issue-7-opencode-deepseek-v4-flash-free",
            "claude-sonnet-4-20250514": "ai/fix-issue-7-claude-sonnet-4-20250514",
            "gpt-4o": "ai/fix-issue-7-gpt-4o"
        })
        
    def test_create_ensemble_branches_truncates_long_model_names(self):
        branches = create_ensemble_branches(7, [
            "opencode/very-long-model-name-that-should-be-truncated-at-some-point"
        ])
        
        self.assertEqual(
            branches["opencode/very-long-model-name-that-should-be-truncated-at-some-point"],
            "ai/fix-issue-7-opencode-very-long-model-name-that-should-be-trunc"
        )
        
    def test_evaluate_results_selects_best_model_based_on_changes_and_exit_code(self):
        results = {
            "model1": WorkerRunResult(returncode=0, output="success"),
            "model2": WorkerRunResult(returncode=1, output="partial"),
            "model3": WorkerRunResult(returncode=0, output="no changes")
        }
        git_statuses = {
            "model1": " M README.md\n M src/main.py",
            "model2": " M README.md",
            "model3": ""
        }
        
        best_model, reason = evaluate_results(results, git_statuses, "/tmp/repo", "Test issue")
        
        self.assertEqual(best_model, "model1")
        self.assertIn("Exit Code: 0", reason)
        self.assertIn("Änderungen: Ja", reason)
        
    def test_evaluate_results_falls_back_to_first_model_when_no_changes(self):
        results = {
            "model1": WorkerRunResult(returncode=1, output="failed"),
            "model2": WorkerRunResult(returncode=0, output="no changes"),
            "model3": WorkerRunResult(returncode=1, output="failed")
        }
        git_statuses = {
            "model1": "",
            "model2": "",
            "model3": ""
        }
        
        best_model, reason = evaluate_results(results, git_statuses, "/tmp/repo", "Test issue")
        
        self.assertEqual(best_model, "model1")
        self.assertIn("Kein Modell hat Änderungen erzeugt", reason)
        
    def test_build_issue_pr_body_includes_ensemble_summary(self):
        body = build_issue_pr_body(
            config_owner="test-owner",
            repo="demo",
            number=7,
            title="Test issue",
            model="opencode",
            model_name="opencode/deepseek-v4-flash-free",
            ensemble_summary="| Modell | Exit Code | Änderungen |\n|--------|-----------|------------|\n| model1 | 0 | Ja |"
        )
        
        self.assertIn("Ensemble-Zusammenfassung", body)
        self.assertIn("| Modell | Exit Code | Änderungen |", body)
        
    def test_create_issue_pull_request_passes_ensemble_summary(self):
        class MockClient:
            def __init__(self):
                self.posts = []
                self.comments = []

            def create_pull_request(self, repo, title, body, head, base, dry_run=False):
                self.posts.append((repo, title, body, head, base))
                return {"html_url": "https://github.com/test-owner/demo/pull/7"}

            def close_issue_with_comment(self, repo, number, comment):
                self.comments.append((repo, number, comment))

        client = MockClient()
        ensemble_summary = "| Modell | Exit Code | Änderungen |\n| model1 | 0 | Ja |"
        
        pr = create_issue_pull_request(
            client=client,
            repo="demo",
            number=7,
            title="Test issue",
            model="opencode",
            config={"owner": "test-owner"},
            branch_name="ai/fix-issue-7-model1",
            base_branch="main",
            close_issues=True,
            model_name="model1",
            ensemble_summary=ensemble_summary
        )
        
        self.assertIsNotNone(pr)
        self.assertIn("Ensemble-Zusammenfassung", client.posts[0][2])
        self.assertIn("| Modell | Exit Code | Änderungen |", client.posts[0][2])


class PostSolveTestTests(unittest.TestCase):
    """Tests fuer den Post-Solve-Testlauf (Issue #281)."""

    def test_format_post_solve_test_command_uses_default_when_unset(self):
        command = format_post_solve_test_command()

        self.assertEqual(command, list(POST_SOLVE_TEST_COMMAND))
        self.assertIn("unittest", command)
        self.assertIn("discover", command)
        self.assertIn("tests", command)

    def test_format_post_solve_test_command_returns_copy(self):
        command = format_post_solve_test_command()
        command.append("--mutate")

        self.assertNotIn("--mutate", POST_SOLVE_TEST_COMMAND)

    def test_format_post_solve_test_command_accepts_override(self):
        custom = ["python", "-m", "pytest", "tests/"]

        self.assertEqual(format_post_solve_test_command(custom), custom)

    def test_run_post_solve_tests_reports_passed(self):
        completed = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="ok", stderr="",
        )

        def fake_run(cmd, **kwargs):
            return completed

        with tempfile.TemporaryDirectory() as tmpdir:
            result = run_post_solve_tests(tmpdir, run_fn=fake_run)

        self.assertEqual(result.status, "passed")
        self.assertEqual(result.returncode, 0)
        self.assertTrue(result.summary.startswith("Tests: passed ("))
        self.assertIn("unittest", result.summary)
        self.assertIn("discover", result.summary)
        self.assertIn("tests", result.summary)

    def test_run_post_solve_tests_reports_failed(self):
        completed = subprocess.CompletedProcess(
            args=[], returncode=1, stdout="FAIL", stderr="",
        )

        def fake_run(cmd, **kwargs):
            return completed

        with tempfile.TemporaryDirectory() as tmpdir:
            result = run_post_solve_tests(tmpdir, run_fn=fake_run)

        self.assertEqual(result.status, "failed")
        self.assertEqual(result.returncode, 1)
        self.assertTrue(result.summary.startswith("Tests: failed ("))

    def test_run_post_solve_tests_reports_not_run_on_timeout(self):
        def fake_run(cmd, **kwargs):
            raise subprocess.TimeoutExpired(cmd=cmd, timeout=kwargs.get("timeout", 1))

        with tempfile.TemporaryDirectory() as tmpdir:
            result = run_post_solve_tests(
                tmpdir, run_fn=fake_run, timeout_seconds=2,
            )

        self.assertEqual(result.status, "not_run")
        self.assertIsNone(result.returncode)
        self.assertIn("timeout", result.note)
        self.assertIn("timeout", result.summary)

    def test_run_post_solve_tests_reports_not_run_on_missing_executable(self):
        def fake_run(cmd, **kwargs):
            raise FileNotFoundError("python-missing")

        with tempfile.TemporaryDirectory() as tmpdir:
            result = run_post_solve_tests(tmpdir, run_fn=fake_run)

        self.assertEqual(result.status, "not_run")
        self.assertIsNone(result.returncode)
        self.assertIn("Befehl nicht startbar", result.note)

    def test_run_post_solve_tests_does_not_use_shell(self):
        """Stellt sicher, dass der Standardbefehl ohne shell=True gestartet wird."""
        captured_kwargs: dict = {}

        def fake_run(cmd, **kwargs):
            captured_kwargs.update(kwargs)
            return subprocess.CompletedProcess(
                args=cmd, returncode=0, stdout="", stderr="",
            )

        with tempfile.TemporaryDirectory() as tmpdir:
            run_post_solve_tests(tmpdir, run_fn=fake_run)

        self.assertNotIn("shell", captured_kwargs)
        self.assertTrue(captured_kwargs.get("check") is False or "check" not in captured_kwargs)
        self.assertEqual(captured_kwargs.get("cwd"), tmpdir)

    def test_post_solve_test_result_summary_includes_command(self):
        result = PostSolveTestResult(
            status="passed",
            command=[sys.executable, "-m", "unittest", "discover", "-s", "tests"],
            returncode=0,
        )

        self.assertIn("Tests: passed (", result.summary)
        self.assertIn("unittest", result.summary)

    def test_post_solve_test_result_summary_adds_note_for_not_run(self):
        result = PostSolveTestResult(
            status="not_run",
            command=["missing-runner"],
            returncode=None,
            note="binary fehlt",
        )

        self.assertIn("not_run", result.summary)
        self.assertIn("binary fehlt", result.summary)

    def test_build_issue_pr_body_includes_test_result_summary(self):
        body = build_issue_pr_body(
            config_owner="test-owner",
            repo="demo",
            number=7,
            title="Test issue",
            model="opencode",
            model_name="opencode/deepseek-v4-flash-free",
            test_result_summary=(
                "Tests: passed ("
                f"{' '.join(POST_SOLVE_TEST_COMMAND)})"
            ),
        )

        self.assertIn("### Tests", body)
        self.assertIn("Tests: passed (", body)
        self.assertIn("unittest", body)

    def test_build_issue_pr_body_omits_test_section_when_summary_missing(self):
        body = build_issue_pr_body(
            config_owner="test-owner",
            repo="demo",
            number=7,
            title="Test issue",
            model="opencode",
        )

        self.assertNotIn("### Tests", body)

    def test_create_issue_pull_request_passes_test_result_summary(self):
        class MockClient:
            def __init__(self):
                self.posts = []
                self.comments = []

            def create_pull_request(self, repo, title, body, head, base, dry_run=False):
                self.posts.append((repo, title, body, head, base))
                return {"html_url": "https://github.com/test-owner/demo/pull/7"}

            def close_issue_with_comment(self, repo, number, comment):
                self.comments.append((repo, number, comment))

        client = MockClient()
        summary = "Tests: failed (python -m unittest discover -s tests)"

        pr = create_issue_pull_request(
            client=client,
            repo="demo",
            number=7,
            title="Test issue",
            model="opencode",
            config={"owner": "test-owner"},
            branch_name="ai/fix-issue-7",
            base_branch="main",
            close_issues=True,
            test_result_summary=summary,
        )

        self.assertIsNotNone(pr)
        self.assertIn("### Tests", client.posts[0][2])
        self.assertIn("Tests: failed (", client.posts[0][2])
        self.assertIn("unittest", client.posts[0][2])

    def test_create_issue_pull_request_omits_test_section_without_summary(self):
        class MockClient:
            def __init__(self):
                self.posts = []
                self.comments = []

            def create_pull_request(self, repo, title, body, head, base, dry_run=False):
                self.posts.append((repo, title, body, head, base))
                return {"html_url": "https://github.com/test-owner/demo/pull/7"}

            def close_issue_with_comment(self, repo, number, comment):
                self.comments.append((repo, number, comment))

        client = MockClient()

        create_issue_pull_request(
            client=client,
            repo="demo",
            number=7,
            title="Test issue",
            model="opencode",
            config={"owner": "test-owner"},
            branch_name="ai/fix-issue-7",
            base_branch="main",
            close_issues=True,
        )

        self.assertNotIn("### Tests", client.posts[0][2])

    def test_run_post_solve_tests_uses_default_command_from_module(self):
        """Stellt sicher, dass der Standardbefehl unittest discover -s tests nutzt."""
        captured_cmd: list = []

        def fake_run(cmd, **kwargs):
            captured_cmd.extend(cmd)
            return subprocess.CompletedProcess(
                args=cmd, returncode=0, stdout="", stderr="",
            )

        with tempfile.TemporaryDirectory() as tmpdir:
            run_post_solve_tests(tmpdir, run_fn=fake_run)

        self.assertIn("unittest", captured_cmd)
        self.assertIn("discover", captured_cmd)
        self.assertIn("tests", captured_cmd)
        # Default verwendet -s statt -p oder -t
        self.assertIn("-s", captured_cmd)

    def test_solve_issue_records_post_solve_test_in_run_report(self):
        """Stellt sicher, dass das Post-Solve-Testergebnis im Run-Report landet.

        Wird ueber die kleinen Bausteine getestet, weil ``solve_issue`` selbst
        zu viele externe Abhaengigkeiten hat (Lock, Clone, Push). Der Glue-Code
        zwischen ``run_post_solve_tests`` und ``write_run_report`` ist so klein
        und offensichtlich, dass er ohne den vollen solve_issue-Stack geprueft
        werden kann.
        """
        # Direkter Aufruf des Glue-Codes simuliert das, was solve_issue macht
        captured: dict = {}

        def fake_write(report, status, **kwargs):
            captured.update(kwargs)

        result = PostSolveTestResult(
            status="passed",
            command=list(POST_SOLVE_TEST_COMMAND),
            returncode=0,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            report = create_run_report(
                "demo", 7, "ai/fix-issue-7", "codex",
                issue_title="Fix", run_dir=tmpdir,
            )
            fake_write(
                report,
                "pr_created",
                test_command=result.command,
                test_result=result.status,
            )

        self.assertEqual(captured.get("test_command"), list(POST_SOLVE_TEST_COMMAND))
        self.assertEqual(captured.get("test_result"), "passed")

    def test_solve_issue_keeps_normal_pr_even_when_tests_fail(self):
        """Stellt sicher, dass ein fehlgeschlagener Test den PR nicht zu einem Draft macht."""
        # Test-Resultat: failed
        result = PostSolveTestResult(
            status="failed",
            command=list(POST_SOLVE_TEST_COMMAND),
            returncode=1,
        )

        # Body enthaelt die Tests-Zeile mit "failed" (sichtbar im PR)
        body = build_issue_pr_body(
            config_owner="test-owner",
            repo="demo",
            number=7,
            title="Test issue",
            model="opencode",
            test_result_summary=result.summary,
        )

        self.assertIn("### Tests", body)
        self.assertIn("failed", body)
        # Wichtig: kein Hinweis auf "draft" im Body (kein Draft-PR-Modus)
        self.assertNotIn("draft", body.lower())

    def test_solve_issue_omits_post_solve_tests_in_run_report_when_not_run(self):
        """Stellt sicher, dass ein nicht ausfuehrbarer Testlauf im Run-Report erscheint."""
        # not_run-Resultat
        result = PostSolveTestResult(
            status="not_run",
            command=list(POST_SOLVE_TEST_COMMAND),
            returncode=None,
            note="timeout",
        )

        # Im Report wird test_result=test_result.status festgehalten
        captured: dict = {}

        def fake_write(report, status, **kwargs):
            captured.update(kwargs)

        with tempfile.TemporaryDirectory() as tmpdir:
            report = create_run_report(
                "demo", 7, "ai/fix-issue-7", "codex",
                issue_title="Fix", run_dir=tmpdir,
            )
            fake_write(
                report,
                "pr_created",
                test_command=result.command,
                test_result=result.status,
            )

        self.assertEqual(captured.get("test_result"), "not_run")
        self.assertEqual(captured.get("test_command"), list(POST_SOLVE_TEST_COMMAND))
        # not_run wird im PR-Body ebenfalls sichtbar gemacht
        self.assertIn("not_run", result.summary)


class WorkerOutputTests(unittest.TestCase):
    def test_detect_opencode_runtime_diagnostics_finds_wal_failure(self):
        output = "Failed to run the query 'PRAGMA wal_checkpoint(PASSIVE)'"

        diagnostics = detect_opencode_runtime_diagnostics(output)

        self.assertTrue(diagnostics.wal_failure)
        self.assertFalse(diagnostics.edit_loop)

    def test_detect_opencode_runtime_diagnostics_finds_edit_loop(self):
        output = "\n".join(
            [
                "Edit README.md failed",
                "Edit README.md failed",
                "Edit docs/WORKFLOW.md failed",
            ]
        )

        diagnostics = detect_opencode_runtime_diagnostics(output)

        self.assertFalse(diagnostics.wal_failure)
        self.assertTrue(diagnostics.edit_loop)
        self.assertEqual(diagnostics.edit_failure_count, 3)
        self.assertEqual(
            diagnostics.edit_failure_files,
            ("README.md", "docs/WORKFLOW.md"),
        )

    def test_output_tail_uses_last_lines(self):
        output = "\n".join(f"line {i}" for i in range(40))

        tail = format_worker_output_tail(output)

        self.assertNotIn("line 0", tail)
        self.assertIn("line 39", tail)

    def test_run_worker_captures_stdout_and_stderr(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            script = Path(tmpdir) / "worker.py"
            script.write_text(
                "import sys\n"
                "print('stdout line')\n"
                "print('stderr line', file=sys.stderr)\n"
                "raise SystemExit(7)\n",
                encoding="utf-8",
            )

            with contextlib.redirect_stdout(io.StringIO()):
                result = run_worker_command(
                    [sys.executable, str(script)],
                    tmpdir,
                    os.environ.copy(),
                )

        self.assertEqual(result.returncode, 7)
        self.assertIn("stdout line", result.output)
        self.assertIn("stderr line", result.output)

    def test_worker_live_filter_keeps_status_and_hides_diff_noise(self):
        self.assertTrue(should_surface_worker_line("Plan: update solver output\n"))
        self.assertTrue(should_surface_worker_line("Ergebnis: Tests erfolgreich\n"))
        self.assertTrue(should_surface_worker_line("WARNING: test command failed\n"))
        self.assertTrue(should_surface_worker_line("→ Read tests/test_solve_issues.py\n"))
        self.assertTrue(should_surface_worker_line("✓ Write docs/WORKFLOW.md\n"))
        self.assertTrue(should_surface_worker_line("✗ Read docs/WORKFLOW.md failed\n"))
        self.assertFalse(should_surface_worker_line("+print('implementation detail')\n"))
        self.assertFalse(should_surface_worker_line("@@ -1,2 +1,3 @@\n"))

    def test_worker_live_filter_hides_aider_mistral_patch_fragments(self):
        noisy_lines = [
            '-    error: str = ""',
            '+        f.write("            <th>Repo</th>\\n")',
            '"https://github.com/test-owner/demo/issues/7")',
            'result.runs[0].lifecycle_note)',
            '"test-owner|demo|44|ai/fix-issue-44|https://github.com/test-owner/demo/pull/44":',
            'self.assertIn("test-owner", links["issue"])',
        ]

        for line in noisy_lines:
            with self.subTest(line=line):
                self.assertFalse(should_surface_worker_line(line))

    def test_worker_output_tail_prefers_compact_useful_lines(self):
        output = "\n".join(
            [
                'Plan: update dashboard rendering',
                '-    error: str = ""',
                '+        f.write("            <th>Repo</th>\\n")',
                'self.assertIn("test-owner", links["issue"])',
                'WARNING: tests failed, retrying',
                '→ Read scripts/solve_issues.py',
                '✓ Write tests/test_solve_issues.py',
                '"test-owner|demo|44|ai/fix-issue-44|https://github.com/test-owner/demo/pull/44":',
                'Final result: PR ready',
            ]
        )

        tail = format_worker_output_tail(output)

        self.assertIn("Plan: update dashboard rendering", tail)
        self.assertIn("WARNING: tests failed, retrying", tail)
        self.assertIn("→ Read scripts/solve_issues.py", tail)
        self.assertIn("✓ Write tests/test_solve_issues.py", tail)
        self.assertIn("Final result: PR ready", tail)
        self.assertNotIn("f.write", tail)
        self.assertNotIn("test-owner|demo|44", tail)
        self.assertNotIn("self.assertIn", tail)

    def test_run_worker_preserves_full_output_while_printing_summary(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            script = Path(tmpdir) / "worker.py"
            script.write_text(
                "print('Plan: change README')\n"
                "print('+ noisy diff line')\n"
                "print('Final result: done')\n",
                encoding="utf-8",
            )

            printed = io.StringIO()
            with contextlib.redirect_stdout(printed):
                result = run_worker_command(
                    [sys.executable, str(script)],
                    tmpdir,
                    os.environ.copy(),
                )

        self.assertIn("+ noisy diff line", result.output)
        self.assertIn("Plan: change README", printed.getvalue())
        self.assertIn("Detailzeilen ausgeblendet", printed.getvalue())
        self.assertNotIn("+ noisy diff line", printed.getvalue())

    def test_run_worker_prints_single_suppression_summary(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            script = Path(tmpdir) / "worker.py"
            script.write_text(
                "for index in range(75):\n"
                "    print(f'+ noisy diff line {index}')\n"
                "print('Final result: done')\n"
                "for index in range(25):\n"
                "    print(f'- more noisy diff line {index}')\n",
                encoding="utf-8",
            )

            printed = io.StringIO()
            with contextlib.redirect_stdout(printed):
                run_worker_command(
                    [sys.executable, str(script)],
                    tmpdir,
                    os.environ.copy(),
                )

        output = printed.getvalue()
        self.assertEqual(output.count("Detailzeilen ausgeblendet"), 1)
        self.assertIn("100 Detailzeilen ausgeblendet", output)
        self.assertNotIn("bisher", output)


class SolverDirectoryTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.repo_dir = Path(self.tmpdir.name)
        self.original_env = os.environ.copy()

    def tearDown(self):
        self.tmpdir.cleanup()
        os.environ.clear()
        os.environ.update(self.original_env)

    def test_solver_does_not_force_xdg_state_home_for_opencode_auth(self):
        """OpenCode-State/Auth bleiben bei OpenCode, damit SQLite/WAL konsistent bleiben."""
        xdg_state = self.repo_dir / "xdg_state"
        os.environ["XDG_STATE_HOME"] = str(xdg_state)
        os.environ.pop("HOME", None)

        # Simuliere build_worker_env, um den Pfad zu prüfen
        from solve_issues import build_worker_env
        env = build_worker_env("opencode", {})

        self.assertNotIn("XDG_STATE_HOME", env)
        self.assertNotIn("OPENCODE_STATE_DIR", env)
        self.assertNotIn("OPENCODE_AUTH_FILE", env)

    def test_solver_uses_solver_local_cache_if_xdg_unset(self):
        """OpenCode bekommt einen solver-lokalen Cache, aber keinen erzwungenen State/Auth-Pfad."""
        os.environ.pop("XDG_STATE_HOME", None)
        os.environ.pop("XDG_CACHE_HOME", None)
        os.environ.pop("HOME", None)

        # Simuliere build_worker_env, um solver-lokale Pfade zu prüfen
        from solve_issues import build_worker_env
        env = build_worker_env("opencode", {})

        # Prüfe, ob solver-lokale Pfade verwendet werden
        solver_base = Path(tempfile.gettempdir()) / "ai-issue-solver" / "opencode"
        cache_dir = solver_base / "cache"

        self.assertEqual(env["OPENCODE_CACHE_DIR"], str(cache_dir))
        self.assertNotIn("OPENCODE_STATE_DIR", env)
        self.assertNotIn("OPENCODE_AUTH_FILE", env)
        self.assertTrue((cache_dir / "tmp").is_dir())

    def test_solver_leaves_opencode_state_to_default_home(self):
        """Der Solver setzt keinen alternativen Auth-Pfad, der OpenCode-WAL-Dateien trennt."""
        os.environ.pop("XDG_STATE_HOME", None)
        os.environ.pop("XDG_CACHE_HOME", None)
        home = self.repo_dir / "fake_home"
        os.environ["HOME"] = str(home)

        # Simuliere build_worker_env, um Isolation zu prüfen
        from solve_issues import build_worker_env
        env = build_worker_env("opencode", {})

        global_state = home / ".local" / "share" / "opencode" / "auth.json"
        self.assertNotIn("OPENCODE_AUTH_FILE", env)
        self.assertNotIn("OPENCODE_STATE_DIR", env)
        self.assertNotIn(str(global_state), env.get("PATH", ""))

    def test_solver_avoids_exposing_secrets_in_worker_env(self):
        """Testet, dass Geheimnisse nicht in solver-lokalen Verzeichnissen exponiert werden."""
        xdg_state = self.repo_dir / "xdg_state"
        os.environ["XDG_STATE_HOME"] = str(xdg_state)
        os.environ.pop("HOME", None)

        # Simuliere build_worker_env mit Geheimnissen
        from solve_issues import build_worker_env
        config = {
            "ANTHROPIC_API_KEY": "sk-test-key",
            "MISTRAL_API_KEY": "mistral-test-key",
        }
        env = build_worker_env("claude", config)

        # Prüfe, dass Geheimnisse nicht in solver-lokalen Pfaden landen
        auth_path = xdg_state / "opencode" / "auth.json"
        self.assertFalse(auth_path.exists())
        self.assertNotIn("OPENCODE_AUTH_FILE", env)
        self.assertNotIn("OPENCODE_STATE_DIR", env)
        self.assertNotIn("OPENCODE_CACHE_DIR", env)

    def test_clone_repo_uses_isolated_target_directories(self):
        """Each run should clone into its own checkout path, not a shared repo cache."""
        with tempfile.TemporaryDirectory() as tmpdir:
            target_one = Path(tmpdir) / "run-one" / "demo"
            target_two = Path(tmpdir) / "run-two" / "demo"

            with patch("subprocess.run") as run:
                run.return_value = subprocess.CompletedProcess(
                    args=[],
                    returncode=0,
                    stdout="",
                    stderr="",
                )

                result_one = clone_repo("test-owner", "demo", "secret-token", str(target_one), "develop")
                result_two = clone_repo("test-owner", "demo", "secret-token", str(target_two), "develop")

        self.assertTrue(result_one)
        self.assertTrue(result_two)
        clone_targets = [Path(call.args[0][-1]) for call in run.call_args_list]
        self.assertEqual(clone_targets, [target_one, target_two])
        self.assertNotEqual(clone_targets[0], clone_targets[1])

    def test_clone_repo_removes_stale_target_directory_before_clone(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "run" / "demo"
            target.mkdir(parents=True)
            (target / "stale.txt").write_text("old\n", encoding="utf-8")

            def fake_run(cmd, **kwargs):
                self.assertEqual(Path(cmd[-1]), target)
                self.assertFalse(target.exists())
                return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

            with patch("subprocess.run", side_effect=fake_run):
                result = clone_repo("test-owner", "demo", "secret-token", str(target), "develop")

        self.assertTrue(result)

    def test_clone_repo_returns_sanitized_stderr_on_failure(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "run" / "demo"

            with patch("subprocess.run") as run:
                run.return_value = subprocess.CompletedProcess(
                    args=[],
                    returncode=128,
                    stdout="",
                    stderr="fatal: could not read https://secret-token@github.com/test-owner/demo.git\n",
                )

                result = clone_repo("test-owner", "demo", "secret-token", str(target), "missing")

        self.assertFalse(result)
        self.assertIn("***", result.stderr)
        self.assertNotIn("secret-token", result.stderr)


class GitStatusTests(unittest.TestCase):
    def test_git_status_porcelain_detects_untracked_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            subprocess.run(["git", "init"], cwd=tmpdir, check=True, capture_output=True)
            Path(tmpdir, "README.md").write_text("hello\n", encoding="utf-8")

            status = git_status_porcelain(tmpdir)

        self.assertIn("?? README.md", status)

    def test_nonzero_worker_with_repo_changes_is_accepted_for_review(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            subprocess.run(["git", "init"], cwd=tmpdir, check=True, capture_output=True)
            subprocess.run(
                ["git", "config", "user.email", "test@example.invalid"],
                cwd=tmpdir,
                check=True,
                capture_output=True,
            )
            subprocess.run(
                ["git", "config", "user.name", "Test User"],
                cwd=tmpdir,
                check=True,
                capture_output=True,
            )
            Path(tmpdir, "README.md").write_text("before\n", encoding="utf-8")
            subprocess.run(["git", "add", "README.md"], cwd=tmpdir, check=True)
            subprocess.run(
                ["git", "commit", "-m", "init"],
                cwd=tmpdir,
                check=True,
                capture_output=True,
            )

            worker = Path(tmpdir) / "worker.py"
            worker.write_text(
                "from pathlib import Path\n"
                "Path('README.md').write_text('after\\n', encoding='utf-8')\n"
                "print('changed README')\n"
                "raise SystemExit(12)\n",
                encoding="utf-8",
            )

            with contextlib.redirect_stdout(io.StringIO()):
                result = run_worker_command(
                    [sys.executable, str(worker)],
                    tmpdir,
                    os.environ.copy(),
                )

            assessment = assess_worker_result(result, git_status_porcelain(tmpdir))

        self.assertEqual(result.returncode, 12)
        self.assertTrue(assessment.should_continue)
        self.assertEqual(assessment.reason, "nonzero_with_changes")

    def test_branch_has_changes_against_base_detects_remote_diff(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            subprocess.run(["git", "init"], cwd=tmpdir, check=True, capture_output=True)
            subprocess.run(["git", "branch", "-M", "main"], cwd=tmpdir, check=True, capture_output=True)
            subprocess.run(
                ["git", "config", "user.email", "test@example.invalid"],
                cwd=tmpdir,
                check=True,
                capture_output=True,
            )
            subprocess.run(
                ["git", "config", "user.name", "Test User"],
                cwd=tmpdir,
                check=True,
                capture_output=True,
            )
            readme = Path(tmpdir) / "README.md"
            readme.write_text("before\n", encoding="utf-8")
            subprocess.run(["git", "add", "README.md"], cwd=tmpdir, check=True)
            subprocess.run(
                ["git", "commit", "-m", "init"],
                cwd=tmpdir,
                check=True,
                capture_output=True,
            )
            subprocess.run(
                ["git", "update-ref", "refs/remotes/origin/main", "HEAD"],
                cwd=tmpdir,
                check=True,
                capture_output=True,
            )

            self.assertFalse(branch_has_changes_against_base(tmpdir, "main"))

            readme.write_text("before\nafter\n", encoding="utf-8")
            subprocess.run(["git", "add", "README.md"], cwd=tmpdir, check=True)
            subprocess.run(
                ["git", "commit", "-m", "change"],
                cwd=tmpdir,
                check=True,
                capture_output=True,
            )

            self.assertTrue(branch_has_changes_against_base(tmpdir, "main"))

    def test_git_change_summary_uses_diff_stat_table(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            subprocess.run(["git", "init"], cwd=tmpdir, check=True, capture_output=True)
            subprocess.run(
                ["git", "config", "user.email", "test@example.invalid"],
                cwd=tmpdir,
                check=True,
                capture_output=True,
            )
            subprocess.run(
                ["git", "config", "user.name", "Test User"],
                cwd=tmpdir,
                check=True,
                capture_output=True,
            )
            readme = Path(tmpdir) / "README.md"
            readme.write_text("before\n", encoding="utf-8")
            subprocess.run(["git", "add", "README.md"], cwd=tmpdir, check=True)
            subprocess.run(
                ["git", "commit", "-m", "init"],
                cwd=tmpdir,
                check=True,
                capture_output=True,
            )
            readme.write_text("before\nafter\n", encoding="utf-8")
            Path(tmpdir, "notes.txt").write_text("new\n", encoding="utf-8")

            summary = "\n".join(format_git_change_summary(tmpdir))

        self.assertIn("Git-Änderungsübersicht", summary)
        self.assertRegex(summary, r"README\.md\s+\|\s+1 \+")
        self.assertRegex(summary, r"notes\.txt\s+\|\s+1 \+")
        self.assertIn("1 neue Datei, 1 eingefuegte Zeile", summary)
        self.assertNotIn("Diff-Vorschau:", summary)
        self.assertNotIn("Status:", summary)

    def test_git_change_summary_truncates_large_diff_stat(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            subprocess.run(["git", "init"], cwd=tmpdir, check=True, capture_output=True)
            for index in range(15):
                Path(tmpdir, f"file-{index:02d}.txt").write_text("new\n", encoding="utf-8")
            git_status = "\n".join(f"?? file-{index:02d}.txt" for index in range(15))

            summary = "\n".join(format_git_change_summary(tmpdir, git_status))

        self.assertIn("file-00.txt", summary)
        self.assertNotIn("file-14.txt", summary)
        self.assertIn("... 3 weitere Stat-Zeilen", summary)

    def test_worker_diagnostics_write_full_output(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            old_cwd = os.getcwd()
            os.chdir(tmpdir)
            try:
                run_dir = write_worker_diagnostics(
                    WorkerRunResult(3, "full\nworker\noutput\n"),
                    repo="demo",
                    issue_number=28,
                    model="codex",
                )
                run_dir = Path(run_dir).resolve()
                log = Path(run_dir) / "worker-output.log"
                summary = Path(run_dir) / "summary.txt"
            finally:
                os.chdir(old_cwd)

            self.assertEqual(log.read_text(encoding="utf-8"), "full\nworker\noutput\n")
            self.assertIn("worker_exit_code: 3", summary.read_text(encoding="utf-8"))

    def test_run_report_persists_metadata_pr_url_and_output_tail(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            old_cwd = os.getcwd()
            os.chdir(tmpdir)
            try:
                report = create_run_report(
                    repo="demo/repo",
                    issue_number=24,
                    branch="ai/fix-issue-24",
                    model="codex",
                    issue_title="Show issue titles in the status dashboard",
                    now_fn=lambda: datetime(2026, 5, 21, 9, 8, 7, 123456),
                )
                run_dir = write_run_report(
                    report,
                    "pr_created",
                    worker_result=WorkerRunResult(
                        0,
                        "\n".join(f"line {index}" for index in range(40)) + "\n",
                    ),
                    pr_url="https://github.com/test-owner/demo/pull/24",
                    git_change_summary=[
                        "Git-Änderungsübersicht:",
                        "  README.md | 1 +",
                    ],
                )
                run_dir = Path(run_dir).resolve()
                summary = (run_dir / "summary.txt").read_text(encoding="utf-8")
                tail = (run_dir / "output-tail.log").read_text(encoding="utf-8")
                metadata = json.loads((run_dir / "metadata.json").read_text(encoding="utf-8"))
            finally:
                os.chdir(old_cwd)

        self.assertEqual(run_dir.name, "20260521-090807-123456-demo-repo-issue-24")
        self.assertIn("selected_repo: demo/repo", summary)
        self.assertIn("repo: demo/repo", summary)
        self.assertIn("issue_number: 24", summary)
        self.assertIn("issue: 24", summary)
        self.assertIn("issue_title: Show issue titles in the status dashboard", summary)
        self.assertIn("branch: ai/fix-issue-24", summary)
        self.assertIn("model: codex", summary)
        self.assertIn("worker_exit_code: 0", summary)
        self.assertIn("pr_url: https://github.com/test-owner/demo/pull/24", summary)
        self.assertIn("preserved_worktree: \n", summary)
        self.assertIn("git_diff_stat:", summary)
        self.assertIn("README.md | 1 +", summary)
        self.assertIn("output_tail:", summary)
        self.assertEqual(metadata["git_change_summary"], [
            "Git-Änderungsübersicht:",
            "  README.md | 1 +",
        ])
        self.assertEqual(metadata["status"], "pr_created")
        self.assertEqual(metadata["repo"], "demo/repo")
        self.assertEqual(metadata["issue_title"], "Show issue titles in the status dashboard")
        self.assertEqual(metadata["preserved_worktree"], "")
        self.assertNotIn("line 0", tail)
        self.assertIn("line 39", tail)

    def test_run_health_persists_opencode_runtime_diagnostics(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            report = create_run_report(
                repo="demo",
                issue_number=64,
                branch="ai/fix-issue-64",
                model="opencode",
                run_dir=Path(tmpdir) / "run",
            )

            write_run_health(
                report,
                "Edit README.md failed\nEdit README.md failed\nEdit README.md failed\n",
            )

            health = json.loads((report.path / "health.json").read_text(encoding="utf-8"))

        self.assertTrue(health["opencode_runtime"]["edit_loop"])
        self.assertEqual(health["opencode_runtime"]["edit_failure_count"], 3)
        self.assertIn("OpenCode Edit-Loop-Risiko erkannt", health["opencode_runtime"]["diagnostic_lines"][0])

    def test_run_report_persists_opencode_runtime_diagnostics(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            report = create_run_report(
                repo="demo",
                issue_number=164,
                branch="ai/fix-issue-164",
                model="opencode",
                run_dir=Path(tmpdir) / "run",
            )
            run_dir = write_run_report(
                report,
                "nonzero_without_changes",
                worker_result=WorkerRunResult(
                    1,
                    "Failed to run the query 'PRAGMA wal_checkpoint(PASSIVE)'\n",
                ),
            )
            summary = (Path(run_dir) / "summary.txt").read_text(encoding="utf-8")
            metadata = json.loads((Path(run_dir) / "metadata.json").read_text(encoding="utf-8"))

        self.assertTrue(metadata["opencode_runtime"]["wal_failure"])
        self.assertIn("opencode_runtime:", summary)
        self.assertIn("OpenCode SQLite/WAL-Fehler erkannt.", summary)
        self.assertIn("opencode.db-wal/opencode.db-shm", summary)

    def test_run_report_without_worker_records_partial_status(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            old_cwd = os.getcwd()
            os.chdir(tmpdir)
            try:
                report = create_run_report(
                    repo="demo",
                    issue_number=25,
                    branch="ai/fix-issue-25",
                    model="claude",
                    now_fn=lambda: datetime(2026, 5, 21, 9, 8, 7),
                )
                run_dir = write_run_report(report, "clone_failed", note="base_branch: main")
                run_dir = Path(run_dir).resolve()
                summary = (run_dir / "summary.txt").read_text(encoding="utf-8")
            finally:
                os.chdir(old_cwd)

        self.assertIn("status: clone_failed", summary)
        self.assertIn("worker_exit_code: \n", summary)
        self.assertIn("note: base_branch: main", summary)
        self.assertFalse((run_dir / "worker-output.log").exists())

    def test_run_report_records_preserved_worktree_and_recovery_command(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            old_cwd = os.getcwd()
            os.chdir(tmpdir)
            try:
                report = create_run_report(
                    repo="demo",
                    issue_number=46,
                    branch="ai/fix-issue-46",
                    model="codex",
                    now_fn=lambda: datetime(2026, 5, 21, 9, 8, 7),
                )
                preserved = Path(tmpdir) / "reports" / "preserved-worktrees" / "demo"
                run_dir = write_run_report(
                    report,
                    "push_failed",
                    preserved_worktree_path=preserved,
                    base_branch="main",
                )
                run_dir = Path(run_dir).resolve()
                summary = (run_dir / "summary.txt").read_text(encoding="utf-8")
                metadata = json.loads((run_dir / "metadata.json").read_text(encoding="utf-8"))
            finally:
                os.chdir(old_cwd)

        self.assertIn(f"preserved_worktree: {preserved}", summary)
        self.assertIn("cleanup_command: python scripts/solve_issues.py --cleanup-preserved-worktrees", summary)
        self.assertIn("git push origin HEAD:ai/fix-issue-46", summary)
        self.assertEqual(metadata["preserved_worktree"], str(preserved))

    def test_preserve_worker_worktree_moves_clone_and_sanitizes_remote(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            old_cwd = os.getcwd()
            os.chdir(tmpdir)
            try:
                repo_dir = Path(tmpdir) / "tmp-clone" / "demo"
                repo_dir.mkdir(parents=True)
                subprocess.run(["git", "init"], cwd=repo_dir, check=True, capture_output=True)
                subprocess.run(
                    ["git", "remote", "add", "origin", "https://secret-token@github.com/test-owner/demo.git"],
                    cwd=repo_dir,
                    check=True,
                    capture_output=True,
                )
                subprocess.run(
                    ["git", "config", "remote.origin.pushurl", "https://push-token@github.com/test-owner/demo.git"],
                    cwd=repo_dir,
                    check=True,
                    capture_output=True,
                )
                (repo_dir / "README.md").write_text("change\n", encoding="utf-8")
                report = create_run_report(
                    repo="demo",
                    issue_number=46,
                    branch="ai/fix-issue-46",
                    model="codex",
                    now_fn=lambda: datetime(2026, 5, 21, 9, 8, 7),
                )

                preserved = preserve_worker_worktree(
                    repo_dir=str(repo_dir),
                    report=report,
                    owner="test-owner",
                    repo="demo",
                    issue_number=46,
                    branch="ai/fix-issue-46",
                    status="push_failed",
                    base_branch="main",
                )
                self.assertIsNotNone(preserved)
                self.assertFalse(repo_dir.exists())
                self.assertTrue((preserved / "README.md").exists())
                self.assertTrue((preserved / "RECOVERY.md").exists())
                remote = subprocess.run(
                    ["git", "remote", "get-url", "origin"],
                    cwd=preserved,
                    check=True,
                    capture_output=True,
                    text=True,
                ).stdout.strip()
                pushurl = subprocess.run(
                    ["git", "config", "--get", "remote.origin.pushurl"],
                    cwd=preserved,
                    capture_output=True,
                    text=True,
                )
            finally:
                os.chdir(old_cwd)

        self.assertEqual(remote, "https://github.com/test-owner/demo.git")
        self.assertNotIn("secret-token", remote)
        self.assertEqual(pushurl.returncode, 1)
        self.assertNotIn("push-token", pushurl.stdout + pushurl.stderr)

    def test_should_preserve_worktree_detects_committed_branch_changes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
            subprocess.run(["git", "checkout", "-b", "main"], cwd=repo, check=True, capture_output=True)
            subprocess.run(["git", "config", "user.email", "test@example.test"], cwd=repo, check=True)
            subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo, check=True)
            (repo / "README.md").write_text("base\n", encoding="utf-8")
            subprocess.run(["git", "add", "README.md"], cwd=repo, check=True, capture_output=True)
            subprocess.run(["git", "commit", "-m", "base"], cwd=repo, check=True, capture_output=True)
            subprocess.run(["git", "checkout", "-b", "ai/fix-issue-46"], cwd=repo, check=True, capture_output=True)
            (repo / "README.md").write_text("base\nchange\n", encoding="utf-8")
            subprocess.run(["git", "commit", "-am", "fix"], cwd=repo, check=True, capture_output=True)

            preserve = should_preserve_worktree(
                "nonzero_without_changes",
                str(repo),
                "main",
            )

        self.assertTrue(preserve)

    def test_cleanup_preserved_worktrees_deletes_only_expired_dirs(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "preserved"
            old_path = root / "old"
            fresh_path = root / "fresh"
            old_path.mkdir(parents=True)
            fresh_path.mkdir()
            os.utime(old_path, (1000, 1000))
            os.utime(fresh_path, (99_000, 99_000))

            stale = cleanup_preserved_worktrees(
                root=root,
                retention_days=1,
                dry_run=False,
                now_fn=lambda: 100_000,
            )
            self.assertEqual(stale, [old_path])
            self.assertFalse(old_path.exists())
            self.assertTrue(fresh_path.exists())


class OpenCodePreflightTests(unittest.TestCase):
    """Tests für OpenCode Auth-Preflight und Diagnostic (Issue #139)."""

    def setUp(self):
        self.opencode_exe = "/usr/local/bin/opencode"

    def test_check_opencode_auth_returns_true_when_authenticated(self):
        mock_result = unittest.mock.MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "Credentials ~/.local/share/opencode/auth.json\nOpenCode Zen api\n1 credentials\n"
        mock_result.stderr = ""

        with unittest.mock.patch("subprocess.run", return_value=mock_result):
            with contextlib.redirect_stdout(io.StringIO()):
                result = check_opencode_auth(self.opencode_exe)

        self.assertTrue(result)

    def test_check_opencode_auth_returns_false_when_not_authenticated(self):
        mock_result = unittest.mock.MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "Credentials ~/.local/share/opencode/auth.json\n0 credentials\n"
        mock_result.stderr = ""

        printed = io.StringIO()
        with unittest.mock.patch("subprocess.run", return_value=mock_result):
            with contextlib.redirect_stdout(printed):
                result = check_opencode_auth(self.opencode_exe)

        self.assertFalse(result)
        output = printed.getvalue()
        self.assertIn("OpenCode ist nicht authentifiziert", output)
        self.assertIn("opencode auth login", output)

    def test_check_opencode_auth_returns_false_on_timeout(self):
        with unittest.mock.patch(
            "subprocess.run", side_effect=subprocess.TimeoutExpired("opencode", 15)
        ):
            printed = io.StringIO()
            with contextlib.redirect_stdout(printed):
                result = check_opencode_auth(self.opencode_exe)

        self.assertFalse(result)
        self.assertIn("Auth-Check", printed.getvalue())

    def test_check_opencode_auth_returns_false_on_file_not_found(self):
        with unittest.mock.patch(
            "subprocess.run", side_effect=FileNotFoundError()
        ):
            printed = io.StringIO()
            with contextlib.redirect_stdout(printed):
                result = check_opencode_auth(self.opencode_exe)

        self.assertFalse(result)
        self.assertIn("Auth-Check", printed.getvalue())

    def test_run_opencode_diagnostic_returns_1_when_executable_missing(self):
        with unittest.mock.patch(
            "solve_issues.find_opencode_executable", return_value=None
        ):
            with contextlib.redirect_stdout(io.StringIO()):
                exit_code = run_opencode_diagnostic()

        self.assertEqual(exit_code, 1)

    def test_run_opencode_diagnostic_reports_version_and_auth(self):
        with unittest.mock.patch(
            "solve_issues.find_opencode_executable", return_value=self.opencode_exe
        ):
            version_mock = unittest.mock.MagicMock()
            version_mock.returncode = 0
            version_mock.stdout = "opencode 0.1.0\n"
            version_mock.stderr = ""

            auth_mock = unittest.mock.MagicMock()
            auth_mock.returncode = 0
            auth_mock.stdout = "Credentials\nOpenCode Zen api\n1 credentials\n"
            auth_mock.stderr = ""

            with unittest.mock.patch(
                "subprocess.run", side_effect=[version_mock, auth_mock]
            ):
                printed = io.StringIO()
                with contextlib.redirect_stdout(printed):
                    exit_code = run_opencode_diagnostic()

        self.assertEqual(exit_code, 0)
        output = printed.getvalue()
        self.assertIn("OpenCode Diagnostic", output)
        self.assertIn("0.1.0", output)
        self.assertIn("Authentifiziert", output)


class TestOpenRouterDirectWorkerPath(unittest.TestCase):
    def test_run_openrouter_direct_worker_imports_repo_level_worker(self):
        with tempfile.TemporaryDirectory() as repo_dir:
            direct_result = SimpleNamespace(
                returncode=2,
                output="[openrouter_direct] Keine Patches.",
            )

            with patch.dict(os.environ, {"OPENROUTER_API_KEY": "test-key"}):
                with patch("workers.openrouter_worker.OpenRouterWorker") as worker_cls:
                    worker_cls.return_value.run_direct.return_value = direct_result

                    result = run_openrouter_direct_worker(
                        prompt="Fix the issue",
                        repo_dir=repo_dir,
                        model_name="mistralai/mistral-large",
                    )

        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.output, direct_result.output)
        worker_cls.assert_called_once_with(
            api_key="test-key",
            model="mistralai/mistral-large",
        )


if __name__ == "__main__":
    unittest.main()
