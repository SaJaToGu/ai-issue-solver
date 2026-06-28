"""ais_core.run_state — run-id generation and per-run state persistence.

This module owns the canonical Run-ID format and the read/write helpers
for the per-run metadata files used by AIS. It is intentionally pure:
no logging side-effects, no GitHub client, no env-var reads at import
time. All I/O is explicit in :func:`save_state` and :func:`load_state`.

Run-ID format::

    <UTC-timestamp>-<repo-short>-<8-char-hash>
    Beispiel: 20260627T192412Z-bulwipgame-7f3a2b1c

Report files written for each run:

- ``reports/runs/<run-id>/metadata.json`` (maschinenlesbar)
- ``reports/runs/<run-id>/summary.md`` (human-readable, written by callers)
- ``reports/runs/<run-id>/worker.log`` (Worker stdout/stderr, written by callers)

Public API:

- :func:`make_run_id` — generate a unique Run-ID
- :func:`save_state` — persist a :class:`RunState` to ``metadata.json``
- :func:`load_state` — load a :class:`RunState` from ``metadata.json``
- :data:`DEFAULT_REPORTS_DIR` — default base dir (``reports/runs``)
"""

from __future__ import annotations

import hashlib
import json
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import NamedTuple


class RunState(NamedTuple):
    """A typed view of a per-run state record.

    Attributes:
        run_id: Canonical Run-ID (see module docstring).
        status: One of ``"queued"``, ``"running"``, ``"succeeded"``,
            ``"failed"``.
        data: Free-form structured payload (worker_exit_code, pr_url,
            branch, model, cost, etc.).
    """

    run_id: str
    status: str
    data: dict


DEFAULT_REPORTS_DIR: Path = Path("reports/runs")


__all__ = [
    "RunState",
    "DEFAULT_REPORTS_DIR",
    "make_run_id",
    "save_state",
    "load_state",
]


_REPO_SHORT_RE = re.compile(r"[^a-z0-9-]+")
_REPO_SHORT_DASH_RE = re.compile(r"-{2,}")


def _sanitize_repo_short(repo: str) -> str:
    """Lowercase, replace non-alphanum with ``-``, collapse dashes, max 20."""
    s = _REPO_SHORT_RE.sub("-", repo.lower())
    s = _REPO_SHORT_DASH_RE.sub("-", s).strip("-")
    s = s[:20]
    return s or "repo"


def make_run_id(
    owner: str,
    repo: str,
    timestamp: datetime | None = None,
) -> str:
    """Return a unique Run-ID for the given repo at the given time.

    Args:
        owner: GitHub owner (used as salt for the hash).
        repo: GitHub repository name (used for the repo-short label
            AND as salt for the hash).
        timestamp: Optional UTC datetime. Defaults to ``datetime.now(tz=UTC)``.

    Returns:
        A Run-ID matching the format ``<UTC>-<repo-short>-<hash>``.
        The hash is the first 8 hex chars of SHA-256 over
        ``"<owner>|<repo>|<UTC-timestamp>"``.
    """
    if timestamp is None:
        timestamp = datetime.now(timezone.utc)
    if timestamp.tzinfo is None:
        # Treat naive timestamps as UTC for reproducibility.
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    ts_str = timestamp.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    repo_short = _sanitize_repo_short(repo)
    digest_input = f"{owner}|{repo}|{ts_str}".encode("utf-8")
    digest = hashlib.sha256(digest_input).hexdigest()[:8]
    return f"{ts_str}-{repo_short}-{digest}"


def _state_path(run_id: str, base_dir: Path) -> Path:
    """Return the canonical metadata.json path for a given Run-ID."""
    return base_dir / run_id / "metadata.json"


def save_state(
    run_id: str,
    state: RunState,
    *,
    base_dir: Path | None = None,
) -> Path:
    """Persist ``state`` to ``<base_dir>/<run_id>/metadata.json``.

    Creates the parent directory if needed. Returns the path written.
    """
    if base_dir is None:
        base_dir = DEFAULT_REPORTS_DIR
    path = _state_path(run_id, Path(base_dir))
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "run_id": state.run_id,
        "status": state.status,
        "data": state.data,
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True))
    return path


def load_state(
    run_id: str,
    *,
    base_dir: Path | None = None,
) -> RunState:
    """Load a previously-saved ``RunState`` by Run-ID.

    Raises ``FileNotFoundError`` if the metadata file does not exist.
    """
    if base_dir is None:
        base_dir = DEFAULT_REPORTS_DIR
    path = _state_path(run_id, Path(base_dir))
    payload = json.loads(path.read_text())
    return RunState(
        run_id=payload["run_id"],
        status=payload["status"],
        data=payload["data"],
    )
