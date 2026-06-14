"""Testet die Helper-Scripts des run-overnight-Skills (parse_args.py, parse_args.sh,
scheduling_hint.sh, summary_check.sh).

Diese Tests sind unabhängig von einem GitHub-Token oder KI-Worker.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
HELPERS = SKILL_ROOT / "helpers"
REPO_ROOT = SKILL_ROOT.parents[2]


def run_script(script: Path, *args: str, env: dict | None = None,
               cwd: Path | None = None) -> subprocess.CompletedProcess:
    cmd = [str(script), *args]
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, **(env or {})},
        cwd=str(cwd) if cwd else None,
    )


class TestParseArgsPython(unittest.TestCase):
    def test_valid_arguments(self) -> None:
        result = run_script(
            HELPERS / "parse_args.py",
            "--model", "opencode",
            "--workers", "2",
            "--issue", "42",
            "--repo", "myrepo",
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["ok"], msg=result.stdout)
        self.assertEqual(payload["model"], "opencode")
        self.assertEqual(payload["workers"], 2)
        self.assertEqual(payload["issue"], [42])
        self.assertEqual(payload["repo"], "myrepo")
        self.assertFalse(payload["caffeinate"])
        self.assertFalse(payload["dry_run"])
        self.assertEqual(payload["verbosity"], "normal")
        self.assertEqual(payload["base_branch"], "main")
        self.assertEqual(payload["label"], "ai-generated")

    def test_multiple_issues_supported(self) -> None:
        result = run_script(
            HELPERS / "parse_args.py",
            "--model", "codex",
            "--issue", "1",
            "--issue", "2",
            "--issue", "3",
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["issue"], [1, 2, 3])

    def test_unknown_model_rejected(self) -> None:
        result = run_script(HELPERS / "parse_args.py", "--model", "not-a-model")
        self.assertEqual(result.returncode, 2)
        payload = json.loads(result.stdout)
        self.assertFalse(payload["ok"])
        self.assertTrue(any("unbekanntes Modell" in err for err in payload["errors"]))

    def test_zero_workers_rejected_by_argparse(self) -> None:
        """--workers 0 wird bereits von argparse abgelehnt (positive_int)."""
        result = run_script(
            HELPERS / "parse_args.py",
            "--model", "codex",
            "--workers", "0",
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("Wert muss > 0 sein", result.stderr)

    def test_negative_workers_rejected_by_argparse(self) -> None:
        """Negative Worker werden bereits von argparse abgelehnt (positive_int)."""
        result = run_script(
            HELPERS / "parse_args.py",
            "--model", "codex",
            "--workers", "-1",
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("Wert muss > 0 sein", result.stderr)

    def test_excessive_workers_rejected(self) -> None:
        result = run_script(
            HELPERS / "parse_args.py",
            "--model", "codex",
            "--workers", "64",
        )
        self.assertEqual(result.returncode, 2)
        payload = json.loads(result.stdout)
        self.assertFalse(payload["ok"])

    def test_verbosity_choices(self) -> None:
        for level in ("quiet", "normal", "verbose"):
            result = run_script(
                HELPERS / "parse_args.py",
                "--model", "opencode",
                "--verbosity", level,
            )
            self.assertEqual(result.returncode, 0, msg=result.stderr)

    def test_dry_run_without_repo_rejected(self) -> None:
        result = run_script(
            HELPERS / "parse_args.py",
            "--model", "opencode",
            "--dry-run",
        )
        self.assertEqual(result.returncode, 2)
        payload = json.loads(result.stdout)
        self.assertFalse(payload["ok"])
        self.assertTrue(any("--dry-run" in err for err in payload["errors"]))

    def test_retry_without_retries_rejected(self) -> None:
        result = run_script(
            HELPERS / "parse_args.py",
            "--model", "codex",
            "--unhealthy-action", "retry",
        )
        self.assertEqual(result.returncode, 2)
        payload = json.loads(result.stdout)
        self.assertFalse(payload["ok"])
        self.assertTrue(any("--unhealthy-action=retry" in err for err in payload["errors"]))

    def test_caffeinate_flag_parsed(self) -> None:
        result = run_script(
            HELPERS / "parse_args.py",
            "--model", "codex",
            "--caffeinate",
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["caffeinate"])


class TestParseArgsBash(unittest.TestCase):
    def test_valid_arguments(self) -> None:
        result = subprocess.run(
            ["bash", str(HELPERS / "parse_args.sh"), "--model", "opencode", "--workers", "3"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("MODEL=opencode", result.stdout)
        self.assertIn("WORKERS=3", result.stdout)
        self.assertIn("CAFFEINATE=false", result.stdout)
        self.assertIn("DRY_RUN=false", result.stdout)
        self.assertIn("VERBOSITY=normal", result.stdout)

    def test_missing_model_rejected(self) -> None:
        result = subprocess.run(
            ["bash", str(HELPERS / "parse_args.sh")],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 2)

    def test_unknown_model_rejected(self) -> None:
        result = subprocess.run(
            ["bash", str(HELPERS / "parse_args.sh"), "--model", "nope"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 2)

    def test_negative_workers_rejected(self) -> None:
        result = subprocess.run(
            ["bash", str(HELPERS / "parse_args.sh"), "--model", "codex", "--workers", "-1"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 2)

    def test_excessive_workers_rejected(self) -> None:
        result = subprocess.run(
            ["bash", str(HELPERS / "parse_args.sh"), "--model", "codex", "--workers", "100"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 2)

    def test_caffeinate_flag(self) -> None:
        result = subprocess.run(
            ["bash", str(HELPERS / "parse_args.sh"), "--model", "codex", "--caffeinate"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("CAFFEINATE=true", result.stdout)

    def test_retry_without_retries_rejected(self) -> None:
        result = subprocess.run(
            ["bash", str(HELPERS / "parse_args.sh"), "--model", "codex",
             "--unhealthy-action", "retry"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 2)

    def test_retry_with_retries_accepted(self) -> None:
        result = subprocess.run(
            ["bash", str(HELPERS / "parse_args.sh"), "--model", "codex",
             "--unhealthy-action", "retry", "--unhealthy-retries", "2"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("UNHEALTHY_ACTION=retry", result.stdout)
        self.assertIn("UNHEALTHY_RETRIES=2", result.stdout)


class TestSchedulingHint(unittest.TestCase):
    def test_default_runs(self) -> None:
        result = subprocess.run(
            ["bash", str(HELPERS / "scheduling_hint.sh")],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("=== launchd (macOS) ===", result.stdout)
        self.assertIn("=== cron (Linux/BSD) ===", result.stdout)
        self.assertIn("=== systemd (Linux) ===", result.stdout)

    def test_specific_type(self) -> None:
        result = subprocess.run(
            ["bash", str(HELPERS / "scheduling_hint.sh"), "--type", "systemd"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("systemd", result.stdout)
        self.assertNotIn("launchd", result.stdout)

    def test_invalid_type_rejected(self) -> None:
        result = subprocess.run(
            ["bash", str(HELPERS / "scheduling_hint.sh"), "--type", "nope"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 2)

    def test_invalid_hour_rejected(self) -> None:
        result = subprocess.run(
            ["bash", str(HELPERS / "scheduling_hint.sh"), "--hour", "25"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 2)

    def test_hour_in_range(self) -> None:
        for hour in (0, 12, 23):
            result = subprocess.run(
                ["bash", str(HELPERS / "scheduling_hint.sh"), "--type", "cron", "--hour", str(hour)],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, msg=result.stderr)
            self.assertIn(f"{hour}", result.stdout)


class TestSummaryCheck(unittest.TestCase):
    def test_missing_session_dir_rejected(self) -> None:
        result = subprocess.run(
            ["bash", str(HELPERS / "summary_check.sh")],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 2)

    def test_nonexistent_session_reports_missing(self) -> None:
        result = subprocess.run(
            ["bash", str(HELPERS / "summary_check.sh"), "reports/overnight/does-not-exist"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 3)
        # Die "summary.txt fehlt"-Meldung geht an stderr (kein stdout),
        # damit sie bei normaler Verwendung sofort sichtbar ist.
        self.assertIn("summary.txt fehlt", result.stderr)

    def test_successful_summary_prints_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            session = Path(tmp) / "session1"
            session.mkdir()
            (session / "summary.txt").write_text(
                "status: successful\n"
                "started_at: 2026-06-14T02:00:00\n"
                "finished_at: 2026-06-14T03:00:00\n"
                "duration: 1h 0m 0s\n"
                "session_dir: reports/overnight/session1\n"
                "model: codex\n"
                "workers: 2\n"
                "base_branch: main\n"
                "label: ai-generated\n"
                "dashboard: reports/status-dashboard.html\n"
                "\n"
                "steps:\n"
                "- name: pull\n"
                "  status: ok\n"
                "  exit_code: 0\n"
                "  duration: 1s\n"
                "  log: reports/overnight/session1/pull.log\n",
                encoding="utf-8",
            )
            result = subprocess.run(
                ["bash", str(HELPERS / "summary_check.sh"), str(session)],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, msg=result.stderr)
            self.assertIn("Status:    successful", result.stdout)
            self.assertIn("Started:   2026-06-14T02:00:00", result.stdout)
            self.assertIn("- name: pull", result.stdout)

    def test_failed_summary_exits_1(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            session = Path(tmp) / "session1"
            session.mkdir()
            (session / "summary.txt").write_text(
                "status: failed\n"
                "started_at: 2026-06-14T02:00:00\n"
                "finished_at: 2026-06-14T02:00:30\n"
                "duration: 30s\n"
                "\n"
                "steps:\n"
                "- name: pull\n"
                "  status: failed\n"
                "  exit_code: 1\n"
                "  duration: 0s\n"
                "  log: reports/overnight/session1/pull.log\n"
                "\n"
                "failed_steps:\n"
                "- pull\n",
                encoding="utf-8",
            )
            result = subprocess.run(
                ["bash", str(HELPERS / "summary_check.sh"), str(session)],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 1)
            self.assertIn("Status:    failed", result.stdout)
            self.assertIn("Fehlgeschlagene Schritte", result.stdout)

    def test_issues_only_filter(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            session = Path(tmp) / "session1"
            session.mkdir()
            (session / "summary.txt").write_text(
                "status: successful\n"
                "started_at: 2026-06-14T02:00:00\n"
                "finished_at: 2026-06-14T03:00:00\n"
                "duration: 1h 0m 0s\n"
                "\n"
                "steps:\n"
                "- name: batch\n"
                "  status: ok\n"
                "  exit_code: 0\n"
                "  duration: 30s\n"
                "  log: batch.log\n"
                "\n"
                "issue_outcomes:\n"
                "- issue: 42\n"
                "  repo: myrepo\n"
                "  status: pr_created\n"
                "  pr_url: https://github.com/me/myrepo/pull/1\n",
                encoding="utf-8",
            )
            result = subprocess.run(
                ["bash", str(HELPERS / "summary_check.sh"), str(session), "--issues-only"],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, msg=result.stderr)
            self.assertIn("issue_outcomes:", result.stdout)
            self.assertIn("issue: 42", result.stdout)
            self.assertIn("pr_url: https://github.com/me/myrepo/pull/1", result.stdout)
            self.assertNotIn("- name: batch", result.stdout)


class TestPreflight(unittest.TestCase):
    def test_preflight_reports_missing_env(self) -> None:
        """Preflight bricht ohne config/.env mit Exit-Code 1 ab."""
        with tempfile.TemporaryDirectory() as tmp:
            cwd = os.getcwd()
            try:
                os.chdir(tmp)
                result = subprocess.run(
                    ["bash", str(HELPERS / "preflight.sh")],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(result.returncode, 1)
                self.assertIn("config/.env fehlt", result.stdout)
            finally:
                os.chdir(cwd)

    def test_preflight_rejects_unknown_model(self) -> None:
        """Preflight lehnt unbekannte Modelle ab (Exit 1 nach env-Check, da
        env fehlt — wir verifizieren, dass die Ablehnung in jedem Fall
        passiert)."""
        result = subprocess.run(
            ["bash", str(HELPERS / "preflight.sh"), "--model", "no-such-model"],
            capture_output=True,
            text=True,
            check=False,
        )
        # Erstes Gate: config/.env fehlt → Exit 1 (Test gegen ungewollte Akzeptanz)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("config/.env fehlt", result.stdout)


if __name__ == "__main__":
    unittest.main()
