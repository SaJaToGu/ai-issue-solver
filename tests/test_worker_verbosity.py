import io
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from solve_issues import WorkerRunResult, run_worker_command  # noqa: E402
from solver_reporting import RunReport, write_run_health  # noqa: E402


class VerbosityTests(unittest.TestCase):
    """run_worker_command druckt Zeilen je nach Verbosity."""

    def _make_popen(self, lines):
        """Fake-Popen der die gegebenen Zeilen liefert."""
        text = "".join(lines)
        proc = unittest.mock.MagicMock()
        proc.stdout = io.StringIO(text)
        proc.returncode = 0
        proc.wait.return_value = 0
        proc.poll.return_value = None
        return proc

    def _run(self, lines, verbosity):
        """Führt run_worker_command aus und gibt gedruckte Zeilen zurück."""
        proc = self._make_popen(lines)
        printed = []
        with patch("subprocess.Popen", return_value=proc), \
             patch("builtins.print", side_effect=lambda *a, **kw: printed.append(a[0] if a else "")):
            run_worker_command(["fake"], "/tmp", {}, verbosity=verbosity)
        return printed

    def test_normal_surfaces_plan_line(self):
        lines = ["Plan: update README\n", "+++ patch detail\n"]
        printed = self._run(lines, "normal")
        self.assertTrue(any("Plan" in p for p in printed))
        self.assertFalse(any("+++ patch" in p for p in printed))

    def test_verbose_shows_all_non_empty_lines(self):
        lines = ["Plan: update README\n", "+++ patch detail\n", "\n"]
        printed = self._run(lines, "verbose")
        self.assertTrue(any("Plan" in p for p in printed))
        self.assertTrue(any("+++ patch" in p for p in printed))

    def test_quiet_prints_nothing(self):
        lines = ["Plan: update README\n", "Error: something failed\n"]
        printed = self._run(lines, "quiet")
        # quiet druckt keine Worker-Zeilen
        self.assertFalse(any("Plan" in p or "Error" in p for p in printed))

    def test_normal_prints_suppression_summary(self):
        lines = ["+++ suppressed line\n"] * 5
        printed = self._run(lines, "normal")
        self.assertTrue(any("ausgeblendet" in p for p in printed))

    def test_quiet_suppresses_suppression_summary(self):
        lines = ["+++ suppressed line\n"] * 5
        printed = self._run(lines, "quiet")
        self.assertFalse(any("ausgeblendet" in p for p in printed))

    def test_result_contains_all_output_regardless_of_verbosity(self):
        lines = ["Plan: update README\n", "+++ patch detail\n"]
        proc = self._make_popen(lines)
        with patch("subprocess.Popen", return_value=proc), \
             patch("builtins.print"):
            result = run_worker_command(["fake"], "/tmp", {}, verbosity="quiet")
        self.assertIn("Plan", result.output)
        self.assertIn("+++ patch", result.output)


class HeartbeatPhaseTests(unittest.TestCase):
    """write_run_health schreibt phase in health.json."""

    def _make_report(self, path):
        return RunReport(
            path=Path(path),
            repo="test-repo",
            issue_number=1,
            issue_title="Test",
            branch="ai/fix-1",
            model="opencode",
        )

    def test_phase_written_to_health_json(self):
        import json
        with tempfile.TemporaryDirectory() as tmpdir:
            report = self._make_report(tmpdir)
            write_run_health(report, status="running", phase="worker_running")
            health = json.loads(Path(tmpdir, "health.json").read_text())
        self.assertEqual(health["phase"], "worker_running")
        self.assertEqual(health["status"], "running")

    def test_process_metadata_written_to_health_json(self):
        import json
        with tempfile.TemporaryDirectory() as tmpdir:
            report = self._make_report(tmpdir)
            write_run_health(
                report,
                status="running",
                phase="worker_running",
                worker_pid=12345,
            )
            health = json.loads(Path(tmpdir, "health.json").read_text())
        self.assertIn("process", health)
        self.assertGreater(health["process"]["runner_pid"], 0)
        self.assertGreater(health["process"]["parent_pid"], 0)
        self.assertEqual(health["process"]["worker_pid"], 12345)

    def test_phase_defaults_to_empty_string(self):
        import json
        with tempfile.TemporaryDirectory() as tmpdir:
            report = self._make_report(tmpdir)
            write_run_health(report, status="running")
            health = json.loads(Path(tmpdir, "health.json").read_text())
        self.assertEqual(health["phase"], "")

    def test_phase_clone_before_validating(self):
        import json
        with tempfile.TemporaryDirectory() as tmpdir:
            report = self._make_report(tmpdir)
            write_run_health(report, status="running", phase="clone")
            health1 = json.loads(Path(tmpdir, "health.json").read_text())
            write_run_health(report, status="running", phase="validating")
            health2 = json.loads(Path(tmpdir, "health.json").read_text())
        self.assertEqual(health1["phase"], "clone")
        self.assertEqual(health2["phase"], "validating")

    def test_all_expected_phases_written(self):
        import json
        phases = ["clone", "worker_running", "validating", "committing", "creating_pr"]
        with tempfile.TemporaryDirectory() as tmpdir:
            report = self._make_report(tmpdir)
            for phase in phases:
                write_run_health(report, status="running", phase=phase)
                health = json.loads(Path(tmpdir, "health.json").read_text())
                self.assertEqual(health["phase"], phase, f"phase mismatch for {phase}")


if __name__ == "__main__":
    unittest.main()
