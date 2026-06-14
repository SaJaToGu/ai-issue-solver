"""Testet die Helper-Scripts des model-selection-Skills.

Diese Tests sind unabhängig von einem GitHub-Token oder KI-Worker. Sie
rufen `parse_args.py` / `parse_args.sh` mit gültigen und ungültigen
Argumenten auf und prüfen die JSON-Ausgabe.
"""

from __future__ import annotations

import json
import os
import subprocess
import unittest
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
HELPERS = SKILL_ROOT / "helpers"
# tests/ → model-selection/ → skills/ → .agents/ → <repo-root>
REPO_ROOT = SKILL_ROOT.parents[2]


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
    def test_minimal_valid_arguments(self) -> None:
        result = run_script(
            HELPERS / "parse_args.py",
            "--repo-type", "python",
            "--issue-text", "Refactor the test runner",
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["repo_type"], "python")
        self.assertEqual(payload["issue_text"], "Refactor the test runner")
        self.assertEqual(payload["max_cost_tier"], "expensive")
        self.assertEqual(payload["format"], "json")

    def test_labels_and_files_parsed(self) -> None:
        result = run_script(
            HELPERS / "parse_args.py",
            "--repo-type", "r",
            "--labels", "documentation, good first issue",
            "--touched-files", "README.md,docs/index.md",
            "--max-cost-tier", "cheap",
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["labels"], ["documentation", "good first issue"])
        self.assertEqual(payload["touched_files"], ["README.md", "docs/index.md"])
        self.assertEqual(payload["max_cost_tier"], "cheap")

    def test_invalid_cost_tier_rejected(self) -> None:
        result = run_script(
            HELPERS / "parse_args.py",
            "--repo-type", "python",
            "--max-cost-tier", "free",
        )
        self.assertEqual(result.returncode, 2)

    def test_invalid_task_type_rejected(self) -> None:
        result = run_script(
            HELPERS / "parse_args.py",
            "--repo-type", "python",
            "--task-type", "magic",
        )
        self.assertEqual(result.returncode, 2)
        payload = json.loads(result.stdout)
        self.assertFalse(payload["ok"])
        self.assertTrue(any("--task-type" in err for err in payload["errors"]))

    def test_negative_issue_rejected(self) -> None:
        result = run_script(
            HELPERS / "parse_args.py",
            "--repo-type", "python",
            "--issue", "-1",
        )
        self.assertEqual(result.returncode, 2)
        payload = json.loads(result.stdout)
        self.assertFalse(payload["ok"])
        self.assertTrue(any("--issue" in err for err in payload["errors"]))

    def test_empty_arguments_rejected(self) -> None:
        result = run_script(HELPERS / "parse_args.py")
        self.assertEqual(result.returncode, 2)
        payload = json.loads(result.stdout)
        self.assertFalse(payload["ok"])
        self.assertTrue(any("Mindestens eine Quelle" in err for err in payload["errors"]))

    def test_manual_model_alone_satisfies_source(self) -> None:
        result = run_script(
            HELPERS / "parse_args.py",
            "--manual-model", "claude-sonnet-4",
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["manual_model"], "claude-sonnet-4")

    def test_format_choices(self) -> None:
        for fmt in ("json", "text"):
            result = run_script(
                HELPERS / "parse_args.py",
                "--repo-type", "python",
                "--format", fmt,
            )
            self.assertEqual(result.returncode, 0, msg=result.stderr)
            self.assertEqual(json.loads(result.stdout)["format"], fmt)


class TestParseArgsBash(unittest.TestCase):
    def test_valid_arguments(self) -> None:
        result = subprocess.run(
            ["bash", str(HELPERS / "parse_args.sh"), "--repo-type", "python", "--issue", "3"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("REPO_TYPE=python", result.stdout)
        self.assertIn("ISSUE=3", result.stdout)
        self.assertIn("MAX_COST_TIER=expensive", result.stdout)

    def test_missing_source_rejected(self) -> None:
        result = subprocess.run(
            ["bash", str(HELPERS / "parse_args.sh")],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("Mindestens eine Quelle", result.stderr)

    def test_invalid_cost_tier_rejected(self) -> None:
        result = subprocess.run(
            ["bash", str(HELPERS / "parse_args.sh"), "--repo-type", "python",
             "--max-cost-tier", "free"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("max-cost-tier", result.stderr)

    def test_invalid_format_rejected(self) -> None:
        result = subprocess.run(
            ["bash", str(HELPERS / "parse_args.sh"), "--repo-type", "python",
             "--format", "yaml"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("--format", result.stderr)

    def test_max_cost_alias_overrides_default(self) -> None:
        result = subprocess.run(
            ["bash", str(HELPERS / "parse_args.sh"), "--repo-type", "python",
             "--max-cost", "cheap"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("MAX_COST_TIER=cheap", result.stdout)


class TestHistoryCheck(unittest.TestCase):
    def test_history_check_requires_one_arg(self) -> None:
        result = subprocess.run(
            ["bash", str(HELPERS / "history_check.sh")],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 2)

    def test_history_check_rejects_non_numeric_issue(self) -> None:
        result = subprocess.run(
            ["bash", str(HELPERS / "history_check.sh"), "abc"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 2)

    def test_history_check_no_entries_for_issue(self) -> None:
        """Wenn reports/runs existiert, aber kein Eintrag zur Issue-Nummer
        vorliegt, meldet das Script das explizit."""
        runs_dir = REPO_ROOT / "reports" / "runs"
        runs_dir.mkdir(parents=True, exist_ok=True)
        result = subprocess.run(
            ["bash", str(HELPERS / "history_check.sh"), "999999"],
            capture_output=True,
            text=True,
            check=False,
        )
        # Exit 0 mit "Keine metadata.json für Issue #…"
        self.assertIn(result.returncode, (0, 1))
        combined = result.stdout + result.stderr
        self.assertTrue(
            "Keine metadata.json" in combined or "existiert nicht" in combined,
            f"unerwartete Ausgabe: {combined!r}",
        )


if __name__ == "__main__":
    unittest.main()
