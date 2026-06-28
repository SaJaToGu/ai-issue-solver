"""ais_core.run_state — run-id generation and per-run state persistence.

This module owns the canonical Run-ID format and the read/write helpers
for the per-run metadata files used by AIS. It is intentionally pure:
no logging side-effects, no GitHub client, no env-var reads at import
time. All I/O is explicit in ``save_state`` / ``load_state``.

Run-ID format:
    <UTC-timestamp>-<repo-short>-<8-char-hash>
    Beispiel: 20260627T192412Z-bulwipgame-7f3a2b1c

Report files written for each run:
    reports/runs/<run-id>/metadata.json   (maschinenlesbar)
    reports/runs/<run-id>/summary.md      (human-readable)
    reports/runs/<run-id>/worker.log      (Worker stdout/stderr)

Public API:
    make_run_id(owner, repo, timestamp) -> str
    save_state(run_id, state)             -> Path
    load_state(run_id)                    -> dict
    RunState                              — typed result
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import NamedTuple


class RunState(NamedTuple):
    """A typed view of a per-run state record.

    Attributes:
        run_id: Canonical Run-ID (see module docstring).
        status: One of 'queued', 'running', 'succeeded', 'failed'.
        data: Free-form structured payload (worker_exit_code, pr_url,
              branch, model, cost, etc.).
    """

    run_id: str
    status: str
    data: dict


__all__ = [
    "RunState",
    "make_run_id",
    "save_state",
    "load_state",
]


def make_run_id(owner: str, repo: str, timestamp: datetime | None = None) -> str:
    """Return a unique Run-ID for the given repo at the given time."""
    raise NotImplementedError("ais_core.run_state.make_run_id (Issue #1c)")


def save_state(run_id: str, state: RunState) -> Path:
    """Persist ``state`` to ``reports/runs/<run_id>/metadata.json``."""
    raise NotImplementedError("ais_core.run_state.save_state (Issue #1c)")


def load_state(run_id: str) -> RunState:
    """Load a previously-saved ``RunState`` by Run-ID."""
    raise NotImplementedError("ais_core.run_state.load_state (Issue #1c)")