"""Testet die Helper-Scripts des solve-issues-Skills (parse_args.py, parse_args.sh).

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


def run_script(script: Path, *args: str, env: dict | None = None) -> subprocess.CompletedProcess:
    cmd = [str(script), *args]
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, **(env or {})},
    )


class TestParseArgsPython(unittest.TestCase):
    def test_valid_arguments(self) -> None:
        result = run_script(
            HELPERS / "parse_args.py",
            "--model", "opencode",
            "--issue", "3",
            "--repo", "myrepo",
            "--model-name", "opencode/deepseek-v4-flash-free",
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["model"], "opencode")
        self.assertEqual(payload["issue"], 3)
        self.assertEqual(payload["repo"], "myrepo")
        self.assertEqual(payload["model_name"], "opencode/deepseek-v4-flash-free")
        self.assertFalse(payload["dry_run"])
        self.assertEqual(payload["verbosity"], "normal")

    def test_unknown_model_rejected(self) -> None:
        result = run_script(HELPERS / "parse_args.py", "--model", "not-a-model")
        self.assertEqual(result.returncode, 2)
        payload = json.loads(result.stdout)
        self.assertFalse(payload["ok"])
        self.assertTrue(any("unbekanntes Modell" in err for err in payload["errors"]))

    def test_negative_issue_rejected(self) -> None:
        result = run_script(
            HELPERS / "parse_args.py",
            "--model", "opencode",
            "--issue", "-3",
        )
        self.assertEqual(result.returncode, 2)
        payload = json.loads(result.stdout)
        self.assertFalse(payload["ok"])
        self.assertTrue(any("--issue" in err for err in payload["errors"]))

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


class TestParseArgsBash(unittest.TestCase):
    def test_valid_arguments(self) -> None:
        result = subprocess.run(
            ["bash", str(HELPERS / "parse_args.sh"), "--model", "opencode", "--issue", "3"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("MODEL=opencode", result.stdout)
        self.assertIn("ISSUE=3", result.stdout)
        self.assertIn("DRY_RUN=false", result.stdout)

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

    def test_dry_run_flag(self) -> None:
        result = subprocess.run(
            ["bash", str(HELPERS / "parse_args.sh"), "--model", "codex", "--dry-run"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("DRY_RUN=true", result.stdout)

    def test_negative_issue_rejected(self) -> None:
        result = subprocess.run(
            ["bash", str(HELPERS / "parse_args.sh"), "--model", "codex", "--issue", "-1"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 2)


class TestPreflightAndRecovery(unittest.TestCase):
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

    def test_recovery_check_requires_three_args(self) -> None:
        result = subprocess.run(
            ["bash", str(HELPERS / "recovery_check.sh")],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 2)
        result_two = subprocess.run(
            ["bash", str(HELPERS / "recovery_check.sh"), "owner", "repo"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result_two.returncode, 2)

    def test_recovery_check_rejects_non_numeric_issue(self) -> None:
        # Issue-Validierung erfolgt vor dem Token-Check, daher ohne
        # GITHUB_TOKEN testbar.
        result = subprocess.run(
            ["bash", str(HELPERS / "recovery_check.sh"), "owner", "repo", "abc"],
            capture_output=True,
            text=True,
            check=False,
            env={"PATH": os.environ.get("PATH", "")},
        )
        self.assertEqual(result.returncode, 2)


if __name__ == "__main__":
    unittest.main()
