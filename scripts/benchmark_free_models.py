#!/usr/bin/env python3
"""Benchmark all free models (OpenRouter + OpenCode) against Issue #446.

Runs N solver-invocations sequentially, aggregating per-model results into
a single JSON file. Used by the Free-Models-Benchmark-Sweep on 2026-06-26.

Exit codes:
  0 — all runs finished (success, partial, or infrastructure; aggregated)
  1 — script-level error (could not start, missing files, etc.)
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DEFAULT_ISSUE_NUMBER = 446
DEFAULT_RUN_LABEL = "free-models-2026-06-26"
RUN_TIMEOUT_SECONDS = 180  # per-model wall-clock cap

# File paths are computed in main() once we know the issue_number + run_label


def log(message: str) -> None:
    ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
    line = f"[{ts}] {message}"
    print(line, flush=True)
    # LOG_FILE may be reassigned in main() to a per-run path
    log_path = globals().get("LOG_FILE")
    if log_path is None:
        return
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def run_one(issue_number: int, model_arg: str, model_name: str, run_idx: int, total: int) -> dict:
    started_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    log(f"=== Run {run_idx}/{total} START (issue #{issue_number}, {model_arg} / {model_name}) ===")
    cmd = [
        ".venv/bin/python",
        "scripts/solve_issues.py",
        "--repo",
        "ai-issue-solver",
        "--issue",
        str(issue_number),
        "--model",
        model_arg,
        "--model-name",
        model_name,
        "--skip-slug-verification",
        "--skip-hygiene-check",
        "--benchmark",
        "--skip-pr",
    ]
    try:
        proc = subprocess.run(
            cmd,
            cwd=REPO,
            capture_output=True,
            text=True,
            timeout=RUN_TIMEOUT_SECONDS,
        )
        rc = proc.returncode
        stdout_tail = "\n".join(proc.stdout.splitlines()[-15:])
        stderr_tail = "\n".join(proc.stderr.splitlines()[-15:])
    except subprocess.TimeoutExpired:
        rc = -1
        stdout_tail = ""
        stderr_tail = f"TIMEOUT after {RUN_TIMEOUT_SECONDS}s"
    except Exception as exc:
        rc = -2
        stdout_tail = ""
        stderr_tail = f"EXCEPTION: {exc}"

    finished_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    classification = classify(model_arg, model_name, rc, stdout_tail + stderr_tail)
    log(
        f"=== Run {run_idx}/{total} END: rc={rc}, classification={classification} ==="
    )
    return {
        "run_idx": run_idx,
        "issue_number": issue_number,
        "model_arg": model_arg,
        "model_name": model_name,
        "started_at": started_at,
        "finished_at": finished_at,
        "exit_code": rc,
        "classification": classification,
        "stdout_tail": stdout_tail[-2000:],
        "stderr_tail": stderr_tail[-2000:],
    }


def classify(model_arg: str, model_name: str, rc: int, log_text: str) -> str:
    if rc != 0:
        if "Versions-/Executable-Konflikt" in log_text or "opencode-serve" in log_text:
            return "infrastructure_opencode_state_conflict"
        if "VALIDATION-FAILED" in log_text or "Reject-Artefakte" in log_text:
            return "patch_validation_failed_rc5"
        if "no_patches" in log_text or "no parseable patches" in log_text:
            return "no_patches"
        if "patches_failed" in log_text or "Patch konnte nicht angewendet werden" in log_text:
            return "patch_mismatch_mode_c"
        if "400" in log_text and "Bad Request" in log_text:
            return "openrouter_400"
        return "infrastructure_or_unknown_failure"
    if "PR erstellt" in log_text or "pr_created" in log_text:
        return "success_pr_created"
    if "Keine Patches" in log_text:
        return "no_patches"
    return "success_no_pr"


def explicit_model_specs(raw_models: str) -> list[tuple[str, str]]:
    all_models = []
    for spec in raw_models.split(","):
        spec = spec.strip()
        if not spec:
            continue
        if ":" in spec:
            # provider:model — but model names can also contain ':'
            # (e.g. "deepseek/deepseek-chat-v3.1:free"). Split only on FIRST ':'.
            provider, model_name = spec.split(":", 1)
            all_models.append((provider, model_name))
        else:
            # bare model name → assume openrouter_direct
            all_models.append(("openrouter_direct", spec))
    return all_models


def default_model_specs() -> tuple[list[tuple[str, str]], str]:
    try:
        from scripts.model_catalog import (
            fetch_opencode_free_models,
            fetch_openrouter_free_models,
        )
    except ModuleNotFoundError:
        from model_catalog import (
            fetch_opencode_free_models,
            fetch_openrouter_free_models,
        )

    openrouter = fetch_openrouter_free_models()
    opencode = fetch_opencode_free_models()
    models = (
        [("openrouter_direct", model) for model in openrouter.models]
        + [("opencode", model) for model in opencode.models]
    )
    source = f"openrouter:{openrouter.source}/opencode:{opencode.source}"
    return models, source


def main(argv: list[str] | None = None) -> int:
    import argparse
    parser = argparse.ArgumentParser(
        description="Benchmark all free models (OpenRouter + OpenCode) on an issue."
    )
    parser.add_argument(
        "--issue",
        type=int,
        default=DEFAULT_ISSUE_NUMBER,
        help=f"Issue number to benchmark (default: {DEFAULT_ISSUE_NUMBER})",
    )
    parser.add_argument(
        "--run-label",
        default=DEFAULT_RUN_LABEL,
        help="Label for this benchmark run, used in aggregate/log filenames.",
    )
    parser.add_argument(
        "--models",
        default=None,
        help=(
            "Comma-separated list of provider:model pairs to benchmark. "
            "Examples: 'openrouter_direct:deepseek/deepseek-chat-v3.1:free,"
            "openrouter_direct:qwen/qwen3-coder:free'. "
            "Default: all free OpenRouter + OpenCode models."
        ),
    )
    args = parser.parse_args(argv)

    aggregate_file = REPO / "reports" / "benchmarks" / f"{args.run_label}.json"
    log_file = REPO / "reports" / "benchmarks" / f"{args.run_label}.log"
    aggregate_file.parent.mkdir(parents=True, exist_ok=True)
    if aggregate_file.exists():
        aggregate_file.unlink()
    log_file.unlink(missing_ok=True)

    global LOG_FILE  # used by log()
    LOG_FILE = log_file

    if args.models:
        all_models = explicit_model_specs(args.models)
        model_source = "explicit"
    else:
        all_models, model_source = default_model_specs()

    runs: list[dict] = []
    total = len(all_models)
    log(
        "=== Free-Models-Benchmark START "
        f"(issue #{args.issue}, {total} models, source={model_source}) ==="
    )

    for idx, (model_arg, model_name) in enumerate(all_models, start=1):
        result = run_one(args.issue, model_arg, model_name, idx, total)
        runs.append(result)
        # Persist after each run (so a partial sweep is still recoverable)
        aggregate_file.write_text(
            json.dumps(
                {
                    "started_at": runs[0]["started_at"] if runs else None,
                    "finished_at": None,
                    "issue_number": args.issue,
                    "model_source": model_source,
                    "total_models": total,
                    "completed_runs": len(runs),
                    "runs": runs,
                },
                indent=2,
            ),
            encoding="utf-8",
        )

    finished_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    summary = {
        "started_at": runs[0]["started_at"] if runs else None,
        "finished_at": finished_at,
        "issue_number": args.issue,
        "run_label": args.run_label,
        "model_source": model_source,
        "total_models": total,
        "completed_runs": len(runs),
        "classification_counts": {},
        "runs": runs,
    }
    for r in runs:
        c = r["classification"]
        summary["classification_counts"][c] = summary["classification_counts"].get(c, 0) + 1

    aggregate_file.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    log(f"=== Free-Models-Benchmark END ({total} runs, counts={summary['classification_counts']}) ===")
    print(f"\nAggregate: {aggregate_file}")
    print(f"Log:      {log_file}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
