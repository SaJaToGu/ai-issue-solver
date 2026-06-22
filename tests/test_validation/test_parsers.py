from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.validation.parsers import (  # noqa: E402
    collect_run_reports,
    parse_summary_file,
    read_run_report,
)


class ParseSummaryFileTests(unittest.TestCase):
    def test_parses_valid_summary(self):
        content = """status: success
issue_number: 42
issue_title: Fix the bug
pr_number: 100
pr_url: https://github.com/owner/repo/pull/100
duration_seconds: 123.45
cost_usd: 0.5678
model: opencode/deepseek-v4-flash-free
run_id: run-20240601-123456
started_at: 2024-06-01T12:00:00
finished_at: 2024-06-01T12:02:03
error_class: timeout
error_detail: subprocess timed out
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write(content)
            f.flush()
            path = Path(f.name)

        try:
            result = parse_summary_file(path)
            self.assertEqual(result["status"], "success")
            self.assertEqual(result["issue_number"], 42)
            self.assertEqual(result["issue_title"], "Fix the bug")
            self.assertEqual(result["pr_number"], 100)
            self.assertEqual(result["duration_seconds"], 123.45)
            self.assertEqual(result["cost_usd"], 0.5678)
            self.assertEqual(result["model"], "opencode/deepseek-v4-flash-free")
            self.assertEqual(result["error_class"], "timeout")
        finally:
            path.unlink(missing_ok=True)

    def test_returns_empty_dict_for_empty_content(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("")
            f.flush()
            path = Path(f.name)

        try:
            result = parse_summary_file(path)
            self.assertEqual(result, {})
        finally:
            path.unlink(missing_ok=True)

    def test_parses_partial_content_without_error(self):
        content = "status: failed\nissue_number: 7\n"
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write(content)
            f.flush()
            path = Path(f.name)

        try:
            result = parse_summary_file(path)
            self.assertEqual(result["status"], "failed")
            self.assertEqual(result["issue_number"], 7)
            self.assertNotIn("cost_usd", result)
        finally:
            path.unlink(missing_ok=True)

    def test_raises_on_missing_file(self):
        with self.assertRaises(FileNotFoundError):
            parse_summary_file(Path("/nonexistent/summary.txt"))

    def test_handles_malformed_content_gracefully(self):
        content = "garbage\nnoise=123\nno colon here\n"
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write(content)
            f.flush()
            path = Path(f.name)

        try:
            result = parse_summary_file(path)
            self.assertEqual(result, {})
        finally:
            path.unlink(missing_ok=True)


class ReadRunReportTests(unittest.TestCase):
    def test_reads_from_directory_with_summary(self):
        with tempfile.TemporaryDirectory() as tmpdir_str:
            tmpdir = Path(tmpdir_str)
            summary = tmpdir / "summary.txt"
            summary.write_text("status: success\nissue_number: 10\nissue_title: Test\n")
            report = read_run_report(Path(tmpdir))
            self.assertEqual(report.issue_number, 10)
            self.assertEqual(report.status, "success")
            self.assertEqual(report.issue_title, "Test")

    def test_raises_on_directory_without_summary(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with self.assertRaises(FileNotFoundError):
                read_run_report(Path(tmpdir))

    def test_reads_from_file_path(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("status: failed\nissue_number: 5\nissue_title: Bug\n")
            f.flush()
            path = Path(f.name)

        try:
            report = read_run_report(path)
            self.assertEqual(report.issue_number, 5)
            self.assertEqual(report.status, "failed")
        finally:
            path.unlink(missing_ok=True)


class CollectRunReportsTests(unittest.TestCase):
    def test_returns_empty_list_for_nonexistent_dir(self):
        reports = collect_run_reports(Path("/nonexistent/dir"))
        self.assertEqual(reports, [])

    def test_returns_empty_list_for_empty_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            reports = collect_run_reports(Path(tmpdir))
            self.assertEqual(reports, [])

    def test_collects_valid_run_reports(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            d1 = Path(tmpdir) / "run1"
            d1.mkdir()
            (d1 / "summary.txt").write_text("status: success\nissue_number: 1\nissue_title: A\n")

            d2 = Path(tmpdir) / "run2"
            d2.mkdir()
            (d2 / "summary.txt").write_text("status: failed\nissue_number: 2\nissue_title: B\n")

            reports = collect_run_reports(Path(tmpdir))
            self.assertEqual(len(reports), 2)
            self.assertEqual(reports[0].issue_number, 1)
            self.assertEqual(reports[1].issue_number, 2)

    def test_skips_directories_without_summary(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            d = Path(tmpdir) / "empty_run"
            d.mkdir()
            reports = collect_run_reports(Path(tmpdir))
            self.assertEqual(reports, [])


if __name__ == "__main__":
    unittest.main()
