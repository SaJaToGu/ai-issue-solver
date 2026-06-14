"""Testet die Helper-Scripts des solver-reporting-Skills.

Diese Tests sind unabhängig von einem GitHub-Token oder KI-Worker.
Sie erzeugen synthetische Run-Report-Verzeichnisse und prüfen das
Verhalten der Helper-Skripte.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
HELPERS = SKILL_ROOT / "helpers"
REPO_ROOT = SKILL_ROOT.parents[3]


def run_python(script: Path, *args: str, cwd: Path | None = None) -> subprocess.CompletedProcess:
    cmd = [sys.executable, str(script), *args]
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        check=False,
        cwd=str(cwd) if cwd else None,
        env={**os.environ, "PYTHONPATH": ""},
    )


def run_python_with_path(script: Path, *args: str,
                          cwd: Path | None = None) -> subprocess.CompletedProcess:
    """Führt ein Helper-Script mit PYTHONPATH=<repo_root> aus.

    Die Helpers in ``.agents/skills/solver-reporting/helpers/`` fügen den
    Repo-Root selbst zu ``sys.path`` hinzu, aber in Subprozessen ohne
    gesetztes ``PYTHONPATH`` funktioniert das Modul-Import via
    ``from scripts.utils import ...``.
    """
    cmd = [sys.executable, str(script), *args]
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        check=False,
        cwd=str(cwd) if cwd else None,
        env={**os.environ, "PYTHONPATH": str(REPO_ROOT)},
    )


def run_bash(script: Path, *args: str, cwd: Path | None = None,
            env: dict | None = None) -> subprocess.CompletedProcess:
    cmd = ["bash", str(script), *args]
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        check=False,
        cwd=str(cwd) if cwd else None,
        env={**os.environ, **(env or {})},
    )


def write_metadata(reports_dir: Path, run_id: str, metadata: dict) -> None:
    run_dir = reports_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "metadata.json").write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def base_metadata(**overrides) -> dict:
    payload = {
        "status": "pr_created",
        "repo": "myrepo",
        "issue": 3,
        "branch": "ai/fix-issue-3",
        "model": "opencode",
        "worker_exit_code": "0",
        "pr_url": "https://github.com/owner/myrepo/pull/3",
        "provider_scorecard": {
            "requested_model": "opencode/deepseek-v4-flash-free",
            "actual_model": "opencode/deepseek-v4-flash-free",
            "fallback_source": None,
            "duration_seconds": 90.0,
            "worker_exit_code": 0,
            "run_status": "pr_created",
            "pr_url": "https://github.com/owner/myrepo/pull/3",
            "test_command": "pytest",
            "test_result": "passed",
            "no_change": False,
            "fallback_used": False,
            "estimated_cost": 0.05,
            "cost_currency": "USD",
            "cost_confidence": "low",
            "cost_source": "estimated",
        },
        "run_outcome": {
            "worker_status": "succeeded",
            "has_changes": True,
            "test_status": "passed",
            "delivery_status": "pr_created",
            "failure_class": "success",
            "recovery_status": "none",
        },
    }
    payload.update(overrides)
    return payload


class TestAggregateRuns(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.reports_dir = Path(self._tmp.name) / "reports" / "runs"
        self.reports_dir.mkdir(parents=True)
        write_metadata(self.reports_dir, "20260614-1-myrepo-issue-3", base_metadata())
        write_metadata(
            self.reports_dir,
            "20260614-2-myrepo-issue-4",
            base_metadata(
                status="push_failed",
                issue=4,
                run_outcome={
                    "worker_status": "succeeded",
                    "has_changes": True,
                    "test_status": "passed",
                    "delivery_status": "push_failed",
                    "failure_class": "pipeline_failure",
                    "recovery_status": "preserved_worktree",
                },
            ),
        )

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_markdown_output(self) -> None:
        result = run_python(
            HELPERS / "aggregate_runs.py",
            "--reports-dir", str(self.reports_dir),
            "--format", "markdown",
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("| run_id |", result.stdout)
        self.assertIn("20260614-1-myrepo-issue-3", result.stdout)
        self.assertIn("20260614-2-myrepo-issue-4", result.stdout)

    def test_outcome_distribution(self) -> None:
        result = run_python(
            HELPERS / "aggregate_runs.py",
            "--reports-dir", str(self.reports_dir),
            "--format", "outcome",
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("Run-Outcome-Verteilung (2 Runs)", result.stdout)
        self.assertIn("pr_created=1", result.stdout)
        self.assertIn("pipeline_failure=1", result.stdout)

    def test_status_filter(self) -> None:
        result = run_python(
            HELPERS / "aggregate_runs.py",
            "--reports-dir", str(self.reports_dir),
            "--format", "outcome",
            "--status-filter", "pr_created",
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("Run-Outcome-Verteilung (1 Runs)", result.stdout)

    def test_repo_filter(self) -> None:
        write_metadata(
            self.reports_dir,
            "20260614-3-other-issue-1",
            base_metadata(repo="other", issue=1, branch="ai/fix-issue-1"),
        )
        result = run_python(
            HELPERS / "aggregate_runs.py",
            "--reports-dir", str(self.reports_dir),
            "--format", "markdown",
            "--repo-filter", "myrepo",
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("20260614-1-myrepo-issue-3", result.stdout)
        self.assertNotIn("20260614-3-other-issue-1", result.stdout)

    def test_tsv_output(self) -> None:
        result = run_python(
            HELPERS / "aggregate_runs.py",
            "--reports-dir", str(self.reports_dir),
            "--format", "tsv",
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        first_line = result.stdout.splitlines()[0]
        self.assertIn("run_id", first_line)
        self.assertIn("\t", first_line)

    def test_text_output_requires_run_id(self) -> None:
        result = run_python(
            HELPERS / "aggregate_runs.py",
            "--reports-dir", str(self.reports_dir),
            "--format", "text",
        )
        self.assertEqual(result.returncode, 2)

    def test_text_output_for_single_run(self) -> None:
        result = run_python(
            HELPERS / "aggregate_runs.py",
            "--reports-dir", str(self.reports_dir),
            "--run-id", "20260614-1-myrepo-issue-3",
            "--format", "text",
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("status:", result.stdout)
        self.assertIn("repo:                  myrepo", result.stdout)


class TestDiagnoseOpencode(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_no_findings(self) -> None:
        with tempfile.NamedTemporaryFile(
            "w", suffix=".log", delete=False, encoding="utf-8"
        ) as handle:
            handle.write("all good, no runtime issues here\n")
            path = Path(handle.name)
        try:
            result = run_python_with_path(
                HELPERS / "diagnose_opencode.py",
                "--worker-output", str(path),
            )
            self.assertEqual(result.returncode, 0, msg=result.stderr)
            self.assertIn("WAL-Fehler:        keine", result.stdout)
            self.assertIn("Edit-Loop:         keine", result.stdout)
        finally:
            if path.exists():
                path.unlink()

    def test_wal_and_edit_loop_detected(self) -> None:
        with tempfile.NamedTemporaryFile(
            "w", suffix=".log", delete=False, encoding="utf-8"
        ) as handle:
            handle.write("PRAGMA wal_checkpoint(PASSIVE)\n")
            handle.write("Edit README.md failed\n")
            handle.write("Edit scripts/a.py failed\n")
            handle.write("Edit scripts/b.py failed\n")
            handle.write("Edit scripts/c.py failed\n")
            path = Path(handle.name)
        try:
            result = run_python_with_path(
                HELPERS / "diagnose_opencode.py",
                "--worker-output", str(path),
                "--strict",
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("WAL-Fehler:        erkannt", result.stdout)
            self.assertIn("Edit-Loop:         erkannt", result.stdout)
            self.assertIn("Edit-Failures:     4", result.stdout)
        finally:
            if path.exists():
                path.unlink()

    def test_stdin_input(self) -> None:
        result = subprocess.run(
            [sys.executable, str(HELPERS / "diagnose_opencode.py"), "--stdin", "--json"],
            input="Edit foo.py failed\n",
            capture_output=True,
            text=True,
            check=False,
            env={**os.environ, "PYTHONPATH": str(REPO_ROOT)},
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["wal_failure"], False)
        self.assertEqual(payload["edit_loop"], False)
        self.assertEqual(payload["edit_failure_count"], 1)


class TestFormatHeartbeat(unittest.TestCase):
    def test_basic_output(self) -> None:
        result = run_python_with_path(
            HELPERS / "format_heartbeat.py",
            "--issue", "223",
            "--elapsed-seconds", "1020",
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        # width = elapsed_minutes // 2 = 17 // 2 = 8
        self.assertEqual(result.stdout.strip(), "#223 ....+... 17min")

    def test_with_job_label(self) -> None:
        result = run_python_with_path(
            HELPERS / "format_heartbeat.py",
            "--issue", "223",
            "--elapsed-seconds", "1020",
            "--job-label", "PR2",
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("PR2", result.stdout)
        self.assertTrue(result.stdout.strip().startswith("#223"))

    def test_progress_only(self) -> None:
        result = run_python_with_path(
            HELPERS / "format_heartbeat.py",
            "--issue", "223",
            "--elapsed-seconds", "1020",
            "--progress-only",
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertNotIn("#223", result.stdout)
        self.assertIn("17min", result.stdout)

    def test_json_output(self) -> None:
        result = run_python_with_path(
            HELPERS / "format_heartbeat.py",
            "--issue", "223",
            "--elapsed-seconds", "60",
            "--job-label", "codex",
            "--json",
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["issue"], 223)
        self.assertEqual(payload["job_label"], "codex")
        self.assertTrue(payload["heartbeat"].startswith("#223"))


class TestCleanupWorktrees(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name) / "reports" / "preserved-worktrees"
        self.root.mkdir(parents=True)
        self.cwd_backup = Path.cwd()

    def tearDown(self) -> None:
        os.chdir(self.cwd_backup)
        self._tmp.cleanup()

    def _make_stale(self, name: str = "stale") -> Path:
        target = self.root / name
        target.mkdir(parents=True, exist_ok=True)
        old_time = time.time() - 30 * 24 * 60 * 60
        os.utime(target, (old_time, old_time))
        return target

    def test_dry_run_lists_candidates(self) -> None:
        target = self._make_stale("stale")
        result = run_bash(
            HELPERS / "cleanup_worktrees.sh",
            "--root", str(self.root),
            "--retention-days", "14",
            env={"SOLVER_REPORTING_ALLOW_UNSAFE_ROOT": "1"},
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("Kandidaten", result.stdout)
        self.assertIn("stale", result.stdout)
        self.assertIn("Dry-Run:        ja", result.stdout)
        # Datei muss noch existieren
        self.assertTrue(target.exists())

    def test_apply_removes_candidates(self) -> None:
        target = self._make_stale("stale")
        result = run_bash(
            HELPERS / "cleanup_worktrees.sh",
            "--root", str(self.root),
            "--retention-days", "14",
            "--apply",
            env={"SOLVER_REPORTING_ALLOW_UNSAFE_ROOT": "1"},
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("Gelöscht:  1", result.stdout)
        self.assertFalse(target.exists())

    def test_refuses_unsafe_root(self) -> None:
        result = run_bash(
            HELPERS / "cleanup_worktrees.sh",
            "--root", "/tmp/not-under-reports",
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("verweigert", result.stderr)


if __name__ == "__main__":
    unittest.main()
