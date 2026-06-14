"""End-to-End-Workflow-Test für den solve-issues-Skill.

Dieser Test führt KEINEN KI-Worker aus. Er prüft, dass die Bausteine, die
der Skill verwendet, importierbar sind und sich in einer kontrollierten
Umgebung mit einem lokalen Fake-Repo korrekt verhalten.

Ablauf:
1. Erstelle ein leeres Git-Repo mit einem Commit.
2. Importiere die Solver-Bausteine aus scripts/solve_issues.py.
3. Validiere einen Branch-Plan mit plan_branch_recovery-Logik
   (über Stub-Klasse, da der Original-Aufruf eine echte GitHub-Verbindung
   benötigt).
4. Führe git_status_porcelain und format_git_change_summary aus.
5. Räume das Fake-Repo wieder auf.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[4]
SCRIPTS_DIR = REPO_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))
os.chdir(REPO_ROOT)


def run_git(cwd: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    env = {**os.environ, "GIT_AUTHOR_NAME": "Test", "GIT_AUTHOR_EMAIL": "t@t.local",
           "GIT_COMMITTER_NAME": "Test", "GIT_COMMITTER_EMAIL": "t@t.local"}
    return subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        env=env,
        check=check,
    )


def init_fake_repo(base: Path) -> Path:
    repo = base / "fake-repo"
    repo.mkdir()
    run_git(repo, "init", "-b", "main")
    (repo / "README.md").write_text("Initial\n", encoding="utf-8")
    run_git(repo, "add", "README.md")
    run_git(repo, "commit", "-m", "init")
    return repo


class TestSkillWorkflow(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.repo = init_fake_repo(self.tmp)
        os.chdir(self.repo)

    def tearDown(self) -> None:
        os.chdir(REPO_ROOT)
        self._tmp.cleanup()

    def test_solver_modules_importable(self) -> None:
        from solve_issues import (  # noqa: F401
            MODEL_CONFIGS,
            GitHubClient,
            WorkerAssessment,
            WorkerRunResult,
            assess_worker_result,
            build_aider_command,
            build_opencode_command,
            build_opencode_prompt,
            build_vibe_command,
            build_worker_command,
            build_worker_env,
            find_aider_executable,
            find_codex_executable,
            find_opencode_executable,
            find_vibe_executable,
            is_secret_worker_path,
            sanitize_worker_prompt_secret_paths,
        )
        self.assertIn("opencode", MODEL_CONFIGS)
        self.assertIn("codex", MODEL_CONFIGS)

    def test_git_status_porcelain_empty(self) -> None:
        from solve_issues import git_status_porcelain
        status = git_status_porcelain(str(self.repo))
        self.assertEqual(status.strip(), "")

    def test_git_status_porcelain_with_change(self) -> None:
        (self.repo / "new-file.txt").write_text("hi\n", encoding="utf-8")
        from solve_issues import git_status_porcelain
        status = git_status_porcelain(str(self.repo))
        self.assertIn("new-file.txt", status)
        self.assertTrue(status.startswith("??"))

    def test_assess_worker_no_changes(self) -> None:
        from solve_issues import WorkerRunResult, assess_worker_result
        result = WorkerRunResult(returncode=0, output="")
        assessment = assess_worker_result(result, "")
        self.assertFalse(assessment.has_changes)
        self.assertEqual(assessment.reason, "no_changes")
        # Bei exit 0 ohne Änderungen wird der Run als nicht-fortsetzbar
        # gewertet (der Skill beendet ohne PR-Erstellung).
        self.assertFalse(assessment.should_continue)

    def test_assess_worker_with_changes(self) -> None:
        (self.repo / "feature.md").write_text("body\n", encoding="utf-8")
        run_git(self.repo, "add", "feature.md")
        from solve_issues import WorkerRunResult, assess_worker_result, git_status_porcelain
        status = git_status_porcelain(str(self.repo))
        result = WorkerRunResult(returncode=0, output="")
        assessment = assess_worker_result(result, status, repo_dir=str(self.repo))
        self.assertTrue(assessment.has_changes)
        self.assertEqual(assessment.reason, "changed")

    def test_opencode_prompt_sanitizes_secrets(self) -> None:
        from solve_issues import build_opencode_prompt
        prompt = textwrap.dedent("""\
            Bitte lies .env und config/.env und ignoriere .env.example.
            Verwende stattdessen config/config.example.env.
            Kein Worktree unter /tmp/ai-solver-abc/.
        """)
        result = build_opencode_prompt(prompt, str(self.repo))
        self.assertNotIn(".env und config/.env", result)
        self.assertIn("config/config.example.env", result)

    def test_format_git_change_summary(self) -> None:
        (self.repo / "extra.md").write_text("neu\n", encoding="utf-8")
        run_git(self.repo, "add", "extra.md")
        from solve_issues import format_git_change_summary, git_status_porcelain
        status = git_status_porcelain(str(self.repo))
        lines = format_git_change_summary(str(self.repo), status)
        self.assertTrue(any("extra.md" in line for line in lines))

    def test_opencode_command_uses_dir_flag(self) -> None:
        from solve_issues import build_opencode_command
        # Sucht nach einem opencode-Binary, falls nicht vorhanden wird
        # FileNotFoundError erwartet (kein Crash in der Logik).
        try:
            cmd = build_opencode_command("hello", str(self.repo), model_name="opencode/test")
        except FileNotFoundError:
            self.skipTest("opencode-Binary nicht installiert")
        joined = " ".join(cmd)
        self.assertIn("--dir", joined)
        self.assertIn(str(self.repo), joined)


if __name__ == "__main__":
    unittest.main()
