from __future__ import annotations

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
    main,
    parse_args,
)


class BuildParserTests(unittest.TestCase):
    def test_parser_has_four_subcommands(self):
        parser = build_parser()
        subcommands = {name for name, _ in parser._subparsers._group_actions[0].choices.items()}
        self.assertEqual(subcommands, {"run", "report", "check-prs", "list"})

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
        args = parse_args(["check-prs", "--issues", "1", "2", "3"])
        self.assertEqual(args.command, "check-prs")
        self.assertEqual(args.issues, ["1", "2", "3"])

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
        args = parse_args(["run", "--dry-run", "--issues", "1"])
        with patch("scripts.validation.cli.select_issues_by_label") as mock_select:
            from scripts.validation.models import ValidationIssue
            mock_select.return_value = [
                ValidationIssue(number=1, title="Test", body="body"),
            ]
            exit_code = cmd_run(args, config)
            self.assertEqual(exit_code, 0)

    def test_cmd_run_no_issues_returns_one(self):
        config = {"GITHUB_OWNER": "test-owner"}
        args = parse_args(["run"])
        with patch("scripts.validation.cli.select_issues_by_label") as mock_select:
            mock_select.return_value = []
            exit_code = cmd_run(args, config)
            self.assertEqual(exit_code, 1)


class CmdReportTests(unittest.TestCase):
    def test_cmd_report_no_reports_returns_one(self):
        config = {"GITHUB_OWNER": "test-owner"}
        args = parse_args(["report", "--no-github"])
        with patch("scripts.validation.cli.collect_run_reports") as mock_collect:
            mock_collect.return_value = []
            exit_code = cmd_report(args, config)
            self.assertEqual(exit_code, 1)


class CmdCheckPrsTests(unittest.TestCase):
    def test_cmd_check_prs_no_issues_found(self):
        config = {"GITHUB_OWNER": "test-owner", "GITHUB_TOKEN": "test"}
        args = parse_args(["check-prs", "--issues", "999"])
        with patch("scripts.validation.cli.ValidationGitHubClient.get_pull_requests") as mock_get_prs:
            mock_get_prs.return_value = []
            exit_code = cmd_check_prs(args, config)
            self.assertEqual(exit_code, 0)


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


if __name__ == "__main__":
    unittest.main()
