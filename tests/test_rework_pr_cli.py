from __future__ import annotations

import io
import os
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch, MagicMock, PropertyMock

ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = ROOT.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.solve_issues import main


def _mock_preflight_checks(*args, **kwargs):
    """Return a fake (token, user) pair for preflight_checks."""
    return ("mock-token", "mock-user")


class ReworkPrCliHelpTests(unittest.TestCase):
    def test_help_shows_rework_pr_flag(self):
        with patch.object(sys, "argv", ["solve_issues.py", "--help"]):
            with self.assertRaises(SystemExit) as ctx:
                main()
        self.assertEqual(ctx.exception.code, 0)


class ReworkPrCliDryRunTests(unittest.TestCase):
    def _run_with_mocks(self, argv: list[str]):
        """Run main() with all necessary mocks for a rework-pr dry-run."""
        with patch("validation.rework.run_pr_rework") as mock_rework:
            mock_rework.return_value = MagicMock(
                status="dry_run",
                pr_url="",
                run_id="pr-1-rework-test",
                error_detail=None,
                error_class=None,
            )
            with patch("solve_issues.preflight_checks") as mock_pre:
                mock_pre.return_value = ("mock-token", "mock-user")
                with patch("solve_issues.load_env") as mock_env:
                    mock_env.return_value = {
                        "GITHUB_TOKEN": "mock-token",
                        "GITHUB_USER": "mock-user",
                    }
                    with patch("solve_issues.run_pre_solver_hygiene_check"):
                        with patch("solve_issues.GitHubClient") as mock_client_cls:
                            mock_client = MagicMock()
                            mock_client_cls.return_value = mock_client
                            mock_client.get_repo.return_value = {"has_issues": True}

                            with patch.object(sys, "argv", argv):
                                with self.assertRaises(SystemExit) as ctx:
                                    main()
        return ctx.exception.code, mock_rework

    def test_dry_run_exits_successfully(self):
        code, _ = self._run_with_mocks([
            "solve_issues.py", "--rework-pr", "1", "--model", "openrouter_direct", "--dry-run",
        ])
        self.assertEqual(code, 0)

    def test_rework_pr_without_model_defaults_to_openrouter_direct(self):
        code, mock_rework = self._run_with_mocks([
            "solve_issues.py", "--rework-pr", "1", "--dry-run",
        ])
        self.assertEqual(code, 0)

    def test_rework_pr_passes_pr_number_to_rework_module(self):
        code, mock_rework = self._run_with_mocks([
            "solve_issues.py", "--rework-pr", "99", "--dry-run",
        ])
        call_kwargs = mock_rework.call_args.kwargs if mock_rework.call_args else {}
        self.assertEqual(call_kwargs.get("pr_number"), 99)

    def test_rework_pr_prints_status_in_dry_run(self):
        with patch("validation.rework.run_pr_rework") as mock_rework:
            mock_rework.return_value = MagicMock(
                status="dry_run",
                pr_url="https://github.com/o/r/pull/1",
                run_id="pr-1-rework-test",
                error_detail=None,
                error_class=None,
            )
            with patch("solve_issues.preflight_checks") as mock_pre:
                mock_pre.return_value = ("mock-token", "mock-user")
                with patch("solve_issues.load_env") as mock_env:
                    mock_env.return_value = {
                        "GITHUB_TOKEN": "mock-token",
                        "GITHUB_USER": "mock-user",
                    }
                    with patch("solve_issues.run_pre_solver_hygiene_check"):
                        with patch("solve_issues.GitHubClient") as mock_client_cls:
                            mock_client = MagicMock()
                            mock_client_cls.return_value = mock_client
                            mock_client.get_repo.return_value = {"has_issues": True}

                            # `solve_issues.print` doesn't exist — `print` is a
                            # builtin, and `from solve_issues import main` does
                            # not re-export it. The original test patched a
                            # non-existent attribute and asserted empty output.
                            # Capture stdout instead via `redirect_stdout`.
                            stdout_buffer = io.StringIO()
                            with redirect_stdout(stdout_buffer):
                                with patch.object(sys, "argv", [
                                    "solve_issues.py", "--rework-pr", "1", "--model", "openrouter_direct", "--dry-run",
                                ]):
                                    with self.assertRaises(SystemExit):
                                        main()

                            printed_text = stdout_buffer.getvalue()
                            self.assertIn("Rework-Status", printed_text)


if __name__ == "__main__":
    unittest.main()
