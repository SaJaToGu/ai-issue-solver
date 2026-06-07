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
"""

import sqlite3
from pathlib import Path
from typing import Optional, Dict, List

# Overridable global for test isolation
REGISTRY_DB = Path("solver_registry.db")


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
                pid_tree TEXT NOT NULL,
                run_report_path TEXT NOT NULL,
                status TEXT NOT NULL CHECK(status IN ('healthy', 'unhealthy', 'terminated')),
                local_changes INTEGER NOT NULL DEFAULT 0,
                current_phase TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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
    with sqlite3.connect(REGISTRY_DB) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO runs (
                run_id, repo, issue, branch, worker_adapter, model_name, 
                pid_tree, run_report_path, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'healthy')
        """, (run_id, repo, issue, branch, worker_adapter, model_name, pid_tree, run_report_path))
        conn.commit()


def get_run(run_id: str) -> Optional[Dict]:
    """Retrieve a run by ID. Returns None if not found."""
    with sqlite3.connect(REGISTRY_DB) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,))
        row = cursor.fetchone()
        return dict(row) if row else None


def terminate_run(run_id: str) -> None:
    """Terminate a run by setting its status to 'terminated'."""
    with sqlite3.connect(REGISTRY_DB) as conn:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE runs SET status = 'terminated' WHERE run_id = ?",
            (run_id,)
        )
        conn.commit()


def update_health(
    run_id: str,
    current_phase: str = "",
    status: str = "healthy",
) -> None:
    """Update the health status and phase of a run."""
    with sqlite3.connect(REGISTRY_DB) as conn:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE runs SET status = ?, current_phase = ? WHERE run_id = ?",
            (status, current_phase, run_id)
        )
        conn.commit()


def mark_local_changes(run_id: str, has_changes: bool) -> None:
    """Mark whether a run has local changes."""
    with sqlite3.connect(REGISTRY_DB) as conn:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE runs SET local_changes = ? WHERE run_id = ?",
            (has_changes, run_id)
        )
        conn.commit()


def get_active_runs() -> List[Dict]:
    """Get all runs where status is not 'terminated'."""
    with sqlite3.connect(REGISTRY_DB) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM runs WHERE status != 'terminated'")
        return [dict(row) for row in cursor.fetchall()]