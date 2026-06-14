"""End-to-End-Workflow-Test für den model-selection-Skill.

Dieser Test ruft `scripts/model_selection.py` direkt auf, prüft die
Empfehlung anhand reproduzierbarer Eingaben und vergleicht sie mit den
Erwartungen aus `tests/test_model_selection.py`. Zusätzlich wird der
Bash-Wrapper `recommend_model.sh` validiert.
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
# tests/ → model-selection/ → skills/ → .agents/ → <repo-root>
REPO_ROOT = SKILL_ROOT.parents[2]
SCRIPTS_DIR = REPO_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))


class TestHeuristics(unittest.TestCase):
    """Prüft die Heuristik gegen die in tests/test_model_selection.py
    dokumentierten Erwartungen."""

    def setUp(self) -> None:
        os.chdir(REPO_ROOT)

    def test_docs_only_picks_cheap_model(self) -> None:
        from model_selection import select_model

        result = select_model(
            issue_text="Update the documentation for the API",
            labels=["documentation"],
            touched_files=["README.md"],
            repo_type="python",
            max_cost_tier="cheap",
        )
        self.assertEqual(result["category"], "docs-only")
        self.assertEqual(result["cost_tier"], "cheap")
        self.assertIn(result["model"], ["mistral-small", "deepseek-coder:6.7b", "qwen-coder"])

    def test_escalation_after_failure(self) -> None:
        from model_selection import select_model

        result = select_model(
            issue_text="Fix the bug",
            labels=["bug"],
            touched_files=["src/main.py"],
            repo_type="python",
            run_history=[{"model": "mistral-small", "status": "failed"}],
        )
        self.assertIn("Eskalation", result["reason"])
        self.assertNotEqual(result["model"], "mistral-small")

    def test_manual_override_wins(self) -> None:
        from model_selection import select_model

        result = select_model(
            issue_text="Fix the bug",
            labels=["bug"],
            touched_files=["src/main.py"],
            repo_type="python",
            manual_overrides={"model": "claude-sonnet-4"},
        )
        self.assertEqual(result["model"], "claude-sonnet-4")
        self.assertIn("Manuell übersteuert", result["reason"])

    def test_select_model_for_issue_adapter(self) -> None:
        from model_selection import select_model_for_issue

        result = select_model_for_issue(
            issue={"body": "Update the documentation", "labels": ["documentation"]},
            repo_type="python",
            max_cost_tier="cheap",
        )
        self.assertEqual(result["category"], "docs-only")
        self.assertEqual(result["cost_tier"], "cheap")

    def test_high_risk_uses_expensive_tier(self) -> None:
        from model_selection import select_model

        result = select_model(
            issue_text="Refactor the dashboard components",
            labels=["refactor"],
            touched_files=["ui/Dashboard.tsx"],
            repo_type="dashboard",
        )
        self.assertEqual(result["risk"], "high")
        self.assertIn(
            result["model"],
            ["mistral-large", "claude-sonnet-4", "gpt-4o"],
        )


class TestRecommendModelScript(unittest.TestCase):
    """Prüft den Bash-Wrapper `recommend_model.sh`."""

    def setUp(self) -> None:
        os.chdir(REPO_ROOT)

    def test_json_output(self) -> None:
        result = subprocess.run(
            [
                "bash",
                str(SKILL_ROOT / "helpers" / "recommend_model.sh"),
                "--repo-type", "python",
                "--issue-text", "Update the documentation",
                "--max-cost-tier", "cheap",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["category"], "docs-only")
        self.assertEqual(payload["cost_tier"], "cheap")
        self.assertIn("model", payload)
        self.assertIn("fallback_plan", payload)

    def test_text_output(self) -> None:
        result = subprocess.run(
            [
                "bash",
                str(SKILL_ROOT / "helpers" / "recommend_model.sh"),
                "--repo-type", "python",
                "--issue-text", "Update the documentation",
                "--format", "text",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("=== model-selection ===", result.stdout)
        self.assertIn("Model:", result.stdout)
        self.assertIn("Reason:", result.stdout)

    def test_manual_override_via_cli(self) -> None:
        result = subprocess.run(
            [
                "bash",
                str(SKILL_ROOT / "helpers" / "recommend_model.sh"),
                "--repo-type", "python",
                "--issue-text", "Fix the bug",
                "--manual-model", "claude-sonnet-4",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["model"], "claude-sonnet-4")
        self.assertTrue(payload["routing"]["manual_override"])

    def test_invalid_args_propagate_exit_code(self) -> None:
        result = subprocess.run(
            [
                "bash",
                str(SKILL_ROOT / "helpers" / "recommend_model.sh"),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 2)


if __name__ == "__main__":
    unittest.main()
