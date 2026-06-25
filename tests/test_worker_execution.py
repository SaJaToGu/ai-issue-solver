"""
test_worker_execution.py — Tests for shared worker execution/health primitives.

Covers:
- WorkerHealthConfig / WorkerHealthResult dataclass construction
- run_worker_subprocess health timeout detection and unhealthy action
- classify_worker_outcome for all result categories
- Interaction of health timeout with rate-limit waiting detection

These tests exercise the shared primitives in ``workers.execution`` that are
used by both single-run (``scripts/solve_issues.py``) and batch
(``scripts/solve_issues_batch.py``) code paths.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

from workers.execution import (
    WorkerHealthConfig,
    WorkerHealthResult,
    classify_worker_outcome,
    run_worker_subprocess,
)
from workers.base import (
    PATCH_VALIDATION_FAILED_RETURN_CODE,
    PARTIAL_PATCH_FAILURE_RETURN_CODE,
    WorkerOutcome,
    WorkerRunResult,
)


class WorkerHealthConfigTests(unittest.TestCase):
    """WorkerHealthConfig and WorkerHealthResult construction."""

    def test_health_config_defaults(self):
        cfg = WorkerHealthConfig()
        self.assertIsNone(cfg.health_timeout_seconds)
        self.assertEqual(cfg.unhealthy_action, "warn")
        self.assertIsNone(cfg.heartbeat_interval_seconds)

    def test_health_config_custom(self):
        cfg = WorkerHealthConfig(
            health_timeout_seconds=300.0,
            unhealthy_action="stop",
            heartbeat_interval_seconds=60.0,
        )
        self.assertEqual(cfg.health_timeout_seconds, 300.0)
        self.assertEqual(cfg.unhealthy_action, "stop")
        self.assertEqual(cfg.heartbeat_interval_seconds, 60.0)

    def test_health_result_defaults(self):
        hr = WorkerHealthResult()
        self.assertFalse(hr.unhealthy)
        self.assertIsNone(hr.unhealthy_reason)

    def test_health_result_custom(self):
        hr = WorkerHealthResult(
            unhealthy=True,
            unhealthy_reason="timeout",
        )
        self.assertTrue(hr.unhealthy)
        self.assertEqual(hr.unhealthy_reason, "timeout")


class ClassifyWorkerOutcomeTests(unittest.TestCase):
    """Test shared outcome classification."""

    def _make_result(self, returncode: int = 0, output: str = "") -> WorkerRunResult:
        return WorkerRunResult(returncode=returncode, output=output)

    # --- returncode 0 ---

    def test_returncode_0_with_changes_is_changed(self):
        outcome = classify_worker_outcome(self._make_result(0), " M README.md\n")
        self.assertEqual(outcome.reason, "changed")
        self.assertTrue(outcome.should_continue)
        self.assertTrue(outcome.has_changes)

    def test_returncode_0_without_changes_is_no_changes(self):
        outcome = classify_worker_outcome(self._make_result(0), "")
        self.assertEqual(outcome.reason, "no_changes")
        self.assertFalse(outcome.should_continue)
        self.assertFalse(outcome.has_changes)

    # --- nonzero returncode ---

    def test_nonzero_with_meaningful_changes_continues(self):
        outcome = classify_worker_outcome(
            self._make_result(1), " M scripts/solver.py\n",
        )
        self.assertEqual(outcome.reason, "nonzero_with_changes")
        self.assertTrue(outcome.should_continue)
        self.assertTrue(outcome.has_changes)

    def test_partial_patch_failure_with_changes_stops(self):
        outcome = classify_worker_outcome(
            self._make_result(
                PARTIAL_PATCH_FAILURE_RETURN_CODE,
                "PARTIAL-PATCH-FAILURE: 1/2 Patch(es) angewendet",
            ),
            " M scripts/solver.py\n",
        )
        self.assertEqual(outcome.reason, "partial_patch_failure")
        self.assertFalse(outcome.should_continue)
        self.assertTrue(outcome.has_changes)

    def test_patch_validation_failed_with_changes_stops(self):
        outcome = classify_worker_outcome(
            self._make_result(
                PATCH_VALIDATION_FAILED_RETURN_CODE,
                "VALIDATION-FAILED: Reject-Artifakte wurden erkannt",
            ),
            " M scripts/solve_issues.py\n",
        )
        self.assertEqual(outcome.reason, "patch_validation_failed")
        self.assertFalse(outcome.should_continue)
        self.assertTrue(outcome.has_changes)

    def test_nonzero_without_changes_stops(self):
        outcome = classify_worker_outcome(self._make_result(1), "")
        self.assertEqual(outcome.reason, "nonzero_without_changes")
        self.assertFalse(outcome.should_continue)
        self.assertFalse(outcome.has_changes)

    def test_returncode_2_treated_as_nonzero(self):
        outcome = classify_worker_outcome(self._make_result(2), "")
        self.assertEqual(outcome.reason, "nonzero_without_changes")
        self.assertFalse(outcome.should_continue)

    def test_returncode_2_with_changes_continues(self):
        outcome = classify_worker_outcome(
            self._make_result(2), " M scripts/solver.py\n",
        )
        self.assertEqual(outcome.reason, "nonzero_with_changes")
        self.assertTrue(outcome.should_continue)

    # --- side-effect filtering ---

    def test_aider_side_effects_only_stops(self):
        outcome = classify_worker_outcome(
            self._make_result(1), "?? .aider.chat.history.md\n",
        )
        self.assertEqual(outcome.reason, "nonzero_without_changes")
        self.assertFalse(outcome.should_continue)


class RunWorkerSubprocessHealthTimeoutTests(unittest.TestCase):
    """Health timeout detection through the shared runner."""

    def test_unhealthy_worker_without_output_is_detected(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            worker = Path(tmpdir) / "sleep_worker.py"
            worker.write_text(
                "import time\n"
                "time.sleep(5)\n",
                encoding="utf-8",
            )

            result, health = run_worker_subprocess(
                [sys.executable, str(worker)],
                tmpdir,
                {},
                health_config=WorkerHealthConfig(
                    health_timeout_seconds=0.1,
                    unhealthy_action="stop",
                ),
            )

        self.assertTrue(health.unhealthy)
        self.assertIn("keine Worker-Ausgabe", health.unhealthy_reason)
        self.assertIn("[batch-health] Unhealthy", result.output)

    def test_healthy_worker_completes_normally(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            worker = Path(tmpdir) / "quick_worker.py"
            worker.write_text(
                "import sys\n"
                "print('hello', flush=True)\n"
                "sys.exit(0)\n",
                encoding="utf-8",
            )

            result, health = run_worker_subprocess(
                [sys.executable, str(worker)],
                tmpdir,
                {},
                health_config=WorkerHealthConfig(
                    health_timeout_seconds=5.0,
                    unhealthy_action="stop",
                ),
            )

        self.assertFalse(health.unhealthy)
        self.assertEqual(result.returncode, 0)
        self.assertIn("hello", result.output)

    def test_warn_action_does_not_mark_unhealthy(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            worker = Path(tmpdir) / "sleep_worker.py"
            worker.write_text(
                "import time\n"
                "time.sleep(5)\n",
                encoding="utf-8",
            )

            result, health = run_worker_subprocess(
                [sys.executable, str(worker)],
                tmpdir,
                {},
                health_config=WorkerHealthConfig(
                    health_timeout_seconds=0.1,
                    unhealthy_action="warn",
                ),
            )

        self.assertFalse(health.unhealthy)
        self.assertIsNone(health.unhealthy_reason)
        self.assertIn("[batch-health] Unhealthy", result.output)

    def test_no_health_config_no_timeout(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            worker = Path(tmpdir) / "slightly_slow_worker.py"
            worker.write_text(
                "import time\n"
                "time.sleep(0.5)\n"
                "print('done', flush=True)\n",
                encoding="utf-8",
            )

            result, health = run_worker_subprocess(
                [sys.executable, str(worker)],
                tmpdir,
                {},
                health_config=None,
            )

        self.assertFalse(health.unhealthy)
        self.assertEqual(result.returncode, 0)
        self.assertIn("done", result.output)

    def test_unhealthy_retry_action_marked_unhealthy(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            worker = Path(tmpdir) / "sleep_worker.py"
            worker.write_text(
                "import time\n"
                "time.sleep(5)\n",
                encoding="utf-8",
            )

            result, health = run_worker_subprocess(
                [sys.executable, str(worker)],
                tmpdir,
                {},
                health_config=WorkerHealthConfig(
                    health_timeout_seconds=0.1,
                    unhealthy_action="retry",
                ),
            )

        self.assertTrue(health.unhealthy)
        self.assertIsNotNone(health.unhealthy_reason)

    def test_worker_producing_output_avoids_health_timeout(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            worker = Path(tmpdir) / "chatty_worker.py"
            worker.write_text(
                "import sys, time\n"
                "for i in range(10):\n"
                "    print(f'line {i}', flush=True)\n"
                "    time.sleep(0.05)\n",
                encoding="utf-8",
            )

            result, health = run_worker_subprocess(
                [sys.executable, str(worker)],
                tmpdir,
                {},
                health_config=WorkerHealthConfig(
                    health_timeout_seconds=0.3,
                    unhealthy_action="stop",
                ),
            )

        self.assertFalse(health.unhealthy)
        self.assertEqual(result.returncode, 0)
        self.assertIn("line 9", result.output)

    def test_rate_limit_suppresses_health_timeout(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            worker = Path(tmpdir) / "rate_limited_worker.py"
            worker.write_text(
                "import sys, time\n"
                "print('Your rate limit will be reset on June 22, 2026, at 1:36 AM.', flush=True)\n"
                "time.sleep(0.5)\n"
                "print('done', flush=True)\n",
                encoding="utf-8",
            )

            def fake_detect_rate_limit(output):
                class FakeRateLimit:
                    reset_at = datetime(2026, 6, 22, 1, 36)
                    reset_text = "June 22, 2026, at 1:36 AM"
                return FakeRateLimit() if "rate limit" in output.lower() else None

            result, health = run_worker_subprocess(
                [sys.executable, str(worker)],
                tmpdir,
                {},
                health_config=WorkerHealthConfig(
                    health_timeout_seconds=0.1,
                    unhealthy_action="stop",
                ),
                detect_rate_limit_fn=fake_detect_rate_limit,
                now_fn=lambda: datetime(2026, 6, 22, 1, 30),
            )

        self.assertFalse(health.unhealthy)
        self.assertEqual(result.returncode, 0)

    def test_on_line_callback_invoked_per_line(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            worker = Path(tmpdir) / "echo_worker.py"
            worker.write_text(
                "print('a', flush=True)\n"
                "print('b', flush=True)\n",
                encoding="utf-8",
            )

            lines: list[str] = []

            result, health = run_worker_subprocess(
                [sys.executable, str(worker)],
                tmpdir,
                {},
                on_line=lambda line: lines.append(line.strip()),
            )

        self.assertFalse(health.unhealthy)
        self.assertEqual(result.returncode, 0)
        self.assertIn("a", lines)
        self.assertIn("b", lines)

    def test_nonzero_returncode_in_result(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            worker = Path(tmpdir) / "failing_worker.py"
            worker.write_text(
                "import sys\n"
                "print('error', flush=True)\n"
                "sys.exit(42)\n",
                encoding="utf-8",
            )

            result, health = run_worker_subprocess(
                [sys.executable, str(worker)],
                tmpdir,
                {},
            )

        self.assertFalse(health.unhealthy)
        self.assertEqual(result.returncode, 42)
        self.assertIn("error", result.output)


if __name__ == "__main__":
    unittest.main()
