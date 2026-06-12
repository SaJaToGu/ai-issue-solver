"""
Tests für den OpenCode-Session-Reader (workers.opencode_session_reader).

Abgedeckte Szenarien:
- Lesen von Session-Metriken aus einer temporären SQLite-Datenbank
- Matching nach directory und Startzeit
- Erkennung von ueberschrittenen Budgetgrenzen
- Report-Summary-Felder fuer OpenCode-Kosten/Token-Metriken
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))


# ─────────────────────────────────────────────────────────────
# Test-Daten
# ─────────────────────────────────────────────────────────────

def _make_test_sessions(repo_dir: str, base_time: datetime) -> list[dict]:
    def opencode_time(dt: datetime) -> int:
        return int(dt.timestamp() * 1000)

    return [
        {
            "id": "ses_1",
            "model": "opencode/deepseek-v4-flash-free",
            "cost": 0.0015,
            "tokens_input": 1500,
            "tokens_output": 500,
            "tokens_reasoning": 200,
            "tokens_cache_read": 300,
            "tokens_cache_write": 100,
            "directory": repo_dir,
            "time_created": opencode_time(base_time + timedelta(seconds=5)),
            "time_updated": opencode_time(base_time + timedelta(seconds=30)),
        },
        {
            "id": "ses_2",
            "model": "opencode/deepseek-v4-flash-free",
            "cost": 0.0020,
            "tokens_input": 2000,
            "tokens_output": 800,
            "tokens_reasoning": 300,
            "tokens_cache_read": 500,
            "tokens_cache_write": 150,
            "directory": repo_dir,
            "time_created": opencode_time(base_time + timedelta(seconds=20)),
            "time_updated": opencode_time(base_time + timedelta(seconds=45)),
        },
        {
            "id": "ses_3",
            "model": "opencode/mimo-v2.5-free",
            "cost": 0.0000,
            "tokens_input": 100,
            "tokens_output": 50,
            "tokens_reasoning": 0,
            "tokens_cache_read": 0,
            "tokens_cache_write": 0,
            "directory": "/other/repo",
            "time_created": opencode_time(base_time + timedelta(seconds=10)),
            "time_updated": opencode_time(base_time + timedelta(seconds=20)),
        },
    ]


# ─────────────────────────────────────────────────────────────
# Hilfsfunktion: Test-DB erstellen
# ─────────────────────────────────────────────────────────────

def _create_test_db(db_path: str, sessions: list[dict]) -> None:
    from workers.opencode_session_reader import create_test_database
    create_test_database(db_path, sessions)


# ─────────────────────────────────────────────────────────────
# Tests: Session-Metriken lesen
# ─────────────────────────────────────────────────────────────

class TestReadOpenCodeSessions(unittest.TestCase):
    """Tests fuer read_opencode_sessions()."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmpdir.name, "opencode.db")
        self.repo_dir = "/tmp/test-repo"
        self.base_time = datetime(2026, 6, 10, 12, 0, 0)
        sessions = _make_test_sessions(self.repo_dir, self.base_time)
        _create_test_db(self.db_path, sessions)

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_read_all_sessions(self):
        from workers.opencode_session_reader import read_opencode_sessions
        result = read_opencode_sessions(self.db_path)
        self.assertEqual(len(result), 3)

    def test_read_sessions_filter_by_directory(self):
        from workers.opencode_session_reader import read_opencode_sessions
        result = read_opencode_sessions(self.db_path, directory=self.repo_dir)
        self.assertEqual(len(result), 2)
        for s in result:
            self.assertEqual(s.directory, self.repo_dir)

    def test_read_sessions_filter_by_time_after(self):
        from workers.opencode_session_reader import read_opencode_sessions
        cutoff = self.base_time + timedelta(seconds=15)
        result = read_opencode_sessions(self.db_path, time_created_after=cutoff)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].id, "ses_2")

    def test_read_sessions_filter_by_time_before(self):
        from workers.opencode_session_reader import read_opencode_sessions
        cutoff = self.base_time + timedelta(seconds=15)
        result = read_opencode_sessions(self.db_path, time_created_before=cutoff)
        self.assertEqual(len(result), 2)

    def test_session_fields_are_read_correctly(self):
        from workers.opencode_session_reader import read_opencode_sessions
        result = read_opencode_sessions(self.db_path, directory=self.repo_dir)
        session = result[0]
        self.assertEqual(session.model, "opencode/deepseek-v4-flash-free")
        self.assertIsInstance(session.cost, float)
        self.assertIsInstance(session.tokens_input, int)
        self.assertIsInstance(session.tokens_output, int)
        self.assertIsInstance(session.directory, str)
        self.assertIsInstance(session.time_created, datetime)

    def test_sessions_ordered_by_time_desc(self):
        from workers.opencode_session_reader import read_opencode_sessions
        result = read_opencode_sessions(self.db_path, directory=self.repo_dir)
        self.assertGreater(result[0].time_created, result[1].time_created)


# ─────────────────────────────────────────────────────────────
# Tests: Matching nach directory und Startzeit
# ─────────────────────────────────────────────────────────────

class TestMatchSessionsByRun(unittest.TestCase):
    """Tests fuer match_sessions_by_run()."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmpdir.name, "opencode.db")
        self.repo_dir = "/tmp/test-repo"
        self.base_time = datetime(2026, 6, 10, 12, 0, 0)
        sessions = _make_test_sessions(self.repo_dir, self.base_time)
        _create_test_db(self.db_path, sessions)

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_match_finds_sessions_within_window(self):
        from workers.opencode_session_reader import match_sessions_by_run
        result = match_sessions_by_run(
            self.db_path, self.repo_dir, self.base_time, time_window_seconds=30
        )
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0].directory, self.repo_dir)

    def test_match_returns_empty_for_wrong_directory(self):
        from workers.opencode_session_reader import match_sessions_by_run
        result = match_sessions_by_run(
            self.db_path, "/wrong/path", self.base_time, time_window_seconds=30
        )
        self.assertEqual(len(result), 0)

    def test_match_returns_empty_for_far_off_time(self):
        from workers.opencode_session_reader import match_sessions_by_run
        far_time = self.base_time - timedelta(hours=1)
        result = match_sessions_by_run(
            self.db_path, self.repo_dir, far_time, time_window_seconds=30
        )
        self.assertEqual(len(result), 0)


# ─────────────────────────────────────────────────────────────
# Tests: Aggregierte Totals
# ─────────────────────────────────────────────────────────────

class TestCalculateSessionTotals(unittest.TestCase):
    """Tests fuer calculate_session_totals()."""

    def setUp(self):
        from workers.opencode_session_reader import OpenCodeSessionRow
        self.sessions = [
            OpenCodeSessionRow(id="ses_1", model="m", cost=0.001, tokens_input=100,
                               tokens_output=50, tokens_reasoning=10,
                               tokens_cache_read=20, tokens_cache_write=5,
                               directory="/repo", time_created=None, time_updated=None),
            OpenCodeSessionRow(id="ses_2", model="m", cost=0.002, tokens_input=200,
                               tokens_output=100, tokens_reasoning=20,
                               tokens_cache_read=40, tokens_cache_write=10,
                               directory="/repo", time_created=None, time_updated=None),
        ]

    def test_calculate_totals(self):
        from workers.opencode_session_reader import calculate_session_totals
        totals = calculate_session_totals(self.sessions)
        self.assertEqual(totals.total_cost, 0.003)
        self.assertEqual(totals.total_tokens_input, 300)
        self.assertEqual(totals.total_tokens_output, 150)
        self.assertEqual(totals.total_tokens_reasoning, 30)
        self.assertEqual(totals.total_tokens_cache_read, 60)
        self.assertEqual(totals.total_tokens_cache_write, 15)

    def test_calculate_totals_empty_list(self):
        from workers.opencode_session_reader import calculate_session_totals
        totals = calculate_session_totals([])
        self.assertEqual(totals.total_cost, 0.0)
        self.assertEqual(totals.total_tokens_input, 0)
        self.assertEqual(totals.total_tokens_output, 0)
        self.assertEqual(totals.total_tokens_reasoning, 0)
        self.assertEqual(totals.total_tokens_cache_read, 0)
        self.assertEqual(totals.total_tokens_cache_write, 0)

    def test_totals_to_dict(self):
        from workers.opencode_session_reader import calculate_session_totals
        totals = calculate_session_totals(self.sessions)
        d = totals.to_dict()
        self.assertEqual(d["total_cost"], 0.003)
        self.assertEqual(d["total_tokens_input"], 300)
        self.assertIn("total_cost", d)
        self.assertIn("total_tokens_reasoning", d)
        self.assertIn("total_tokens_cache_read", d)
        self.assertIn("total_tokens_cache_write", d)


# ─────────────────────────────────────────────────────────────
# Tests: Budgetgrenzen erkennen
# ─────────────────────────────────────────────────────────────

class TestCheckBudgetLimits(unittest.TestCase):
    """Tests fuer check_budget_limits()."""

    def setUp(self):
        from workers.opencode_session_reader import (
            OpenCodeBudgetLimits, OpenCodeSessionTotals,
        )
        self.totals = OpenCodeSessionTotals(
            total_cost=0.005,
            total_tokens_input=5000,
            total_tokens_output=2000,
            total_tokens_cache_read=1000,
        )

    def test_no_limits_set_no_exceeded(self):
        from workers.opencode_session_reader import check_budget_limits, OpenCodeBudgetLimits
        limits = OpenCodeBudgetLimits()
        result = check_budget_limits(self.totals, limits)
        self.assertIsNone(result.exceeded_reason)

    def test_cost_exceeded(self):
        from workers.opencode_session_reader import check_budget_limits, OpenCodeBudgetLimits
        limits = OpenCodeBudgetLimits(max_cost_usd=0.001)
        result = check_budget_limits(self.totals, limits)
        self.assertIsNotNone(result.exceeded_reason)
        self.assertIn("cost", result.exceeded_reason)
        self.assertIn("0.005", result.exceeded_reason)

    def test_input_tokens_exceeded(self):
        from workers.opencode_session_reader import check_budget_limits, OpenCodeBudgetLimits
        limits = OpenCodeBudgetLimits(max_input_tokens=1000)
        result = check_budget_limits(self.totals, limits)
        self.assertIsNotNone(result.exceeded_reason)
        self.assertIn("input_tokens", result.exceeded_reason)

    def test_output_tokens_exceeded(self):
        from workers.opencode_session_reader import check_budget_limits, OpenCodeBudgetLimits
        limits = OpenCodeBudgetLimits(max_output_tokens=1000)
        result = check_budget_limits(self.totals, limits)
        self.assertIsNotNone(result.exceeded_reason)
        self.assertIn("output_tokens", result.exceeded_reason)

    def test_cache_read_exceeded(self):
        from workers.opencode_session_reader import check_budget_limits, OpenCodeBudgetLimits
        limits = OpenCodeBudgetLimits(max_cache_read_tokens=500)
        result = check_budget_limits(self.totals, limits)
        self.assertIsNotNone(result.exceeded_reason)
        self.assertIn("cache_read_tokens", result.exceeded_reason)

    def test_no_exceeded_when_within_limits(self):
        from workers.opencode_session_reader import check_budget_limits, OpenCodeBudgetLimits
        limits = OpenCodeBudgetLimits(
            max_cost_usd=0.01,
            max_input_tokens=10000,
            max_output_tokens=5000,
            max_cache_read_tokens=2000,
        )
        result = check_budget_limits(self.totals, limits)
        self.assertIsNone(result.exceeded_reason)

    def test_multiple_exceeded(self):
        from workers.opencode_session_reader import check_budget_limits, OpenCodeBudgetLimits
        limits = OpenCodeBudgetLimits(
            max_cost_usd=0.001,
            max_input_tokens=1000,
        )
        result = check_budget_limits(self.totals, limits)
        self.assertIsNotNone(result.exceeded_reason)
        self.assertIn("cost", result.exceeded_reason)
        self.assertIn("input_tokens", result.exceeded_reason)


# ─────────────────────────────────────────────────────────────
# Tests: has_any_limit
# ─────────────────────────────────────────────────────────────

class TestHasAnyLimit(unittest.TestCase):
    """Tests fuer has_any_limit()."""

    def test_no_limits(self):
        from workers.opencode_session_reader import OpenCodeBudgetLimits, has_any_limit
        self.assertFalse(has_any_limit(OpenCodeBudgetLimits()))

    def test_cost_limit(self):
        from workers.opencode_session_reader import OpenCodeBudgetLimits, has_any_limit
        self.assertTrue(has_any_limit(OpenCodeBudgetLimits(max_cost_usd=0.01)))

    def test_input_tokens_limit(self):
        from workers.opencode_session_reader import OpenCodeBudgetLimits, has_any_limit
        self.assertTrue(has_any_limit(OpenCodeBudgetLimits(max_input_tokens=100)))

    def test_output_tokens_limit(self):
        from workers.opencode_session_reader import OpenCodeBudgetLimits, has_any_limit
        self.assertTrue(has_any_limit(OpenCodeBudgetLimits(max_output_tokens=100)))

    def test_cache_read_limit(self):
        from workers.opencode_session_reader import OpenCodeBudgetLimits, has_any_limit
        self.assertTrue(has_any_limit(OpenCodeBudgetLimits(max_cache_read_tokens=100)))


# ─────────────────────────────────────────────────────────────
# Tests: Report-Summary-Felder (opencode_session in metadata)
# ─────────────────────────────────────────────────────────────

class TestReportSummaryFields(unittest.TestCase):
    """Tests, dass opencode_session-Metriken korrekt in Reports landen."""

    def test_opencode_session_totals_in_metadata(self):
        from workers.opencode_session_reader import (
            OpenCodeSessionTotals, calculate_session_totals,
        )
        totals = OpenCodeSessionTotals(
            total_cost=0.0035,
            total_tokens_input=3500,
            total_tokens_output=1300,
            total_tokens_reasoning=500,
            total_tokens_cache_read=800,
            total_tokens_cache_write=250,
        )
        d = totals.to_dict()
        self.assertEqual(d["total_cost"], 0.0035)
        self.assertEqual(d["total_tokens_input"], 3500)
        self.assertEqual(d["total_tokens_output"], 1300)
        self.assertEqual(d["total_tokens_reasoning"], 500)
        self.assertEqual(d["total_tokens_cache_read"], 800)
        self.assertEqual(d["total_tokens_cache_write"], 250)

    def test_totals_integrate_with_report_metadata(self):
        from workers.opencode_session_reader import calculate_session_totals
        sessions_for_report = [
            type("Row", (), {
                "id": "ses_1", "model": "m", "cost": 0.001, "tokens_input": 100,
                "tokens_output": 50, "tokens_reasoning": 10, "tokens_cache_read": 20,
                "tokens_cache_write": 5, "directory": "/r", "time_created": None,
                "time_updated": None,
            })(),
            type("Row", (), {
                "id": "ses_2", "model": "m", "cost": 0.002, "tokens_input": 200,
                "tokens_output": 100, "tokens_reasoning": 20, "tokens_cache_read": 40,
                "tokens_cache_write": 10, "directory": "/r", "time_created": None,
                "time_updated": None,
            })(),
        ]
        totals = calculate_session_totals(sessions_for_report)
        d = totals.to_dict()
        self.assertEqual(d["total_cost"], 0.003)
        self.assertEqual(d["total_tokens_input"], 300)
        self.assertEqual(d["total_tokens_reasoning"], 30)
        self.assertEqual(d["total_tokens_cache_write"], 15)

    def test_budget_exceeded_flag_in_summary(self):
        from workers.opencode_session_reader import (
            OpenCodeBudgetLimits, OpenCodeSessionTotals, check_budget_limits,
        )
        totals = OpenCodeSessionTotals(
            total_cost=0.05,
            total_tokens_input=10000,
            total_tokens_output=5000,
            total_tokens_reasoning=0,
            total_tokens_cache_read=2000,
            total_tokens_cache_write=0,
        )
        limits = OpenCodeBudgetLimits(max_cost_usd=0.01)
        result = check_budget_limits(totals, limits)
        self.assertIsNotNone(result.exceeded_reason)
        self.assertIn("cost", result.exceeded_reason)

    def test_no_exceeded_flag_when_within_budget(self):
        from workers.opencode_session_reader import (
            OpenCodeBudgetLimits, OpenCodeSessionTotals, check_budget_limits,
        )
        totals = OpenCodeSessionTotals(
            total_cost=0.001,
            total_tokens_input=100,
            total_tokens_output=50,
            total_tokens_reasoning=0,
            total_tokens_cache_read=20,
            total_tokens_cache_write=0,
        )
        limits = OpenCodeBudgetLimits(max_cost_usd=0.01)
        result = check_budget_limits(totals, limits)
        self.assertIsNone(result.exceeded_reason)


# ─────────────────────────────────────────────────────────────
# Tests: AdapterDiagnostics Integration
# ─────────────────────────────────────────────────────────────

class TestAdapterDiagnosticsOpenCodeFields(unittest.TestCase):
    """Tests, dass die neuen OpenCode-Felder in AdapterDiagnostics vorhanden sind."""

    def test_opencode_session_totals_field_exists(self):
        from workers.base import AdapterDiagnostics
        diag = AdapterDiagnostics()
        self.assertIsNone(diag.opencode_session_totals)
        diag.opencode_session_totals = {"total_cost": 0.005}
        self.assertEqual(diag.opencode_session_totals["total_cost"], 0.005)

    def test_opencode_budget_exceeded_field_exists(self):
        from workers.base import AdapterDiagnostics
        diag = AdapterDiagnostics()
        self.assertIsNone(diag.opencode_budget_exceeded)
        diag.opencode_budget_exceeded = "cost exceeded"
        self.assertEqual(diag.opencode_budget_exceeded, "cost exceeded")


# ─────────────────────────────────────────────────────────────
# Tests: NULL/None handling
# ─────────────────────────────────────────────────────────────

class TestNullHandling(unittest.TestCase):
    """Tests fuer korrekte Behandlung von NULL-Werten in der Datenbank."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmpdir.name, "opencode.db")
        from workers.opencode_session_reader import create_test_database
        create_test_database(self.db_path, [
            {
                "id": "ses_null",
                "model": "opencode/test",
                "cost": None,
                "tokens_input": None,
                "tokens_output": None,
                "tokens_reasoning": None,
                "tokens_cache_read": None,
                "tokens_cache_write": None,
                "directory": "/repo",
                "time_created": int(datetime(2026, 1, 1, 0, 0, 0).timestamp() * 1000),
                "time_updated": None,
            },
        ])

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_null_fields_read_as_none(self):
        from workers.opencode_session_reader import read_opencode_sessions
        result = read_opencode_sessions(self.db_path)
        self.assertEqual(len(result), 1)
        session = result[0]
        self.assertIsNone(session.cost)
        self.assertIsNone(session.tokens_input)
        self.assertIsNone(session.tokens_output)
        self.assertIsNone(session.time_updated)

    def test_totals_skip_none_values(self):
        from workers.opencode_session_reader import read_opencode_sessions, calculate_session_totals
        sessions = read_opencode_sessions(self.db_path)
        totals = calculate_session_totals(sessions)
        self.assertEqual(totals.total_cost, 0.0)
        self.assertEqual(totals.total_tokens_input, 0)
        self.assertEqual(totals.total_tokens_output, 0)
        self.assertEqual(totals.total_tokens_reasoning, 0)
        self.assertEqual(totals.total_tokens_cache_read, 0)
        self.assertEqual(totals.total_tokens_cache_write, 0)


# ─────────────────────────────────────────────────────────────
# Tests: find_opencode_db_path
# ─────────────────────────────────────────────────────────────

class TestFindOpenCodeDbPath(unittest.TestCase):
    """Tests fuer find_opencode_db_path()."""

    def test_returns_none_when_no_db_exists(self):
        from workers.opencode_session_reader import find_opencode_db_path, _first_existing
        # _first_existing mit leerer Liste sollte None zurueckgeben
        self.assertIsNone(_first_existing([]))

    def test_first_existing_returns_first_match(self):
        from workers.opencode_session_reader import _first_existing
        with tempfile.TemporaryDirectory() as tmpdir:
            first = Path(tmpdir) / "first.db"
            second = Path(tmpdir) / "second.db"
            first.write_text("test")
            result = _first_existing([first, second])
            self.assertEqual(result, first)


if __name__ == "__main__":
    unittest.main()
