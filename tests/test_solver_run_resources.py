#!/usr/bin/env python3
"""Tests für solver_run_resources.py — Per-Run-Ressourcenmodell und Locking.

Abgedeckte Szenarien:
- Zwei parallele Same-Repo-Runs (verschiedene Issues): kein Lock-Konflikt
- Zwei parallele Same-Issue-Runs: Lock-Konflikt erkannt
- Stale Locks werden automatisch übernommen
- Branch-Name-Konflikte werden erkannt
- Cleanup nach fehlgeschlagenen Runs
- Ressourcen-Diagnosen erscheinen in Run-Report-Metadaten
- Lock-Akquisition mit Timeout
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import time
import unittest
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from solver_run_resources import (
    LOCK_STALE_SECONDS,
    LockMetadata,
    ResourceLock,
    RunResourceDiagnostics,
    RunResources,
    cleanup_stale_locks,
    create_run_resources,
    detect_branch_name_conflict,
    format_resource_diagnostics_summary_lines,
    make_run_id,
    write_resource_diagnostics_to_report,
    _lock_path,
    _read_lock,
    _write_lock,
    _remove_lock,
    _is_stale_lock,
)


def _make_resources(
    repo: str = "my-repo",
    issue_number: int = 42,
    branch_name: str = "ai/fix-issue-42",
    provider: str = "opencode",
    run_id: str | None = None,
    tmp_base: Path | None = None,
    report_path: Path | None = None,
    comparison_id: str | None = None,
) -> RunResources:
    """Hilfsfunktion: erzeugt RunResources für Tests."""
    tmp_base = tmp_base or Path(tempfile.mkdtemp())
    report_path = report_path or Path(tempfile.mkdtemp())
    return create_run_resources(
        repo=repo,
        issue_number=issue_number,
        branch_name=branch_name,
        provider=provider,
        base_branch="main",
        temp_base=tmp_base,
        report_path=report_path,
        cleanup_on_exit=False,
        comparison_id=comparison_id,
        run_id=run_id or f"test-{repo}-{issue_number}-{branch_name}",
    )


# ─────────────────────────────────────────────────────────────
# RunResources-Modell-Tests
# ─────────────────────────────────────────────────────────────

class RunResourcesModelTests(unittest.TestCase):
    def test_issue_key_contains_repo_and_issue_number(self):
        resources = _make_resources(repo="demo", issue_number=7)
        self.assertIn("demo", resources.issue_key)
        self.assertIn("7", resources.issue_key)

    def test_branch_lock_key_contains_repo_and_branch(self):
        resources = _make_resources(repo="demo", branch_name="ai/fix-issue-7")
        self.assertIn("demo", resources.branch_lock_key)
        self.assertIn("ai/fix-issue-7", resources.branch_lock_key)

    def test_to_report_dict_contains_no_secrets(self):
        resources = _make_resources(repo="demo", issue_number=7)
        d = resources.to_report_dict()
        # Pflichtfelder vorhanden
        self.assertIn("run_id", d)
        self.assertIn("repo", d)
        self.assertIn("branch_name", d)
        self.assertIn("provider", d)
        # Kein Feld mit Credentials
        combined = json.dumps(d)
        for secret_word in ("token", "password", "secret", "api_key"):
            self.assertNotIn(secret_word, combined.lower())

    def test_checkout_path_is_isolated_per_run(self):
        r1 = _make_resources(repo="demo", run_id="run-001")
        r2 = _make_resources(repo="demo", run_id="run-002")
        self.assertNotEqual(r1.checkout_path, r2.checkout_path)

    def test_comparison_id_exposed_in_report_dict(self):
        resources = _make_resources(comparison_id="bench-alpha")
        d = resources.to_report_dict()
        self.assertEqual(d["comparison_id"], "bench-alpha")

    def test_make_run_id_is_unique_across_calls(self):
        ids = {
            make_run_id("repo", 1, "opencode", now_fn=lambda: datetime(2026, 1, 1, 0, 0, 0, i))
            for i in range(5)
        }
        # Alle IDs müssen unterschiedlich sein (Mikrosekunden variieren)
        self.assertEqual(len(ids), 5)

    def test_make_run_id_has_no_slashes(self):
        run_id = make_run_id("owner/repo", 42, "opencode/mistral-large")
        self.assertNotIn("/", run_id)

    def test_make_run_id_comparison_id_in_output(self):
        run_id = make_run_id("repo", 42, comparison_id="bench-1")
        self.assertIn("cmp-bench-1", run_id)


# ─────────────────────────────────────────────────────────────
# Lock-Datei-Tests
# ─────────────────────────────────────────────────────────────

class LockFileTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.locks_root = Path(self.tmpdir.name) / "locks"
        self.locks_root.mkdir()

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_write_and_read_lock_roundtrip(self):
        resources = _make_resources(run_id="run-abc")
        lock_file = _lock_path("test-key", self.locks_root)
        _write_lock(lock_file, resources)

        meta = _read_lock(lock_file)
        self.assertIsNotNone(meta)
        self.assertEqual(meta.run_id, "run-abc")
        self.assertEqual(meta.repo, "my-repo")
        self.assertGreater(meta.pid, 0)
        # Keine Secrets in der Lock-Datei
        content = lock_file.read_text(encoding="utf-8")
        for secret_word in ("token", "password", "api_key"):
            self.assertNotIn(secret_word, content.lower())

    def test_read_lock_returns_none_for_missing_file(self):
        missing = self.locks_root / "nonexistent.lock"
        self.assertIsNone(_read_lock(missing))

    def test_read_lock_returns_none_for_corrupt_file(self):
        corrupt = self.locks_root / "corrupt.lock"
        corrupt.write_text("this is not json", encoding="utf-8")
        self.assertIsNone(_read_lock(corrupt))

    def test_remove_lock_deletes_file(self):
        resources = _make_resources()
        lock_file = _lock_path("remove-key", self.locks_root)
        _write_lock(lock_file, resources)
        self.assertTrue(lock_file.exists())
        _remove_lock(lock_file)
        self.assertFalse(lock_file.exists())

    def test_remove_lock_tolerates_missing_file(self):
        missing = self.locks_root / "missing.lock"
        # Darf keine Exception werfen
        result = _remove_lock(missing)
        self.assertTrue(result)

    def test_is_stale_lock_based_on_age(self):
        resources = _make_resources()
        lock_file = _lock_path("stale-key", self.locks_root)
        _write_lock(lock_file, resources)

        # Noch nicht veraltet (Zeitstempel jetzt, Threshold 1 Sekunde in Zukunft)
        self.assertFalse(_is_stale_lock(lock_file, stale_seconds=999999))
        # Als veraltet betrachtet, wenn Threshold 0
        self.assertTrue(_is_stale_lock(lock_file, stale_seconds=0))

    def test_lock_key_with_slashes_becomes_safe_filename(self):
        lock_file = _lock_path("my-repo/branch-ai/fix", self.locks_root)
        self.assertNotIn("/", lock_file.name)


# ─────────────────────────────────────────────────────────────
# ResourceLock-Tests
# ─────────────────────────────────────────────────────────────

class ResourceLockTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.locks_root = Path(self.tmpdir.name) / "locks"
        self.locks_root.mkdir()

    def tearDown(self):
        self.tmpdir.cleanup()

    def _make_lock(self, resources: RunResources, key: str = "demo-issue-42",
                   timeout: float = 5.0) -> ResourceLock:
        return ResourceLock(
            key=key,
            resources=resources,
            locks_root=self.locks_root,
            timeout_seconds=timeout,
            poll_interval=0.05,
        )

    def test_acquire_succeeds_when_no_lock_exists(self):
        resources = _make_resources(run_id="run-001")
        lock = self._make_lock(resources)
        diag = RunResourceDiagnostics()

        with lock.acquire(diag) as acquired:
            self.assertTrue(acquired)
            self.assertIn("demo-issue-42", diag.acquired_locks)

    def test_lock_is_released_after_context_exit(self):
        resources = _make_resources(run_id="run-001")
        lock = self._make_lock(resources)
        diag = RunResourceDiagnostics()

        with lock.acquire(diag):
            lock_file = _lock_path("demo-issue-42", self.locks_root)
            self.assertTrue(lock_file.exists())

        # Nach dem Exit muss die Lock-Datei verschwunden sein
        self.assertFalse(lock_file.exists())

    def test_lock_is_released_even_on_exception(self):
        resources = _make_resources(run_id="run-001")
        lock = self._make_lock(resources)
        diag = RunResourceDiagnostics()
        lock_file = _lock_path("demo-issue-42", self.locks_root)

        try:
            with lock.acquire(diag):
                raise RuntimeError("Absichtlicher Fehler")
        except RuntimeError:
            pass

        self.assertFalse(lock_file.exists())

    def test_same_run_id_can_reenter_own_lock(self):
        """Derselbe Run kann seinen eigenen Lock erneut erwerben."""
        resources = _make_resources(run_id="run-same")
        lock1 = self._make_lock(resources, key="demo-issue-42")
        lock2 = self._make_lock(resources, key="demo-issue-42")
        diag = RunResourceDiagnostics()

        with lock1.acquire(diag) as acquired1:
            self.assertTrue(acquired1)
            with lock2.acquire(diag) as acquired2:
                self.assertTrue(acquired2)

    def test_two_same_repo_different_issue_runs_do_not_conflict(self):
        """Zwei parallele Runs desselben Repos auf verschiedenen Issues dürfen nicht blockieren."""
        r1 = _make_resources(repo="demo", issue_number=1, run_id="run-001")
        r2 = _make_resources(repo="demo", issue_number=2, run_id="run-002")

        lock1 = self._make_lock(r1, key=r1.issue_key)
        lock2 = self._make_lock(r2, key=r2.issue_key)
        diag1 = RunResourceDiagnostics()
        diag2 = RunResourceDiagnostics()

        results: list[bool] = []

        with lock1.acquire(diag1) as a1:
            with lock2.acquire(diag2) as a2:
                results.append(a1)
                results.append(a2)

        # Beide müssen erfolgreich sein — kein Konflikt
        self.assertEqual(results, [True, True])
        self.assertFalse(diag1.lock_conflicts)
        self.assertFalse(diag2.lock_conflicts)

    def test_two_same_issue_parallel_runs_conflict(self):
        """Zwei parallele Runs auf demselben Issue erkennen den Konflikt."""
        r1 = _make_resources(repo="demo", issue_number=42, run_id="run-A")
        r2 = _make_resources(repo="demo", issue_number=42, run_id="run-B")

        lock1 = self._make_lock(r1, key=r1.issue_key, timeout=0.3)
        lock2 = self._make_lock(r2, key=r2.issue_key, timeout=0.3)
        diag1 = RunResourceDiagnostics()
        diag2 = RunResourceDiagnostics()

        with lock1.acquire(diag1) as acquired1:
            self.assertTrue(acquired1)
            # Lock2 soll nicht erworben werden können (gleicher Key, anderer Run)
            with lock2.acquire(diag2) as acquired2:
                second_acquired = acquired2

        # run-B muss am Lock scheitern
        self.assertFalse(second_acquired)
        self.assertTrue(diag2.lock_acquire_failures or diag2.lock_conflicts)

    def test_stale_lock_from_dead_process_is_cleaned_up(self):
        """Lock eines bereits beendeten Prozesses wird übernommen."""
        resources_stale = _make_resources(run_id="run-dead")
        lock_file = _lock_path("demo-issue-99", self.locks_root)

        # Schreibe Lock mit PID 0 (garantiert inaktiv)
        meta_data = {
            "run_id": "run-dead",
            "pid": 0,
            "branch_name": "ai/fix-issue-99",
            "repo": "demo",
            "issue_number": 99,
            "started_at": "2020-01-01T00:00:00",
            "provider": "opencode",
        }
        self.locks_root.mkdir(parents=True, exist_ok=True)
        lock_file.write_text(json.dumps(meta_data), encoding="utf-8")

        resources_new = _make_resources(repo="demo", issue_number=99, run_id="run-new")
        lock = self._make_lock(resources_new, key="demo-issue-99")
        diag = RunResourceDiagnostics()

        with lock.acquire(diag) as acquired:
            self.assertTrue(acquired)
            self.assertTrue(diag.stale_locks_cleaned)

    def test_timeout_failure_recorded_in_diagnostics(self):
        """Lock-Timeout wird in diagnostics.lock_acquire_failures eingetragen."""
        r1 = _make_resources(repo="demo", issue_number=5, run_id="run-holder")
        r2 = _make_resources(repo="demo", issue_number=5, run_id="run-waiter")

        # Manuell Lock schreiben mit echtem aktiven PID
        lock_file = _lock_path(r1.issue_key, self.locks_root)
        self.locks_root.mkdir(parents=True, exist_ok=True)
        meta_data = {
            "run_id": "run-holder",
            "pid": os.getpid(),  # Eigener aktiver Prozess
            "branch_name": "ai/fix-issue-5",
            "repo": "demo",
            "issue_number": 5,
            "started_at": datetime.now().isoformat(timespec="seconds"),
            "provider": "opencode",
        }
        lock_file.write_text(json.dumps(meta_data), encoding="utf-8")

        lock2 = ResourceLock(
            key=r1.issue_key,
            resources=r2,
            locks_root=self.locks_root,
            timeout_seconds=0.1,
            poll_interval=0.05,
        )
        diag = RunResourceDiagnostics()

        with lock2.acquire(diag) as acquired:
            self.assertFalse(acquired)

        self.assertTrue(diag.lock_acquire_failures)
        self.assertIn("Timeout", diag.lock_acquire_failures[0])


# ─────────────────────────────────────────────────────────────
# Branch-Konflikt-Tests
# ─────────────────────────────────────────────────────────────

class BranchConflictTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.locks_root = Path(self.tmpdir.name) / "locks"
        self.locks_root.mkdir()

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_no_conflict_when_locks_dir_empty(self):
        result = detect_branch_name_conflict(
            branch_name="ai/fix-issue-42",
            repo="demo",
            issue_number=42,
            locks_root=self.locks_root,
        )
        self.assertIsNone(result)

    def test_conflict_detected_when_branch_used_by_active_run(self):
        """Konflikt erkannt, wenn ein anderer laufender Run denselben Branch beansprucht."""
        lock_file = self.locks_root / "existing.lock"
        meta_data = {
            "run_id": "other-run-xyz",
            "pid": os.getpid(),  # Eigener aktiver Prozess
            "branch_name": "ai/fix-issue-42",
            "repo": "demo",
            "issue_number": 42,
            "started_at": datetime.now().isoformat(timespec="seconds"),
            "provider": "opencode",
        }
        lock_file.write_text(json.dumps(meta_data), encoding="utf-8")

        result = detect_branch_name_conflict(
            branch_name="ai/fix-issue-42",
            repo="demo",
            issue_number=42,
            locks_root=self.locks_root,
            own_run_id="my-run-abc",
        )
        self.assertIsNotNone(result)
        self.assertIn("other-run-xyz", result)
        self.assertIn("ai/fix-issue-42", result)

    def test_no_conflict_when_branch_used_by_dead_process(self):
        """Kein Konflikt, wenn der haltende Prozess nicht mehr läuft."""
        lock_file = self.locks_root / "dead.lock"
        meta_data = {
            "run_id": "dead-run",
            "pid": 0,  # Inaktiver Prozess
            "branch_name": "ai/fix-issue-42",
            "repo": "demo",
            "issue_number": 42,
            "started_at": "2020-01-01T00:00:00",
            "provider": "opencode",
        }
        lock_file.write_text(json.dumps(meta_data), encoding="utf-8")

        result = detect_branch_name_conflict(
            branch_name="ai/fix-issue-42",
            repo="demo",
            issue_number=42,
            locks_root=self.locks_root,
        )
        self.assertIsNone(result)

    def test_no_conflict_for_own_run_id(self):
        """Kein Konflikt, wenn der Lock vom eigenen Run gehalten wird."""
        lock_file = self.locks_root / "own.lock"
        meta_data = {
            "run_id": "my-run",
            "pid": os.getpid(),
            "branch_name": "ai/fix-issue-42",
            "repo": "demo",
            "issue_number": 42,
            "started_at": datetime.now().isoformat(timespec="seconds"),
            "provider": "opencode",
        }
        lock_file.write_text(json.dumps(meta_data), encoding="utf-8")

        result = detect_branch_name_conflict(
            branch_name="ai/fix-issue-42",
            repo="demo",
            issue_number=42,
            locks_root=self.locks_root,
            own_run_id="my-run",
        )
        self.assertIsNone(result)

    def test_no_conflict_for_different_branch(self):
        """Kein Konflikt, wenn der andere Run einen anderen Branch nutzt."""
        lock_file = self.locks_root / "other.lock"
        meta_data = {
            "run_id": "other-run",
            "pid": os.getpid(),
            "branch_name": "ai/fix-issue-99",  # Anderer Branch
            "repo": "demo",
            "issue_number": 99,
            "started_at": datetime.now().isoformat(timespec="seconds"),
            "provider": "opencode",
        }
        lock_file.write_text(json.dumps(meta_data), encoding="utf-8")

        result = detect_branch_name_conflict(
            branch_name="ai/fix-issue-42",
            repo="demo",
            issue_number=42,
            locks_root=self.locks_root,
        )
        self.assertIsNone(result)


# ─────────────────────────────────────────────────────────────
# Stale-Lock-Cleanup-Tests
# ─────────────────────────────────────────────────────────────

class StaleLockCleanupTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.locks_root = Path(self.tmpdir.name) / "locks"
        self.locks_root.mkdir()

    def tearDown(self):
        self.tmpdir.cleanup()

    def _write_lock_file(self, name: str, pid: int = 0,
                         started_at: str = "2020-01-01T00:00:00") -> Path:
        lock_file = self.locks_root / f"{name}.lock"
        meta = {
            "run_id": f"run-{name}",
            "pid": pid,
            "branch_name": f"ai/fix-{name}",
            "repo": "demo",
            "issue_number": 1,
            "started_at": started_at,
            "provider": "opencode",
        }
        lock_file.write_text(json.dumps(meta), encoding="utf-8")
        return lock_file

    def test_cleanup_stale_locks_dry_run_does_not_delete(self):
        lock_file = self._write_lock_file("stale-dry")
        # Setze mtime auf weit in der Vergangenheit
        old_time = time.time() - LOCK_STALE_SECONDS - 1000
        os.utime(lock_file, (old_time, old_time))

        stale = cleanup_stale_locks(
            locks_root=self.locks_root,
            dry_run=True,
        )
        self.assertIn(lock_file, stale)
        # Datei muss noch existieren
        self.assertTrue(lock_file.exists())

    def test_cleanup_stale_locks_deletes_when_not_dry_run(self):
        lock_file = self._write_lock_file("stale-delete")
        old_time = time.time() - LOCK_STALE_SECONDS - 1000
        os.utime(lock_file, (old_time, old_time))

        stale = cleanup_stale_locks(
            locks_root=self.locks_root,
            dry_run=False,
        )
        self.assertIn(lock_file, stale)
        self.assertFalse(lock_file.exists())

    def test_cleanup_stale_locks_keeps_active_process_lock(self):
        """Lock mit eigenem aktivem PID wird nicht als stale behandelt."""
        lock_file = self._write_lock_file("active-lock", pid=os.getpid())
        # Setze Zeitstempel auf alt, aber PID ist aktiv
        old_time = time.time() - LOCK_STALE_SECONDS - 1000
        os.utime(lock_file, (old_time, old_time))

        stale = cleanup_stale_locks(
            locks_root=self.locks_root,
            dry_run=False,
        )
        # Lock mit aktivem Prozess darf NICHT bereinigt werden
        self.assertNotIn(lock_file, stale)
        self.assertTrue(lock_file.exists())

    def test_cleanup_stale_locks_returns_empty_for_missing_dir(self):
        missing = Path(self.tmpdir.name) / "nonexistent-locks"
        result = cleanup_stale_locks(locks_root=missing, dry_run=True)
        self.assertEqual(result, [])

    def test_cleanup_ignores_fresh_locks(self):
        lock_file = self._write_lock_file("fresh")
        # Zeitstempel ist aktuell → nicht stale
        stale = cleanup_stale_locks(
            locks_root=self.locks_root,
            stale_seconds=LOCK_STALE_SECONDS,
            dry_run=True,
        )
        self.assertNotIn(lock_file, stale)


# ─────────────────────────────────────────────────────────────
# RunResourceDiagnostics-Tests
# ─────────────────────────────────────────────────────────────

class RunResourceDiagnosticsTests(unittest.TestCase):
    def test_has_findings_false_when_empty(self):
        diag = RunResourceDiagnostics()
        self.assertFalse(diag.has_findings)

    def test_has_findings_true_with_stale_lock_cleaned(self):
        diag = RunResourceDiagnostics()
        diag.stale_locks_cleaned.append("demo-issue-1")
        self.assertTrue(diag.has_findings)

    def test_has_findings_true_with_branch_conflict(self):
        diag = RunResourceDiagnostics()
        diag.branch_conflict_detected = True
        diag.branch_conflict_message = "Branch bereits belegt"
        self.assertTrue(diag.has_findings)

    def test_to_report_dict_serializable_as_json(self):
        diag = RunResourceDiagnostics()
        diag.acquired_locks.append("demo-issue-42")
        diag.stale_locks_cleaned.append("demo-issue-1 (veraltet)")
        diag.lock_conflicts.append("Konflikt: anderer Run")
        d = diag.to_report_dict()
        # Muss JSON-serialisierbar sein
        serialized = json.dumps(d)
        self.assertIn("demo-issue-42", serialized)

    def test_to_summary_lines_empty_when_no_findings(self):
        diag = RunResourceDiagnostics()
        lines = diag.to_summary_lines()
        self.assertEqual(lines, [])

    def test_to_summary_lines_contains_stale_lock_info(self):
        diag = RunResourceDiagnostics()
        diag.stale_locks_cleaned.append("demo-issue-1")
        lines = diag.to_summary_lines()
        self.assertTrue(any("Stale" in line or "bereinigt" in line for line in lines))

    def test_format_resource_diagnostics_summary_lines_prefixed(self):
        diag = RunResourceDiagnostics()
        diag.lock_conflicts.append("Konflikt: run-A vs run-B")
        lines = format_resource_diagnostics_summary_lines(diag)
        self.assertTrue(lines)
        self.assertIn("resource_diagnostics:", lines[0])


# ─────────────────────────────────────────────────────────────
# Report-Integration-Tests
# ─────────────────────────────────────────────────────────────

class ResourceDiagnosticsReportTests(unittest.TestCase):
    def test_write_resource_diagnostics_creates_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            report_path = Path(tmpdir)
            resources = _make_resources(run_id="run-report-test", report_path=report_path)
            diag = RunResourceDiagnostics()
            diag.acquired_locks.append("demo-issue-42")
            diag.stale_locks_cleaned.append("old-lock")

            write_resource_diagnostics_to_report(report_path, resources, diag)

            diag_file = report_path / "resource-diagnostics.json"
            self.assertTrue(diag_file.exists())

            data = json.loads(diag_file.read_text(encoding="utf-8"))
            self.assertEqual(data["run_id"], "run-report-test")
            self.assertIn("resources", data)
            self.assertIn("diagnostics", data)
            self.assertIn("old-lock", data["diagnostics"]["stale_locks_cleaned"])
            # Keine Secrets in der Datei
            content = diag_file.read_text(encoding="utf-8")
            for secret_word in ("token", "password", "api_key"):
                self.assertNotIn(secret_word, content.lower())

    def test_write_resource_diagnostics_tolerates_oserror(self):
        """Schreib-Fehler darf nicht zu einer Exception führen."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Schreibgeschütztes Verzeichnis simulieren durch nicht-existenten Pfad
            bad_path = Path(tmpdir) / "nonexistent-subdir"
            resources = _make_resources(run_id="run-err", report_path=bad_path)
            diag = RunResourceDiagnostics()
            # Darf keine Exception werfen
            write_resource_diagnostics_to_report(bad_path, resources, diag)


# ─────────────────────────────────────────────────────────────
# Parallele Runs — Integrations-Tests
# ─────────────────────────────────────────────────────────────

class ParallelRunsIntegrationTests(unittest.TestCase):
    """
    Simuliert parallele Solver-Jobs und prüft dass Checkouts, Locks und
    Ressourcen korrekt isoliert bleiben.
    """

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.locks_root = Path(self.tmpdir.name) / "locks"
        self.locks_root.mkdir()

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_parallel_same_repo_different_issues_no_lock_conflict(self):
        """
        Zwei parallele Runs desselben Repos auf verschiedenen Issues:
        beide sollen ihren Lock erwerben können.
        """
        results: dict[str, bool] = {}
        errors: list[str] = []

        def run_job(run_id: str, issue_number: int) -> None:
            resources = _make_resources(
                repo="shared-repo",
                issue_number=issue_number,
                run_id=run_id,
            )
            lock = ResourceLock(
                key=resources.issue_key,
                resources=resources,
                locks_root=self.locks_root,
                timeout_seconds=5.0,
                poll_interval=0.05,
            )
            diag = RunResourceDiagnostics()
            try:
                with lock.acquire(diag) as acquired:
                    results[run_id] = acquired
                    time.sleep(0.05)  # Kritischer Abschnitt simulieren
            except Exception as exc:
                errors.append(str(exc))

        t1 = threading.Thread(target=run_job, args=("run-issue-1", 1))
        t2 = threading.Thread(target=run_job, args=("run-issue-2", 2))
        t1.start()
        t2.start()
        t1.join(timeout=10)
        t2.join(timeout=10)

        self.assertFalse(errors, f"Unerwartete Fehler: {errors}")
        self.assertTrue(results.get("run-issue-1"), "run-issue-1 musste Lock erwerben")
        self.assertTrue(results.get("run-issue-2"), "run-issue-2 musste Lock erwerben")

    def test_parallel_same_issue_two_provider_attempts_never_overlap(self):
        """
        Zwei parallele Runs für dasselbe Issue (Benchmark-Gruppe mit zwei Providern):
        Sie dürfen den kritischen Abschnitt nie gleichzeitig betreten.
        Jeder Run braucht exklusive Checkouts und unterschiedliche Branch-Namen.

        Erwartetes Verhalten: Beide können den Lock erwerben, aber niemals gleichzeitig.
        Der zweite wartet, bis der erste den Lock freigibt.
        """
        concurrent_holders: list[int] = []  # Maximale gleichzeitige Halter
        currently_holding = 0
        max_concurrent = 0
        lock = threading.Lock()
        barrier = threading.Barrier(2)  # Beide Threads gleichzeitig starten

        def run_job(run_id: str) -> None:
            nonlocal currently_holding, max_concurrent
            resources = _make_resources(
                repo="bench-repo",
                issue_number=42,
                run_id=run_id,
                # Unterschiedliche Branch-Namen für Benchmark-Gruppen
                branch_name=f"ai/fix-issue-42-{run_id}",
            )
            res_lock = ResourceLock(
                key=resources.issue_key,
                resources=resources,
                locks_root=self.locks_root,
                timeout_seconds=2.0,
                poll_interval=0.02,
            )
            diag = RunResourceDiagnostics()
            barrier.wait()  # Synchron starten
            with res_lock.acquire(diag) as acquired:
                if acquired:
                    with lock:
                        currently_holding += 1
                        max_concurrent = max(max_concurrent, currently_holding)
                    time.sleep(0.05)  # Kritischen Abschnitt kurz halten
                    with lock:
                        currently_holding -= 1

        t1 = threading.Thread(target=run_job, args=("provider-A",))
        t2 = threading.Thread(target=run_job, args=("provider-B",))
        t1.start()
        t2.start()
        t1.join(timeout=10)
        t2.join(timeout=10)

        # Niemals mehr als ein Holder gleichzeitig
        self.assertEqual(max_concurrent, 1,
                         "Zwei parallele Same-Issue-Runs dürfen nie gleichzeitig den Lock halten")

    def test_checkout_paths_are_exclusive_per_run(self):
        """Checkouts dürfen sich nicht überschneiden."""
        r1 = _make_resources(repo="demo", issue_number=1, run_id="run-A")
        r2 = _make_resources(repo="demo", issue_number=1, run_id="run-B")
        self.assertNotEqual(r1.checkout_path, r2.checkout_path)
        self.assertNotEqual(r1.temp_path, r2.temp_path)

    def test_report_paths_are_exclusive_per_run(self):
        """Report-Pfade müssen pro Run eindeutig sein."""
        with tempfile.TemporaryDirectory() as tmpdir:
            r1_report = Path(tmpdir) / "run-A-report"
            r2_report = Path(tmpdir) / "run-B-report"
            r1 = _make_resources(repo="demo", issue_number=1, run_id="run-A",
                                  report_path=r1_report)
            r2 = _make_resources(repo="demo", issue_number=1, run_id="run-B",
                                  report_path=r2_report)
            self.assertNotEqual(r1.report_path, r2.report_path)

    def test_benchmark_group_same_issue_distinct_branch_names(self):
        """
        Same-Issue-Benchmark-Gruppe: Beide Runs müssen unterschiedliche Branch-Namen haben.
        """
        r1 = _make_resources(
            repo="bench", issue_number=10,
            branch_name="ai/fix-issue-10-mistral",
            run_id="run-mistral",
            comparison_id="bench-alpha",
        )
        r2 = _make_resources(
            repo="bench", issue_number=10,
            branch_name="ai/fix-issue-10-claude",
            run_id="run-claude",
            comparison_id="bench-alpha",
        )
        self.assertNotEqual(r1.branch_name, r2.branch_name)
        self.assertEqual(r1.comparison_id, r2.comparison_id)


if __name__ == "__main__":
    unittest.main()
