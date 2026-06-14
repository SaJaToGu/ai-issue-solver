"""End-to-End-Workflow-Test für den solver-reporting-Skill.

Dieser Test prüft, dass die Bausteine aus ``scripts/solver_reporting.py``
importierbar sind und sich in einer kontrollierten Umgebung mit
synthetischen Run-Reports korrekt verhalten.

Ablauf:
1. Importiere die Solver-Reporting-Bausteine.
2. Erstelle einen temporären Run-Report mit ``create_run_report`` und
   ``write_run_report``.
3. Validiere ``build_run_outcome`` für die gängigen Status-Codes.
4. Validiere ``detect_opencode_runtime_diagnostics`` und
   ``create_provider_scorecard``.
5. Teste ``cleanup_preserved_worktrees`` mit einem synthetischen
   abgelaufenen Worktree.
6. Teste ``format_heartbeat`` für stabile Ausgabe.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock

REPO_ROOT = Path(__file__).resolve().parents[4]
SCRIPTS_DIR = REPO_ROOT / "scripts"
sys.path.insert(0, str(REPO_ROOT))


class TestReportingImports(unittest.TestCase):
    def test_solver_reporting_modules_importable(self) -> None:
        from scripts.solver_reporting import (  # noqa: F401
            OpenCodeRuntimeDiagnostics,
            PRESERVE_WORKTREE_STATUSES,
            PRESERVED_WORKTREES_ROOT,
            PRESERVED_WORKTREE_RETENTION_DAYS,
            RUN_REPORTS_ROOT,
            ProviderScorecard,
            RunReport,
            build_run_outcome,
            cleanup_preserved_worktrees,
            create_provider_scorecard,
            create_run_report,
            detect_opencode_runtime_diagnostics,
            format_git_change_summary,
            format_heartbeat,
            format_heartbeat_progress,
            format_untracked_diff_stat_lines,
            format_untracked_file_stats,
            format_worker_output_tail,
            infer_test_status,
            normalize_diff_stat_lines,
            opencode_runtime_diagnostic_lines,
            preserve_worker_worktree,
            preserved_worktree_cleanup_command,
            preserved_worktree_recovery_note,
            print_git_change_summary,
            print_opencode_runtime_diagnostics,
            safe_run_repo_name,
            sanitize_preserved_remote,
            should_preserve_worktree,
            should_surface_worker_line,
            unique_preserved_worktree_path,
            write_preserved_worktree_readme,
            write_run_health,
            write_run_report,
            write_worker_diagnostics,
        )
        self.assertEqual(PRESERVED_WORKTREE_RETENTION_DAYS, 14)
        self.assertIn("pr_failed", PRESERVE_WORKTREE_STATUSES)
        self.assertIn("push_failed", PRESERVE_WORKTREE_STATUSES)


class TestRunReportCreation(unittest.TestCase):
    def test_create_run_report_writes_files(self) -> None:
        from scripts.solver_reporting import (
            RunReport,
            create_run_report,
            write_run_report,
        )
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            report = RunReport(
                path=tmp_path / "demo-run",
                repo="myrepo",
                issue_number=3,
                issue_title="Demo",
                branch="ai/fix-issue-3",
                model="opencode",
            )
            self.assertIsNotNone(report)
            report.path.mkdir(parents=True, exist_ok=True)
            worker = Mock()
            worker.returncode = 0
            worker.output = "Demo output"
            worker.last_activity_at = datetime.now()
            worker.duration_seconds = 12.0
            result = write_run_report(
                report=report,
                status="pr_created",
                worker_result=worker,
                pr_url="https://github.com/owner/myrepo/pull/3",
            )
            self.assertIsNotNone(result)
            self.assertTrue((report.path / "summary.txt").exists())
            self.assertTrue((report.path / "metadata.json").exists())
            metadata = json.loads(
                (report.path / "metadata.json").read_text(encoding="utf-8")
            )
            self.assertEqual(metadata["status"], "pr_created")
            self.assertEqual(metadata["repo"], "myrepo")
            self.assertEqual(metadata["issue"], 3)
            self.assertIn("provider_scorecard", metadata)
            self.assertIn("run_outcome", metadata)


class TestRunOutcome(unittest.TestCase):
    def test_pr_created_classified_as_success(self) -> None:
        from scripts.solver_reporting import build_run_outcome
        worker = Mock(returncode=0)
        outcome = build_run_outcome(
            "pr_created",
            worker_result=worker,
            pr_url="https://github.com/owner/repo/pull/1",
            git_change_summary=["  README.md | 1 +"],
            test_result="passed",
        )
        self.assertEqual(outcome["worker_status"], "succeeded")
        self.assertEqual(outcome["delivery_status"], "pr_created")
        self.assertEqual(outcome["failure_class"], "success")
        self.assertEqual(outcome["recovery_status"], "none")

    def test_push_failed_with_preserved_is_pipeline_failure(self) -> None:
        from scripts.solver_reporting import build_run_outcome
        worker = Mock(returncode=0)
        outcome = build_run_outcome(
            "push_failed",
            worker_result=worker,
            preserved_worktree_path="reports/preserved-worktrees/run/demo",
            git_change_summary=["  README.md | 1 +"],
        )
        self.assertEqual(outcome["delivery_status"], "push_failed")
        self.assertEqual(outcome["failure_class"], "pipeline_failure")
        self.assertEqual(outcome["recovery_status"], "preserved_worktree")

    def test_model_failure_when_worker_fails_without_changes(self) -> None:
        from scripts.solver_reporting import build_run_outcome
        worker = Mock(returncode=1)
        outcome = build_run_outcome(
            "nonzero_without_changes",
            worker_result=worker,
        )
        self.assertEqual(outcome["worker_status"], "failed")
        self.assertEqual(outcome["failure_class"], "model_failure")
        self.assertEqual(outcome["recovery_status"], "retry_clean")

    def test_noop_for_no_changes(self) -> None:
        from scripts.solver_reporting import build_run_outcome
        outcome = build_run_outcome("no_changes", worker_result=None)
        self.assertEqual(outcome["failure_class"], "noop")

    def test_infer_test_status(self) -> None:
        from scripts.solver_reporting import infer_test_status
        self.assertEqual(infer_test_status("all passed"), "passed")
        self.assertEqual(infer_test_status("FAIL: 1"), "failed")
        self.assertEqual(infer_test_status(None), "unknown")
        self.assertEqual(infer_test_status(""), "unknown")


class TestOpencodeDiagnostics(unittest.TestCase):
    def test_wal_failure_detected(self) -> None:
        from scripts.solver_reporting import detect_opencode_runtime_diagnostics
        diag = detect_opencode_runtime_diagnostics(
            "Database error: PRAGMA wal_checkpoint(PASSIVE)"
        )
        self.assertTrue(diag.wal_failure)
        self.assertFalse(diag.edit_loop)

    def test_edit_loop_detected_above_threshold(self) -> None:
        from scripts.solver_reporting import detect_opencode_runtime_diagnostics
        output = "\n".join(
            f"Edit file_{i}.py failed" for i in range(5)
        )
        diag = detect_opencode_runtime_diagnostics(output)
        self.assertTrue(diag.edit_loop)
        self.assertEqual(diag.edit_failure_count, 5)
        self.assertEqual(len(diag.edit_failure_files), 5)

    def test_edit_loop_below_threshold(self) -> None:
        from scripts.solver_reporting import detect_opencode_runtime_diagnostics
        output = "\n".join(f"Edit file_{i}.py failed" for i in range(2))
        diag = detect_opencode_runtime_diagnostics(output)
        self.assertFalse(diag.edit_loop)
        self.assertEqual(diag.edit_failure_count, 2)

    def test_diagnostic_lines_for_wal(self) -> None:
        from scripts.solver_reporting import (
            detect_opencode_runtime_diagnostics,
            opencode_runtime_diagnostic_lines,
        )
        diag = detect_opencode_runtime_diagnostics("PRAGMA wal_checkpoint(PASSIVE)")
        lines = opencode_runtime_diagnostic_lines(diag)
        self.assertTrue(any("SQLite/WAL" in line for line in lines))


class TestProviderScorecard(unittest.TestCase):
    def test_scorecard_creation(self) -> None:
        from scripts.solver_reporting import RunReport, create_provider_scorecard
        # Wir verwenden eine echte RunReport-Instanz statt eines Mocks,
        # weil ``create_provider_scorecard`` Attribute via ``getattr``/
        # ``hasattr`` ausliest und Mock sonst Auto-Attribute erzeugt.
        report = RunReport(
            path=Path("/tmp/demo"),
            repo="myrepo",
            issue_number=1,
            issue_title="Demo",
            branch="ai/fix-issue-1",
            model="mistral/mistral-medium-latest",
        )
        worker = Mock(returncode=0, duration_seconds=60.0)
        model_selection = {
            "model": "mistral/mistral-large-latest",
            "fallback_from": "anthropic/claude-sonnet-4-6",
            "reason": "rate_limit",
            "estimated_cost": 0.10,
            "cost_currency": "USD",
            "cost_confidence": "high",
            "cost_source": "provider_api",
        }
        scorecard = create_provider_scorecard(
            report=report,
            status="pr_created",
            worker_result=worker,
            pr_url="https://github.com/owner/repo/pull/1",
            model_selection_metadata=model_selection,
            test_command="pytest",
            test_result="passed",
        )
        self.assertEqual(scorecard.requested_model, "mistral/mistral-large-latest")
        # actual_model wird um die Fallback-Information ergänzt, sobald
        # ``fallback_used`` True ist.
        self.assertIn("mistral/mistral-medium-latest", scorecard.actual_model)
        self.assertIn("Fallback von", scorecard.actual_model)
        self.assertIn("anthropic/claude-sonnet-4-6", scorecard.actual_model)
        self.assertTrue(scorecard.fallback_used)
        self.assertEqual(scorecard.estimated_cost, 0.10)
        self.assertEqual(scorecard.cost_source, "provider_api")

    def test_scorecard_no_change(self) -> None:
        from scripts.solver_reporting import RunReport, create_provider_scorecard
        report = RunReport(
            path=Path("/tmp/demo"),
            repo="myrepo",
            issue_number=1,
            issue_title="Demo",
            branch="ai/fix-issue-1",
            model="opencode",
        )
        scorecard = create_provider_scorecard(
            report=report,
            status="no_changes",
            worker_result=None,
        )
        self.assertTrue(scorecard.no_change)
        self.assertFalse(scorecard.fallback_used)


class TestHeartbeat(unittest.TestCase):
    def test_progress_every_fifth_char_is_plus(self) -> None:
        from scripts.solver_reporting import format_heartbeat_progress
        progress = format_heartbeat_progress(elapsed_seconds=300.0, width=20)
        chars = progress.split(" ")[0]
        for i, char in enumerate(chars):
            expected = "+" if (i + 1) % 5 == 0 else "."
            self.assertEqual(char, expected)

    def test_heartbeat_with_label(self) -> None:
        from scripts.solver_reporting import format_heartbeat
        heartbeat = format_heartbeat(223, 1020.0, job_label="PR2")
        self.assertTrue(heartbeat.startswith("#223"))
        self.assertIn("PR2", heartbeat)
        self.assertTrue(heartbeat.endswith("17min"))


class TestWorkerOutputFilter(unittest.TestCase):
    def test_should_surface_status_lines(self) -> None:
        from scripts.solver_reporting import should_surface_worker_line
        self.assertTrue(should_surface_worker_line("## Plan"))
        self.assertTrue(should_surface_worker_line("→ Task gestartet"))
        self.assertTrue(should_surface_worker_line("done"))
        self.assertTrue(should_surface_worker_line("error: something"))

    def test_should_filter_noisy_diff(self) -> None:
        from scripts.solver_reporting import should_surface_worker_line
        self.assertFalse(should_surface_worker_line("diff --git a/foo b/foo"))
        self.assertFalse(should_surface_worker_line("@@ -1,2 +1,2 @@"))
        self.assertFalse(should_surface_worker_line("+x = 1"))
        self.assertFalse(should_surface_worker_line("name = value"))

    def test_format_worker_output_tail(self) -> None:
        from scripts.solver_reporting import format_worker_output_tail
        output = "\n".join(
            [
                "diff --git a/foo b/foo",
                "## Plan",
                "→ Task gestartet",
                "done",
            ]
        )
        tail = format_worker_output_tail(output)
        self.assertNotIn("diff --git", tail)
        self.assertIn("## Plan", tail)
        self.assertIn("done", tail)


class TestPreservedWorktrees(unittest.TestCase):
    def test_safe_run_repo_name(self) -> None:
        from scripts.solver_reporting import safe_run_repo_name
        self.assertEqual(safe_run_repo_name("foo/bar baz"), "foo-bar-baz")
        # Ein leerer String nach Bereinigung fällt auf "repo" zurück
        self.assertEqual(safe_run_repo_name("///"), "repo")
        # Punkte sind erlaubt; sie werden beibehalten
        self.assertEqual(safe_run_repo_name("Hello-World_1.0"), "Hello-World_1.0")
        # Sonderzeichen werden zu Bindestrichen
        self.assertEqual(safe_run_repo_name("a b c"), "a-b-c")

    def test_should_preserve_for_push_failed_with_changes(self) -> None:
        from scripts.solver_reporting import should_preserve_worktree
        # git_status_porcelain und branch_has_changes_against_base
        # brauchen ein echtes Git-Repo, daher nur mit changes_exist=True testen.
        self.assertTrue(
            should_preserve_worktree("push_failed", "/nonexistent", "main", changes_exist=True)
        )
        self.assertFalse(
            should_preserve_worktree("pr_created", "/nonexistent", "main", changes_exist=True)
        )

    def test_preserved_worktree_cleanup_command(self) -> None:
        from scripts.solver_reporting import preserved_worktree_cleanup_command
        cmd = preserved_worktree_cleanup_command()
        self.assertIn("--cleanup-preserved-worktrees", cmd)
        self.assertIn("--retention-days 14", cmd)

    def test_cleanup_removes_stale_worktrees(self) -> None:
        from scripts.solver_reporting import cleanup_preserved_worktrees
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            stale = tmp_path / "stale"
            fresh = tmp_path / "fresh"
            stale.mkdir()
            fresh.mkdir()
            old_time = time.time() - 30 * 24 * 60 * 60
            os.utime(stale, (old_time, old_time))
            removed = cleanup_preserved_worktrees(
                root=tmp_path,
                retention_days=14,
                dry_run=False,
            )
            self.assertIn(stale, removed)
            self.assertNotIn(fresh, removed)
            self.assertFalse(stale.exists())
            self.assertTrue(fresh.exists())


class TestWriteRunHealth(unittest.TestCase):
    def test_write_run_health_creates_file(self) -> None:
        from scripts.solver_reporting import (
            RunReport,
            write_run_health,
        )
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            report = RunReport(
                path=tmp_path / "demo-run",
                repo="myrepo",
                issue_number=1,
                issue_title="Demo",
                branch="ai/fix-issue-1",
                model="opencode",
            )
            report.path.mkdir(parents=True, exist_ok=True)
            write_run_health(
                report,
                output="## Plan\n→ Task gestartet\ndone\n",
                status="running",
                phase="worker_running",
            )
            health = json.loads(
                (report.path / "health.json").read_text(encoding="utf-8")
            )
            self.assertEqual(health["status"], "running")
            self.assertEqual(health["phase"], "worker_running")
            self.assertIn("last_activity_at", health)
            self.assertIn("opencode_runtime", health)
            self.assertFalse(health["opencode_runtime"]["wal_failure"])


class TestFormatGitChangeSummary(unittest.TestCase):
    def test_format_untracked_files(self) -> None:
        from scripts.solver_reporting import format_untracked_file_stats
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            (tmp_path / "new.md").write_text("a\nb\nc\n", encoding="utf-8")
            stats, insertions = format_untracked_file_stats(
                str(tmp_path),
                ["?? new.md"],
            )
            self.assertEqual(stats, [("new.md", 3)])
            self.assertEqual(insertions, 3)

    def test_format_untracked_diff_stat_lines(self) -> None:
        from scripts.solver_reporting import format_untracked_diff_stat_lines
        lines = format_untracked_diff_stat_lines(
            [("README.md", 1), ("longer-filename.py", 5)],
            path_width=20,
        )
        self.assertEqual(len(lines), 2)
        self.assertTrue(all("|" in line for line in lines))
        # '+' pro Zeile
        self.assertIn("+", lines[0])


if __name__ == "__main__":
    unittest.main()
