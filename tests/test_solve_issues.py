import contextlib
import io
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from solve_issues import (  # noqa: E402
    WorkerRunResult,
    assess_worker_result,
    format_worker_output_tail,
    git_status_porcelain,
    run_worker_command,
)


class WorkerAssessmentTests(unittest.TestCase):
    def test_success_with_changes_continues(self):
        assessment = assess_worker_result(WorkerRunResult(0, ""), " M README.md\n")

        self.assertTrue(assessment.should_continue)
        self.assertTrue(assessment.has_changes)
        self.assertEqual(assessment.reason, "changed")

    def test_success_without_changes_stops_as_noop(self):
        assessment = assess_worker_result(WorkerRunResult(0, ""), "")

        self.assertFalse(assessment.should_continue)
        self.assertFalse(assessment.has_changes)
        self.assertEqual(assessment.reason, "no_changes")

    def test_nonzero_with_changes_continues_for_review(self):
        assessment = assess_worker_result(WorkerRunResult(42, "partial"), "?? fix.py\n")

        self.assertTrue(assessment.should_continue)
        self.assertTrue(assessment.has_changes)
        self.assertEqual(assessment.reason, "nonzero_with_changes")

    def test_nonzero_without_changes_stops(self):
        assessment = assess_worker_result(WorkerRunResult(42, "failed"), "")

        self.assertFalse(assessment.should_continue)
        self.assertFalse(assessment.has_changes)
        self.assertEqual(assessment.reason, "nonzero_without_changes")


class WorkerOutputTests(unittest.TestCase):
    def test_output_tail_uses_last_lines(self):
        output = "\n".join(f"line {i}" for i in range(40))

        tail = format_worker_output_tail(output)

        self.assertNotIn("line 0", tail)
        self.assertIn("line 39", tail)

    def test_run_worker_captures_stdout_and_stderr(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            script = Path(tmpdir) / "worker.py"
            script.write_text(
                "import sys\n"
                "print('stdout line')\n"
                "print('stderr line', file=sys.stderr)\n"
                "raise SystemExit(7)\n",
                encoding="utf-8",
            )

            with contextlib.redirect_stdout(io.StringIO()):
                result = run_worker_command(
                    [sys.executable, str(script)],
                    tmpdir,
                    os.environ.copy(),
                )

        self.assertEqual(result.returncode, 7)
        self.assertIn("stdout line", result.output)
        self.assertIn("stderr line", result.output)


class GitStatusTests(unittest.TestCase):
    def test_git_status_porcelain_detects_untracked_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            subprocess.run(["git", "init"], cwd=tmpdir, check=True, capture_output=True)
            Path(tmpdir, "README.md").write_text("hello\n", encoding="utf-8")

            status = git_status_porcelain(tmpdir)

        self.assertIn("?? README.md", status)

    def test_nonzero_worker_with_repo_changes_is_accepted_for_review(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            subprocess.run(["git", "init"], cwd=tmpdir, check=True, capture_output=True)
            subprocess.run(
                ["git", "config", "user.email", "test@example.invalid"],
                cwd=tmpdir,
                check=True,
                capture_output=True,
            )
            subprocess.run(
                ["git", "config", "user.name", "Test User"],
                cwd=tmpdir,
                check=True,
                capture_output=True,
            )
            Path(tmpdir, "README.md").write_text("before\n", encoding="utf-8")
            subprocess.run(["git", "add", "README.md"], cwd=tmpdir, check=True)
            subprocess.run(
                ["git", "commit", "-m", "init"],
                cwd=tmpdir,
                check=True,
                capture_output=True,
            )

            worker = Path(tmpdir) / "worker.py"
            worker.write_text(
                "from pathlib import Path\n"
                "Path('README.md').write_text('after\\n', encoding='utf-8')\n"
                "print('changed README')\n"
                "raise SystemExit(12)\n",
                encoding="utf-8",
            )

            with contextlib.redirect_stdout(io.StringIO()):
                result = run_worker_command(
                    [sys.executable, str(worker)],
                    tmpdir,
                    os.environ.copy(),
                )

            assessment = assess_worker_result(result, git_status_porcelain(tmpdir))

        self.assertEqual(result.returncode, 12)
        self.assertTrue(assessment.should_continue)
        self.assertEqual(assessment.reason, "nonzero_with_changes")


if __name__ == "__main__":
    unittest.main()
