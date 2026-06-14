"""Testet die Helper-Scripts des `plan-issue-batches`-Skills
(parse_args.py, run_plan.sh).

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
    def test_default_arguments(self) -> None:
        result = run_script(
            HELPERS / "parse_args.py",
            "--repo", "ai-issue-solver",
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["repo"], "ai-issue-solver")
        self.assertEqual(payload["model"], "codex")
        self.assertEqual(payload["base_branch"], "develop")
        self.assertFalse(payload["emit_commands"])
        self.assertEqual(payload["label"], "")

    def test_emit_commands_with_model(self) -> None:
        result = run_script(
            HELPERS / "parse_args.py",
            "--repo", "ai-issue-solver",
            "--emit-commands",
            "--model", "opencode",
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["emit_commands"])
        self.assertEqual(payload["model"], "opencode")

    def test_label_filter(self) -> None:
        result = run_script(
            HELPERS / "parse_args.py",
            "--repo", "ai-issue-solver",
            "--label", "agent/planner",
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["label"], "agent/planner")

    def test_custom_base_branch(self) -> None:
        result = run_script(
            HELPERS / "parse_args.py",
            "--repo", "ai-issue-solver",
            "--base-branch", "main",
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["base_branch"], "main")

    def test_unknown_model_rejected(self) -> None:
        result = run_script(
            HELPERS / "parse_args.py",
            "--repo", "ai-issue-solver",
            "--model", "not-a-model",
        )
        # argparse lehnt unbekannte Modelle über `choices=` ab, bevor
        # die eigene Validator-Logik läuft. Beide Pfade führen zu Exit 2.
        self.assertEqual(result.returncode, 2)
        combined = (result.stdout or "") + (result.stderr or "")
        self.assertTrue(
            "invalid choice" in combined
            or "unbekanntes Modell" in combined
            or "not-a-model" in combined,
            msg=f"Unerwartete Ausgabe: {combined!r}",
        )

    def test_supported_models_accepted(self) -> None:
        for model in (
            "codex",
            "claude",
            "openai",
            "mistral",
            "ollama",
            "mistral-vibe",
            "opencode",
            "openrouter",
            "openrouter_direct",
        ):
            result = run_script(
                HELPERS / "parse_args.py",
                "--repo", "ai-issue-solver",
                "--model", model,
            )
            self.assertEqual(
                result.returncode,
                0,
                msg=f"Modell '{model}' wurde abgelehnt: {result.stderr}",
            )


class TestRunPlanBash(unittest.TestCase):
    def test_help_message_when_no_args(self) -> None:
        result = subprocess.run(
            ["bash", str(HELPERS / "run_plan.sh")],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("Verwendung", result.stderr)

    def test_dry_parse_succeeds(self) -> None:
        """Der Wrapper sollte zumindest parsen und ein gültiges JSON
        aus `parse_args.py` produzieren, ohne tatsächlich
        `plan_issue_batches.py` aufzurufen (das würde GitHub-Calls
        auslösen). Wir prüfen hier nur den Aufruf von `parse_args.py`.
        """
        result = subprocess.run(
            ["python", str(HELPERS / "parse_args.py"), "--repo", "ai-issue-solver"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["repo"], "ai-issue-solver")


if __name__ == "__main__":
    unittest.main()
