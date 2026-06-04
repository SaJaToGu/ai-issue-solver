import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from solver_repository import (  # noqa: E402
    CloneResult,
    branch_has_changes_against_base,
    checkout_existing_remote_branch,
    clone_repo,
    commit_and_push,
    create_branch,
    sanitize_clone_output,
)


class SolverRepositoryModuleTests(unittest.TestCase):
    """Stellt sicher, dass der Checkout-/Branch-Lifecycle im eigenen Modul lebt."""

    def test_clone_result_is_truthy_only_when_ok(self):
        self.assertTrue(CloneResult(ok=True))
        self.assertFalse(CloneResult(ok=False))

    def test_sanitize_clone_output_masks_token(self):
        cleaned = sanitize_clone_output(
            "fatal: https://secret-token@github.com/test-owner/demo.git", "secret-token"
        )
        self.assertIn("***", cleaned)
        self.assertNotIn("secret-token", cleaned)

    def test_sanitize_clone_output_handles_empty(self):
        self.assertEqual(sanitize_clone_output("", "secret-token"), "")

    def test_clone_repo_returns_sanitized_output_on_failure(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "run" / "demo"

            with patch("subprocess.run") as run:
                run.return_value = subprocess.CompletedProcess(
                    args=[],
                    returncode=128,
                    stdout="",
                    stderr="fatal: could not read https://secret-token@github.com/test-owner/demo.git\n",
                )

                result = clone_repo("test-owner", "demo", "secret-token", str(target), "missing")

        self.assertFalse(result)
        self.assertIn("***", result.stderr)
        self.assertNotIn("secret-token", result.stderr)
        self.assertEqual(result.target_dir, str(target))


class SolverRepositoryBranchLifecycleTests(unittest.TestCase):
    """Integrationsnahe Tests gegen ein echtes lokales Git-Repository."""

    def _init_repo(self, path: Path) -> None:
        subprocess.run(["git", "init", "-b", "main"], cwd=path, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=path, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=path, check=True, capture_output=True)
        (path / "README.md").write_text("hello\n", encoding="utf-8")
        subprocess.run(["git", "add", "-A"], cwd=path, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=path, check=True, capture_output=True)

    def test_create_branch_creates_new_branch(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self._init_repo(Path(tmpdir))

            self.assertTrue(create_branch(tmpdir, "ai/fix-issue-196"))

            current = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                cwd=tmpdir, capture_output=True, text=True,
            ).stdout.strip()
        self.assertEqual(current, "ai/fix-issue-196")

    def test_checkout_existing_remote_branch_fails_without_remote(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self._init_repo(Path(tmpdir))
            self.assertFalse(checkout_existing_remote_branch(tmpdir, "missing"))

    def test_branch_has_changes_against_base(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self._init_repo(Path(tmpdir))
            create_branch(tmpdir, "feature")
            self.assertFalse(branch_has_changes_against_base(tmpdir, "main"))

            Path(tmpdir, "feature.txt").write_text("new\n", encoding="utf-8")
            subprocess.run(["git", "add", "-A"], cwd=tmpdir, check=True, capture_output=True)
            subprocess.run(["git", "commit", "-m", "feature"], cwd=tmpdir, check=True, capture_output=True)
            self.assertTrue(branch_has_changes_against_base(tmpdir, "main"))

    def test_commit_and_push_returns_false_without_changes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self._init_repo(Path(tmpdir))
            self.assertFalse(
                commit_and_push(tmpdir, "main", "msg", "secret-token", "test-owner", "demo")
            )


if __name__ == "__main__":
    unittest.main()
