#!/usr/bin/env python3
"""Benchmark all free models (OpenRouter + OpenCode) against Issue #446.

Runs N solver-invocations sequentially, aggregating per-model results into
a single JSON file. Used by the Free-Models-Benchmark-Sweep on 2026-06-26.

Exit codes:
  0 — all runs finished (success, partial, or infrastructure; aggregated)
  1 — script-level error (could not start, missing files, etc.)

Classification (see ``classify()`` below for the full logic):

* Per-run reports are the source of truth. After each subprocess we discover
  the matching ``reports/runs/<ts>-<repo>-issue-<N>/`` directory and feed
  ``summary.txt``'s ``worker_exit_code`` + ``run_outcome.has_changes`` +
  ``status`` into the classifier. This replaces the legacy fall-through
  ``return "success_no_pr"`` that masked real worker-failures as successes.
* Log-text heuristics are kept as a fallback for tests / mocked subprocess
  invocations that do not produce a run-report.
"""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DEFAULT_ISSUE_NUMBER = 446
DEFAULT_RUN_LABEL = "free-models-2026-06-26"
RUN_TIMEOUT_SECONDS = 180  # per-model wall-clock cap
RUN_REPORTS_ROOT = REPO / "reports" / "runs"
RUN_REPORT_LOOKBACK_SECONDS = 5  # tolerate clock skew when matching mtimes
RUN_REPORT_LOOKAHEAD_SECONDS = 30  # accept reports finalized after finished_at

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
    started_at_dt = datetime.now(timezone.utc)
    started_at = started_at_dt.isoformat(timespec="seconds")
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

    finished_at_dt = datetime.now(timezone.utc)
    finished_at = finished_at_dt.isoformat(timespec="seconds")
    run_report = _find_run_report(issue_number, started_at_dt, finished_at_dt)
    classification = classify(
        model_arg,
        model_name,
        rc,
        stdout_tail + stderr_tail,
        run_report=run_report,
    )
    log(
        f"=== Run {run_idx}/{total} END: rc={rc}, classification={classification}, "
        f"run_report={run_report.name if run_report else 'none'} ==="
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
        "run_report": str(run_report) if run_report else None,
        "stdout_tail": stdout_tail[-2000:],
        "stderr_tail": stderr_tail[-2000:],
    }


def _find_run_report(
    issue_number: int,
    started_at_dt: datetime,
    finished_at_dt: datetime,
) -> Path | None:
    """Locate the ``reports/runs/<ts>-<repo>-issue-<N>/`` directory written by
    ``solve_issues.py`` for the subprocess invocation that just finished.

    Returns the most-recently-modified matching directory whose mtime falls
    inside the run window (with small slack on either side for clock skew and
    report finalization). Returns ``None`` if no report can be matched — the
    classifier will then fall back to log-text heuristics.
    """
    if not RUN_REPORTS_ROOT.is_dir():
        return None
    suffix = f"-issue-{issue_number}"
    candidates: list[tuple[float, Path]] = []
    for entry in RUN_REPORTS_ROOT.iterdir():
        if not entry.is_dir():
            continue
        if not entry.name.endswith(suffix):
            continue
        try:
            mtime = entry.stat().st_mtime
        except OSError:
            continue
        mtime_dt = datetime.fromtimestamp(mtime, tz=timezone.utc)
        if (
            mtime_dt >= started_at_dt - _td(seconds=RUN_REPORT_LOOKBACK_SECONDS)
            and mtime_dt <= finished_at_dt + _td(seconds=RUN_REPORT_LOOKAHEAD_SECONDS)
        ):
            candidates.append((mtime, entry))
    if not candidates:
        return None
    candidates.sort(key=lambda pair: pair[0])
    return candidates[-1][1]


def _td(seconds: int) -> timedelta:
    return timedelta(seconds=seconds)


def _read_run_report_summary(run_report: Path | None) -> dict[str, str]:
    """Parse single-line ``key: value`` pairs from a run-report ``summary.txt``.

    Returns an empty dict if the report or summary file is missing. Only the
    single-line keys are needed for classification (``worker_exit_code``,
    ``run_outcome_has_changes``, ``status``); the multiline blocks in
    summary.txt (``output_tail``, ``git_diff_stat``, ``git_change_summary``)
    are intentionally skipped — they can run thousands of characters and are
    not consulted by the classifier.

    Inline parsing avoids the ``scripts.solver_reporting`` import, which
    transitively pulls in bare ``from utils import`` lines that do not work
    when this module is loaded via the test harness (no sys.path setup).
    """
    if not run_report:
        return {}
    summary_path = run_report / "summary.txt"
    if not summary_path.is_file():
        return {}
    try:
        lines = summary_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return {}
    fields: dict[str, str] = {}
    for raw_line in lines:
        key, separator, value = raw_line.partition(":")
        if not separator or raw_line.startswith((" ", "\t")):
            continue
        key = key.strip()
        if not key:
            continue
        fields[key] = value.strip()
    return fields


def classify(
    model_arg: str,
    model_name: str,
    rc: int,
    log_text: str,
    run_report: Path | None = None,
) -> str:
    """Classify one benchmark run.

    Order of precedence (per §67 spec):

    1. If a matching ``reports/runs/.../summary.txt`` exists, classify from
       the run-report fields ``worker_exit_code`` + ``run_outcome.has_changes``
       + ``status``. This is the canonical path for live benchmark sweeps.
    2. Otherwise (test mocks, missing report) fall back to log-text heuristics
       that match the patterns emitted by ``solve_issues.py``.

    Returns one of the following canonical classes:

    * ``success_pr_created`` — worker_exit_code=0, has_changes=True, status=pr_created*
    * ``success_pr_skipped`` — worker_exit_code=0, has_changes=True, status=pr_skipped
    * ``no_changes`` — worker_exit_code=0, has_changes=False
    * ``empty_response_rc2`` — worker_exit_code=2 (empty / no patches)
    * ``model_failure_rc1`` — worker_exit_code=1 (general worker error)
    * ``patch_validation_failed_rc5`` — worker_exit_code=5 (reject artifacts)
    * ``partial_patch_failure_rc6`` — worker_exit_code=6
    * ``openrouter_429`` — 429 Too Many Requests (any worker rc)
    * ``infrastructure_opencode_state_conflict`` — OpenCode runtime conflict
    * ``patch_mismatch_mode_c`` — patch could not be applied
    * ``openrouter_400`` — 400 Bad Request from OpenRouter
    * ``no_patches`` — log-text fallback only
    * ``infrastructure_or_unknown_failure`` — last-resort
    """
    summary = _read_run_report_summary(run_report)
    if summary:
        return _classify_from_run_report(summary, log_text)
    return _classify_from_log_text(rc, log_text)


def _classify_from_run_report(summary: dict[str, str], log_text: str) -> str:
    # 429 is a transport-layer signal: surface it before worker-exit-code.
    if "429" in log_text and ("Too Many Requests" in log_text or "Rate limit" in log_text):
        return "openrouter_429"

    worker_exit_code_raw = summary.get("worker_exit_code", "").strip()
    has_changes_raw = summary.get("run_outcome_has_changes", "").strip().lower()
    has_changes = has_changes_raw in {"true", "1", "yes"}
    status = summary.get("status", "").strip()

    try:
        worker_exit_code = int(worker_exit_code_raw) if worker_exit_code_raw else None
    except ValueError:
        worker_exit_code = None

    # OpenCode runtime conflicts are infrastructure issues regardless of rc.
    if "Versions-/Executable-Konflikt" in log_text or "opencode-serve" in log_text:
        return "infrastructure_opencode_state_conflict"

    if worker_exit_code == 0:
        if has_changes:
            if status.startswith("pr_created"):
                return "success_pr_created"
            if status == "pr_skipped":
                return "success_pr_skipped"
            # has_changes=True but status does not signal a PR — treat as noop
            # (the worker pushed a branch but the PR step didn't run).
            return "no_changes"
        return "no_changes"

    if worker_exit_code == 1:
        return "model_failure_rc1"
    if worker_exit_code == 2:
        return "empty_response_rc2"
    if worker_exit_code == 5:
        return "patch_validation_failed_rc5"
    if worker_exit_code == 6:
        return "partial_patch_failure_rc6"

    return _classify_from_log_text(worker_exit_code or -1, log_text)


def _classify_from_log_text(rc: int, log_text: str) -> str:
    """Legacy log-text classifier — kept as the fallback for tests/mocks."""
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
        if "429" in log_text and ("Too Many Requests" in log_text or "Rate limit" in log_text):
            return "openrouter_429"
        return "infrastructure_or_unknown_failure"
    if "PR erstellt" in log_text or "pr_created" in log_text:
        return "success_pr_created"
    if "Keine Patches" in log_text:
        return "no_patches"
    # The legacy fall-through "success_no_pr" is gone: classify() now requires
    # a run-report to call a clean run a success. The default for log-text
    # fallback is "no_changes" so that callers cannot mistake a missing-PR run
    # for a real success.
    return "no_changes"


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
