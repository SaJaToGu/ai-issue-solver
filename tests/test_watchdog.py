#!/usr/bin/env python3
"""test_watchdog.py — Tests für das deterministische Watchdog-Script."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from watchdog import (  # noqa: E402
    CostFinding,
    ProgressFinding,
    WatchdogRun,
    check_cost,
    check_progress,
    check_stuck,
    write_status_report,
    _active_runs,
)


class WatchdogCostCheckTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.runs_dir = Path(self.tmpdir.name)
        self.budget_path = self.runs_dir / "budget_tracker.json"

    def tearDown(self):
        self.tmpdir.cleanup()

    def _write_run_with_cost(self, run_id: str, cost: float | None, status: str = "started"):
        run_dir = self.runs_dir / run_id
        run_dir.mkdir(parents=True)
        metadata = {
            "status": status,
            "repo": "demo",
            "issue_number": 1,
            "model": "test-model",
            "provider_scorecard": {
                "estimated_cost": cost,
                "actual_model": "test-model",
            },
        }
        (run_dir / "metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
        (run_dir / "summary.txt").write_text(f"status: {status}\nrepo: demo\n", encoding="utf-8")

    def _active_runs_from_tmp(self) -> list:
        return _active_runs(self.runs_dir)

    def test_per_run_cost_under_limit_no_finding(self):
        self._write_run_with_cost("run-001", 1.0)
        runs = self._active_runs_from_tmp()
        findings = check_cost(runs, budget_tracker_path=self.budget_path, per_run_limit=5.0)
        self.assertEqual(len(findings), 0)

    def test_per_run_cost_exceeds_limit(self):
        self._write_run_with_cost("run-001", 6.0)
        runs = self._active_runs_from_tmp()
        findings = check_cost(runs, budget_tracker_path=self.budget_path, per_run_limit=5.0)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].kind, "per_run")
        self.assertEqual(findings[0].severity, "warning")
        self.assertIn("$6.00", findings[0].message)
        self.assertIn("$5.00", findings[0].message)

    def test_run_without_cost_skipped(self):
        self._write_run_with_cost("run-001", None)
        runs = self._active_runs_from_tmp()
        findings = check_cost(runs, budget_tracker_path=self.budget_path, per_run_limit=5.0)
        self.assertEqual(len(findings), 0)

    def test_budget_ratio_warning(self):
        tracker = {"solver": {"spent": 18.0, "budget": 20.0}}
        (self.runs_dir / "budget_tracker.json").write_text(
            json.dumps(tracker), encoding="utf-8"
        )
        self._write_run_with_cost("run-001", 1.0)
        runs = self._active_runs_from_tmp()
        findings = check_cost(
            runs, budget_tracker_path=self.budget_path, budget_ratio=0.8
        )
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].kind, "budget_ratio")
        self.assertEqual(findings[0].severity, "warning")
        self.assertIn("90%", findings[0].message)

    def test_budget_ratio_critical_at_100(self):
        tracker = {"solver": {"spent": 20.0, "budget": 20.0}}
        (self.runs_dir / "budget_tracker.json").write_text(
            json.dumps(tracker), encoding="utf-8"
        )
        self._write_run_with_cost("run-001", 1.0)
        runs = self._active_runs_from_tmp()
        findings = check_cost(
            runs, budget_tracker_path=self.budget_path, budget_ratio=0.8
        )
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].severity, "critical")

    def test_budget_ratio_below_threshold_no_finding(self):
        tracker = {"solver": {"spent": 5.0, "budget": 20.0}}
        (self.runs_dir / "budget_tracker.json").write_text(
            json.dumps(tracker), encoding="utf-8"
        )
        self._write_run_with_cost("run-001", 1.0)
        runs = self._active_runs_from_tmp()
        findings = check_cost(
            runs, budget_tracker_path=self.budget_path, budget_ratio=0.8
        )
        self.assertEqual(len(findings), 0)


class WatchdogProgressCheckTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.runs_dir = Path(self.tmpdir.name)

    def tearDown(self):
        self.tmpdir.cleanup()

    def _write_run_with_activity(self, run_id: str, last_activity: str | None, status: str = "started"):
        run_dir = self.runs_dir / run_id
        run_dir.mkdir(parents=True)
        health = {
            "status": status,
            "phase": "worker_running",
        }
        if last_activity:
            health["last_activity_at"] = last_activity
            health["last_report_update_at"] = last_activity
        (run_dir / "health.json").write_text(json.dumps(health), encoding="utf-8")
        (run_dir / "summary.txt").write_text(f"status: {status}\nrepo: demo\nissue: 1\n", encoding="utf-8")

    def test_recent_activity_no_finding(self):
        now = datetime(2026, 6, 17, 12, 0, 0)
        self._write_run_with_activity("run-001", "2026-06-17T11:55:00")
        runs = _active_runs(self.runs_dir)
        findings = check_progress(
            runs, now=now, progress_timeout=timedelta(minutes=30)
        )
        self.assertEqual(len(findings), 0)

    def test_no_progress_detected(self):
        now = datetime(2026, 6, 17, 12, 0, 0)
        self._write_run_with_activity("run-001", "2026-06-17T10:00:00")
        runs = _active_runs(self.runs_dir)
        findings = check_progress(
            runs, now=now, progress_timeout=timedelta(minutes=30)
        )
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].kind, "no_progress")
        self.assertEqual(findings[0].severity, "warning")
        self.assertEqual(findings[0].run_id, "run-001")

    def test_run_without_activity_timestamp_skipped(self):
        now = datetime(2026, 6, 17, 12, 0, 0)
        self._write_run_with_activity("run-001", None)
        runs = _active_runs(self.runs_dir)
        findings = check_progress(
            runs, now=now, progress_timeout=timedelta(minutes=30)
        )
        self.assertEqual(len(findings), 0)

    def test_multiple_runs_some_stalled(self):
        now = datetime(2026, 6, 17, 12, 0, 0)
        self._write_run_with_activity("run-ok", "2026-06-17T11:55:00")
        self._write_run_with_activity("run-stale", "2026-06-17T10:00:00")
        runs = _active_runs(self.runs_dir)
        findings = check_progress(
            runs, now=now, progress_timeout=timedelta(minutes=30)
        )
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].run_id, "run-stale")


class WatchdogStuckCheckTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.runs_dir = Path(self.tmpdir.name)

    def tearDown(self):
        self.tmpdir.cleanup()

    def _write_run_with_activity(self, run_id: str, last_activity: str | None, status: str = "started"):
        run_dir = self.runs_dir / run_id
        run_dir.mkdir(parents=True)
        health = {
            "status": status,
            "phase": "worker_running",
        }
        if last_activity:
            health["last_activity_at"] = last_activity
            health["last_report_update_at"] = last_activity
        (run_dir / "health.json").write_text(json.dumps(health), encoding="utf-8")
        (run_dir / "summary.txt").write_text(f"status: {status}\nrepo: demo\nissue: 1\n", encoding="utf-8")

    def test_recent_activity_not_stuck(self):
        now = datetime(2026, 6, 17, 12, 0, 0)
        self._write_run_with_activity("run-001", "2026-06-17T11:55:00")
        runs = _active_runs(self.runs_dir)
        findings = check_stuck(
            runs, now=now, stuck_timeout=timedelta(minutes=15)
        )
        self.assertEqual(len(findings), 0)

    def test_stuck_detected(self):
        now = datetime(2026, 6, 17, 12, 0, 0)
        self._write_run_with_activity("run-001", "2026-06-17T09:00:00")
        runs = _active_runs(self.runs_dir)
        findings = check_stuck(
            runs, now=now, stuck_timeout=timedelta(minutes=15)
        )
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].kind, "stuck")
        self.assertEqual(findings[0].run_id, "run-001")

    def test_stuck_severity_critical_for_very_long(self):
        now = datetime(2026, 6, 17, 12, 0, 0)
        self._write_run_with_activity("run-001", "2026-06-17T06:00:00")
        runs = _active_runs(self.runs_dir)
        findings = check_stuck(
            runs, now=now, stuck_timeout=timedelta(minutes=15)
        )
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].severity, "critical")


class WatchdogStatusReportTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.report_dir = Path(self.tmpdir.name)
        self.output_path = self.report_dir / "watchdog-status.json"

    def tearDown(self):
        self.tmpdir.cleanup()

    def _make_run(self, run_id: str) -> WatchdogRun:
        return WatchdogRun(
            run_id=run_id,
            run_dir=self.report_dir / run_id,
            repo="demo",
            issue="1",
            phase="worker_running",
            status="started",
            last_activity_at=datetime(2026, 6, 17, 11, 0, 0),
            last_report_update_at=datetime(2026, 6, 17, 11, 0, 0),
            model="test-model",
            worker_exit_code="",
        )

    def test_status_report_no_anomalies(self):
        runs = [self._make_run("run-001")]
        path = write_status_report(runs, [], [], [], output_path=self.output_path)
        self.assertTrue(path.exists())
        data = json.loads(path.read_text(encoding="utf-8"))
        self.assertFalse(data["anomalies_detected"])
        self.assertEqual(data["total_runs"], 1)
        self.assertEqual(data["summary"], "All checks passed.")

    def test_status_report_with_anomalies(self):
        runs = [self._make_run("run-001")]
        cost = [
            CostFinding(
                kind="per_run", severity="warning",
                message="cost exceeded", run_id="run-001",
                current=6.0, threshold=5.0,
            )
        ]
        path = write_status_report(runs, cost, [], [], output_path=self.output_path)
        data = json.loads(path.read_text(encoding="utf-8"))
        self.assertTrue(data["anomalies_detected"])
        self.assertEqual(len(data["cost_findings"]), 1)
        self.assertEqual(data["cost_findings"][0]["kind"], "per_run")

    def test_status_report_counts(self):
        runs = [
            self._make_run("run-001"),
            self._make_run("run-002"),
        ]
        path = write_status_report(runs, [], [], [], output_path=self.output_path)
        data = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(data["total_runs"], 2)

    def test_status_report_has_checked_at(self):
        runs = []
        path = write_status_report(runs, [], [], [], output_path=self.output_path)
        data = json.loads(path.read_text(encoding="utf-8"))
        self.assertIn("checked_at", data)
        self.assertTrue(data["checked_at"])


class WatchdogActiveRunsTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.runs_dir = Path(self.tmpdir.name)

    def tearDown(self):
        self.tmpdir.cleanup()

    def _write_run(self, run_id: str, status: str, health_status: str = ""):
        run_dir = self.runs_dir / run_id
        run_dir.mkdir(parents=True)
        (run_dir / "summary.txt").write_text(
            f"status: {status}\nrepo: demo\nissue: 1\n", encoding="utf-8"
        )
        metadata = {
            "status": status,
            "repo": "demo",
            "issue_number": 1,
            "model": "test-model",
        }
        (run_dir / "metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
        if health_status:
            (run_dir / "health.json").write_text(
                json.dumps({"status": health_status, "phase": "worker_running"}),
                encoding="utf-8",
            )

    def test_empty_dir_returns_empty_list(self):
        runs = _active_runs(self.runs_dir)
        self.assertEqual(runs, [])

    def test_active_run_appears(self):
        self._write_run("run-001", "started")
        runs = _active_runs(self.runs_dir)
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0].run_id, "run-001")

    def test_finished_run_excluded(self):
        self._write_run("run-finished", "pr_created")
        runs = _active_runs(self.runs_dir)
        # Terminal status excluded because it has no health "started"/"running" status
        self.assertEqual(len(runs), 0)

    def test_non_run_directories_skipped(self):
        (self.runs_dir / "README.txt").write_text("not a run", encoding="utf-8")
        self._write_run("run-001", "started")
        runs = _active_runs(self.runs_dir)
        self.assertEqual(len(runs), 1)


if __name__ == "__main__":
    unittest.main()
