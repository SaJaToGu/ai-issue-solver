# Test Suite for Solver Registry

"""
Tests for the SQLite-backed solver registry module.

This test suite verifies the module-level API contract:
- REGISTRY_DB: Overridable global for test isolation
- init_db() -> None
- register_run(...) -> None
- get_run(run_id: str) -> dict | None
- terminate_run(run_id: str) -> None
- update_health(run_id: str, current_phase: str = "", status: str = "healthy") -> None
- mark_local_changes(run_id: str, has_changes: bool) -> None
- get_active_runs() -> list[dict]
"""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

# Import the module under test
from solver_registry import (
    REGISTRY_DB,
    init_db,
    register_run,
    get_run,
    terminate_run,
    update_health,
    mark_local_changes,
    get_active_runs,
)


class TestSolverRegistry(unittest.TestCase):
    """Test the solver registry module."""

    def setUp(self):
        """Set up a temporary database for testing."""
        self.temp_db = tempfile.NamedTemporaryFile(delete=False)
        self.temp_db_path = Path(self.temp_db.name)
        self.temp_db.close()
        
        # Override the global REGISTRY_DB for test isolation
        self.original_registry_db = REGISTRY_DB
        patcher = patch('solver_registry.REGISTRY_DB', self.temp_db_path)
        self.addCleanup(patcher.stop)
        patcher.start()
        
        # Initialize the database
        init_db()

    def tearDown(self):
        """Clean up the temporary database."""
        if self.temp_db_path.exists():
            os.unlink(self.temp_db_path)
        
        # Restore the original REGISTRY_DB
        patcher = patch('solver_registry.REGISTRY_DB', self.original_registry_db)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_init_db_creates_schema(self):
        """Test that init_db creates the database schema."""
        # Verify the schema by inserting a run
        register_run(
            run_id="test-run-1",
            repo="owner/repo",
            issue="123",
            branch="ai/fix-issue-123",
            worker_adapter="opencode",
            model_name="claude",
            pid_tree="12345",
            run_report_path="/tmp/report.json",
        )
        
        run = get_run("test-run-1")
        self.assertIsNotNone(run)
        self.assertEqual(run["run_id"], "test-run-1")
        self.assertEqual(run["repo"], "owner/repo")
        self.assertEqual(run["status"], "healthy")

    def test_register_run(self):
        """Test registering a new run."""
        register_run(
            run_id="test-run-1",
            repo="owner/repo",
            issue="123",
            branch="ai/fix-issue-123",
            worker_adapter="opencode",
            model_name="claude",
            pid_tree="12345",
            run_report_path="/tmp/report.json",
        )
        
        run = get_run("test-run-1")
        self.assertIsNotNone(run)
        self.assertEqual(run["run_id"], "test-run-1")
        self.assertEqual(run["repo"], "owner/repo")
        self.assertEqual(run["issue"], "123")
        self.assertEqual(run["branch"], "ai/fix-issue-123")
        self.assertEqual(run["worker_adapter"], "opencode")
        self.assertEqual(run["model_name"], "claude")
        self.assertEqual(run["pid_tree"], "12345")
        self.assertEqual(run["run_report_path"], "/tmp/report.json")
        self.assertEqual(run["status"], "healthy")
        self.assertEqual(run["local_changes"], 0)

    def test_get_run_nonexistent(self):
        """Test getting a non-existent run."""
        run = get_run("nonexistent-run")
        self.assertIsNone(run)

    def test_terminate_run(self):
        """Test terminating a run."""
        register_run(
            run_id="test-run-1",
            repo="owner/repo",
            issue="123",
            branch="ai/fix-issue-123",
            worker_adapter="opencode",
            model_name="claude",
            pid_tree="12345",
            run_report_path="/tmp/report.json",
        )
        
        terminate_run("test-run-1")
        run = get_run("test-run-1")
        self.assertEqual(run["status"], "terminated")

    def test_update_health(self):
        """Test updating run health."""
        register_run(
            run_id="test-run-1",
            repo="owner/repo",
            issue="123",
            branch="ai/fix-issue-123",
            worker_adapter="opencode",
            model_name="claude",
            pid_tree="12345",
            run_report_path="/tmp/report.json",
        )
        
        update_health("test-run-1", current_phase="worker_running", status="unhealthy")
        run = get_run("test-run-1")
        self.assertEqual(run["status"], "unhealthy")
        self.assertEqual(run["current_phase"], "worker_running")

    def test_mark_local_changes(self):
        """Test marking local changes."""
        register_run(
            run_id="test-run-1",
            repo="owner/repo",
            issue="123",
            branch="ai/fix-issue-123",
            worker_adapter="opencode",
            model_name="claude",
            pid_tree="12345",
            run_report_path="/tmp/report.json",
        )
        
        mark_local_changes("test-run-1", has_changes=True)
        run = get_run("test-run-1")
        self.assertTrue(run["local_changes"])

    def test_get_active_runs(self):
        """Test getting active runs."""
        # Register two runs
        register_run(
            run_id="test-run-1",
            repo="owner/repo",
            issue="123",
            branch="ai/fix-issue-123",
            worker_adapter="opencode",
            model_name="claude",
            pid_tree="12345",
            run_report_path="/tmp/report1.json",
        )
        register_run(
            run_id="test-run-2",
            repo="owner/repo",
            issue="456",
            branch="ai/fix-issue-456",
            worker_adapter="opencode",
            model_name="claude",
            pid_tree="67890",
            run_report_path="/tmp/report2.json",
        )
        
        # Terminate one run
        terminate_run("test-run-1")
        
        # Get active runs
        active_runs = get_active_runs()
        self.assertEqual(len(active_runs), 1)
        self.assertEqual(active_runs[0]["run_id"], "test-run-2")
        self.assertEqual(active_runs[0]["status"], "healthy")

    def test_run_dict_structure(self):
        """Test that run dictionaries contain all required fields."""
        register_run(
            run_id="test-run-1",
            repo="owner/repo",
            issue="123",
            branch="ai/fix-issue-123",
            worker_adapter="opencode",
            model_name="claude",
            pid_tree="12345",
            run_report_path="/tmp/report.json",
        )
        
        run = get_run("test-run-1")
        required_fields = {
            "run_id", "repo", "issue", "branch", "worker_adapter", 
            "model_name", "pid_tree", "run_report_path", "status", 
            "local_changes", "current_phase"
        }
        self.assertTrue(required_fields.issubset(run.keys()))


if __name__ == "__main__":
    unittest.main()