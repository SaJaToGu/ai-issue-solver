#!/usr/bin/env python3
"""
Tests für die automatische Modellauswahl (model_selection.py).

Abgedeckte Szenarien:
- Issue-Klassifizierung nach Text, Labels und Dateien
- Risiko- und Stärke-Schätzung
- Modellauswahl mit Kostenfilter und Eskalation
- Manuelle Übersteuerungen
- Integration in solve_issues.py
"""

from __future__ import annotations
import unittest
from unittest.mock import patch
from model_selection import (
    classify_issue,
    estimate_risk_and_strength,
    select_model,
    select_model_for_issue,
    ISSUE_CATEGORIES,
    RISK_MAP,
    STRENGTH_MAP,
    COST_TIERS,
)


class TestModelSelection(unittest.TestCase):
    """Tests für die Modellauswahl-Logik."""

    def test_classify_issue_by_labels(self):
        """Issue-Klassifizierung basierend auf Labels."""
        issue_text = "Fix the bug in the docs"
        labels = ["documentation", "good first issue"]
        files = []
        repo_type = "python"
        
        category = classify_issue(issue_text, labels, files, repo_type)
        self.assertEqual(category, "docs-only")

    def test_classify_issue_by_files(self):
        """Issue-Klassifizierung basierend auf betroffenen Dateien."""
        issue_text = "Update the README"
        labels = []
        files = ["README.md", "docs/guide.md"]
        repo_type = "python"
        
        category = classify_issue(issue_text, labels, files, repo_type)
        self.assertEqual(category, "docs-only")

    def test_classify_issue_by_keywords(self):
        """Issue-Klassifizierung basierend auf Keywords im Text."""
        issue_text = "The Python unittest is failing"
        labels = []
        files = []
        repo_type = "python"
        
        category = classify_issue(issue_text, labels, files, repo_type)
        self.assertEqual(category, "tests")

    def test_classify_issue_fallback_to_repo_type(self):
        """Fallback auf Repo-Typ, wenn keine spezifische Kategorie passt."""
        issue_text = "General improvement"
        labels = []
        files = []
        repo_type = "r"
        
        category = classify_issue(issue_text, labels, files, repo_type)
        self.assertEqual(category, "r")

    def test_estimate_risk_and_strength(self):
        """Risiko- und Stärke-Schätzung für Issue-Kategorien."""
        risk, strength_tier = estimate_risk_and_strength("docs-only")
        self.assertEqual(risk, "low")
        self.assertIn("mistral-small", strength_tier)
        
        risk, strength_tier = estimate_risk_and_strength("dashboard/ui")
        self.assertEqual(risk, "high")
        self.assertIn("mistral-large", strength_tier)

    def test_select_model_cheap_cost_tier(self):
        """Modellauswahl mit Kostenfilter (cheap)."""
        result = select_model(
            issue_text="Update the README",
            labels=["documentation"],
            touched_files=["README.md"],
            repo_type="python",
            max_cost_tier="cheap",
        )
        self.assertIn(result["cost_tier"], ["cheap"])
        self.assertIn(result["model"], ["mistral-small", "deepseek-coder:6.7b", "qwen-coder"])

    def test_select_model_manual_override(self):
        """Manuelle Übersteuerung des Modells."""
        result = select_model(
            issue_text="Fix the bug",
            labels=["bug"],
            touched_files=["src/main.py"],
            repo_type="python",
            manual_overrides={"model": "claude-sonnet-4"},
        )
        self.assertEqual(result["model"], "claude-sonnet-4")
        self.assertIn("Manuell übersteuert", result["reason"])

    def test_select_model_escalation_after_failure(self):
        """Eskalation nach fehlgeschlagenem Run."""
        run_history = [
            {
                "model": "mistral-small",
                "status": "failed",
            }
        ]
        result = select_model(
            issue_text="Fix the bug",
            labels=["bug"],
            touched_files=["src/main.py"],
            repo_type="python",
            run_history=run_history,
        )
        self.assertNotEqual(result["model"], "mistral-small")
        self.assertIn("Eskalation", result["reason"])

    def test_select_model_for_issue_integration(self):
        """Integration mit solve_issues.py (Mock-Issue)."""
        mock_issue = {
            "body": "Update the documentation",
            "labels": ["documentation"],
        }
        result = select_model_for_issue(
            issue=mock_issue,
            repo_type="python",
            max_cost_tier="cheap",
        )
        self.assertEqual(result["category"], "docs-only")
        self.assertIn(result["model"], ["mistral-small", "deepseek-coder:6.7b", "qwen-coder"])

    def test_issue_categories_coverage(self):
        """Prüft, dass alle Issue-Kategorien in den Maps abgedeckt sind."""
        for category in ISSUE_CATEGORIES:
            self.assertIn(category, RISK_MAP)
            risk = RISK_MAP[category]
            self.assertIn(risk, STRENGTH_MAP)

    def test_cost_tiers_coverage(self):
        """Prüft, dass alle Modelle in den Kosten-Tiers abgedeckt sind."""
        for models in STRENGTH_MAP.values():
            for model in models:
                self.assertIn(model, COST_TIERS)


if __name__ == "__main__":
    unittest.main()