"""Prüft, dass alle vom solver-reporting-Skill erwarteten Dateien
vorhanden und nicht leer sind.

Diese Tests sind read-only und benötigen keinen GitHub-Token.
"""

from __future__ import annotations

import unittest
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = SKILL_ROOT.parents[3]

EXPECTED_FILES = [
    SKILL_ROOT / "SKILL.md",
    SKILL_ROOT / "workflow.md",
    SKILL_ROOT / "examples" / "README.md",
    SKILL_ROOT / "examples" / "01_inspect_single_run.md",
    SKILL_ROOT / "examples" / "02_diagnose_opencode.md",
    SKILL_ROOT / "examples" / "03_aggregate_scorecards.md",
    SKILL_ROOT / "examples" / "04_cleanup_worktrees.md",
    SKILL_ROOT / "examples" / "05_heartbeat.md",
    SKILL_ROOT / "examples" / "06_run_outcome_distribution.md",
    SKILL_ROOT / "tests" / "README.md",
    SKILL_ROOT / "tests" / "run_skill_tests.sh",
    SKILL_ROOT / "tests" / "test_skill_artifacts.py",
    SKILL_ROOT / "tests" / "test_helpers.py",
    SKILL_ROOT / "tests" / "test_skill_workflow.py",
    SKILL_ROOT / "helpers" / "aggregate_runs.py",
    SKILL_ROOT / "helpers" / "diagnose_opencode.py",
    SKILL_ROOT / "helpers" / "format_heartbeat.py",
    SKILL_ROOT / "helpers" / "cleanup_worktrees.sh",
]

EXPECTED_FRONT_MATTER = {
    SKILL_ROOT / "SKILL.md": ("name:", "description:"),
}

EXPECTED_REFERENCES = {
    SKILL_ROOT / "SKILL.md": "scripts/solver_reporting.py",
    SKILL_ROOT / "workflow.md": "scripts/solver_reporting.py",
}

FORBIDDEN_TODO_PLACEHOLDERS = ("TODO ", "FIXME", "XXX ")


class TestSkillArtifacts(unittest.TestCase):
    def test_repo_root_exists(self) -> None:
        self.assertTrue(REPO_ROOT.exists(), f"Repo-Root fehlt: {REPO_ROOT}")

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

    def test_skill_md_mentions_reporting_script(self) -> None:
        skill_md = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("scripts/solver_reporting.py", skill_md)
        self.assertIn("aggregate_runs.py", skill_md)
        self.assertIn("diagnose_opencode.py", skill_md)
        self.assertIn("cleanup_worktrees.sh", skill_md)

    def test_no_todo_placeholders(self) -> None:
        test_self = Path(__file__).resolve()
        for path in EXPECTED_FILES:
            if path.suffix not in {".md", ".py", ".sh"}:
                continue
            if path.resolve() == test_self:
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
            SKILL_ROOT / "helpers" / "aggregate_runs.py",
            SKILL_ROOT / "helpers" / "diagnose_opencode.py",
            SKILL_ROOT / "helpers" / "format_heartbeat.py",
            SKILL_ROOT / "helpers" / "cleanup_worktrees.sh",
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

    def test_examples_reference_skill_helpers(self) -> None:
        required_refs = {
            "01_inspect_single_run.md": ("aggregate_runs.py",),
            "02_diagnose_opencode.md": ("diagnose_opencode.py",),
            "03_aggregate_scorecards.md": ("aggregate_runs.py",),
            "04_cleanup_worktrees.md": ("cleanup_worktrees.sh",),
            "05_heartbeat.md": ("format_heartbeat.py",),
            "06_run_outcome_distribution.md": ("aggregate_runs.py",),
        }
        for filename, needles in required_refs.items():
            path = SKILL_ROOT / "examples" / filename
            text = path.read_text(encoding="utf-8")
            for needle in needles:
                self.assertIn(
                    needle,
                    text,
                    f"{path} referenziert '{needle}' nicht",
                )

    def test_workflow_md_mentions_skill(self) -> None:
        workflow_text = (SKILL_ROOT / "workflow.md").read_text(encoding="utf-8")
        self.assertIn("scripts/solver_reporting.py", workflow_text)
        self.assertIn("provider_scorecard", workflow_text)
        self.assertIn("run_outcome", workflow_text)


if __name__ == "__main__":
    unittest.main()
