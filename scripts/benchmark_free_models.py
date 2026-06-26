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

OPENROUTER_FREE_MODELS: list[tuple[str, str]] = [
    ("openrouter_direct", "cognitivecomputations/dolphin-mistral-24b-venice-edition:free"),
    ("openrouter_direct", "cohere/north-mini-code:free"),
    ("openrouter_direct", "google/gemma-4-26b-a4b-it:free"),
    ("openrouter_direct", "google/gemma-4-31b-it:free"),
    ("openrouter_direct", "liquid/lfm-2.5-1.2b-instruct:free"),
    ("openrouter_direct", "liquid/lfm-2.5-1.2b-thinking:free"),
    ("openrouter_direct", "meta-llama/llama-3.2-3b-instruct:free"),
    ("openrouter_direct", "meta-llama/llama-3.3-70b-instruct:free"),
    ("openrouter_direct", "nousresearch/hermes-3-llama-3.1-405b:free"),
    ("openrouter_direct", "nvidia/nemotron-3-nano-30b-a3b:free"),
    ("openrouter_direct", "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free"),
    ("openrouter_direct", "nvidia/nemotron-3-super-120b-a12b:free"),
    ("openrouter_direct", "nvidia/nemotron-3-ultra-550b-a55b:free"),
    ("openrouter_direct", "nvidia/nemotron-3.5-content-safety:free"),
    ("openrouter_direct", "nvidia/nemotron-nano-12b-v2-vl:free"),
    ("openrouter_direct", "nvidia/nemotron-nano-9b-v2:free"),
    ("openrouter_direct", "openai/gpt-oss-120b:free"),
    ("openrouter_direct", "openai/gpt-oss-20b:free"),
    ("openrouter_direct", "openrouter/free"),
    ("openrouter_direct", "openrouter/owl-alpha"),
    ("openrouter_direct", "poolside/laguna-m.1:free"),
    ("openrouter_direct", "poolside/laguna-xs.2:free"),
    ("openrouter_direct", "qwen/qwen3-coder:free"),
    ("openrouter_direct", "qwen/qwen3-next-80b-a3b-instruct:free"),
    ("openrouter_direct", "google/lyria-3-clip-preview"),
    ("openrouter_direct", "google/lyria-3-pro-preview"),
]

OPENCODE_FREE_MODELS: list[tuple[str, str]] = [
    ("opencode", "opencode/big-pickle"),
    ("opencode", "opencode/deepseek-v4-flash-free"),
    ("opencode", "opencode/mimo-v2.5-free"),
    ("opencode", "opencode/nemotron-3-ultra-free"),
    ("opencode", "opencode/north-mini-code-free"),
]


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
        all_models = []
        for spec in args.models.split(","):
            spec = spec.strip()
            if ":" in spec:
                # provider:model — but model names can also contain ':'
                # (e.g. "deepseek/deepseek-chat-v3.1:free"). Split only on FIRST ':'.
                provider, model_name = spec.split(":", 1)
                all_models.append((provider, model_name))
            else:
                # bare model name → assume openrouter_direct
                all_models.append(("openrouter_direct", spec))
    else:
        all_models = OPENROUTER_FREE_MODELS + OPENCODE_FREE_MODELS

    runs: list[dict] = []
    total = len(all_models)
    log(f"=== Free-Models-Benchmark START (issue #{args.issue}, {total} models) ===")

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
