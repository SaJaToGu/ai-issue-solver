import contextlib
from datetime import datetime
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from solve_issues import (  # noqa: E402
    GitHubClient,
    PullRequestState,
    WorkerRunResult,
    assess_worker_result,
    branch_has_changes_against_base,
    build_aider_command,
    build_opencode_command,
    build_opencode_prompt,
    build_vibe_command,
    build_worker_command,
    build_worker_env,
    check_opencode_auth,
    cleanup_preserved_worktrees,
    create_run_report,
    create_issue_pull_request,
    detect_codex_rate_limit,
    find_vibe_executable,
    format_git_change_summary,
    format_worker_output_tail,
    find_opencode_executable,
    get_worker_display_name,
    git_status_porcelain,
    infer_aider_targets,
    parse_codex_reset_datetime,
    plan_branch_recovery,
    print_branch_recovery_plan,
    relativize_repo_absolute_paths,
    preserve_worker_worktree,
    retry_branch_name,
    run_opencode_diagnostic,
    run_worker_command,
    should_preserve_worktree,
    should_surface_worker_line,
    sleep_until_codex_reset,
    validate_worker_changes,
    solve_issue,
    write_run_report,
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

    def test_resolve_base_branch_falls_back_to_default_when_requested_branch_is_missing(self):
        client = self.make_client()

        with contextlib.redirect_stdout(io.StringIO()):
            base_branch = client.resolve_base_branch("demo", "develop")

        self.assertEqual(base_branch, "main")

    def test_create_pull_request_posts_against_resolved_default_branch(self):
        client = self.make_client()

        with contextlib.redirect_stdout(io.StringIO()):
            pr = client.create_pull_request(
                repo="demo",
                title="Fix",
                body="Body",
                head="ai/fix-issue-1",
                base="develop",
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
            external_path = Path(tmpdir).parent / "outside.py"
            prompt = (
                f"Lies `{internal_path}` und pruefe auch "
                f"{external_path}."
            )

            normalized = relativize_repo_absolute_paths(prompt, str(repo))

        self.assertIn("`scripts/create_issues.py`", normalized)
        self.assertNotIn(str(internal_path), normalized)
        self.assertIn(str(external_path), normalized)

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
        self.assertIn(str(external_path), normalized)

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
        self.assertEqual(get_worker_display_name("openrouter"), "OpenRouter (aider)")

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

        # Leerer String soll als None weitergegeben werden
        mock_codex.assert_called_once_with("prompt", "/repo", None)

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


class WorkerOutputTests(unittest.TestCase):
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
                '"test-owner|demo|44|ai/fix-issue-44|https://github.com/test-owner/demo/pull/44":',
                'Final result: PR ready',
            ]
        )

        tail = format_worker_output_tail(output)

        self.assertIn("Plan: update dashboard rendering", tail)
        self.assertIn("WARNING: tests failed, retrying", tail)
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


if __name__ == "__main__":
    unittest.main()
