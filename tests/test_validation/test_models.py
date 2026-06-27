from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from validation.models import (  # noqa: E402
    RunReportData,
    ValidationConfig,
    ValidationIssue,
    ValidationMetrics,
)


class ValidationIssueTests(unittest.TestCase):
    def test_constructs_with_minimal_args(self):
        issue = ValidationIssue(number=42, title="Fix bug", body="details")
        self.assertEqual(issue.number, 42)
        self.assertEqual(issue.title, "Fix bug")
        self.assertEqual(issue.body, "details")

    def test_constructs_with_all_args(self):
        issue = ValidationIssue(
            number=1,
            title="Test",
            body="body",
            labels=("bug", "ai-generated"),
            state="open",
            html_url="https://github.com/owner/repo/issues/1",
            repo="test-repo",
        )
        self.assertEqual(issue.labels, ("bug", "ai-generated"))
        self.assertEqual(issue.html_url, "https://github.com/owner/repo/issues/1")

    def test_default_values(self):
        issue = ValidationIssue(number=0, title="", body="")
        self.assertEqual(issue.labels, ())
        self.assertEqual(issue.state, "open")
        self.assertEqual(issue.html_url, "")
        self.assertEqual(issue.repo, "")


class RunReportDataTests(unittest.TestCase):
    def test_constructs_with_minimal_args(self):
        report = RunReportData(issue_number=42, issue_title="test", status="success")
        self.assertEqual(report.issue_number, 42)
        self.assertEqual(report.status, "success")

    def test_defaults_are_none_or_empty(self):
        report = RunReportData(issue_number=0, issue_title="", status="")
        self.assertIsNone(report.pr_number)
        self.assertIsNone(report.error_class)

    def test_frozen_prevents_mutation(self):
        report = RunReportData(issue_number=1, issue_title="t", status="s")
        with self.assertRaises(AttributeError):
            report.status = "changed"


class ValidationConfigTests(unittest.TestCase):
    def test_default_values(self):
        """Defaults are empty for user/repo/model (no hardcoded fallback) and
        retain only structural defaults."""
        cfg = ValidationConfig()
        # User/repo/model are intentionally empty (no silent defaults)
        self.assertEqual(cfg.repo, "")
        self.assertEqual(cfg.owner, "")
        self.assertEqual(cfg.model, "")
        self.assertEqual(cfg.model_name, "")
        # Structural defaults stay
        self.assertEqual(cfg.max_issues, 3)
        self.assertEqual(cfg.max_run_cost_usd, 5.0)
        self.assertFalse(cfg.dry_run)

    def test_custom_values(self):
        cfg = ValidationConfig(
            repo="other", owner="someone", model="opencode",
            model_name="opencode/deepseek-v4-flash-free",
            max_issues=10, dry_run=True,
        )
        self.assertEqual(cfg.repo, "other")
        self.assertEqual(cfg.owner, "someone")
        self.assertEqual(cfg.model, "opencode")
        self.assertEqual(cfg.model_name, "opencode/deepseek-v4-flash-free")
        self.assertEqual(cfg.max_issues, 10)
        self.assertTrue(cfg.dry_run)

    def test_required_user_repo_can_be_omitted_at_construction(self):
        """User is expected to fill owner/repo from config; empty default is fine."""
        cfg = ValidationConfig()
        self.assertEqual(cfg.owner, "")


class ValidationMetricsTests(unittest.TestCase):
    def test_empty_metrics(self):
        metrics = ValidationMetrics()
        self.assertEqual(metrics.total_processed, 0)
        self.assertEqual(metrics.success_rate, 0.0)
        self.assertIsNone(metrics.cost_per_solved)
        self.assertIsNone(metrics.time_per_solved)
        self.assertEqual(len(metrics.top_errors), 0)

    def test_success_rate(self):
        report = RunReportData(issue_number=1, issue_title="t", status="s")
        metrics = ValidationMetrics(
            total_processed=4,
            total_merged=3,
            per_issue=(report, report, report, report),
        )
        self.assertEqual(metrics.success_rate, 0.75)

    def test_cost_per_solved(self):
        metrics = ValidationMetrics(
            total_processed=2,
            total_merged=2,
            total_cost_usd=10.0,
        )
        self.assertEqual(metrics.cost_per_solved, 5.0)

    def test_no_solved_returns_none_cost(self):
        metrics = ValidationMetrics(total_processed=2, total_merged=0, total_cost_usd=5.0)
        self.assertIsNone(metrics.cost_per_solved)

    def test_time_per_solved(self):
        metrics = ValidationMetrics(
            total_processed=2,
            total_merged=2,
            total_duration_seconds=120.0,
        )
        self.assertEqual(metrics.time_per_solved, 60.0)

    def test_top_errors_returns_top_five(self):
        errors = (
            ("timeout", 10),
            ("rate_limit", 5),
            ("permission", 3),
            ("not_found", 2),
            ("unknown", 1),
            ("timeout2", 1),
        )
        metrics = ValidationMetrics(total_processed=20, total_merged=5, errors=errors)
        self.assertEqual(len(metrics.top_errors), 5)
        self.assertEqual(metrics.top_errors[0], ("timeout", 10))

    def test_top_errors_with_fewer_than_five(self):
        errors = (("timeout", 3), ("rate_limit", 1))
        metrics = ValidationMetrics(total_processed=5, total_merged=2, errors=errors)
        self.assertEqual(len(metrics.top_errors), 2)

    def test_empty_errors_returns_empty_tuple(self):
        metrics = ValidationMetrics(total_processed=1, total_merged=0)
        self.assertEqual(len(metrics.top_errors), 0)


if __name__ == "__main__":
    unittest.main()
