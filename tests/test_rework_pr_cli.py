from __future__ import annotations

import io
import sys
import unittest
from contextlib import redirect_stdout, ExitStack
from pathlib import Path
from unittest.mock import patch, MagicMock
from unittest import TestCase

ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = ROOT.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
sys.path.insert(0, str(PROJECT_ROOT))

# Make this test independent of whether `requests` is installed in the
# active Python env. `validation.rework` (and therefore `solve_issues.py`)
# import `requests` at module load. Without a stub, the test fails with
# `AttributeError: module 'validation' has no attribute 'rework'` (because
# `validation.rework` could not be imported, so it's never registered as a
# submodule of `validation` — `unittest.mock.patch` on the dotted string
# can't bind). Injecting a stub `requests` into `sys.modules` before any
# test runs lets `validation.rework` import cleanly in both Python 3.10
# and 3.12, regardless of whether real `requests` is on the path.
import types as _types
if "requests" not in sys.modules:
    _stub_requests = _types.ModuleType("requests")

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
                def json(self_inner):
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
# this succeeds on every Python version regardless of env state.
import validation.rework  # noqa: F401

from scripts.solve_issues import main


def _stub_auth(*args, **kwargs):
    """Return a fake (token, user) pair for both `preflight_checks` and
    `require_github_config`. The rework-pr path in main() picks
    `require_github_config` (NOT `preflight_checks`) when `--repo` is unset
    (see scripts/solve_issues.py around line 4174-4177). The original
    tests only mocked `preflight_checks`, so in CI without GITHUB_TOKEN
    the test failed at the auth check with `sys.exit(1)` before any of
    the test's other mocks could bind.
    """
    return ("mock-token", "mock-user")


class ReworkPrCliHelpTests(unittest.TestCase):
    def test_help_shows_rework_pr_flag(self):
        with patch.object(sys, "argv", ["solve_issues.py", "--help"]):
            with self.assertRaises(SystemExit) as ctx:
                main()
        self.assertEqual(ctx.exception.code, 0)


class ReworkPrCliDryRunTests(unittest.TestCase):
    """Drives `main()` through the --rework-pr dry-run path with all
    external dependencies stubbed (closes #428). Each test exercises one
    assertion on either the exit code, the captured mock_rework call
    args, or the captured stdout."""

    def _run_main(self, argv: list[str], *, capture_stdout: bool = False):
        """Run main() with all required mocks bound via ExitStack.
        Returns (exit_code, mock_rework, captured_stdout_or_None)."""
        with ExitStack() as stack:
            # `solve_issues.requests` must be truthy so the
            # `if requests is None: sys.exit(1)` guard at line 4148 passes.
            stack.enter_context(patch("solve_issues.requests", _types.ModuleType("requests")))
            mock_rework = stack.enter_context(patch("validation.rework.run_pr_rework"))
            mock_rework.return_value = MagicMock(
                status="dry_run",
                pr_url="",
                run_id="pr-1-rework-test",
                error_detail=None,
                error_class=None,
            )
            # Both auth paths must be mocked (see _stub_auth docstring).
            stack.enter_context(patch("solve_issues.require_github_config", _stub_auth))
            stack.enter_context(patch("solve_issues.preflight_checks", _stub_auth))
            mock_env = stack.enter_context(patch("solve_issues.load_env"))
            mock_env.return_value = {
                "GITHUB_TOKEN": "mock-token",
                "GITHUB_USER": "mock-user",
            }
            stack.enter_context(patch("solve_issues.run_pre_solver_hygiene_check"))
            mock_client_cls = stack.enter_context(patch("solve_issues.GitHubClient"))
            mock_client = MagicMock()
            mock_client_cls.return_value = mock_client
            mock_client.get_repo.return_value = {"has_issues": True}
            stack.enter_context(patch.object(sys, "argv", argv))

            stdout_buffer = io.StringIO() if capture_stdout else None
            cm = redirect_stdout(stdout_buffer) if capture_stdout else _NullCM()
            with cm:
                with self.assertRaises(SystemExit) as ctx:
                    main()
            return ctx.exception.code, mock_rework, (stdout_buffer.getvalue() if stdout_buffer else None)

    def test_dry_run_exits_successfully(self):
        code, _, _ = self._run_main([
            "solve_issues.py", "--rework-pr", "1", "--model", "openrouter_direct", "--dry-run",
        ])
        self.assertEqual(code, 0)

    def test_rework_pr_without_model_defaults_to_openrouter_direct(self):
        code, _, _ = self._run_main([
            "solve_issues.py", "--rework-pr", "1", "--dry-run",
        ])
        self.assertEqual(code, 0)

    def test_rework_pr_passes_pr_number_to_rework_module(self):
        code, mock_rework, _ = self._run_main([
            "solve_issues.py", "--rework-pr", "99", "--dry-run",
        ])
        call_kwargs = mock_rework.call_args.kwargs if mock_rework.call_args else {}
        self.assertEqual(call_kwargs.get("pr_number"), 99)

    def test_rework_pr_prints_status_in_dry_run(self):
        """The 'Rework-Status' output assertion. Captures stdout via
        `redirect_stdout` (closes #423): `solve_issues.print` does not
        exist as a patchable attribute, so the original
        `patch("solve_issues.print")` was a no-op."""
        # We need a non-empty pr_url for the status line to be interesting;
        # the _run_main helper defaults to empty so we override here.
        with ExitStack() as stack:
            stack.enter_context(patch("solve_issues.requests", _types.ModuleType("requests")))
            mock_rework = stack.enter_context(patch("validation.rework.run_pr_rework"))
            mock_rework.return_value = MagicMock(
                status="dry_run",
                pr_url="https://github.com/o/r/pull/1",
                run_id="pr-1-rework-test",
                error_detail=None,
                error_class=None,
            )
            stack.enter_context(patch("solve_issues.require_github_config", _stub_auth))
            stack.enter_context(patch("solve_issues.preflight_checks", _stub_auth))
            mock_env = stack.enter_context(patch("solve_issues.load_env"))
            mock_env.return_value = {
                "GITHUB_TOKEN": "mock-token",
                "GITHUB_USER": "mock-user",
            }
            stack.enter_context(patch("solve_issues.run_pre_solver_hygiene_check"))
            mock_client_cls = stack.enter_context(patch("solve_issues.GitHubClient"))
            mock_client = MagicMock()
            mock_client_cls.return_value = mock_client
            mock_client.get_repo.return_value = {"has_issues": True}

            stdout_buffer = io.StringIO()
            with redirect_stdout(stdout_buffer):
                with patch.object(sys, "argv", [
                    "solve_issues.py", "--rework-pr", "1", "--model", "openrouter_direct", "--dry-run",
                ]):
                    with self.assertRaises(SystemExit):
                        main()

            printed_text = stdout_buffer.getvalue()
            self.assertIn("Rework-Status", printed_text)


class _NullCM:
    """No-op context manager for when capture_stdout is False."""
    def __enter__(self):
        return self
    def __exit__(self, *a):
        return False


if __name__ == "__main__":
    unittest.main()