"""
workers.execution — Shared worker subprocess execution and health monitoring.

Consolidates the subprocess execution, health timeout detection, output capture,
and result classification that were previously split between single-run
(``scripts/solve_issues.py``) and batch (``scripts/solve_issues_batch.py``) code paths.

Usage:

    from workers.execution import (
        WorkerHealthConfig,
        WorkerHealthResult,
        run_worker_subprocess,
        classify_worker_outcome,
    )

    config = WorkerHealthConfig(health_timeout_seconds=300, unhealthy_action="stop")
    result, health = run_worker_subprocess(cmd, cwd, env, health_config=config)
    outcome = classify_worker_outcome(result, git_status)

"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import queue
import subprocess
import threading
import time
from typing import Any, Callable

from workers.base import (
    PATCH_VALIDATION_FAILED_RETURN_CODE,
    PARTIAL_PATCH_FAILURE_RETURN_CODE,
    WorkerOutcome,
    WorkerRunResult,
)


# ─────────────────────────────────────────────────────────────
# Health monitoring types
# ─────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class WorkerHealthConfig:
    """Configuration for worker health timeout monitoring.

    Attributes:
        health_timeout_seconds: Seconds without output before marking unhealthy.
        unhealthy_action: Action on unhealthy detection ("warn", "stop", "retry").
        heartbeat_interval_seconds: Interval for progress heartbeat output.
    """
    health_timeout_seconds: float | None = None
    unhealthy_action: str = "warn"
    heartbeat_interval_seconds: float | None = None


@dataclass(frozen=True)
class WorkerHealthResult:
    """Result of health monitoring during worker execution.

    Attributes:
        unhealthy: Whether the worker was marked unhealthy.
        unhealthy_reason: Human-readable reason for unhealthy status.
    """
    unhealthy: bool = False
    unhealthy_reason: str | None = None


# ─────────────────────────────────────────────────────────────
# Shared subprocess runner
# ─────────────────────────────────────────────────────────────


def run_worker_subprocess(
    cmd: list,
    cwd: str,
    env: dict[str, str],
    health_config: WorkerHealthConfig | None = None,
    *,
    on_line: Callable[[str], None] | None = None,
    detect_rate_limit_fn: Callable[[str], Any] | None = None,
    is_known_waiting_fn: Callable[[str], bool] | None = None,
    heartbeat_label: str | None = None,
    heartbeat_issue_number: int = 0,
    now_fn: Callable[[], datetime] = datetime.now,
) -> tuple[WorkerRunResult, WorkerHealthResult]:
    """Execute a worker subprocess with health timeout monitoring.

    Uses a thread-based reader for non-blocking I/O, enabling health timeout
    detection while the worker runs. This is the shared execution primitive
    used by both the single-run (``solve_issues.py``) and batch
    (``solve_issues_batch.py``) code paths.

    Args:
        cmd: Command list for subprocess.
        cwd: Working directory for the subprocess.
        env: Environment variables for the subprocess.
        health_config: Optional health monitoring configuration. When provided,
            the process is monitored for health timeouts and the configured
            action is applied.
        on_line: Optional callback invoked for each output line as it is read
            from the subprocess. Useful for verbosity-based filtering or
            live health writes in the single-run path.
        detect_rate_limit_fn: Optional function to detect rate-limit messages
            in worker output. When a rate-limit is detected, health timeout
            checks are suppressed (worker is known to be waiting).
        is_known_waiting_fn: Optional function for finer-grained waiting
            detection (e.g. checks that rate-limit reset time is in the future).
            Receives the full accumulated output string; return True to
            suppress health timeout.
        heartbeat_label: Optional label for heartbeat progress output.
        heartbeat_issue_number: Issue number shown in the heartbeat line
            (only relevant for batch runs; defaults to 0).
        now_fn: Function returning current datetime (injectable for tests).

    Returns:
        Tuple of (WorkerRunResult, WorkerHealthResult).
    """
    process: subprocess.Popen | None = None
    try:
        process = subprocess.Popen(
            cmd,
            cwd=cwd,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
    except OSError as exc:
        return (
            WorkerRunResult(
                returncode=127,
                output=f"Worker could not be started: {exc}\n",
            ),
            WorkerHealthResult(
                unhealthy=True,
                unhealthy_reason="Worker process could not be started",
            ),
        )
    except FileNotFoundError:
        return (
            WorkerRunResult(returncode=127, output=""),
            WorkerHealthResult(
                unhealthy=True,
                unhealthy_reason="Worker executable not found",
            ),
        )

    output_parts: list[str] = []
    line_queue: queue.Queue[str | None] = queue.Queue()
    last_activity = time.monotonic()
    last_heartbeat_at = last_activity
    health_seen = False
    health_reason: str | None = None
    started_at = time.monotonic()

    def read_output() -> None:
        try:
            assert process.stdout is not None
            for line in process.stdout:
                line_queue.put(line)
        finally:
            line_queue.put(None)

    reader = threading.Thread(target=read_output, daemon=True)
    reader.start()

    while True:
        try:
            line = line_queue.get(timeout=0.2)
        except queue.Empty:
            line = ""

        if line is None:
            break
        if line:
            output_parts.append(line)
            last_activity = time.monotonic()
            if on_line:
                on_line(line)

        if process.poll() is not None and line_queue.empty():
            break

        if (
            not health_seen
            and health_config is not None
            and health_config.health_timeout_seconds is not None
            and health_config.health_timeout_seconds > 0
        ):
            elapsed_since_activity = time.monotonic() - last_activity
            if elapsed_since_activity > health_config.health_timeout_seconds:
                output_str = "".join(output_parts)
                known_waiting = (
                    (detect_rate_limit_fn and detect_rate_limit_fn(output_str))
                    or (is_known_waiting_fn and is_known_waiting_fn(output_str))
                )
                if not known_waiting:
                    health_seen = True
                    health_reason = (
                        f"keine Worker-Ausgabe seit "
                        f"{health_config.health_timeout_seconds:.0f}s"
                    )
                    output_parts.append(
                        f"\n[batch-health] Unhealthy: {health_reason}\n"
                    )
                    if health_config.unhealthy_action in {"stop", "retry"}:
                        process.terminate()
                        try:
                            process.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            process.kill()
                            process.wait(timeout=5)
                        break

        if (
            health_config is not None
            and health_config.heartbeat_interval_seconds is not None
            and health_config.heartbeat_interval_seconds > 0
        ):
            elapsed_since_heartbeat = time.monotonic() - last_heartbeat_at
            if elapsed_since_heartbeat >= health_config.heartbeat_interval_seconds:
                from solver_reporting import format_heartbeat
                elapsed_total = time.monotonic() - started_at
                heartbeat_line = format_heartbeat(
                    heartbeat_issue_number,
                    elapsed_total,
                    job_label=heartbeat_label,
                )
                print(heartbeat_line)
                last_heartbeat_at = time.monotonic()

    if process.stdout:
        process.stdout.close()
    reader.join(timeout=1)
    returncode = process.wait()
    output = "".join(output_parts)

    if health_seen and health_config is not None and health_config.unhealthy_action == "warn":
        health_reason = None

    health_result = WorkerHealthResult(
        unhealthy=health_seen
        and health_config is not None
        and health_config.unhealthy_action in {"stop", "retry"},
        unhealthy_reason=health_reason,
    )

    return (
        WorkerRunResult(
            returncode=returncode,
            output=output,
        ),
        health_result,
    )


# ─────────────────────────────────────────────────────────────
# Shared outcome classification
# ─────────────────────────────────────────────────────────────


def classify_worker_outcome(
    result: WorkerRunResult,
    git_status: str,
    repo_dir: str | None = None,
    issue_text: str = "",
) -> WorkerOutcome:
    """Classify a worker result into a structured outcome.

    Evaluates the worker exit code and the Git working tree status to
    determine whether the worker produced meaningful changes, no changes,
    or exited with an error (with or without changes). This is the shared
    classification used by both single-run and batch code paths, replacing
    the prior duplicated logic.

    Outcome reasons:
        ``"changed"``                  — exit 0 with changes
        ``"no_changes"``               — exit 0, no changes
        ``"nonzero_with_changes"``     — exit != 0 with meaningful changes
        ``"nonzero_without_changes"``  — exit != 0, no meaningful changes

    Args:
        result: Raw worker execution result (return code + output).
        git_status: Porcelain-formatted ``git status --short`` output.
        repo_dir: Optional repo path for side-effect filtering.
        issue_text: Optional issue text for relevance matching.

    Returns:
        WorkerOutcome with ``should_continue``, ``has_changes``, and ``reason``.
    """
    from scripts.solve_issues import (
        changed_paths_from_status,
        meaningful_changed_paths_for_worker,
    )

    changed_paths = changed_paths_from_status(git_status)
    meaningful_paths = meaningful_changed_paths_for_worker(
        git_status,
        repo_dir=repo_dir,
        issue_text=issue_text,
        worker_returncode=result.returncode,
    )
    has_changes = bool(changed_paths)
    has_meaningful_changes = bool(meaningful_paths)

    if result.returncode == PARTIAL_PATCH_FAILURE_RETURN_CODE:
        return WorkerOutcome(False, has_changes, "partial_patch_failure")
    if result.returncode == PATCH_VALIDATION_FAILED_RETURN_CODE:
        return WorkerOutcome(False, has_changes, "patch_validation_failed")
    if result.returncode == 0 and has_changes:
        return WorkerOutcome(True, True, "changed")
    if result.returncode == 0:
        return WorkerOutcome(False, False, "no_changes")
    if has_meaningful_changes:
        return WorkerOutcome(True, True, "nonzero_with_changes")
    return WorkerOutcome(False, False, "nonzero_without_changes")
