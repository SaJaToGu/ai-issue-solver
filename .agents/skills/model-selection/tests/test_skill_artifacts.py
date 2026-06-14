"""Prüft, dass alle vom model-selection-Skill erwarteten Dateien vorhanden
und nicht leer sind.

Diese Tests sind read-only und benötigen keinen GitHub-Token oder
KI-Worker. Sie sind ein Skill-spezifisches Pendant zu
`tests/test_model_selection.py`.
"""

from __future__ import annotations

import unittest
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
# tests/ → model-selection/ → skills/ → .agents/ → <repo-root>
REPO_ROOT = SKILL_ROOT.parents[2]
if not (REPO_ROOT / "scripts" / "model_selection.py").exists():
    # Defensive fallback, falls der Test verschoben wird.
    REPO_ROOT = SKILL_ROOT.parents[3]
SCRIPTS_MODEL_SELECTION = REPO_ROOT / "scripts" / "model_selection.py"

EXPECTED_FILES = [
    SKILL_ROOT / "SKILL.md",
    SKILL_ROOT / "workflow.md",
    SKILL_ROOT / "examples" / "README.md",
    SKILL_ROOT / "examples" / "01_auto_select_python_docs.md",
    SKILL_ROOT / "examples" / "02_escalate_after_failure.md",
    SKILL_ROOT / "examples" / "03_manual_override.md",
    SKILL_ROOT / "examples" / "04_history_check.md",
    SKILL_ROOT / "examples" / "05_integration_with_solver.md",
    SKILL_ROOT / "tests" / "README.md",
    SKILL_ROOT / "tests" / "run_skill_tests.sh",
    SKILL_ROOT / "tests" / "test_skill_artifacts.py",
    SKILL_ROOT / "tests" / "test_helpers.py",
    SKILL_ROOT / "tests" / "test_skill_workflow.py",
    SKILL_ROOT / "helpers" / "parse_args.py",
    SKILL_ROOT / "helpers" / "parse_args.sh",
    SKILL_ROOT / "helpers" / "recommend_model.sh",
    SKILL_ROOT / "helpers" / "history_check.sh",
]

EXPECTED_FRONT_MATTER = {
    SKILL_ROOT / "SKILL.md": ("name:", "description:"),
}

EXPECTED_REFERENCES = {
    SKILL_ROOT / "SKILL.md": "scripts/model_selection.py",
    SKILL_ROOT / "workflow.md": "scripts/model_selection.py",
}

FORBIDDEN_TODO_PLACEHOLDERS = ("TODO ", "FIXME", "XXX ")


class TestSkillArtifacts(unittest.TestCase):
    def test_repo_root_exists(self) -> None:
        self.assertTrue(REPO_ROOT.exists(), f"Repo-Root fehlt: {REPO_ROOT}")

    def test_scripts_model_selection_exists(self) -> None:
        self.assertTrue(
            SCRIPTS_MODEL_SELECTION.exists(),
            f"scripts/model_selection.py fehlt: {SCRIPTS_MODEL_SELECTION}",
        )

    def test_all_expected_files_exist(self) -> None:
        missing = [str(path) for path in EXPECTED_FILES if not path.exists()]
        self.assertFalse(missing, f"Fehlende Dateien: {missing}")

    def test_all_expected_files_non_empty(self) -> None:
        empty = [
            str(path)
            for path in EXPECTED_FILES
            if path.exists() and path.stat().st_size == 0
        ]
        self.assertFalse(empty, f"Leere Dateien: {empty}")

    def test_skill_md_has_front_matter(self) -> None:
        for path, keys in EXPECTED_FRONT_MATTER.items():
            text = path.read_text(encoding="utf-8")
            self.assertTrue(text.startswith("---"), f"{path} startet nicht mit ---")
            for needle in keys:
                self.assertIn(needle, text, f"{path} fehlt Schlüssel '{needle}'")

    def test_skill_md_mentions_model_selection_script(self) -> None:
        skill_md = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("scripts/model_selection.py", skill_md)
        self.assertIn("recommend_model.sh", skill_md)
        self.assertIn("parse_args.py", skill_md)
        self.assertIn("model-selection", skill_md)

    def test_skill_md_lists_routing_signals(self) -> None:
        skill_md = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
        for signal in ("--language", "--task-type", "--repo-type", "--issue-text", "--manual-model"):
            self.assertIn(signal, skill_md, f"SKILL.md erwähnt {signal} nicht")

    def test_workflow_documents_escalation(self) -> None:
        workflow_text = (SKILL_ROOT / "workflow.md").read_text(encoding="utf-8")
        self.assertIn("MODEL_ESCALATION", workflow_text)
        self.assertIn("run_history", workflow_text)

    def test_no_todo_placeholders(self) -> None:
        test_self = Path(__file__).resolve()
        for path in EXPECTED_FILES:
            if path.suffix not in {".md", ".py", ".sh"}:
                continue
            if path.resolve() == test_self:
                # Diese Test-Datei selbst enthält die Platzhalter als Konstanten.
                continue
            text = path.read_text(encoding="utf-8")
            for placeholder in FORBIDDEN_TODO_PLACEHOLDERS:
                self.assertNotIn(
                    placeholder,
                    text,
                    f"{path} enthält Platzhalter '{placeholder}'",
                )

    def test_helper_scripts_executable(self) -> None:
        executable = [
            SKILL_ROOT / "helpers" / "parse_args.sh",
            SKILL_ROOT / "helpers" / "parse_args.py",
            SKILL_ROOT / "helpers" / "recommend_model.sh",
            SKILL_ROOT / "helpers" / "history_check.sh",
            SKILL_ROOT / "tests" / "run_skill_tests.sh",
        ]
        for path in executable:
            if not path.exists():
                continue
            mode = path.stat().st_mode
            self.assertTrue(
                mode & 0o111,
                f"{path} ist nicht ausführbar (Modus: {oct(mode)})",
            )

    def test_examples_reference_skill_root(self) -> None:
        for example in (SKILL_ROOT / "examples").glob("*.md"):
            text = example.read_text(encoding="utf-8")
            self.assertTrue(
                "recommend_model.sh" in text or "model_selection" in text,
                f"{example} referenziert weder recommend_model.sh noch model_selection",
            )


if __name__ == "__main__":
    unittest.main()
