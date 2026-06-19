#!/usr/bin/env python3
"""solver_commands.py — Shared command/spec layer for solver invocations.

Centralises CLI-flag forwarding that was previously duplicated across
solve_issues_batch.py, run_overnight.py, and benchmark_issues.py.
"""

from __future__ import annotations

import argparse


def add_solver_core_flags(
    cmd: list[str],
    args: argparse.Namespace,
    *,
    model: str | None = None,
    model_name: str | None = None,
    verbosity: str | None = None,
) -> None:
    """Append core solver flags shared by all invocation entry points.

    Covers: model, model-name, label, base-branch, dry-run, close-issues,
    verbosity.

    Parameters:
        cmd: Command list to extend.
        args: Parsed CLI arguments (provides defaults).
        model: Override for the model (falls back to args.model).
        model_name: Override for the model name (falls back to
                    args.model_name, then skipped if still None/empty).
        verbosity: Override for verbosity (falls back to args.verbosity,
                   then skipped if still None).
    """
    selected_model = model or getattr(args, "model", "")
    cmd.extend(["--model", selected_model])

    selected_model_name = (
        model_name
        if model_name is not None
        else getattr(args, "model_name", None)
    )
    if selected_model_name:
        cmd.extend(["--model-name", selected_model_name])

    label = getattr(args, "label", "ai-generated")
    cmd.extend(["--label", label])

    base_branch = getattr(args, "base_branch", None)
    if base_branch:
        cmd.extend(["--base-branch", base_branch])

    if getattr(args, "dry_run", False):
        cmd.append("--dry-run")
    if getattr(args, "close_issues", False):
        cmd.append("--close-issues")

    v = verbosity or getattr(args, "verbosity", None)
    if v:
        cmd.extend(["--verbosity", v])


def add_budget_flags(cmd: list[str], args: argparse.Namespace) -> None:
    """Append --max-run-* budget limit flags when set on args.

    Covers: max-run-cost-usd, max-run-input-tokens, max-run-output-tokens.

    Only forwards values that are not None; None means "not set on parent"
    and must not be emitted as a flag.
    """
    max_run_cost_usd = getattr(args, "max_run_cost_usd", None)
    if max_run_cost_usd is not None:
        cmd.extend(["--max-run-cost-usd", str(max_run_cost_usd)])
    max_run_input_tokens = getattr(args, "max_run_input_tokens", None)
    if max_run_input_tokens is not None:
        cmd.extend(["--max-run-input-tokens", str(max_run_input_tokens)])
    max_run_output_tokens = getattr(args, "max_run_output_tokens", None)
    if max_run_output_tokens is not None:
        cmd.extend(["--max-run-output-tokens", str(max_run_output_tokens)])


def add_fallback_flags(cmd: list[str], args: argparse.Namespace) -> None:
    """Append --fallback-model and --fallback-model-name when set on args.

    Both are only forwarded when explicitly set (non-None, non-empty).
    """
    fallback_model = getattr(args, "fallback_model", None)
    if fallback_model:
        cmd.extend(["--fallback-model", fallback_model])
    fallback_model_name = getattr(args, "fallback_model_name", None)
    if fallback_model_name:
        cmd.extend(["--fallback-model-name", fallback_model_name])


def add_health_flags(cmd: list[str], args: argparse.Namespace) -> None:
    """Append worker health monitoring flags when set on args.

    Covers: worker-health-timeout-minutes, unhealthy-action,
    unhealthy-retries.
    """
    timeout = getattr(args, "worker_health_timeout_minutes", None)
    if timeout is not None:
        cmd.extend(["--worker-health-timeout-minutes", str(timeout)])
    action = getattr(args, "unhealthy_action", None)
    if action:
        cmd.extend(["--unhealthy-action", action])
    retries = getattr(args, "unhealthy_retries", None)
    if retries is not None:
        cmd.extend(["--unhealthy-retries", str(retries)])
