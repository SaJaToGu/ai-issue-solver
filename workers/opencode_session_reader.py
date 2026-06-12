"""
workers.opencode_session_reader — Liest OpenCode-Session-Metriken aus der lokalen SQLite-Datenbank.

Ermöglicht das Auslesen von Kosten- und Tokenwerten aus OpenCode-eigenen Sessions
sowie die Überwachung von Budgetgrenzen waehrend eines Solver-Runs.

Nutzung:
    from workers.opencode_session_reader import (
        find_opencode_db_path,
        match_sessions_by_run,
        calculate_session_totals,
        check_budget_limits,
        OpenCodeBudgetLimits,
    )
"""

from __future__ import annotations

import platform
import sqlite3
from dataclasses import dataclass
from contextlib import closing
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any


# ─────────────────────────────────────────────────────────────
# Datenklassen
# ─────────────────────────────────────────────────────────────

@dataclass
class OpenCodeSessionRow:
    id: str
    model: str
    cost: float | None
    tokens_input: int | None
    tokens_output: int | None
    tokens_reasoning: int | None
    tokens_cache_read: int | None
    tokens_cache_write: int | None
    directory: str
    time_created: datetime | None
    time_updated: datetime | None


@dataclass
class OpenCodeSessionTotals:
    total_cost: float = 0.0
    total_tokens_input: int = 0
    total_tokens_output: int = 0
    total_tokens_reasoning: int = 0
    total_tokens_cache_read: int = 0
    total_tokens_cache_write: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_cost": self.total_cost,
            "total_tokens_input": self.total_tokens_input,
            "total_tokens_output": self.total_tokens_output,
            "total_tokens_reasoning": self.total_tokens_reasoning,
            "total_tokens_cache_read": self.total_tokens_cache_read,
            "total_tokens_cache_write": self.total_tokens_cache_write,
        }


@dataclass
class OpenCodeBudgetLimits:
    max_cost_usd: float | None = None
    max_input_tokens: int | None = None
    max_output_tokens: int | None = None
    max_cache_read_tokens: int | None = None
    exceeded_reason: str | None = None


# ─────────────────────────────────────────────────────────────
# DB-Pfad finden
# ─────────────────────────────────────────────────────────────

def find_opencode_db_path() -> Path | None:
    """Ermittelt den Pfad zur OpenCode SQLite-Datenbank anhand typischer Installationsorte.

    Suchreihenfolge:
        1. macOS: ~/Library/Application Support/opencode/opencode.db
        2. Linux: ~/.local/share/opencode/opencode.db
        3. ~/.opencode/opencode.db
    """
    home = Path.home()
    candidates: list[Path] = []

    if platform.system() == "Darwin":
        candidates.append(home / "Library" / "Application Support" / "opencode" / "opencode.db")

    candidates.append(home / ".local" / "share" / "opencode" / "opencode.db")
    candidates.append(home / ".opencode" / "opencode.db")

    return _first_existing(candidates)


def _first_existing(candidates: list[Path]) -> Path | None:
    for path in candidates:
        if path.exists():
            return path
    return None


# ─────────────────────────────────────────────────────────────
# Session-Lesen
# ─────────────────────────────────────────────────────────────

_SESSION_COLS = (
    "id", "model", "cost", "tokens_input", "tokens_output",
    "tokens_reasoning", "tokens_cache_read", "tokens_cache_write",
    "directory", "time_created", "time_updated",
)

_SESSION_COLS_CSV = ", ".join(_SESSION_COLS)


def read_opencode_sessions(
    db_path: str | Path,
    directory: str | None = None,
    time_created_after: datetime | None = None,
    time_created_before: datetime | None = None,
) -> list[OpenCodeSessionRow]:
    """Liest OpenCode-Sessions aus der SQLite-Datenbank.

    Args:
        db_path: Pfad zur opencode.db.
        directory: Filtert Sessions mit diesem directory-Wert.
        time_created_after: Nur Sessions ab diesem Zeitpunkt.
        time_created_before: Nur Sessions bis zu diesem Zeitpunkt.

    Returns:
        Liste von OpenCodeSessionRow-Objekten, absteigend sortiert nach time_created.
    """
    query = f"SELECT {_SESSION_COLS_CSV} FROM session WHERE 1=1"
    params: list[Any] = []

    if directory is not None:
        query += " AND directory = ?"
        params.append(directory)
    if time_created_after is not None:
        query += " AND time_created >= ?"
        params.append(_serialize_opencode_time(time_created_after))
    if time_created_before is not None:
        query += " AND time_created <= ?"
        params.append(_serialize_opencode_time(time_created_before))

    query += " ORDER BY time_created DESC"

    db_uri = f"file:{Path(db_path).expanduser()}?mode=ro"
    with closing(sqlite3.connect(db_uri, uri=True, timeout=5)) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(query, params)
        rows = cursor.fetchall()

    return [_row_to_session(r) for r in rows]


def _row_to_session(row: sqlite3.Row) -> OpenCodeSessionRow:
    return OpenCodeSessionRow(
        id=row["id"],
        model=row["model"] or "",
        cost=_maybe_float(row["cost"]),
        tokens_input=_maybe_int(row["tokens_input"]),
        tokens_output=_maybe_int(row["tokens_output"]),
        tokens_reasoning=_maybe_int(row["tokens_reasoning"]),
        tokens_cache_read=_maybe_int(row["tokens_cache_read"]),
        tokens_cache_write=_maybe_int(row["tokens_cache_write"]),
        directory=row["directory"] or "",
        time_created=_parse_dt(row["time_created"]),
        time_updated=_parse_dt(row["time_updated"]),
    )


def _maybe_float(val: Any) -> float | None:
    if val is None:
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def _maybe_int(val: Any) -> int | None:
    if val is None:
        return None
    try:
        return int(val)
    except (ValueError, TypeError):
        return None


def _parse_dt(val: Any) -> datetime | None:
    if val is None:
        return None
    if isinstance(val, datetime):
        return val
    if isinstance(val, (int, float)):
        timestamp = float(val)
        if timestamp > 10_000_000_000:
            timestamp = timestamp / 1000
        return datetime.fromtimestamp(timestamp)
    if isinstance(val, str):
        stripped = val.strip()
        if stripped.isdigit():
            return _parse_dt(int(stripped))
        try:
            return datetime.fromisoformat(stripped)
        except ValueError:
            return None
    return None


def _serialize_opencode_time(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


# ─────────────────────────────────────────────────────────────
# Matching-Logik
# ─────────────────────────────────────────────────────────────

def match_sessions_by_run(
    db_path: str | Path,
    repo_dir: str,
    run_start_time: datetime,
    time_window_seconds: int = 60,
) -> list[OpenCodeSessionRow]:
    """Findet OpenCode-Sessions die zu einem Solver-Run passen.

    Matcht anhand des Repository-Verzeichnisses (directory) und
    des Run-Start-Zeitpunkts (time_created innerhalb eines Fensters).

    Args:
        db_path: Pfad zur opencode.db.
        repo_dir: Absoluter Pfad zum Checkout-Verzeichnis.
        run_start_time: Startzeit des Solver-Runs.
        time_window_seconds: Zeitfenster in Sekunden vor/nach run_start_time.

    Returns:
        Liste passender Sessions.
    """
    window = timedelta(seconds=time_window_seconds)
    return read_opencode_sessions(
        db_path,
        directory=repo_dir,
        time_created_after=run_start_time - window,
        time_created_before=run_start_time + window,
    )


# ─────────────────────────────────────────────────────────────
# Aggregation & Budget-Prüfung
# ─────────────────────────────────────────────────────────────

def calculate_session_totals(
    sessions: list[OpenCodeSessionRow],
) -> OpenCodeSessionTotals:
    """Aggregiert Kosten- und Token-Totals aus einer Liste von Sessions."""
    total_cost = 0.0
    total_input = 0
    total_output = 0
    total_reasoning = 0
    total_cache_read = 0
    total_cache_write = 0

    for s in sessions:
        if s.cost is not None:
            total_cost += s.cost
        if s.tokens_input is not None:
            total_input += s.tokens_input
        if s.tokens_output is not None:
            total_output += s.tokens_output
        if s.tokens_reasoning is not None:
            total_reasoning += s.tokens_reasoning
        if s.tokens_cache_read is not None:
            total_cache_read += s.tokens_cache_read
        if s.tokens_cache_write is not None:
            total_cache_write += s.tokens_cache_write

    return OpenCodeSessionTotals(
        total_cost=round(total_cost, 6),
        total_tokens_input=total_input,
        total_tokens_output=total_output,
        total_tokens_reasoning=total_reasoning,
        total_tokens_cache_read=total_cache_read,
        total_tokens_cache_write=total_cache_write,
    )


def check_budget_limits(
    totals: OpenCodeSessionTotals,
    limits: OpenCodeBudgetLimits,
) -> OpenCodeBudgetLimits:
    """Prüft ob die aktuellen Totals eine der konfigurierten Budgetgrenzen ueberschreiten.

    Returns:
        OpenCodeBudgetLimits mit gesetztem exceeded_reason bei Ueberschreitung.
    """
    exceeded: list[str] = []

    if limits.max_cost_usd is not None and totals.total_cost > limits.max_cost_usd:
        exceeded.append(
            f"cost ${totals.total_cost:.4f} exceeds ${limits.max_cost_usd:.4f}"
        )
    if limits.max_input_tokens is not None and totals.total_tokens_input > limits.max_input_tokens:
        exceeded.append(
            f"input_tokens {totals.total_tokens_input} exceeds {limits.max_input_tokens}"
        )
    if limits.max_output_tokens is not None and totals.total_tokens_output > limits.max_output_tokens:
        exceeded.append(
            f"output_tokens {totals.total_tokens_output} exceeds {limits.max_output_tokens}"
        )
    if limits.max_cache_read_tokens is not None and totals.total_tokens_cache_read > limits.max_cache_read_tokens:
        exceeded.append(
            f"cache_read_tokens {totals.total_tokens_cache_read} exceeds {limits.max_cache_read_tokens}"
        )

    return OpenCodeBudgetLimits(
        max_cost_usd=limits.max_cost_usd,
        max_input_tokens=limits.max_input_tokens,
        max_output_tokens=limits.max_output_tokens,
        max_cache_read_tokens=limits.max_cache_read_tokens,
        exceeded_reason="; ".join(exceeded) if exceeded else None,
    )


def has_any_limit(limits: OpenCodeBudgetLimits) -> bool:
    """Prüft ob mindestens eine Budgetgrenze konfiguriert ist."""
    return any((
        limits.max_cost_usd is not None,
        limits.max_input_tokens is not None,
        limits.max_output_tokens is not None,
        limits.max_cache_read_tokens is not None,
    ))


# ─────────────────────────────────────────────────────────────
# Hilfsfunktion: DB mit Testdaten erstellen
# ─────────────────────────────────────────────────────────────

def create_test_database(path: str | Path, sessions: list[dict]) -> None:
    """Erzeugt eine opencode.db-aehnliche SQLite-Datenbank mit session-Tabelle.

    Nur fuer Tests und Entwicklung gedacht.
    """
    conn = sqlite3.connect(str(path))
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS session (
            id TEXT PRIMARY KEY,
            model TEXT,
            cost REAL,
            tokens_input INTEGER,
            tokens_output INTEGER,
            tokens_reasoning INTEGER,
            tokens_cache_read INTEGER,
            tokens_cache_write INTEGER,
            directory TEXT,
            time_created INTEGER,
            time_updated INTEGER
        )
    """)
    for s in sessions:
        cursor.execute(
            """INSERT INTO session
               (id, model, cost, tokens_input, tokens_output, tokens_reasoning,
                tokens_cache_read, tokens_cache_write, directory, time_created, time_updated)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                s.get("id"),
                s.get("model", ""),
                s.get("cost"),
                s.get("tokens_input"),
                s.get("tokens_output"),
                s.get("tokens_reasoning"),
                s.get("tokens_cache_read"),
                s.get("tokens_cache_write"),
                s.get("directory", ""),
                s.get("time_created"),
                s.get("time_updated"),
            ),
        )
    conn.commit()
    conn.close()
