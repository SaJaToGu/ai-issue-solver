from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.validation.rework import (
    _build_rework_prompt,
    _load_rework_prompt_template,
    run_pr_rework,
)
from scripts.validation.github_client import (
    PullRequestInfo,
    ReviewThread,
)
from scripts.validation.models import RunReportData


class BuildReworkPromptTests(unittest.TestCase):
    def setUp(self):
        self.template = (
            "PR #{pr_number} in {owner}/{repo}\n"
            "Base: {base_branch}, Head: {head_branch}\n"
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
        )
        self.assertIn("PR #42", prompt)
        self.assertIn("test-owner/test-repo", prompt)
        self.assertIn("reviewer1", prompt)
        self.assertIn("reviewer2", prompt)
        self.assertIn("Use a list comprehension", prompt)
        self.assertIn("Add type hints", prompt)
        self.assertIn("main", prompt)
        self.assertIn("ai/fix-issue-1", prompt)

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


class LoadReworkPromptTemplateTests(unittest.TestCase):
    def test_template_file_exists(self):
        template_path = ROOT / "prompts" / "rework_pr.md"
        self.assertTrue(template_path.exists(), "prompts/rework_pr.md must exist")

    def test_template_contains_required_placeholders(self):
        template = _load_rework_prompt_template()
        for placeholder in ("{pr_number}", "{diff}", "{review_threads}", "{reviewer_usernames}"):
            self.assertIn(placeholder, template)


class RunPrReworkDryRunTests(unittest.TestCase):
    def test_dry_run_returns_early_without_api_calls(self):
        with patch("scripts.validation.rework.ValidationGitHubClient") as mock_client_cls:
            mock_client = MagicMock()
            mock_client_cls.return_value = mock_client
            mock_client.get_pull_request.return_value = PullRequestInfo(
                number=404,
                title="Test PR",
                state="open",
                merged=False,
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
                dry_run=True,
            )

        self.assertEqual(result.status, "dry_run")
        self.assertEqual(result.issue_number, 404)
        self.assertIsNotNone(result.run_id)
        self.assertIn("rework", result.run_id or "")

    def test_merged_pr_returns_skip(self):
        with patch("scripts.validation.rework.ValidationGitHubClient") as mock_client_cls:
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
        with patch("scripts.validation.rework.ValidationGitHubClient") as mock_client_cls:
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
        with patch("scripts.validation.rework.ValidationGitHubClient") as mock_client_cls:
            mock_client = MagicMock()
            mock_client_cls.return_value = mock_client
            mock_client.get_pull_request.return_value = PullRequestInfo(
                number=1,
                title="Test",
                state="open",
                merged=False,
                head_ref="fix",
                base_ref="main",
                html_url="",
            )

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
                     "reviewer_usernames", "diff", "review_threads"]
        for field in required:
            self.assertIn(f"{{{field}}}", content, f"Missing placeholder {{{field}}} in prompt template")


if __name__ == "__main__":
    unittest.main()
