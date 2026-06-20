#!/usr/bin/env python3
"""
Golden-table tests for scripts/solver_commands.py.

Every common flag that must survive forwarding through the solver command
pipeline (batch → worker, overnight → batch → worker) is pinned here so
that a single table covers: model, model-name, repo, issue, label,
base-branch, dry-run, close-issues, verbosity, fallback, health,
run-report-dir, and budget limits.
"""

from __future__ import annotations

import argparse
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from solver_commands import (  # noqa: E402
    add_budget_flags,
    add_fallback_flags,
    add_health_flags,
    add_solver_core_flags,
    build_single_solver_command,
)


# ── helpers ────────────────────────────────────────────────────────────────


def make_args(**overrides) -> argparse.Namespace:
    """Build an argparse.Namespace that mirrors what the parsers produce."""
    defaults = {
        "model": "opencode",
        "model_name": "",
        "label": "ai-generated",
        "base_branch": None,
        "dry_run": False,
        "close_issues": False,
        "verbosity": None,
        "fallback_model": None,
        "fallback_model_name": None,
        "worker_health_timeout_minutes": None,
        "unhealthy_action": None,
        "unhealthy_retries": None,
        "max_run_cost_usd": None,
        "max_run_input_tokens": None,
        "max_run_output_tokens": None,
    }
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def has_pair(cmd: list[str], flag: str, value: str) -> bool:
    """Return True iff cmd contains the exact ``--flag value`` pair."""
    for i, token in enumerate(cmd):
        if token == flag and i + 1 < len(cmd) and cmd[i + 1] == value:
            return True
    return False


# ── add_solver_core_flags ─────────────────────────────────────────────────


class SolverCoreFlagsGoldenTable(unittest.TestCase):
    """--model, --model-name, --label, --base-branch, --dry-run,
    --close-issues, --verbosity."""

    # -- model -----------------------------------------------------------

    def test_model_is_always_set(self):
        cmd: list[str] = []
        add_solver_core_flags(cmd, make_args(model="codex"))
        self.assertTrue(has_pair(cmd, "--model", "codex"))

    def test_model_override(self):
        cmd: list[str] = []
        add_solver_core_flags(cmd, make_args(model="codex"), model="ollama")
        self.assertTrue(has_pair(cmd, "--model", "ollama"))


class SolverCoreFlagsMissingModelTests(unittest.TestCase):
    """No silent --model '' — must raise when model is missing/empty."""

    def test_empty_string_raises(self):
        cmd: list[str] = []
        with self.assertRaises(ValueError):
            add_solver_core_flags(cmd, make_args(model=""))

    def test_none_raises(self):
        cmd: list[str] = []
        with self.assertRaises(ValueError):
            add_solver_core_flags(cmd, make_args(model=None))

    def test_missing_attr_raises(self):
        cmd: list[str] = []
        args = argparse.Namespace(label="x", verbosity=None)
        with self.assertRaises(ValueError):
            add_solver_core_flags(cmd, args)

    def test_override_none_falls_back_to_args(self):
        cmd: list[str] = []
        add_solver_core_flags(
            cmd, make_args(model="codex"), model=None
        )
        self.assertTrue(has_pair(cmd, "--model", "codex"))

    def test_override_empty_string_falls_back_to_args(self):
        cmd: list[str] = []
        add_solver_core_flags(
            cmd, make_args(model="codex"), model=""
        )
        self.assertTrue(has_pair(cmd, "--model", "codex"))

    # -- model-name ------------------------------------------------------

    def test_model_name_from_args(self):
        cmd: list[str] = []
        add_solver_core_flags(
            cmd, make_args(model="opencode", model_name="claude-sonnet-4-20250514")
        )
        self.assertTrue(has_pair(cmd, "--model-name", "claude-sonnet-4-20250514"))

    def test_model_name_override_supplants_args(self):
        cmd: list[str] = []
        add_solver_core_flags(
            cmd, make_args(model="opencode", model_name="original"),
            model_name="override",
        )
        self.assertTrue(has_pair(cmd, "--model-name", "override"))

    def test_model_name_omitted_when_empty(self):
        cmd: list[str] = []
        add_solver_core_flags(cmd, make_args(model="codex", model_name=""))
        self.assertNotIn("--model-name", cmd)

    def test_model_name_omitted_when_none(self):
        cmd: list[str] = []
        add_solver_core_flags(cmd, make_args(model="codex", model_name=None))
        self.assertNotIn("--model-name", cmd)

    # -- label -----------------------------------------------------------

    def test_label_custom(self):
        cmd: list[str] = []
        add_solver_core_flags(cmd, make_args(label="custom-label"))
        self.assertTrue(has_pair(cmd, "--label", "custom-label"))

    def test_label_default(self):
        cmd: list[str] = []
        add_solver_core_flags(cmd, make_args())
        self.assertTrue(has_pair(cmd, "--label", "ai-generated"))

    # -- base-branch -----------------------------------------------------

    def test_base_branch_set(self):
        cmd: list[str] = []
        add_solver_core_flags(cmd, make_args(base_branch="develop"))
        self.assertTrue(has_pair(cmd, "--base-branch", "develop"))

    def test_base_branch_omitted_when_none(self):
        cmd: list[str] = []
        add_solver_core_flags(cmd, make_args(base_branch=None))
        self.assertNotIn("--base-branch", cmd)

    # -- dry-run ---------------------------------------------------------

    def test_dry_run_set(self):
        cmd: list[str] = []
        add_solver_core_flags(cmd, make_args(dry_run=True))
        self.assertIn("--dry-run", cmd)

    def test_dry_run_omitted_when_false(self):
        cmd: list[str] = []
        add_solver_core_flags(cmd, make_args(dry_run=False))
        self.assertNotIn("--dry-run", cmd)

    # -- close-issues ----------------------------------------------------

    def test_close_issues_set(self):
        cmd: list[str] = []
        add_solver_core_flags(cmd, make_args(close_issues=True))
        self.assertIn("--close-issues", cmd)

    def test_close_issues_omitted_when_false(self):
        cmd: list[str] = []
        add_solver_core_flags(cmd, make_args(close_issues=False))
        self.assertNotIn("--close-issues", cmd)

    # -- verbosity -------------------------------------------------------

    def test_verbosity_from_args(self):
        cmd: list[str] = []
        add_solver_core_flags(cmd, make_args(verbosity="verbose"))
        self.assertTrue(has_pair(cmd, "--verbosity", "verbose"))

    def test_verbosity_override_wins(self):
        cmd: list[str] = []
        add_solver_core_flags(
            cmd, make_args(verbosity="verbose"), verbosity="quiet"
        )
        self.assertTrue(has_pair(cmd, "--verbosity", "quiet"))

    def test_verbosity_omitted_when_none(self):
        cmd: list[str] = []
        add_solver_core_flags(cmd, make_args(verbosity=None))
        self.assertNotIn("--verbosity", cmd)

    def test_verbosity_override_fills_none_args(self):
        cmd: list[str] = []
        add_solver_core_flags(
            cmd, make_args(verbosity=None), verbosity="quiet"
        )
        self.assertTrue(has_pair(cmd, "--verbosity", "quiet"))


# ── add_budget_flags ────────────────────────────────────────────────────────


class BudgetFlagsGoldenTable(unittest.TestCase):
    """--max-run-cost-usd, --max-run-input-tokens, --max-run-output-tokens."""

    def test_all_three_budget_flags(self):
        cmd: list[str] = []
        add_budget_flags(cmd, make_args(
            max_run_cost_usd=5.0,
            max_run_input_tokens=100000,
            max_run_output_tokens=20000,
        ))
        self.assertTrue(has_pair(cmd, "--max-run-cost-usd", "5.0"))
        self.assertTrue(has_pair(cmd, "--max-run-input-tokens", "100000"))
        self.assertTrue(has_pair(cmd, "--max-run-output-tokens", "20000"))

    def test_all_omitted_when_none(self):
        cmd: list[str] = []
        add_budget_flags(cmd, make_args())
        self.assertNotIn("--max-run-cost-usd", cmd)
        self.assertNotIn("--max-run-input-tokens", cmd)
        self.assertNotIn("--max-run-output-tokens", cmd)

    def test_zero_cost_forwarded(self):
        cmd: list[str] = []
        add_budget_flags(cmd, make_args(max_run_cost_usd=0.0))
        self.assertTrue(has_pair(cmd, "--max-run-cost-usd", "0.0"))

    def test_zero_tokens_forwarded(self):
        cmd: list[str] = []
        add_budget_flags(cmd, make_args(
            max_run_input_tokens=0,
            max_run_output_tokens=0,
        ))
        self.assertTrue(has_pair(cmd, "--max-run-input-tokens", "0"))
        self.assertTrue(has_pair(cmd, "--max-run-output-tokens", "0"))

    def test_partial_budget(self):
        cmd: list[str] = []
        add_budget_flags(cmd, make_args(max_run_cost_usd=1.5))
        self.assertTrue(has_pair(cmd, "--max-run-cost-usd", "1.5"))
        self.assertNotIn("--max-run-input-tokens", cmd)
        self.assertNotIn("--max-run-output-tokens", cmd)


# ── add_fallback_flags ──────────────────────────────────────────────────────


class FallbackFlagsGoldenTable(unittest.TestCase):
    """--fallback-model, --fallback-model-name."""

    def test_fallback_model_only(self):
        cmd: list[str] = []
        add_fallback_flags(cmd, make_args(fallback_model="mistral"))
        self.assertTrue(has_pair(cmd, "--fallback-model", "mistral"))
        self.assertNotIn("--fallback-model-name", cmd)

    def test_fallback_model_with_name(self):
        cmd: list[str] = []
        add_fallback_flags(cmd, make_args(
            fallback_model="mistral",
            fallback_model_name="magistral-medium-2509",
        ))
        self.assertTrue(has_pair(cmd, "--fallback-model", "mistral"))
        self.assertTrue(has_pair(cmd, "--fallback-model-name", "magistral-medium-2509"))

    def test_both_omitted_when_none(self):
        cmd: list[str] = []
        add_fallback_flags(cmd, make_args())
        self.assertNotIn("--fallback-model", cmd)
        self.assertNotIn("--fallback-model-name", cmd)

    def test_name_without_model_still_forwarded(self):
        cmd: list[str] = []
        add_fallback_flags(cmd, make_args(fallback_model_name="custom"))
        self.assertNotIn("--fallback-model", cmd)
        self.assertTrue(has_pair(cmd, "--fallback-model-name", "custom"))


# ── add_health_flags ────────────────────────────────────────────────────────


class HealthFlagsGoldenTable(unittest.TestCase):
    """--worker-health-timeout-minutes, --unhealthy-action,
    --unhealthy-retries."""

    def test_all_health_flags(self):
        cmd: list[str] = []
        add_health_flags(cmd, make_args(
            worker_health_timeout_minutes=15,
            unhealthy_action="stop",
            unhealthy_retries=2,
        ))
        self.assertTrue(has_pair(cmd, "--worker-health-timeout-minutes", "15"))
        self.assertTrue(has_pair(cmd, "--unhealthy-action", "stop"))
        self.assertTrue(has_pair(cmd, "--unhealthy-retries", "2"))

    def test_all_omitted_when_none(self):
        cmd: list[str] = []
        add_health_flags(cmd, make_args())
        self.assertNotIn("--worker-health-timeout-minutes", cmd)
        self.assertNotIn("--unhealthy-action", cmd)
        self.assertNotIn("--unhealthy-retries", cmd)

    def test_only_timeout(self):
        cmd: list[str] = []
        add_health_flags(cmd, make_args(worker_health_timeout_minutes=30))
        self.assertTrue(has_pair(cmd, "--worker-health-timeout-minutes", "30"))
        self.assertNotIn("--unhealthy-action", cmd)
        self.assertNotIn("--unhealthy-retries", cmd)

    def test_zero_retries_forwarded(self):
        cmd: list[str] = []
        add_health_flags(cmd, make_args(unhealthy_retries=0))
        self.assertTrue(has_pair(cmd, "--unhealthy-retries", "0"))

    def test_empty_action_skipped(self):
        cmd: list[str] = []
        add_health_flags(cmd, make_args(unhealthy_action=""))
        self.assertNotIn("--unhealthy-action", cmd)


# ── command structure integration ─────────────────────────────────────────


class CommandStructureIntegrationTest(unittest.TestCase):
    """Verifies that compound commands contain both shared (solver_commands)
    and script-specific flags in the expected structure.
    Narrow integration — not a full workflow test."""

    def test_build_single_solver_command_has_shared_and_specific_flags(self):
        cmd = build_single_solver_command(
            make_args(model="opencode", model_name=""),
            Path("scripts/solve_issues.py"),
            repo="ai-issue-solver",
            issue_number=380,
            model_name="minimax/minimax-m3",
            dry_run=True,
            include_label=False,
            skip_pr=True,
            branch_suffix="bench/123/minimax",
            ensemble=None,
        )

        self.assertEqual(cmd[0], sys.executable)
        self.assertIn("scripts/solve_issues.py", cmd[1])
        self.assertTrue(has_pair(cmd, "--model", "opencode"))
        self.assertTrue(has_pair(cmd, "--model-name", "minimax/minimax-m3"))
        self.assertTrue(has_pair(cmd, "--repo", "ai-issue-solver"))
        self.assertTrue(has_pair(cmd, "--issue", "380"))
        self.assertTrue(has_pair(cmd, "--branch-suffix", "bench/123/minimax"))
        self.assertIn("--dry-run", cmd)
        self.assertIn("--skip-pr", cmd)
        self.assertNotIn("--label", cmd)

    def test_build_worker_command_has_shared_and_specific_flags(self):
        from solve_issues_batch import IssueJob, build_worker_command

        args = argparse.Namespace(**{
            "model": "opencode",
            "model_name": "claude-sonnet-4-20250514",
            "label": "ai-generated",
            "base_branch": "develop",
            "dry_run": True,
            "close_issues": True,
            "verbosity": "quiet",
        })
        cmd = build_worker_command(
            args,
            IssueJob("owner/repo", 42),
            Path("scripts/solve_issues.py"),
            run_report_dir=Path("reports/runs/queued-job"),
        )

        self.assertEqual(cmd[0], sys.executable)
        self.assertIn("scripts/solve_issues.py", cmd[1])
        for flag in ("--model", "--model-name", "--base-branch",
                     "--dry-run", "--close-issues"):
            self.assertIn(flag, cmd)
        for flag in ("--repo", "--issue", "--run-report-dir"):
            self.assertIn(flag, cmd)

    def test_build_batch_command_has_shared_and_specific_flags(self):
        from run_overnight import build_batch_command

        args = argparse.Namespace(**{
            "model": "opencode",
            "model_name": "",
            "repo": "owner/repo",
            "issue": [7, 42],
            "label": "ai-generated",
            "base_branch": "develop",
            "workers": 3,
            "dry_run": False,
            "close_issues": False,
            "fallback_model": None,
            "fallback_model_name": None,
            "worker_health_timeout_minutes": 30,
            "unhealthy_action": "warn",
            "unhealthy_retries": None,
            "verbosity": None,
            "skip_congestion_check": False,
            "max_run_cost_usd": None,
            "max_run_input_tokens": None,
            "max_run_output_tokens": None,
        })
        cmd = build_batch_command(args, Path("scripts/solve_issues_batch.py"))

        self.assertEqual(cmd[0], sys.executable)
        self.assertIn("scripts/solve_issues_batch.py", cmd[1])
        for flag in ("--model", "--base-branch"):
            self.assertIn(flag, cmd)
        for flag in ("--workers", "--repo", "--worker-health-timeout-minutes"):
            self.assertIn(flag, cmd)
        self.assertEqual(cmd.count("--issue"), 2)


if __name__ == "__main__":
    unittest.main()
