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
    GitHubClient,
    WorkerRunResult,
    assess_worker_result,
    build_aider_command,
    format_worker_output_tail,
    git_status_porcelain,
    infer_aider_targets,
    run_worker_command,
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
