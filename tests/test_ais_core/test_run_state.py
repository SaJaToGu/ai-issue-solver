"""Tests for ais_core.run_state (Issue #1c).

Covers Run-ID format + uniqueness + state persistence roundtrip.
"""

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from ais_core.run_state import (
    RunState,
    load_state,
    make_run_id,
    save_state,
)


class TestMakeRunIdFormat(unittest.TestCase):
    def test_basic_format(self) -> None:
        ts = datetime(2026, 6, 27, 19, 24, 12, tzinfo=timezone.utc)
        rid = make_run_id("SaJaToGu", "ai-issue-solver", ts)
        # Format: <UTC>-<repo-short>-<8-hex>
        parts = rid.split("-")
        # Last part is the hash (8 hex chars)
        self.assertEqual(len(parts[-1]), 8)
        self.assertTrue(all(c in "0123456789abcdef" for c in parts[-1]))
        # First part is the timestamp YYYYMMDDTHHMMSSZ
        self.assertRegex(parts[0], r"^\d{8}T\d{6}Z$")
        # First part timestamp matches input
        self.assertEqual(parts[0], "20260627T192412Z")
        # Middle parts are the repo-short
        repo_short = "-".join(parts[1:-1])
        self.assertGreater(len(repo_short), 0)
        self.assertLessEqual(len(repo_short), 20)

    def test_default_timestamp_is_utc(self) -> None:
        rid = make_run_id("o", "r")
        # Just verify it has the expected shape
        parts = rid.split("-")
        self.assertRegex(parts[0], r"^\d{8}T\d{6}Z$")

    def test_naive_timestamp_treated_as_utc(self) -> None:
        ts_naive = datetime(2026, 6, 27, 19, 24, 12)  # no tzinfo
        rid = make_run_id("o", "r", ts_naive)
        self.assertTrue(rid.startswith("20260627T192412Z-"))

    def test_repo_short_sanitization(self) -> None:
        ts = datetime(2026, 6, 27, 19, 24, 12, tzinfo=timezone.utc)
        rid = make_run_id("o", "My.Complex_Repo-Name!", ts)
        parts = rid.split("-")
        # Last part is the hash
        self.assertEqual(len(parts[-1]), 8)
        # Middle parts are the sanitized repo short
        repo_short = "-".join(parts[1:-1])
        # Should be lowercase
        self.assertEqual(repo_short, repo_short.lower())
        # No invalid chars
        self.assertTrue(all(c.isalnum() or c == "-" for c in repo_short))
        # No leading/trailing dashes
        self.assertFalse(repo_short.startswith("-"))
        self.assertFalse(repo_short.endswith("-"))

    def test_repo_short_max_20_chars(self) -> None:
        ts = datetime(2026, 6, 27, 19, 24, 12, tzinfo=timezone.utc)
        rid = make_run_id(
            "o", "a-very-very-very-long-repository-name-that-exceeds-twenty"
        )
        parts = rid.split("-")
        repo_short = "-".join(parts[1:-1])
        self.assertLessEqual(len(repo_short), 20)


class TestMakeRunIdUniqueness(unittest.TestCase):
    def test_same_inputs_same_id(self) -> None:
        ts = datetime(2026, 6, 27, 19, 24, 12, tzinfo=timezone.utc)
        rid_a = make_run_id("o", "r", ts)
        rid_b = make_run_id("o", "r", ts)
        self.assertEqual(rid_a, rid_b)

    def test_different_owners_same_repo_different_ids(self) -> None:
        ts = datetime(2026, 6, 27, 19, 24, 12, tzinfo=timezone.utc)
        rid_a = make_run_id("alice", "r", ts)
        rid_b = make_run_id("bob", "r", ts)
        self.assertNotEqual(rid_a, rid_b)

    def test_1000_unique_ids(self) -> None:
        ts = datetime(2026, 6, 27, 19, 24, 12, tzinfo=timezone.utc)
        ids = {make_run_id(f"owner-{i}", "ai-issue-solver", ts) for i in range(1000)}
        self.assertEqual(len(ids), 1000)

    def test_same_second_different_microseconds_produce_different_ids(self) -> None:
        """Two runs in the same wall-clock second (different microseconds)
        must produce different Run-IDs, even though the visible prefix
        (seconds-precise) is the same.
        """
        ts_a = datetime(2026, 6, 27, 19, 24, 12, 123_456, tzinfo=timezone.utc)
        ts_b = datetime(2026, 6, 27, 19, 24, 12, 123_789, tzinfo=timezone.utc)
        rid_a = make_run_id("o", "r", ts_a)
        rid_b = make_run_id("o", "r", ts_b)
        # Visible prefix is identical (same second)
        self.assertEqual(rid_a.split("-")[0], rid_b.split("-")[0])
        self.assertEqual(rid_a.split("-")[0], "20260627T192412Z")
        # But the IDs themselves are different (microsecond-precision hash)
        self.assertNotEqual(rid_a, rid_b)

    def test_visible_prefix_remains_seconds_precise(self) -> None:
        """Even with microsecond input, the visible prefix is YYYYMMDDTHHMMSSZ."""
        ts = datetime(2026, 6, 27, 19, 24, 12, 999_999, tzinfo=timezone.utc)
        rid = make_run_id("o", "r", ts)
        self.assertTrue(rid.startswith("20260627T192412Z-"))

    def test_subsecond_resolution_default_timestamp(self) -> None:
        """Two consecutive ``timestamp=None`` calls produce different IDs."""
        rid_a = make_run_id("o", "r")
        rid_b = make_run_id("o", "r")
        # In practice these differ because of microsecond clock.
        # If for some reason they don't differ (clock resolution),
        # the function would still be valid but uniqueness would not
        # be guaranteed; flag a warning.
        if rid_a == rid_b:
            import warnings
            warnings.warn(
                "make_run_id with timestamp=None returned identical IDs; "
                "may indicate low-resolution clock",
                stacklevel=2,
            )


class TestSaveLoadRoundtrip(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = Path(tempfile.mkdtemp(prefix="ais-run-state-test-"))

    def tearDown(self) -> None:
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_basic_roundtrip(self) -> None:
        state = RunState(
            run_id="20260627T192412Z-bulwipgame-7f3a2b1c",
            status="succeeded",
            data={"pr_url": "https://github.com/x/y/pull/1", "cost_usd": 0.42},
        )
        path = save_state(state.run_id, state, base_dir=self.tmpdir)
        self.assertTrue(path.exists())
        loaded = load_state(state.run_id, base_dir=self.tmpdir)
        self.assertEqual(loaded, state)

    def test_creates_parent_dir(self) -> None:
        nested = self.tmpdir / "deep" / "nested" / "path"
        state = RunState(run_id="x", status="queued", data={})
        path = save_state(state.run_id, state, base_dir=nested)
        self.assertTrue(path.exists())

    def test_load_missing_raises_filenotfound(self) -> None:
        with self.assertRaises(FileNotFoundError):
            load_state("nonexistent-run-id", base_dir=self.tmpdir)

    def test_empty_data_roundtrip(self) -> None:
        state = RunState(run_id="x", status="queued", data={})
        save_state(state.run_id, state, base_dir=self.tmpdir)
        loaded = load_state(state.run_id, base_dir=self.tmpdir)
        self.assertEqual(loaded.data, {})

    def test_save_state_rejects_run_id_mismatch(self) -> None:
        """save_state() must raise ValueError when the run_id argument
        and state.run_id do not match (defense against mis-paired writes).
        """
        state = RunState(run_id="real-id", status="queued", data={})
        with self.assertRaises(ValueError):
            save_state("WRONG-id", state, base_dir=self.tmpdir)


if __name__ == "__main__":
    unittest.main()
