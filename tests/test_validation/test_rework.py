from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from validation.rework import (
    _build_rework_prompt,
    _format_pr_commits_for_prompt,
    _load_rework_prompt_template,
    _rework_max_tokens_from_env,
    _run_worker_via_subprocess,
    run_pr_rework,
)
from validation.github_client import (
    PullRequestInfo,
    ReviewThread,
)
from validation.models import RunReportData


class BuildReworkPromptTests(unittest.TestCase):
    def setUp(self):
        self.template = (
            "PR #{pr_number} in {owner}/{repo}\n"
            "Base: {base_branch}, Head: {head_branch}\n"
            "Head SHA: {head_sha}\n"
            "Commits:\n{existing_commits_list}\n"
            "Reviewers: {reviewer_usernames}\n"
            "DIFF:\n{diff}\n"
            "FEEDBACK:\n{review_threads}\n"
        )

    def test_basic_prompt_build(self):
        threads = [
            ReviewThread(id=1, body="Use a list comprehension", user="reviewer1", path="scripts/foo.py"),
            ReviewThread(id=2, body="Add type hints", user="reviewer2", path="scripts/bar.py"),
        ]
        prompt = _build_rework_prompt(
            template=self.template,
            pr_number=42,
            owner="test-owner",
            repo="test-repo",
            base_branch="main",
            head_branch="ai/fix-issue-1",
            diff="--- a/file.py\n+++ b/file.py\n@@ -1 +1 @@\n-foo\n+bar",
            review_threads=threads,
            head_sha="abc123",
            existing_commits_list="- abc123 latest fix",
        )
        self.assertIn("PR #42", prompt)
        self.assertIn("test-owner/test-repo", prompt)
        self.assertIn("reviewer1", prompt)
        self.assertIn("reviewer2", prompt)
        self.assertIn("Use a list comprehension", prompt)
        self.assertIn("Add type hints", prompt)
        self.assertIn("main", prompt)
        self.assertIn("ai/fix-issue-1", prompt)
        self.assertIn("abc123", prompt)
        self.assertIn("latest fix", prompt)

    def test_empty_review_threads(self):
        prompt = _build_rework_prompt(
            template=self.template,
            pr_number=1,
            owner="o",
            repo="r",
            base_branch="main",
            head_branch="fix",
            diff="",
            review_threads=[],
        )
        self.assertIn("(no review comments found)", prompt)

    def test_reviewer_usernames_deduplicated(self):
        threads = [
            ReviewThread(id=1, body="Fix A", user="alice", path="a.py"),
            ReviewThread(id=2, body="Fix B", user="alice", path="b.py"),
            ReviewThread(id=3, body="Fix C", user="bob", path="c.py"),
        ]
        prompt = _build_rework_prompt(
            template=self.template,
            pr_number=1,
            owner="o",
            repo="r",
            base_branch="main",
            head_branch="fix",
            diff="",
            review_threads=threads,
        )
        self.assertIn("alice", prompt)
        self.assertIn("bob", prompt)
        reviewers_line = [l for l in prompt.splitlines() if l.startswith("Reviewers:")][0]
        self.assertEqual(reviewers_line.count("alice"), 1)
        self.assertEqual(reviewers_line.count("bob"), 1)


class ReworkCommitContextTests(unittest.TestCase):
    def test_format_pr_commits_newest_first(self):
        commits = [
            {"sha": "111111111111aaaa", "commit": {"message": "old commit\n\nbody"}},
            {"sha": "222222222222bbbb", "commit": {"message": "new commit"}},
        ]

        formatted = _format_pr_commits_for_prompt(commits)

        self.assertLess(formatted.index("222222222222"), formatted.index("111111111111"))
        self.assertIn("new commit", formatted)
        self.assertIn("old commit", formatted)

    def test_format_pr_commits_handles_empty_list(self):
        self.assertIn("no existing PR commits", _format_pr_commits_for_prompt([]))


class ReworkWorkerInvocationTests(unittest.TestCase):
    def test_rework_max_tokens_default_and_env_override(self):
        with patch.dict("os.environ", {}, clear=True):
            self.assertEqual(_rework_max_tokens_from_env(), 16384)
        with patch.dict("os.environ", {"OPENROUTER_REWORK_MAX_TOKENS": "32768"}):
            self.assertEqual(_rework_max_tokens_from_env(), 32768)
        with patch.dict("os.environ", {"OPENROUTER_REWORK_MAX_TOKENS": "not-int"}):
            self.assertEqual(_rework_max_tokens_from_env(), 16384)

    def test_run_worker_uses_plain_patch_prompt_without_response_format(self):
        with patch("workers.openrouter_worker.OpenRouterWorker") as worker_cls:
            worker = MagicMock()
            worker.build_patch_prompt.return_value = "PATCH PROMPT"
            worker.generate_with_usage.return_value = (
                '{"patches":[{"file_path":"x.py","diff":"--- a/x.py\\n+++ b/x.py\\n@@ -1 +1 @@\\n-a\\n+b\\n"}]}',
                MagicMock(model="test-model", cost_usd=None, total_tokens=10),
            )
            worker.extract_patches.return_value = ["--- a/x.py\n+++ b/x.py\n@@ -1 +1 @@\n-a\n+b\n"]
            worker.apply_patches.return_value = [
                MagicMock(success=True, applied_file="x.py", error=None)
            ]
            worker_cls.return_value = worker

            returncode, output = _run_worker_via_subprocess(
                prompt="Original prompt",
                repo_dir="/tmp/repo",
                model="openai/gpt-4o-mini",
                openrouter_key="key",
            )

        self.assertEqual(returncode, 0)
        worker_cls.assert_called_once()
        self.assertFalse(worker_cls.call_args.kwargs["use_structured_output"])
        worker.build_patch_prompt.assert_called_once_with("Original prompt", structured=False)
        worker.generate_with_usage.assert_called_once()
        self.assertEqual(worker.generate_with_usage.call_args.kwargs["prompt"], "PATCH PROMPT")
        self.assertEqual(worker.generate_with_usage.call_args.kwargs["max_tokens"], 16384)
        self.assertIn("Applied patch", output)


class LoadReworkPromptTemplateTests(unittest.TestCase):
    def test_template_file_exists(self):
        template_path = ROOT / "prompts" / "rework_pr.md"
        self.assertTrue(template_path.exists(), "prompts/rework_pr.md must exist")

    def test_template_contains_required_placeholders(self):
        template = _load_rework_prompt_template()
        for placeholder in (
            "{pr_number}",
            "{diff}",
            "{review_threads}",
            "{reviewer_usernames}",
            "{head_sha}",
            "{existing_commits_list}",
        ):
            self.assertIn(placeholder, template)


class RunPrReworkDryRunTests(unittest.TestCase):
    def test_dry_run_returns_early_without_api_calls(self):
        with patch("validation.rework.ValidationGitHubClient") as mock_client_cls:
            mock_client = MagicMock()
            mock_client_cls.return_value = mock_client
            mock_client.get_pull_request.return_value = PullRequestInfo(
                number=404,
                title="Test PR",
                state="open",
                merged=False,
                head_ref="ai/fix-issue-1",
                head_sha="abc123",
                base_ref="main",
                html_url="https://github.com/o/r/pull/404",
            )
            mock_client.get_pull_request_commits.return_value = [
                {"sha": "abc123", "commit": {"message": "latest commit"}},
            ]

            result = run_pr_rework(
                owner="o",
                repo="r",
                pr_number=404,
                model="test-model",
                github_token="test-token",
                dry_run=True,
            )

        self.assertEqual(result.status, "dry_run")
        self.assertEqual(result.issue_number, 404)
        self.assertIsNotNone(result.run_id)
        self.assertIn("rework", result.run_id or "")

    def test_merged_pr_returns_skip(self):
        with patch("validation.rework.ValidationGitHubClient") as mock_client_cls:
            mock_client = MagicMock()
            mock_client_cls.return_value = mock_client
            mock_client.get_pull_request.return_value = PullRequestInfo(
                number=404,
                title="Merged PR",
                state="closed",
                merged=True,
                head_ref="ai/fix-issue-1",
                base_ref="main",
                html_url="https://github.com/o/r/pull/404",
            )

            result = run_pr_rework(
                owner="o",
                repo="r",
                pr_number=404,
                model="test-model",
                github_token="test-token",
                dry_run=False,
            )

        self.assertEqual(result.status, "skip_merged_pr")

    def test_nonexistent_pr_returns_not_found(self):
        with patch("validation.rework.ValidationGitHubClient") as mock_client_cls:
            mock_client = MagicMock()
            mock_client_cls.return_value = mock_client
            mock_client.get_pull_request.return_value = None

            result = run_pr_rework(
                owner="o",
                repo="r",
                pr_number=999,
                model="test-model",
                github_token="test-token",
                dry_run=False,
            )

        self.assertEqual(result.status, "failed")
        self.assertEqual(result.error_class, "not_found")


class RunPrReworkConfigGuardTests(unittest.TestCase):
    def test_missing_github_token(self):
        with patch.dict("os.environ", {}, clear=True):
            result = run_pr_rework(
                owner="o",
                repo="r",
                pr_number=1,
                github_token=None,
            )
        self.assertEqual(result.status, "failed")
        self.assertEqual(result.error_class, "config")

    def test_missing_openrouter_key_triggers_config_error(self):
        with patch("validation.rework.ValidationGitHubClient") as mock_client_cls:
            mock_client = MagicMock()
            mock_client_cls.return_value = mock_client
            mock_client.get_pull_request.return_value = PullRequestInfo(
                number=1,
                title="Test",
                state="open",
                merged=False,
                head_ref="fix",
                head_sha="abc123",
                base_ref="main",
                html_url="",
            )
            mock_client.get_pull_request_commits.return_value = [
                {"sha": "abc123", "commit": {"message": "latest commit"}},
            ]

            result = run_pr_rework(
                owner="o",
                repo="r",
                pr_number=1,
                github_token="test-token",
                openrouter_key=None,
            )

        self.assertEqual(result.status, "failed")
        self.assertEqual(result.error_class, "config")
        self.assertIn("OPENROUTER_API_KEY", result.error_detail or "")


class ReworkPromptTemplateFormatTests(unittest.TestCase):
    def test_placeholders_in_template(self):
        template_path = ROOT / "prompts" / "rework_pr.md"
        content = template_path.read_text(encoding="utf-8")
        required = ["pr_number", "owner", "repo", "base_branch", "head_branch",
                     "head_sha", "existing_commits_list", "reviewer_usernames",
                     "diff", "review_threads"]
        for field in required:
            self.assertIn(f"{{{field}}}", content, f"Missing placeholder {{{field}}} in prompt template")


if __name__ == "__main__":
    unittest.main()
