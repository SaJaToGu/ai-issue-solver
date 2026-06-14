"""End-to-End-Workflow-Test für den run-overnight-Skill.

Dieser Test startet KEINEN KI-Worker und ruft KEIN GitHub. Er prüft, dass
die Bausteine, die der Skill verwendet, importierbar sind und sich in
einer kontrollierten Umgebung mit einem lokalen Fake-Repo korrekt
verhalten.

Ablauf:
1. Erstelle ein leeres Git-Repo mit einem Commit.
2. Importiere die Runner-Bausteine aus scripts/run_overnight.py.
3. Validiere die wichtigsten Helper-Funktionen (create_session_dir,
   command_to_text, get_step_priority, get_step_badge, …).
4. Schreibe eine Beispiel-Session mit summary.txt und prüfe, dass
   summary_check.sh sie korrekt einliest.
5. Räume das Fake-Repo und die Beispiel-Session wieder auf.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[4]
SCRIPTS_DIR = REPO_ROOT / "scripts"
TESTS_DIR = REPO_ROOT / "reports" / "overnight"
HELPERS_DIR = REPO_ROOT / ".agents" / "skills" / "run-overnight" / "helpers"

sys.path.insert(0, str(SCRIPTS_DIR))


def run_git(cwd: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "Test",
        "GIT_AUTHOR_EMAIL": "t@t.local",
        "GIT_COMMITTER_NAME": "Test",
        "GIT_COMMITTER_EMAIL": "t@t.local",
    }
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

    def test_runner_modules_importable(self) -> None:
        from run_overnight import (  # noqa: F401
            DEFAULT_BASE_BRANCH,
            DEFAULT_DASHBOARD_OUTPUT,
            DEFAULT_LABEL,
            DEFAULT_OVERNIGHT_DIR,
            DEFAULT_TEST_COMMAND,
            IssueOutcome,
            StepResult,
            build_batch_command,
            build_dashboard_command,
            build_pull_command,
            classify_status,
            collect_issue_outcomes,
            command_to_text,
            create_session_dir,
            detect_warning_markers,
            format_duration,
            get_step_badge,
            get_step_priority,
            parse_summary_file,
            shell_words,
            skipped_step,
            write_final_summary,
            write_log_header,
        )
        self.assertEqual(DEFAULT_BASE_BRANCH, "main")
        self.assertEqual(DEFAULT_LABEL, "ai-generated")
        self.assertTrue(str(DEFAULT_DASHBOARD_OUTPUT).endswith("status-dashboard.html"))

    def test_create_session_dir_creates_unique_dirs(self) -> None:
        from run_overnight import create_session_dir

        root = self.tmp / "sessions"
        root.mkdir()
        first = create_session_dir(root, now_fn=lambda: datetime(2026, 6, 14, 2, 0, 0))
        second = create_session_dir(root, now_fn=lambda: datetime(2026, 6, 14, 2, 0, 0))
        self.assertTrue(first.exists())
        self.assertTrue(second.exists())
        self.assertNotEqual(first, second)
        self.assertTrue(second.name.startswith("20260614-020000-"))

    def test_command_to_text_quotes_args(self) -> None:
        from run_overnight import command_to_text

        text = command_to_text(["git", "pull", "--ff-only", "origin", "main"])
        self.assertIn("git pull --ff-only origin main", text)

    def test_get_step_priority_orders(self) -> None:
        from run_overnight import StepResult, get_step_priority

        ok = StepResult("ok", ["true"], 0, Path("/tmp/ok"), 0.0)
        skipped = StepResult("skipped", [], 0, Path("/tmp/sk"), 0.0, skipped=True)
        failed = StepResult("failed", ["false"], 1, Path("/tmp/fa"), 0.0)
        self.assertLess(get_step_priority(ok), get_step_priority(skipped))
        self.assertLess(get_step_priority(skipped), get_step_priority(failed))

    def test_get_step_badge(self) -> None:
        from run_overnight import StepResult, get_step_badge

        ok = StepResult("ok", ["true"], 0, Path("/tmp/ok"), 0.0)
        skipped = StepResult("skipped", [], 0, Path("/tmp/sk"), 0.0, skipped=True)
        failed = StepResult("failed", ["false"], 1, Path("/tmp/fa"), 0.0)
        self.assertEqual(get_step_badge(ok), "[OK]")
        self.assertEqual(get_step_badge(skipped), "[SKIP]")
        self.assertEqual(get_step_badge(failed), "[FAIL]")

    def test_classify_status(self) -> None:
        from run_overnight import classify_status

        self.assertEqual(classify_status("pr_created"), "successful")
        self.assertEqual(classify_status("pr_created_from_existing_branch"), "successful")
        self.assertEqual(classify_status("cleanup_successful"), "successful")
        self.assertEqual(classify_status("skip_existing_pr"), "noop")
        self.assertEqual(classify_status("no_changes"), "failed")
        self.assertEqual(classify_status("nonzero_without_changes"), "failed")
        self.assertEqual(classify_status("branch_create_failed"), "failed")
        self.assertEqual(classify_status("clone_failed"), "failed")
        self.assertEqual(classify_status("rate_limit_deferred"), "failed")
        self.assertEqual(classify_status("archived"), "archived")
        self.assertEqual(classify_status("started"), "running")
        self.assertEqual(classify_status("queued"), "queued")
        # Leerer Status und Exit-Code sind beide "unknown" — diese
        # Kombination signalisiert "Run nicht abgeschlossen", nicht "fail".
        self.assertEqual(classify_status(""), "unknown")
        self.assertEqual(classify_status("", "1"), "unknown")
        # Mit einem Status, der nicht in den oberen Klassen landet, gewinnt
        # der Worker-Exit-Code.
        self.assertEqual(classify_status("weird_state", "1"), "failed")

    def test_format_duration(self) -> None:
        from run_overnight import format_duration

        self.assertEqual(format_duration(5), "5s")
        self.assertEqual(format_duration(65), "1m 5s")
        self.assertEqual(format_duration(3725), "1h 2m 5s")

    def test_parse_summary_file_multiline(self) -> None:
        from run_overnight import parse_summary_file

        # Reale Reihenfolge: einfache Felder zuerst, dann ein
        # multiline-Block (z. B. git_diff_stat) am Ende. parse_summary_file
        # sammelt bis EOF und schreibt den akkumulierten Block in
        # fields[current_multiline_key].
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as fh:
            fh.write(
                "repo: myrepo\n"
                "issue_number: 42\n"
                "status: pr_created\n"
                "git_diff_stat: scripts/run_overnight.py | 12 +++++-------\n"
                "                  tests/test_run_overnight.py | 4 ++++\n"
            )
            path = Path(fh.name)
        try:
            fields = parse_summary_file(path)
            self.assertEqual(fields["repo"], "myrepo")
            self.assertEqual(fields["issue_number"], "42")
            self.assertEqual(fields["status"], "pr_created")
            self.assertIn("run_overnight.py", fields["git_diff_stat"])
            self.assertIn("test_run_overnight.py", fields["git_diff_stat"])
        finally:
            path.unlink()

    def test_parse_summary_file_simple(self) -> None:
        from run_overnight import parse_summary_file

        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as fh:
            fh.write(
                "repo: myrepo\n"
                "issue_number: 42\n"
                "status: pr_created\n"
            )
            path = Path(fh.name)
        try:
            fields = parse_summary_file(path)
            self.assertEqual(fields["repo"], "myrepo")
            self.assertEqual(fields["issue_number"], "42")
            self.assertEqual(fields["status"], "pr_created")
        finally:
            path.unlink()

    def test_detect_warning_markers_conflict(self) -> None:
        from run_overnight import detect_warning_markers

        run_dir = self.tmp / "run-with-conflict"
        run_dir.mkdir()
        (run_dir / "summary.txt").write_text(
            "git_diff_stat: scripts/foo.py | conflict marker detected\n",
            encoding="utf-8",
        )
        markers = detect_warning_markers(run_dir)
        self.assertIn("conflict", markers)

    def test_detect_warning_markers_conflict_from_output_tail(self) -> None:
        from run_overnight import detect_warning_markers

        run_dir = self.tmp / "run-with-output-tail"
        run_dir.mkdir()
        (run_dir / "summary.txt").write_text(
            "output_tail: Hinweis: enthaelt Konfliktmarker\n",
            encoding="utf-8",
        )
        markers = detect_warning_markers(run_dir)
        self.assertIn("conflict", markers)

    def test_detect_warning_markers_syntax(self) -> None:
        from run_overnight import detect_warning_markers

        run_dir = self.tmp / "run-with-syntax"
        run_dir.mkdir()
        (run_dir / "worker-output.log").write_text(
            "Python-Syntaxpruefung fehlgeschlagen: unexpected EOF\n",
            encoding="utf-8",
        )
        markers = detect_warning_markers(run_dir)
        self.assertIn("syntax", markers)

    def test_shell_words_valid(self) -> None:
        from run_overnight import shell_words

        self.assertEqual(
            shell_words("python -m unittest discover"),
            ["python", "-m", "unittest", "discover"],
        )

    def test_build_pull_command(self) -> None:
        from run_overnight import build_pull_command

        cmd = build_pull_command("main")
        self.assertEqual(cmd, ["git", "pull", "--ff-only", "origin", "main"])

    def test_summary_check_reads_session(self) -> None:
        """End-to-End-Test: Summary in Session schreiben und mit summary_check.sh lesen."""
        with tempfile.TemporaryDirectory() as tmp:
            session = Path(tmp) / "session-smoke"
            session.mkdir()
            (session / "summary.txt").write_text(
                "status: successful\n"
                "started_at: 2026-06-14T02:00:00\n"
                "finished_at: 2026-06-14T03:00:00\n"
                "duration: 1h 0m 0s\n"
                "session_dir: reports/overnight/session-smoke\n"
                "model: codex\n"
                "model_name: \n"
                "workers: 2\n"
                "base_branch: main\n"
                "label: ai-generated\n"
                "dry_run: False\n"
                "dashboard: reports/status-dashboard.html\n"
                "\n"
                "steps:\n"
                "- name: pull\n"
                "  status: ok\n"
                "  exit_code: 0\n"
                "  duration: 1s\n"
                "  log: pull.log\n"
                "- name: batch\n"
                "  status: ok\n"
                "  exit_code: 0\n"
                "  duration: 30m\n"
                "  log: batch.log\n"
                "\n"
                "issue_outcomes:\n"
                "- issue: 7\n"
                "  repo: myrepo\n"
                "  title: Add tests\n"
                "  status: pr_created\n"
                "  category: successful\n"
                "  worker_exit_code: 0\n"
                "  pr_url: https://github.com/me/myrepo/pull/9\n"
                "  branch: ai/fix-issue-7\n"
                "  model: codex\n"
                "  run_dir: 20260614-020000-abcdef\n",
                encoding="utf-8",
            )
            result = subprocess.run(
                ["bash", str(HELPERS_DIR / "summary_check.sh"), str(session)],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, msg=result.stderr)
            self.assertIn("Status:    successful", result.stdout)
            self.assertIn("- name: pull", result.stdout)
            self.assertIn("- name: batch", result.stdout)
            self.assertIn("issue: 7", result.stdout)
            self.assertIn("pr_url: https://github.com/me/myrepo/pull/9", result.stdout)


if __name__ == "__main__":
    unittest.main()
