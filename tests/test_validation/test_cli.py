from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.validation.cli import (  # noqa: E402
    build_parser,
    cmd_check_prs,
    cmd_list,
    cmd_report,
    cmd_run,
    cmd_split,
    main,
    parse_args,
)


class BuildParserTests(unittest.TestCase):
    def test_parser_has_five_subcommands(self):
        parser = build_parser()
        subcommands = {name for name, _ in parser._subparsers._group_actions[0].choices.items()}
        self.assertEqual(subcommands, {"run", "report", "check-prs", "list", "split"})

    def test_parser_requires_subcommand(self):
        with self.assertRaises(SystemExit):
            parse_args([])

    def test_run_subcommand_parses_issues(self):
        args = parse_args(["run", "--issues", "5"])
        self.assertEqual(args.command, "run")
        self.assertEqual(args.issues, 5)

    def test_run_dry_run_flag(self):
        args = parse_args(["run", "--dry-run"])
        self.assertTrue(args.dry_run)

    def test_run_default_issues(self):
        args = parse_args(["run"])
        self.assertEqual(args.issues, 3)

    def test_report_subcommand(self):
        args = parse_args(["report"])
        self.assertEqual(args.command, "report")

    def test_report_no_github_flag(self):
        args = parse_args(["report", "--no-github"])
        self.assertTrue(args.no_github)

    def test_check_prs_subcommand(self):
        args = parse_args(["check-prs", "--numbers", "1", "2", "3"])
        self.assertEqual(args.command, "check-prs")
        self.assertEqual(args.numbers, ["1", "2", "3"])

    def test_check_prs_deprecated_issues_alias_still_accepted(self):
        """`--issues` is a deprecated alias that still populates
        args.issues. `cmd_check_prs` then merges both `--numbers` and
        `--issues` into the lookup set."""
        args = parse_args(["check-prs", "--issues", "9"])
        # Namespace exposes both — they are separate argparse attributes
        # that cmd_check_prs reads and merges.
        self.assertEqual(args.issues, ["9"])
        self.assertIsNone(args.numbers)

    def test_list_subcommand(self):
        args = parse_args(["list", "--label", "bug"])
        self.assertEqual(args.command, "list")
        self.assertEqual(args.label, "bug")

    def test_list_default_label(self):
        args = parse_args(["list"])
        self.assertEqual(args.label, "ai-generated")

    def test_run_with_all_options(self):
        args = parse_args([
            "--title", "custom-report",
            "--repo", "my-repo",
            "run", "--issues", "5", "--label", "bug",
            "--model", "claude", "--model-name", "claude-sonnet-4-20250514",
            "--max-run-cost-usd", "10.0", "--base-branch", "develop",
            "--dry-run", "--output", "custom.md",
        ])
        self.assertEqual(args.issues, 5)
        self.assertEqual(args.label, "bug")
        self.assertEqual(args.model, "claude")
        self.assertEqual(args.max_run_cost_usd, 10.0)
        self.assertEqual(args.base_branch, "develop")
        self.assertTrue(args.dry_run)
        self.assertEqual(args.output, "custom.md")
        self.assertEqual(args.title, "custom-report")
        self.assertEqual(args.repo, "my-repo")


class CmdRunTests(unittest.TestCase):
    def test_cmd_run_dry_run_returns_zero(self):
        config = {"GITHUB_OWNER": "test-owner"}
        args = parse_args(
            [
                "run", "--dry-run", "--issues", "1",
                "--model", "opencode",
                "--model-name", "opencode/deepseek-v4-flash-free",
            ]
        )
        with patch("scripts.validation.cli.select_issues_by_label") as mock_select:
            from scripts.validation.models import ValidationIssue
            mock_select.return_value = [
                ValidationIssue(number=1, title="Test", body="body"),
            ]
            exit_code = cmd_run(args, config)
            self.assertEqual(exit_code, 0)

    def test_cmd_run_no_issues_returns_one(self):
        config = {"GITHUB_OWNER": "test-owner"}
        args = parse_args(
            [
                "run",
                "--model", "opencode",
                "--model-name", "opencode/deepseek-v4-flash-free",
            ]
        )
        with patch("scripts.validation.cli.select_issues_by_label") as mock_select:
            mock_select.return_value = []
            exit_code = cmd_run(args, config)
            self.assertEqual(exit_code, 1)

    def test_cmd_run_missing_model_returns_one(self):
        """Without --model/--model-name (or env), cmd_run fails fast."""
        config = {"GITHUB_OWNER": "test-owner"}
        # No --model flag, no env vars → should fail-fast
        for key in ("OPENCODE_MODEL", "OPENCODE_MODEL_NAME"):
            os.environ.pop(key, None)
        args = parse_args(["run", "--dry-run", "--issues", "1"])
        with patch("scripts.validation.cli.select_issues_by_label") as mock_select:
            from scripts.validation.models import ValidationIssue
            mock_select.return_value = [
                ValidationIssue(number=1, title="Test", body="body"),
            ]
            exit_code = cmd_run(args, config)
            self.assertEqual(exit_code, 1)

    def test_cmd_run_missing_owner_returns_nonzero(self):
        """Without GITHUB_OWNER in config, cmd_run fails fast."""
        config: dict = {}  # no GITHUB_OWNER
        args = parse_args(
            [
                "run", "--dry-run", "--issues", "1",
                "--model", "opencode",
                "--model-name", "opencode/deepseek-v4-flash-free",
            ]
        )
        exit_code = cmd_run(args, config)
        self.assertNotEqual(exit_code, 0)


class CmdReportTests(unittest.TestCase):
    def test_cmd_report_no_reports_returns_one(self):
        config = {"GITHUB_OWNER": "test-owner"}
        args = parse_args(["report", "--no-github"])
        with patch("scripts.validation.cli.collect_run_reports") as mock_collect:
            mock_collect.return_value = []
            exit_code = cmd_report(args, config)
            self.assertEqual(exit_code, 1)


class CmdCheckPrsTests(unittest.TestCase):
    def test_cmd_check_prs_no_pr_found(self):
        """When neither get_pull_request nor branch lookup finds a PR,
        the command reports the number and continues."""
        config = {"GITHUB_OWNER": "test-owner", "GITHUB_TOKEN": "test"}
        args = parse_args(["check-prs", "--numbers", "999"])
        with patch("scripts.validation.cli.ValidationGitHubClient.get_pull_request", return_value=None), \
             patch("scripts.validation.cli.ValidationGitHubClient.get_pull_requests", return_value=[]):
            exit_code = cmd_check_prs(args, config)
        self.assertEqual(exit_code, 0)

    def test_cmd_check_prs_resolves_pr_by_number(self):
        """PR-by-number is the primary lookup path. Works for merged
        PRs whose branch was deleted by --delete-branch."""
        config = {"GITHUB_OWNER": "test-owner", "GITHUB_TOKEN": "test"}
        args = parse_args(["check-prs", "--numbers", "416"])
        fake_pr = MagicMock(
            number=416, title="Test PR", merged=True,
            merge_commit_sha="deadbeef", head_sha="abc1234",
        )
        fake_ci = MagicMock(state="success")
        with patch("scripts.validation.cli.ValidationGitHubClient.get_pull_request", return_value=fake_pr) as mock_pr_lookup, \
             patch("scripts.validation.cli.ValidationGitHubClient.get_pull_requests") as mock_branch_fallback, \
             patch("scripts.validation.cli.ValidationGitHubClient.get_combined_ci_status", return_value=fake_ci) as mock_ci, \
             patch("builtins.print") as mock_print:
            exit_code = cmd_check_prs(args, config)
        self.assertEqual(exit_code, 0)
        mock_pr_lookup.assert_called_once_with("ai-issue-solver", 416)
        # Branch fallback must NOT be called when PR-by-number succeeds
        mock_branch_fallback.assert_not_called()
        # CI must be queried on the head_sha (not merge_commit_sha)
        mock_ci.assert_called_once_with("ai-issue-solver", "abc1234")
        # Output line must include the PR number + GREEN status
        printed = "\n".join(str(c.args[0]) for c in mock_print.call_args_list)
        self.assertIn("#416", printed)
        self.assertIn("MERGED", printed)
        self.assertIn("CI:GREEN", printed)

    def test_cmd_check_prs_falls_back_to_branch_lookup(self):
        """When get_pull_request returns None (e.g. number is a real
        issue, not a PR), the script falls back to the
        `ai/fix-issue-{N}` branch lookup for legacy open-PR support."""
        config = {"GITHUB_OWNER": "test-owner", "GITHUB_TOKEN": "test"}
        args = parse_args(["check-prs", "--numbers", "42"])
        fake_pr = MagicMock(
            number=99, title="Branch-found PR", merged=False,
            merge_commit_sha=None, head_sha="",
        )
        with patch("scripts.validation.cli.ValidationGitHubClient.get_pull_request", return_value=None), \
             patch("scripts.validation.cli.ValidationGitHubClient.get_pull_requests", return_value=[fake_pr]) as mock_branch, \
             patch("builtins.print") as mock_print:
            exit_code = cmd_check_prs(args, config)
        self.assertEqual(exit_code, 0)
        # Branch lookup was called with the conventional branch name
        mock_branch.assert_called_once_with("ai-issue-solver", head="test-owner:ai/fix-issue-42")
        printed = "\n".join(str(c.args[0]) for c in mock_print.call_args_list)
        self.assertIn("#99", printed)
        self.assertIn("open", printed)

    def test_cmd_check_prs_open_pr_uses_head_sha_for_ci(self):
        """For OPEN PRs with no merge_commit_sha, CI is queried on
        the head_sha (the latest commit, where CI actually ran)."""
        config = {"GITHUB_OWNER": "test-owner", "GITHUB_TOKEN": "test"}
        args = parse_args(["check-prs", "--numbers", "500"])
        fake_pr = MagicMock(
            number=500, title="Open PR", merged=False,
            merge_commit_sha=None, head_sha="opensha",
        )
        with patch("scripts.validation.cli.ValidationGitHubClient.get_pull_request", return_value=fake_pr), \
             patch("scripts.validation.cli.ValidationGitHubClient.get_combined_ci_status") as mock_ci, \
             patch("builtins.print"):
            cmd_check_prs(args, config)
        mock_ci.assert_called_once_with("ai-issue-solver", "opensha")


class CmdListTests(unittest.TestCase):
    def test_cmd_list_no_issues(self):
        config = {"GITHUB_OWNER": "test-owner", "GITHUB_TOKEN": "test"}
        args = parse_args(["list"])
        with patch("scripts.validation.cli.select_issues_by_label") as mock_select:
            mock_select.return_value = []
            exit_code = cmd_list(args, config)
            self.assertEqual(exit_code, 0)

    def test_cmd_list_shows_issues(self):
        config = {"GITHUB_OWNER": "test-owner", "GITHUB_TOKEN": "test"}
        args = parse_args(["list"])
        with patch("scripts.validation.cli.select_issues_by_label") as mock_select:
            from scripts.validation.models import ValidationIssue
            mock_select.return_value = [
                ValidationIssue(number=1, title="Fix", body="", labels=("ai-generated",)),
            ]
            exit_code = cmd_list(args, config)
            self.assertEqual(exit_code, 0)


class CmdSplitTests(unittest.TestCase):
    def test_cmd_split_not_oversized(self):
        config = {"GITHUB_OWNER": "test-owner", "GITHUB_TOKEN": "test"}
        args = parse_args(["split", "--pr", "42"])
        with patch("scripts.validation.cli.decompose_pr_to_sub_issues") as mock_split:
            mock_split.return_value = {
                "is_oversized": False,
                "total_loc": 100,
                "total_files": 3,
                "sub_issues": [],
            }
            exit_code = cmd_split(args, config)
            self.assertEqual(exit_code, 0)

    def test_cmd_split_oversized_creates_issues(self):
        config = {"GITHUB_OWNER": "test-owner", "GITHUB_TOKEN": "test"}
        args = parse_args(["split", "--pr", "42"])
        with patch("scripts.validation.cli.decompose_pr_to_sub_issues") as mock_split:
            mock_split.return_value = {
                "is_oversized": True,
                "total_loc": 600,
                "total_files": 12,
                "sub_issues": [
                    {"number": 100, "title": "sub-1"},
                    {"number": 101, "title": "sub-2"},
                ],
                "manual_review_files": [],
            }
            exit_code = cmd_split(args, config)
            self.assertEqual(exit_code, 0)

    def test_cmd_split_missing_owner(self):
        config: dict = {}
        args = parse_args(["split", "--pr", "42"])
        exit_code = cmd_split(args, config)
        self.assertNotEqual(exit_code, 0)

    def test_cmd_split_pr_not_found(self):
        config = {"GITHUB_OWNER": "test-owner", "GITHUB_TOKEN": "test"}
        args = parse_args(["split", "--pr", "42"])
        with patch("scripts.validation.cli.decompose_pr_to_sub_issues") as mock_split:
            mock_split.side_effect = ValueError("PR #42 not found")
            exit_code = cmd_split(args, config)
            self.assertEqual(exit_code, 1)

    def test_split_subcommand_parses_pr(self):
        args = parse_args(["split", "--pr", "42"])
        self.assertEqual(args.command, "split")
        self.assertEqual(args.pr, 42)

    def test_split_subcommand_close_parent_flag(self):
        args = parse_args(["split", "--pr", "42", "--close-parent"])
        self.assertTrue(args.close_parent)

    def test_split_subcommand_custom_thresholds(self):
        args = parse_args(["split", "--pr", "42", "--max-loc", "1000", "--max-files", "20"])
        self.assertEqual(args.max_loc, 1000)
        self.assertEqual(args.max_files, 20)


class MainTests(unittest.TestCase):
    def test_main_handles_argument_error_gracefully(self):
        with patch("scripts.validation.cli.parse_args") as mock_parse:
            mock_parse.side_effect = SystemExit(2)
            with self.assertRaises(SystemExit):
                main(["unknown"])

    def test_main_with_run_dry_run(self):
        with patch("scripts.validation.cli.cmd_run") as mock_run:
            mock_run.return_value = 0
            exit_code = main(["run", "--dry-run", "--issues", "1"])
            self.assertEqual(exit_code, 0)
            mock_run.assert_called_once()

    def test_main_with_report(self):
        with patch("scripts.validation.cli.cmd_report") as mock_report:
            mock_report.return_value = 0
            exit_code = main(["report", "--no-github"])
            self.assertEqual(exit_code, 0)
            mock_report.assert_called_once()

    def test_main_with_check_prs(self):
        with patch("scripts.validation.cli.cmd_check_prs") as mock_check:
            mock_check.return_value = 0
            exit_code = main(["check-prs"])
            self.assertEqual(exit_code, 0)
            mock_check.assert_called_once()

    def test_main_with_list(self):
        with patch("scripts.validation.cli.cmd_list") as mock_list:
            mock_list.return_value = 0
            exit_code = main(["list"])
            self.assertEqual(exit_code, 0)
            mock_list.assert_called_once()

    def test_main_with_split(self):
        with patch("scripts.validation.cli.cmd_split") as mock_split:
            mock_split.return_value = 0
            exit_code = main(["split", "--pr", "42"])
            self.assertEqual(exit_code, 0)
            mock_split.assert_called_once()


if __name__ == "__main__":
    unittest.main()
