"""solver_commands.py — Shared command/spec layer for solver invocations.

Centralises CLI-flag forwarding that was previously duplicated across
solve_issues_batch.py, run_overnight.py, and benchmark_issues.py.

Every ``build_*`` function in this module is the single source of truth for
command construction. Callers should NOT construct flags by hand.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def _require_non_empty(value: str | None, *, name: str = "model") -> str:
    if not value:
        raise ValueError(f"{name} must be set; got {value!r}")
    return value


def add_solver_core_flags(
    cmd: list[str],
    args: argparse.Namespace,
    *,
    model: str | None = None,
    model_name: str | None = None,
    dry_run: bool | None = None,
    verbosity: str | None = None,
    include_label: bool = True,
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
        dry_run: Override for dry-run mode (falls back to args.dry_run when
                 None).
        verbosity: Override for verbosity (falls back to args.verbosity,
                   then skipped if still None).
    """
    selected_model = _require_non_empty(
        model or getattr(args, "model", None), name="model"
    )
    cmd.extend(["--model", selected_model])

    selected_model_name = (
        model_name
        if model_name is not None
        else getattr(args, "model_name", None)
    )
    if selected_model_name:
        cmd.extend(["--model-name", selected_model_name])

    if include_label:
        label = getattr(args, "label", "ai-generated")
        cmd.extend(["--label", label])

    base_branch = getattr(args, "base_branch", None)
    if base_branch:
        cmd.extend(["--base-branch", base_branch])

    selected_dry_run = getattr(args, "dry_run", False) if dry_run is None else dry_run
    if selected_dry_run:
        cmd.append("--dry-run")
    if getattr(args, "close_issues", False):
        cmd.append("--close-issues")

    v = verbosity or getattr(args, "verbosity", None)
    if v:
        cmd.extend(["--verbosity", v])


def add_solver_model_flags(
    cmd: list[str],
    args: argparse.Namespace,
    *,
    model: str | None = None,
    model_name: str | None = None,
) -> None:
    """Append --model and --model-name only (subset of core flags)."""
    selected_model = _require_non_empty(
        model or getattr(args, "model", None), name="model"
    )
    cmd.extend(["--model", selected_model])

    selected_model_name = (
        model_name
        if model_name is not None
        else getattr(args, "model_name", None)
    )
    if selected_model_name:
        cmd.extend(["--model-name", selected_model_name])


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


def build_single_solver_command(
    args: argparse.Namespace,
    solve_script: Path,
    *,
    repo: str,
    issue_number: int,
    model: str | None = None,
    model_name: str | None = None,
    dry_run: bool | None = None,
    include_label: bool = True,
    skip_pr: bool = False,
    branch_suffix: str | None = None,
    ensemble: int | None = None,
    run_report_dir: Path | None = None,
    defer_codex_rate_limit: bool = False,
    allow_opencode_state_conflict: bool = False,
    verbosity: str | None = None,
) -> list[str]:
    """Build a command for one ``solve_issues.py`` invocation.

    This is the shared command spec for callers that launch the single-run
    solver directly, such as benchmark, batch-style wrappers, and overnight
    runners.

    Parameters:
        args: Parsed CLI arguments (provides defaults for many flags).
        solve_script: Path to ``scripts/solve_issues.py``.
        repo: Owner/repo string, e.g. ``"owner/repo"``.
        issue_number: GitHub issue number.
        model: Override for the model (falls back to args.model).
        model_name: Override for the model name.
        dry_run: Override for dry-run mode.
        include_label: Whether to forward --label.
        skip_pr: Append ``--skip-pr``.
        branch_suffix: Append ``--branch-suffix <value>``.
        ensemble: Append ``--ensemble <N>`` when > 0.
        run_report_dir: Append ``--run-report-dir <path>``.
        defer_codex_rate_limit: Append ``--defer-codex-rate-limit``.
        allow_opencode_state_conflict: Append ``--allow-opencode-state-conflict``.
        verbosity: Override for verbosity.
    """
    cmd = [sys.executable, str(solve_script)]
    add_solver_core_flags(
        cmd,
        args,
        model=model,
        model_name=model_name,
        dry_run=dry_run,
        include_label=include_label,
        verbosity=verbosity,
    )
    cmd.extend(["--repo", repo, "--issue", str(issue_number)])
    if skip_pr:
        cmd.append("--skip-pr")
    if branch_suffix:
        cmd.extend(["--branch-suffix", branch_suffix])
    if ensemble is not None and ensemble > 0:
        cmd.extend(["--ensemble", str(ensemble)])
    if run_report_dir:
        cmd.extend(["--run-report-dir", str(run_report_dir)])
    if defer_codex_rate_limit:
        cmd.append("--defer-codex-rate-limit")
    if allow_opencode_state_conflict:
        cmd.append("--allow-opencode-state-conflict")
    add_budget_flags(cmd, args)
    return cmd


def build_batch_command(
    args: argparse.Namespace,
    batch_script: Path,
    *,
    model: str | None = None,
    model_name: str | None = None,
    dry_run: bool | None = None,
    verbosity: str | None = None,
    jobs: list[tuple[str, int]] | None = None,
    skip_congestion_check: bool = False,
    allow_opencode_state_conflict: bool | None = None,
) -> list[str]:
    """Build a command for one ``solve_issues_batch.py`` invocation.

    This consolidates flag forwarding that ``run_overnight.py`` and other
    batch launchers previously did by hand.

    Parameters:
        args: Parsed CLI arguments (provides defaults).
        batch_script: Path to ``scripts/solve_issues_batch.py``.
        model: Override for the model.
        model_name: Override for the model name.
        dry_run: Override for dry-run.
        verbosity: Override for verbosity.
        jobs: List of ``(repo, issue_number)`` tuples to forward.
        skip_congestion_check: Append ``--skip-congestion-check``.
        allow_opencode_state_conflict: Auto-detect from model when None.
    """
    cmd = [sys.executable, str(batch_script)]
    add_solver_core_flags(
        cmd,
        args,
        model=model,
        model_name=model_name,
        dry_run=dry_run,
        verbosity=verbosity,
    )
    cmd.extend(["--workers", str(getattr(args, "workers", 2))])
    add_fallback_flags(cmd, args)
    add_health_flags(cmd, args)

    repo_attr = getattr(args, "repo", None)
    if repo_attr:
        cmd.extend(["--repo", repo_attr])
    if jobs:
        for repo, issue_number in jobs:
            cmd.extend(["--issue", str(issue_number)])
    else:
        for issue_number in getattr(args, "issue", []) or []:
            cmd.extend(["--issue", str(issue_number)])

    if skip_congestion_check or getattr(args, "skip_congestion_check", False):
        cmd.append("--skip-congestion-check")

    effective_model = model or getattr(args, "model", None)
    conflict_allowed = allow_opencode_state_conflict
    if conflict_allowed is None:
        conflict_allowed = getattr(args, "allow_opencode_state_conflict", False)
    if effective_model == "opencode" and conflict_allowed:
        cmd.append("--allow-opencode-state-conflict")

    add_budget_flags(cmd, args)
    return cmd


def build_dashboard_command(
    dashboard_script: Path,
    output_path: Path,
    *,
    runs_dir: Path | None = None,
    owner: str | None = None,
) -> list[str]:
    """Build a command for ``serve_dashboard.py`` or ``status_dashboard.py``."""
    cmd = [sys.executable, str(dashboard_script), "--output", str(output_path)]
    if runs_dir:
        cmd.extend(["--runs-dir", str(runs_dir)])
    if owner:
        cmd.extend(["--owner", owner])
    return cmd


def build_caffeinate_command(pid: int | None = None) -> list[str]:
    """Build a macOS sleep-prevention command."""
    cmd = ["caffeinate", "-dimsu"]
    if pid is not None:
        cmd.extend(["-w", str(pid)])
    return cmd
