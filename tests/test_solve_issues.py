import contextlib
from datetime import datetime
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
    GitHubClient,
    WorkerRunResult,
    assess_worker_result,
    build_aider_command,
    detect_codex_rate_limit,
    format_git_change_summary,
    format_worker_output_tail,
    git_status_porcelain,
    infer_aider_targets,
    parse_codex_reset_datetime,
    run_worker_command,
    should_surface_worker_line,
    sleep_until_codex_reset,
    write_worker_diagnostics,
)


class FakeResponse:
    def __init__(self, status_code, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.text = text

    def json(self):
        return self._payload


class FakeGitHubSession:
    def __init__(self):
        self.headers = {}
        self.posts = []

    def get(self, url, params=None):
        if url.endswith("/repos/test-owner/demo"):
            return FakeResponse(200, {"default_branch": "main"})
        if url.endswith("/repos/test-owner/demo/branches/main"):
            return FakeResponse(200, {"name": "main"})
        if url.endswith("/repos/test-owner/demo/branches/develop"):
            return FakeResponse(404, {"message": "Branch not found"})
        return FakeResponse(404, {"message": "Not found"})

    def post(self, url, json=None):
        self.posts.append((url, json))
        return FakeResponse(201, {"html_url": "https://github.com/test-owner/demo/pull/1"})


class GitHubClientBranchTests(unittest.TestCase):
    def make_client(self):
        client = GitHubClient.__new__(GitHubClient)
        client.owner = "test-owner"
        client.session = FakeGitHubSession()
        return client

    def test_resolve_base_branch_uses_default_branch_without_override(self):
        client = self.make_client()

        base_branch = client.resolve_base_branch("demo")

        self.assertEqual(base_branch, "main")

    def test_resolve_base_branch_falls_back_to_default_when_requested_branch_is_missing(self):
        client = self.make_client()

        with contextlib.redirect_stdout(io.StringIO()):
            base_branch = client.resolve_base_branch("demo", "develop")

        self.assertEqual(base_branch, "main")

    def test_create_pull_request_posts_against_resolved_default_branch(self):
        client = self.make_client()

        with contextlib.redirect_stdout(io.StringIO()):
            pr = client.create_pull_request(
                repo="demo",
                title="Fix",
                body="Body",
                head="ai/fix-issue-1",
                base="develop",
            )

        self.assertEqual(pr["html_url"], "https://github.com/test-owner/demo/pull/1")
        self.assertEqual(client.session.posts[0][1]["base"], "main")


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


class CodexRateLimitTests(unittest.TestCase):
    def test_detects_codex_rate_limit_and_parses_reset_time(self):
        output = (
            "You have reached the Codex message limit\n"
            "Your rate limit will be reset on May 20, 2026, at 1:36 AM. "
            "To continue using Codex, add credits or upgrade to Pro today.\n"
        )

        rate_limit = detect_codex_rate_limit(output)

        self.assertIsNotNone(rate_limit)
        self.assertEqual(rate_limit.reset_text, "May 20, 2026, at 1:36 AM")
        self.assertEqual(rate_limit.reset_at, datetime(2026, 5, 20, 1, 36))

    def test_parse_codex_reset_datetime_accepts_abbreviated_month(self):
        reset_at = parse_codex_reset_datetime("May 20, 2026, at 1:36 AM")

        self.assertEqual(reset_at, datetime(2026, 5, 20, 1, 36))

    def test_sleep_until_codex_reset_uses_remaining_seconds(self):
        sleeps = []
        rate_limit = detect_codex_rate_limit(
            "Your rate limit will be reset on May 20, 2026, at 1:36 AM."
        )

        with contextlib.redirect_stdout(io.StringIO()):
            sleep_until_codex_reset(
                rate_limit,
                sleep_fn=sleeps.append,
                now_fn=lambda: datetime(2026, 5, 20, 1, 35, 30),
            )

        self.assertEqual(sleeps, [30.0])


class AiderCommandTests(unittest.TestCase):
    def test_aider_command_adds_valid_issue_file_targets(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            (repo / "scripts").mkdir()
            (repo / "scripts" / "solve_issues.py").write_text("print('x')\n", encoding="utf-8")
            prompt = "Bitte `scripts/solve_issues.py` und README.md prüfen."

            cmd = build_aider_command("claude", "", prompt, str(repo))

        self.assertIn("--subtree-only", cmd)
        self.assertIn("--message", cmd)
        self.assertIn("scripts/solve_issues.py", cmd)
        self.assertIn("README.md", cmd)

    def test_aider_target_inference_rejects_paths_outside_repo(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            (repo / "README.md").write_text("hello\n", encoding="utf-8")
            prompt = "Ändere `README.md`, `../secret.txt` und https://example.test/file.py"

            targets = infer_aider_targets(prompt, str(repo))

        self.assertEqual(targets, ["README.md"])

    def test_aider_command_can_use_explicit_file_targets(self):
        cmd = build_aider_command(
            "ollama",
            "llama3.2:3b",
            "Fix",
            "/tmp/repo",
            file_targets=["src/app.py"],
        )

        self.assertIn("--model", cmd)
        self.assertIn("ollama/llama3.2:3b", cmd)
        self.assertEqual(cmd[-1], "src/app.py")


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

    def test_worker_live_filter_keeps_status_and_hides_diff_noise(self):
        self.assertTrue(should_surface_worker_line("Plan: update solver output\n"))
        self.assertTrue(should_surface_worker_line("Ergebnis: Tests erfolgreich\n"))
        self.assertTrue(should_surface_worker_line("WARNING: test command failed\n"))
        self.assertFalse(should_surface_worker_line("+print('implementation detail')\n"))
        self.assertFalse(should_surface_worker_line("@@ -1,2 +1,3 @@\n"))

    def test_run_worker_preserves_full_output_while_printing_summary(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            script = Path(tmpdir) / "worker.py"
            script.write_text(
                "print('Plan: change README')\n"
                "print('+ noisy diff line')\n"
                "print('Final result: done')\n",
                encoding="utf-8",
            )

            printed = io.StringIO()
            with contextlib.redirect_stdout(printed):
                result = run_worker_command(
                    [sys.executable, str(script)],
                    tmpdir,
                    os.environ.copy(),
                )

        self.assertIn("+ noisy diff line", result.output)
        self.assertIn("Plan: change README", printed.getvalue())
        self.assertIn("Detailzeilen ausgeblendet", printed.getvalue())
        self.assertNotIn("+ noisy diff line", printed.getvalue())

    def test_run_worker_prints_single_suppression_summary(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            script = Path(tmpdir) / "worker.py"
            script.write_text(
                "for index in range(75):\n"
                "    print(f'+ noisy diff line {index}')\n"
                "print('Final result: done')\n"
                "for index in range(25):\n"
                "    print(f'- more noisy diff line {index}')\n",
                encoding="utf-8",
            )

            printed = io.StringIO()
            with contextlib.redirect_stdout(printed):
                run_worker_command(
                    [sys.executable, str(script)],
                    tmpdir,
                    os.environ.copy(),
                )

        output = printed.getvalue()
        self.assertEqual(output.count("Detailzeilen ausgeblendet"), 1)
        self.assertIn("100 Detailzeilen ausgeblendet", output)
        self.assertNotIn("bisher", output)


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

    def test_git_change_summary_contains_status_and_diff_stat(self):
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
            readme = Path(tmpdir) / "README.md"
            readme.write_text("before\n", encoding="utf-8")
            subprocess.run(["git", "add", "README.md"], cwd=tmpdir, check=True)
            subprocess.run(
                ["git", "commit", "-m", "init"],
                cwd=tmpdir,
                check=True,
                capture_output=True,
            )
            readme.write_text("before\nafter\n", encoding="utf-8")
            Path(tmpdir, "notes.txt").write_text("new\n", encoding="utf-8")

            summary = "\n".join(format_git_change_summary(tmpdir))

        self.assertIn("Git-Änderungsübersicht", summary)
        self.assertIn("README.md", summary)
        self.assertIn("notes.txt", summary)
        self.assertIn("Statistik:", summary)
        self.assertIn("Neue Dateien: 1 Datei, 1 eingefuegte Zeile", summary)
        self.assertIn("Diff-Vorschau:", summary)
        self.assertIn("new file, 1 eingefuegte Zeile", summary)

    def test_worker_diagnostics_write_full_output(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            old_cwd = os.getcwd()
            os.chdir(tmpdir)
            try:
                run_dir = write_worker_diagnostics(
                    WorkerRunResult(3, "full\nworker\noutput\n"),
                    repo="demo",
                    issue_number=28,
                    model="codex",
                )
                run_dir = Path(run_dir).resolve()
                log = Path(run_dir) / "worker-output.log"
                summary = Path(run_dir) / "summary.txt"
            finally:
                os.chdir(old_cwd)

            self.assertEqual(log.read_text(encoding="utf-8"), "full\nworker\noutput\n")
            self.assertIn("worker_exit_code: 3", summary.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
