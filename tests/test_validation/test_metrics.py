from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.validation.metrics import (  # noqa: E402
    compute_metrics,
    format_cost,
    format_duration,
    generate_report,
    is_oversized,
    load_thresholds,
    persist_validation_run,
    write_validation_report,
)
from scripts.validation.models import (  # noqa: E402
    RunReportData,
    ValidationMetrics,
)


class ComputeMetricsTests(unittest.TestCase):
    def test_empty_reports(self):
        metrics = compute_metrics([])
        self.assertEqual(metrics.total_processed, 0)
        self.assertEqual(metrics.total_merged, 0)
        self.assertEqual(metrics.success_rate, 0.0)

    def test_all_merged_and_green(self):
        reports = [
            RunReportData(issue_number=1, issue_title="A", status="success", pr_number=10, pr_merged=True, ci_green=True, cost_usd=1.0, duration_seconds=100.0),
            RunReportData(issue_number=2, issue_title="B", status="success", pr_number=11, pr_merged=True, ci_green=True, cost_usd=2.0, duration_seconds=200.0),
        ]
        metrics = compute_metrics(reports)
        self.assertEqual(metrics.total_processed, 2)
        self.assertEqual(metrics.total_merged, 2)
        self.assertEqual(metrics.total_prs_created, 2)
        self.assertEqual(metrics.total_cost_usd, 3.0)
        self.assertEqual(metrics.total_duration_seconds, 300.0)
        self.assertEqual(metrics.success_rate, 1.0)

    def test_mixed_results(self):
        reports = [
            RunReportData(issue_number=1, issue_title="A", status="success", pr_number=10, pr_merged=True, cost_usd=1.0, duration_seconds=50.0),
            RunReportData(issue_number=2, issue_title="B", status="pr_created", pr_number=11, pr_merged=False, cost_usd=0.5, duration_seconds=30.0),
            RunReportData(issue_number=3, issue_title="C", status="failed", error_class="timeout", cost_usd=0.1, duration_seconds=10.0),
        ]
        metrics = compute_metrics(reports)
        self.assertEqual(metrics.total_processed, 3)
        self.assertEqual(metrics.total_merged, 1)
        self.assertEqual(metrics.total_prs_created, 2)
        self.assertEqual(metrics.success_rate, 1.0 / 3.0)

    def test_counts_errors(self):
        reports = [
            RunReportData(issue_number=1, issue_title="", status="failed", error_class="timeout"),
            RunReportData(issue_number=2, issue_title="", status="failed", error_class="timeout"),
            RunReportData(issue_number=3, issue_title="", status="failed", error_class="rate_limit"),
        ]
        metrics = compute_metrics(reports)
        self.assertEqual(len(metrics.errors), 2)
        error_dict = dict(metrics.errors)
        self.assertEqual(error_dict["timeout"], 2)
        self.assertEqual(error_dict["rate_limit"], 1)

    def test_handles_none_cost_and_duration(self):
        reports = [
            RunReportData(issue_number=1, issue_title="A", status="success"),
        ]
        metrics = compute_metrics(reports)
        self.assertEqual(metrics.total_cost_usd, 0.0)
        self.assertEqual(metrics.total_duration_seconds, 0.0)

    def test_per_issue_preserves_order(self):
        reports = [
            RunReportData(issue_number=3, issue_title="C", status="failed"),
            RunReportData(issue_number=1, issue_title="A", status="success"),
        ]
        metrics = compute_metrics(reports)
        self.assertEqual(len(metrics.per_issue), 2)
        self.assertEqual(metrics.per_issue[0].issue_number, 3)


class FormatDurationTests(unittest.TestCase):
    def test_seconds(self):
        self.assertEqual(format_duration(45), "45s")

    def test_minutes(self):
        self.assertEqual(format_duration(150), "2.5m")

    def test_hours(self):
        self.assertEqual(format_duration(7200), "2.0h")

    def test_none(self):
        self.assertEqual(format_duration(None), "N/A")

    def test_zero(self):
        self.assertEqual(format_duration(0), "0s")


class FormatCostTests(unittest.TestCase):
    def test_formats_cost(self):
        result = format_cost(1.2345)
        self.assertIn("$", result)
        self.assertIn("1.2345", result)

    def test_zero(self):
        self.assertEqual(format_cost(0.0), "$0.0000")

    def test_none(self):
        self.assertEqual(format_cost(None), "N/A")


class GenerateReportTests(unittest.TestCase):
    def test_generates_report_with_data(self):
        reports = [
            RunReportData(issue_number=1, issue_title="Fix bug", status="success", pr_number=10, pr_merged=True, ci_green=True, cost_usd=1.0, duration_seconds=60.0),
        ]
        metrics = compute_metrics(reports)
        report = generate_report(metrics, title="test-report")
        self.assertIn("Validation Report: test-report", report)
        self.assertIn("#1", report)
        self.assertIn("Fix bug", report)
        self.assertIn("100.0%", report)

    def test_generates_report_with_top_errors(self):
        reports = [
            RunReportData(issue_number=1, issue_title="", status="failed", error_class="timeout"),
        ]
        metrics = compute_metrics(reports)
        report = generate_report(metrics)
        self.assertIn("timeout", report)
        self.assertIn("Top Error Classes", report)

    def test_generates_report_without_errors(self):
        metrics = ValidationMetrics(total_processed=1, total_merged=1)
        report = generate_report(metrics)
        self.assertNotIn("Top Error Classes", report)

    def test_generates_empty_per_issue_table(self):
        metrics = ValidationMetrics()
        report = generate_report(metrics)
        self.assertIn("Per-Issue Results", report)


class WriteValidationReportTests(unittest.TestCase):
    def test_writes_report_to_disk(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "report.md"
            metrics = ValidationMetrics(total_processed=1, total_merged=1)
            write_validation_report(metrics, output, title="test")
            self.assertTrue(output.is_file())
            content = output.read_text(encoding="utf-8")
            self.assertIn("Validation Report: test", content)


class PersistValidationRunTests(unittest.TestCase):
    def test_persists_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            reports_dir = Path(tmpdir) / "validation"
            metrics = ValidationMetrics(total_processed=2, total_merged=1)
            path = persist_validation_run(metrics, reports_dir, run_id="test-run")
            self.assertTrue(path.is_file())
            import json
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(data["run_id"], "test-run")
            self.assertEqual(data["total_processed"], 2)
            self.assertEqual(data["total_merged"], 1)

    def test_persists_with_auto_run_id(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            reports_dir = Path(tmpdir) / "validation"
            metrics = ValidationMetrics(total_processed=1, total_merged=0)
            path = persist_validation_run(metrics, reports_dir)
            self.assertTrue(path.is_file())
            self.assertIn("validation-", path.stem)


class IsOversizedTests(unittest.TestCase):
    def test_under_threshold_returns_false(self):
        self.assertFalse(is_oversized(100, 3, 0.5, {"max_loc": 500, "max_files": 10, "test_ratio": 0.3}))

    def test_over_loc_returns_true(self):
        self.assertTrue(is_oversized(600, 3, 0.5))

    def test_over_files_returns_true(self):
        self.assertTrue(is_oversized(100, 15, 0.5))

    def test_low_test_ratio_returns_true(self):
        self.assertTrue(is_oversized(100, 3, 0.1))

    def test_custom_thresholds(self):
        thresholds = {"max_loc": 1000, "max_files": 20, "test_ratio": 0.5}
        self.assertFalse(is_oversized(800, 15, 0.6, thresholds))
        self.assertTrue(is_oversized(800, 15, 0.3, thresholds))

    def test_zero_values(self):
        self.assertFalse(is_oversized(0, 0, 1.0))

    def test_load_thresholds_defaults(self):
        thresholds = load_thresholds()
        self.assertEqual(thresholds["max_loc"], 500)
        self.assertEqual(thresholds["max_files"], 10)
        self.assertEqual(thresholds["test_ratio"], 0.3)

    def test_load_thresholds_with_overrides(self):
        thresholds = load_thresholds({"max_loc": 999, "max_files": 50})
        self.assertEqual(thresholds["max_loc"], 999)
        self.assertEqual(thresholds["max_files"], 50)
        self.assertEqual(thresholds["test_ratio"], 0.3)


if __name__ == "__main__":
    unittest.main()
