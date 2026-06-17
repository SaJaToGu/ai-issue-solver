#!/usr/bin/env python3
"""
Tests for cost-limit forwarding in solve_issues_batch.py and run_overnight.py.

Regression coverage for issue #324 (0.9.0 Cost-Limit-Forwarding Fix).

Background: `--max-run-cost-usd`, `--max-run-input-tokens`, and
`--max-run-output-tokens` are defined on `solve_issues.py` and consumed by
`workers/opencode_adapter.py`. Without explicit forwarding, a `--max-run-*`
flag set on the parent batch / overnight runner is silently dropped before
the worker process sees it — which means the per-run cost cap never
engages. This file pins the forwarding behaviour so it cannot regress.
"""

from __future__ import annotations

import argparse
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


# ── helpers ────────────────────────────────────────────────────────────────

def _make_batch_args(**overrides) -> argparse.Namespace:
    """Build an argparse.Namespace suitable for solve_issues_batch.build_worker_command.

    Mirrors the defaults that solve_issues_batch.parse_args would produce for a
    minimal `--model codex --repo X --issue N --label Y` invocation.
    """
    defaults = {
        "model": "opencode",
        "model_name": "",
        "fallback_model": None,
        "fallback_model_name": None,
        "label": "ai-generated",
        "base_branch": None,
        "dry_run": False,
        "close_issues": False,
        "verbosity": "quiet",
        # The three flags under test:
        "max_run_cost_usd": None,
        "max_run_input_tokens": None,
        "max_run_output_tokens": None,
    }
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def _make_overnight_args(**overrides) -> argparse.Namespace:
    """Build an argparse.Namespace suitable for run_overnight.build_batch_command."""
    defaults = {
        "model": "opencode",
        "model_name": "",
        "fallback_model": None,
        "fallback_model_name": None,
        "repo": None,
        "issue": None,
        "label": "ai-generated",
        "base_branch": "develop",
        "workers": 2,
        "dry_run": False,
        "close_issues": False,
        "worker_health_timeout_minutes": None,
        "unhealthy_action": None,
        "unhealthy_retries": None,
        "verbosity": None,
        "skip_congestion_check": False,
        # The three flags under test:
        "max_run_cost_usd": None,
        "max_run_input_tokens": None,
        "max_run_output_tokens": None,
    }
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def _has_pair(cmd: list[str], flag: str, value: str) -> bool:
    """Return True iff the command list contains the exact `--flag value` pair."""
    for i, token in enumerate(cmd):
        if token == flag and i + 1 < len(cmd) and cmd[i + 1] == value:
            return True
    return False


# ── solve_issues_batch.build_worker_command ────────────────────────────────

class SolveIssuesBatchForwardingTests(unittest.TestCase):
    """Pin the forwarding contract for batch → solve_issues.py workers."""

    def _build(self, **overrides) -> list[str]:
        from solve_issues_batch import IssueJob, build_worker_command

        args = _make_batch_args(**overrides)
        job = IssueJob(repo="ai-issue-solver", issue_number=42)
        return build_worker_command(
            args, job, Path("scripts/solve_issues.py")
        )

    def test_forwards_all_three_limits_when_set(self):
        cmd = self._build(
            max_run_cost_usd=5.0,
            max_run_input_tokens=100000,
            max_run_output_tokens=20000,
        )
        self.assertTrue(_has_pair(cmd, "--max-run-cost-usd", "5.0"))
        self.assertTrue(_has_pair(cmd, "--max-run-input-tokens", "100000"))
        self.assertTrue(_has_pair(cmd, "--max-run-output-tokens", "20000"))

    def test_omits_limits_when_none(self):
        cmd = self._build()
        # None means "not set on parent" — must not be forwarded as a flag.
        self.assertNotIn("--max-run-cost-usd", cmd)
        self.assertNotIn("--max-run-input-tokens", cmd)
        self.assertNotIn("--max-run-output-tokens", cmd)

    def test_forwards_only_cost_when_only_cost_set(self):
        cmd = self._build(max_run_cost_usd=1.5)
        self.assertTrue(_has_pair(cmd, "--max-run-cost-usd", "1.5"))
        self.assertNotIn("--max-run-input-tokens", cmd)
        self.assertNotIn("--max-run-output-tokens", cmd)

    def test_zero_cost_is_forwarded_not_treated_as_unset(self):
        # 0.0 is a meaningful cap (e.g. "no spending allowed"). It must
        # travel through; only None should mean "unset".
        cmd = self._build(max_run_cost_usd=0.0)
        self.assertTrue(_has_pair(cmd, "--max-run-cost-usd", "0.0"))


# ── run_overnight.build_batch_command ─────────────────────────────────────

class RunOvernightForwardingTests(unittest.TestCase):
    """Pin the forwarding contract for overnight → batch → solve_issues.py."""

    def _build(self, **overrides) -> list[str]:
        from run_overnight import build_batch_command

        args = _make_overnight_args(**overrides)
        return build_batch_command(args, Path("scripts/solve_issues_batch.py"))

    def test_forwards_all_three_limits_when_set(self):
        cmd = self._build(
            max_run_cost_usd=5.0,
            max_run_input_tokens=100000,
            max_run_output_tokens=20000,
        )
        self.assertTrue(_has_pair(cmd, "--max-run-cost-usd", "5.0"))
        self.assertTrue(_has_pair(cmd, "--max-run-input-tokens", "100000"))
        self.assertTrue(_has_pair(cmd, "--max-run-output-tokens", "20000"))

    def test_omits_limits_when_none(self):
        cmd = self._build()
        self.assertNotIn("--max-run-cost-usd", cmd)
        self.assertNotIn("--max-run-input-tokens", cmd)
        self.assertNotIn("--max-run-output-tokens", cmd)

    def test_forwards_only_tokens_when_only_tokens_set(self):
        cmd = self._build(
            max_run_input_tokens=50000,
            max_run_output_tokens=10000,
        )
        self.assertNotIn("--max-run-cost-usd", cmd)
        self.assertTrue(_has_pair(cmd, "--max-run-input-tokens", "50000"))
        self.assertTrue(_has_pair(cmd, "--max-run-output-tokens", "10000"))

    def test_zero_cost_is_forwarded_not_treated_as_unset(self):
        cmd = self._build(max_run_cost_usd=0.0)
        self.assertTrue(_has_pair(cmd, "--max-run-cost-usd", "0.0"))


# ── end-to-end: overnight → batch → worker (command shape) ────────────────

class EndToEndForwardingTests(unittest.TestCase):
    """Overnight's batch command is itself consumed by solve_issues_batch, whose
    build_worker_command then emits the worker command. This integration test
    asserts that a limit set on the overnight runner survives both forwarding
    hops and lands as the canonical `--max-run-cost-usd <value>` pair in the
    worker command that the batch runner will actually execute.
    """

    def test_overnight_limit_survives_both_forwarding_hops(self):
        from run_overnight import build_batch_command
        from solve_issues_batch import IssueJob, build_worker_command

        # Simulate `run_overnight.py --max-run-cost-usd 7.5 --max-run-input-tokens 80000`
        overnight_args = _make_overnight_args(
            max_run_cost_usd=7.5,
            max_run_input_tokens=80000,
        )
        batch_cmd = build_batch_command(
            overnight_args, Path("scripts/solve_issues_batch.py")
        )

        # The batch runner sees a `--max-run-cost-usd 7.5` flag — that's
        # what argparse would consume on its side. Verify it's there.
        self.assertTrue(_has_pair(batch_cmd, "--max-run-cost-usd", "7.5"))
        self.assertTrue(_has_pair(batch_cmd, "--max-run-input-tokens", "80000"))

        # Now build the worker command from a Namespace that mirrors the
        # parsed batch args (i.e. as if the batch runner had parsed batch_cmd
        # itself). This is the second hop.
        batch_parsed_args = _make_batch_args(
            model=overnight_args.model,
            label=overnight_args.label,
            base_branch=overnight_args.base_branch,
            max_run_cost_usd=7.5,
            max_run_input_tokens=80000,
        )
        worker_cmd = build_worker_command(
            batch_parsed_args,
            IssueJob(repo="ai-issue-solver", issue_number=1),
            Path("scripts/solve_issues.py"),
        )
        # The worker sees the limits too.
        self.assertTrue(_has_pair(worker_cmd, "--max-run-cost-usd", "7.5"))
        self.assertTrue(_has_pair(worker_cmd, "--max-run-input-tokens", "80000"))


if __name__ == "__main__":
    unittest.main()
