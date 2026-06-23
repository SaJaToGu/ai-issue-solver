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

# Make this test independent of whether `requests` is installed in the
# active Python env. `validation.rework` (and therefore `solve_issues.py`)
# import `requests` at module load. Without a stub, the test fails with
# `AttributeError: module 'validation' has no attribute 'rework'` (because
# `validation.rework` could not be imported, so it's not registered as a
# submodule of `validation` — `unittest.mock.patch` on the dotted string
# can't bind). Injecting a stub `requests` into `sys.modules` before any
# test runs lets `validation.rework` import cleanly in both Python 3.10
# and 3.12, regardless of whether real `requests` is on the path.
import types as _types
if "requests" not in sys.modules:
    _stub_requests = _types.ModuleType("requests")
    _stub_requests.get = lambda *a, **kw: None  # type: ignore[attr-defined]
    _stub_requests.post = lambda *a, **kw: None  # type: ignore[attr-defined]

    class _StubHeaders:
        def update(self, *a, **kw):
            pass

    class _StubSession:
        def __init__(self, *a, **kw):
            self.headers = _StubHeaders()

        def request(self, *a, **kw):
            class _Resp:
                status_code = 200
                text = "{}"
                def json(self):
                    return {}
            return _Resp()

        def get(self, *a, **kw):
            return self.request(*a, **kw)

        def post(self, *a, **kw):
            return self.request(*a, **kw)

    _stub_requests.Session = _StubSession  # type: ignore[attr-defined]
    sys.modules["requests"] = _stub_requests

# Force-load `validation.rework` so `patch("validation.rework.run_pr_rework")`
# below has a valid attribute path to bind to. With the `requests` stub above,
# this should now succeed on every Python version regardless of env state.
import validation.rework  # noqa: F401

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
        # solve_issues.py does `sys.exit(1)` if its top-level `requests` import
        # fell back to None. In some CI environments `requests` is not on the
        # active Python's path even though it's in requirements.txt. Mock the
        # module reference inside solve_issues so the guard passes regardless.
        import types as _types
        _stub_requests = _types.ModuleType("requests")
        with patch("solve_issues.requests", _stub_requests), \
             patch("validation.rework.run_pr_rework") as mock_rework:
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

                            # `solve_issues.print` doesn't exist (print is a
                            # builtin; `from solve_issues import main` does not
                            # re-export it). Capture stdout via
                            # `redirect_stdout` instead.
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
