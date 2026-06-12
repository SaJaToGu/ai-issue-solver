# SQLite-backed Solver Registry Module

"""
This module provides a SQLite-backed registry for tracking solver runs.
It replaces the previous file-based system with a structured database.

Module-level API (as required by tests):
- REGISTRY_DB: Path - Overridable global for test isolation
- init_db() -> None: Initialize the database schema
- register_run(...) -> None: Register a new solver run
- get_run(run_id: str) -> dict | None: Retrieve a run by ID
- terminate_run(run_id: str) -> None: Terminate a run
- update_health(run_id: str, current_phase: str = "", status: str = "healthy") -> None: Update run health
- mark_local_changes(run_id: str, has_changes: bool) -> None: Mark if local changes exist
- get_active_runs() -> list[dict]: Get all active runs (status != "terminated")

Erweiterte Features fuer den Supervisor:
- start_time und latest_health_timestamp Tracking
- cancellation_reason bei终止
- Suchfunktionen nach Repo, Issue, Branch
- Stale-Run Erkennung
"""

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, List

REGISTRY_DB = Path("solver_registry.db")

CANCELLATION_REASONS = {
    "manual": "Manuell durch Benutzer abgebrochen",
    "stale": "Run ist stale (keine Aktualisierung)",
    "unhealthy": "Run als unhealthy markiert",
    "test_loop": "Wiederholte Testschleifen erkannt",
    "edit_failure": "Wiederholte Edit-Fehler erkannt",
    "wal_failure": "WAL/Datenbank-Fehler erkannt",
    "network_stall": "Netzwerk-Stall erkannt",
    "output_inactivity": "Worker-Output-Inaktivitaet erkannt",
    "escalation": "Eskalation nach Grace-Period abgeschlossen",
}


def init_db() -> None:
    """Initialize the database schema."""
    with sqlite3.connect(REGISTRY_DB) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS runs (
                run_id TEXT PRIMARY KEY,
                repo TEXT NOT NULL,
                issue TEXT NOT NULL,
                branch TEXT NOT NULL,
                worker_adapter TEXT NOT NULL,
                model_name TEXT NOT NULL,
                pid_tree TEXT NOT NULL DEFAULT '',
                run_report_path TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'healthy'
                    CHECK(status IN ('healthy', 'unhealthy', 'terminated', 'stale')),
                local_changes INTEGER NOT NULL DEFAULT 0,
                current_phase TEXT NOT NULL DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                start_time TIMESTAMP NOT NULL,
                latest_health_timestamp TIMESTAMP,
                cancellation_reason TEXT
            )
        """)
        cursor.execute("""
            CREATE TRIGGER IF NOT EXISTS update_run_timestamp
            AFTER UPDATE ON runs
            FOR EACH ROW
            BEGIN
                UPDATE runs SET updated_at = CURRENT_TIMESTAMP WHERE run_id = OLD.run_id;
            END
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_runs_status ON runs(status)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_runs_repo ON runs(repo)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_runs_issue ON runs(issue)
        """)
        conn.commit()


def register_run(
    run_id: str,
    repo: str,
    issue: str,
    branch: str,
    worker_adapter: str,
    model_name: str,
    pid_tree: str,
    run_report_path: str,
) -> None:
    """Register a new solver run."""
    now = datetime.now().isoformat()
    with sqlite3.connect(REGISTRY_DB) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO runs (
                run_id, repo, issue, branch, worker_adapter, model_name,
                pid_tree, run_report_path, status, start_time
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'healthy', ?)
        """, (run_id, repo, issue, branch, worker_adapter, model_name,
              pid_tree, run_report_path, now))
        conn.commit()


def get_run(run_id: str) -> Optional[Dict]:
    """Retrieve a run by ID. Returns None if not found."""
    with sqlite3.connect(REGISTRY_DB) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,))
        row = cursor.fetchone()
        return dict(row) if row else None


def get_run_by_pid(pid: int) -> Optional[Dict]:
    """Retrieve a run by a PID in its pid_tree."""
    with sqlite3.connect(REGISTRY_DB) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM runs WHERE ',' || pid_tree || ',' LIKE ?",
            (f"%,{pid},%",)
        )
        row = cursor.fetchone()
        return dict(row) if row else None


def terminate_run(run_id: str, cancellation_reason: str = "manual") -> None:
    """Terminate a run and set the cancellation reason."""
    reason_text = CANCELLATION_REASONS.get(cancellation_reason, cancellation_reason)
    with sqlite3.connect(REGISTRY_DB) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE runs
            SET status = 'terminated', cancellation_reason = ?
            WHERE run_id = ?
        """, (reason_text, run_id))
        conn.commit()


def update_health(
    run_id: str,
    current_phase: str = "",
    status: str = "healthy",
) -> None:
    """Update the health status and phase of a run."""
    now = datetime.now().isoformat()
    with sqlite3.connect(REGISTRY_DB) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE runs
            SET status = ?, current_phase = ?, latest_health_timestamp = ?
            WHERE run_id = ?
        """, (status, current_phase, now, run_id))
        conn.commit()


def update_pid_tree(run_id: str, pid_tree: str) -> None:
    """Update the PID tree of a run."""
    with sqlite3.connect(REGISTRY_DB) as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE runs SET pid_tree = ? WHERE run_id = ?", (pid_tree, run_id))
        conn.commit()


def mark_local_changes(run_id: str, has_changes: bool) -> None:
    """Mark whether a run has local changes."""
    with sqlite3.connect(REGISTRY_DB) as conn:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE runs SET local_changes = ? WHERE run_id = ?",
            (int(has_changes), run_id)
        )
        conn.commit()


def mark_stale_runs(stale_seconds: int = 900) -> List[str]:
    """Mark runs as stale that haven't been updated in stale_seconds."""
    cutoff = datetime.now().timestamp() - stale_seconds
    cutoff_dt = datetime.fromtimestamp(cutoff)
    stale_run_ids = []

    with sqlite3.connect(REGISTRY_DB) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("""
            SELECT run_id FROM runs
            WHERE status NOT IN ('terminated', 'stale')
            AND (
                latest_health_timestamp IS NULL
                OR latest_health_timestamp < ?
            )
        """, (cutoff_dt.isoformat(),))
        for row in cursor.fetchall():
            stale_run_ids.append(row["run_id"])

        if stale_run_ids:
            placeholders = ",".join("?" * len(stale_run_ids))
            cursor.execute(f"""
                UPDATE runs
                SET status = 'stale'
                WHERE run_id IN ({placeholders})
            """, stale_run_ids)
            conn.commit()

    return stale_run_ids


def get_active_runs() -> List[Dict]:
    """Get all runs where status is not 'terminated'."""
    with sqlite3.connect(REGISTRY_DB) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM runs
            WHERE status NOT IN ('terminated')
            ORDER BY created_at DESC
        """)
        return [dict(row) for row in cursor.fetchall()]


def get_stale_runs() -> List[Dict]:
    """Get all stale runs."""
    with sqlite3.connect(REGISTRY_DB) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM runs WHERE status = 'stale' ORDER BY created_at DESC")
        return [dict(row) for row in cursor.fetchall()]


def search_runs(
    repo: Optional[str] = None,
    issue: Optional[str] = None,
    branch: Optional[str] = None,
    status: Optional[str] = None,
) -> List[Dict]:
    """Search runs by various criteria."""
    conditions = []
    params = []

    if repo:
        conditions.append("repo = ?")
        params.append(repo)
    if issue:
        conditions.append("issue = ?")
        params.append(issue)
    if branch:
        conditions.append("branch = ?")
        params.append(branch)
    if status:
        conditions.append("status = ?")
        params.append(status)

    where_clause = " AND ".join(conditions) if conditions else "1=1"

    with sqlite3.connect(REGISTRY_DB) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(f"SELECT * FROM runs WHERE {where_clause} ORDER BY created_at DESC", params)
        return [dict(row) for row in cursor.fetchall()]