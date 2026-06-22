from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.validation.models import RunReportData  # noqa: E402
from scripts.validation.runner import (  # noqa: E402
    run_reviewer_for_pr,
    run_solver_for_issue,
)


class RunSolverForIssueTests(unittest.TestCase):
    @patch("scripts.validation.runner.subprocess.run")
    def test_dry_run_returns_early(self, mock_run):
        result = run_solver_for_issue(
            repo="test-repo",
            model="opencode",
            model_name="opencode/deepseek-v4-flash-free",
            issue_number=42,
            dry_run=True,
        )
        self.assertEqual(result.status, "dry_run")
        self.assertEqual(result.duration_seconds, 0.0)
        mock_run.assert_not_called()

    @patch("scripts.validation.runner.subprocess.run")
    def test_successful_run_returns_success(self, mock_run):
        mock_process = MagicMock()
        mock_process.returncode = 0
        mock_process.stdout = "PR created: #100\n"
        mock_process.stderr = ""
        mock_run.return_value = mock_process

        result = run_solver_for_issue(
            repo="test-repo",
            model="opencode",
            model_name="opencode/deepseek-v4-flash-free",
            issue_number=42,
            dry_run=False,
        )
        self.assertEqual(result.status, "success")
        self.assertIsNone(result.error_class)

    @patch("scripts.validation.runner.subprocess.run")
    def test_failed_run_sets_error_class(self, mock_run):
        mock_process = MagicMock()
        mock_process.returncode = 1
        mock_process.stdout = ""
        mock_process.stderr = "timeout exceeded"
        mock_run.return_value = mock_process

        result = run_solver_for_issue(
            repo="test-repo",
            model="opencode",
            model_name="opencode/deepseek-v4-flash-free",
            issue_number=42,
            dry_run=False,
        )
        self.assertEqual(result.status, "failed")
        self.assertIsNotNone(result.error_class)

    @patch("scripts.validation.runner.subprocess.run")
    def test_rate_limit_error_detected(self, mock_run):
        mock_process = MagicMock()
        mock_process.returncode = 1
        mock_process.stdout = ""
        mock_process.stderr = "rate limit exceeded"
        mock_run.return_value = mock_process

        result = run_solver_for_issue(
            repo="test-repo",
            model="opencode",
            model_name="opencode/deepseek-v4-flash-free",
            issue_number=42,
            dry_run=False,
        )
        self.assertEqual(result.error_class, "rate_limit")

    @patch("scripts.validation.runner.subprocess.run")
    def test_permission_error_detected(self, mock_run):
        mock_process = MagicMock()
        mock_process.returncode = 1
        mock_process.stdout = ""
        mock_process.stderr = "permission denied"
        mock_run.return_value = mock_process

        result = run_solver_for_issue(
            repo="test-repo",
            model="opencode",
            model_name="opencode/deepseek-v4-flash-free",
            issue_number=42,
            dry_run=False,
        )
        self.assertEqual(result.error_class, "permission")

    @patch("scripts.validation.runner.subprocess.run")
    def test_timeout_is_handled(self, mock_run):
        import subprocess
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="test", timeout=30)

        result = run_solver_for_issue(
            repo="test-repo",
            model="opencode",
            model_name="opencode/deepseek-v4-flash-free",
            issue_number=42,
            timeout_seconds=30,
            dry_run=False,
        )
        self.assertEqual(result.status, "timeout")
        self.assertEqual(result.error_class, "timeout")

    def test_returns_run_report_dataclass(self):
        result = run_solver_for_issue(
            repo="test-repo",
            model="opencode",
            model_name="opencode/deepseek-v4-flash-free",
            issue_number=1,
            dry_run=True,
        )
        self.assertIsInstance(result, RunReportData)


class RunReviewerForPrTests(unittest.TestCase):
    @patch("scripts.validation.runner.subprocess.run")
    def test_dry_run_returns_early(self, mock_run):
        mock_process = MagicMock()
        mock_process.returncode = 0
        mock_run.return_value = mock_process
        result = run_reviewer_for_pr(pr_number=100, dry_run=True)
        self.assertEqual(result["status"], "success")
        mock_run.assert_called_once()

    @patch("scripts.validation.runner.subprocess.run")
    def test_successful_review(self, mock_run):
        mock_process = MagicMock()
        mock_process.returncode = 0
        mock_process.stdout = "**Verdict**: approve\n"
        mock_process.stderr = ""
        mock_run.return_value = mock_process

        result = run_reviewer_for_pr(pr_number=100, dry_run=False)
        self.assertEqual(result["status"], "success")

    @patch("scripts.validation.runner.subprocess.run")
    def test_failed_review(self, mock_run):
        mock_process = MagicMock()
        mock_process.returncode = 1
        mock_process.stdout = ""
        mock_process.stderr = "error"
        mock_run.return_value = mock_process

        result = run_reviewer_for_pr(pr_number=100, dry_run=False)
        self.assertEqual(result["status"], "failed")

    @patch("scripts.validation.runner.subprocess.run")
    def test_timeout_is_handled(self, mock_run):
        import subprocess
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="test", timeout=30)

        result = run_reviewer_for_pr(pr_number=100, timeout_seconds=30)
        self.assertEqual(result["status"], "timeout")


if __name__ == "__main__":
    unittest.main()
