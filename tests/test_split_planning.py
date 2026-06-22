import unittest
from contextlib import redirect_stdout
from io import StringIO
from unittest.mock import patch

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from split_planning import (  # noqa: E402
    ChildIssue,
    ExecutionWave,
    SplitPlan,
    determine_breadth,
    extract_sections,
    infer_issue_touches,
    propose_child_issues,
    plan_execution_waves,
    create_split_plan,
    render_plan,
    detect_conflicts,
)


class SplitPlanningTests(unittest.TestCase):

    def test_determine_breadth_returns_false_for_small_issue(self):
        is_broad, reasons = determine_breadth(
            "Fix typo in README",
            "Fix the spelling error in the project description.",
            ("documentation",),
        )
        self.assertFalse(is_broad)
        self.assertEqual(len(reasons), 0)

    def test_determine_breadth_returns_true_for_long_issue(self):
        long_body = "\n".join(
            f"- Punkt {i}: Lorem ipsum dolor sit amet consectetur adipiscing elit"
            for i in range(10)
        )
        is_broad, reasons = determine_breadth(
            "Refactor entire solver workflow",
            long_body,
            ("enhancement",),
        )
        self.assertTrue(is_broad)
        self.assertTrue(any("Bullet-Items" in r for r in reasons))

    def test_determine_breadth_detects_keywords(self):
        body = "Diese Issue umfasst sowohl die Dashboard-Logik als auch den Batch-Scheduler."
        is_broad, reasons = determine_breadth(
            "Multiple components update",
            body,
            ("feature",),
        )
        self.assertTrue(is_broad)
        self.assertTrue(any("Breiten-Hinweise" in r for r in reasons))

    def test_determine_breadth_detects_many_sections(self):
        body = "\n".join(
            f"## Abschnitt {i}\nInhalt von Abschnitt {i}.\n- Punkt A\n- Punkt B"
            for i in range(3)
        )
        is_broad, reasons = determine_breadth(
            "Broad feature with many sections and points",
            body,
            (),
        )
        self.assertTrue(is_broad)

    def test_extract_sections_returns_headings_and_content(self):
        body = "## Erster Abschnitt\nInhalt A.\n## Zweiter Abschnitt\nInhalt B."
        sections = extract_sections(body)
        self.assertEqual(len(sections), 2)
        self.assertEqual(sections[0][0], "Erster Abschnitt")
        self.assertEqual(sections[1][0], "Zweiter Abschnitt")

    def test_extract_sections_without_headings(self):
        body = "Nur ein Fliesstext ohne Ueberschriften."
        sections = extract_sections(body)
        self.assertEqual(len(sections), 1)
        self.assertEqual(sections[0][0], "Einleitung")

    def test_extract_sections_handles_varying_heading_levels(self):
        body = "# Ebene 1\nInhalt.\n## Ebene 2\nMehr Inhalt.\n### Ebene 3\nNoch mehr."
        sections = extract_sections(body)
        self.assertEqual(len(sections), 3)

    def test_infer_issue_touches_from_code_spans(self):
        touches = infer_issue_touches(
            "Aendere `scripts/solve_issues.py` und `tests/test_solve_issues.py`."
        )
        self.assertIn("scripts/solve_issues.py", touches)
        self.assertIn("tests/test_solve_issues.py", touches)

    def test_infer_issue_touches_filters_urls(self):
        touches = infer_issue_touches(
            "Siehe https://example.com und `scripts/dashboard.py`"
        )
        self.assertIn("scripts/dashboard.py", touches)
        self.assertNotIn("https://example.com", touches)

    def test_propose_child_issues_creates_children_from_sections(self):
        body = "## Dashboard\nAendere das Status-Dashboard.\n## Batch\nOptimiere den Batch-Scheduler."
        children = propose_child_issues(
            "Refactor workflow", body, ("automation",)
        )
        self.assertEqual(len(children), 2)
        self.assertIn("Dashboard", children[0].title)
        self.assertIn("Batch", children[1].title)

    def test_propose_child_issues_falls_back_to_single_child(self):
        body = "Ein einfaches Issue ohne Unterteilung."
        children = propose_child_issues(
            "Simple fix", body, ()
        )
        self.assertEqual(len(children), 1)
        self.assertIn("Simple fix", children[0].title)

    def test_propose_child_issues_preserves_labels(self):
        body = "## Config\nAendere die config.\n## Tests\nFuege Tests hinzu."
        children = propose_child_issues(
            "Update config and tests", body, ("automation", "ai-generated")
        )
        for child in children:
            self.assertIn("automation", child.labels)

    def test_detect_conflicts_finds_same_file(self):
        children = (
            ChildIssue(None, "A", "", (), ("scripts/dashboard.py",), "opencode", 1),
            ChildIssue(None, "B", "", (), ("scripts/dashboard.py",), "opencode", 2),
        )
        conflicts = detect_conflicts(children)
        self.assertEqual(len(conflicts), 1)
        self.assertIn("gleiche Datei", conflicts[0][2])

    def test_detect_conflicts_finds_directory_conflict(self):
        children = (
            ChildIssue(None, "A", "", (), ("scripts/dashboard.py",), "opencode", 1),
            ChildIssue(None, "B", "", (), ("tests/",), "opencode", 2),
            ChildIssue(None, "C", "", (), ("scripts/status.py",), "opencode", 3),
        )
        conflicts = detect_conflicts(children)
        conflict_files = {c[2] for c in conflicts}
        self.assertTrue(any("scripts" in c for c in conflict_files))

    def test_detect_conflicts_no_conflicts(self):
        children = (
            ChildIssue(None, "A", "", (), ("scripts/dashboard.py",), "opencode", 1),
            ChildIssue(None, "B", "", (), ("tests/",), "opencode", 2),
        )
        conflicts = detect_conflicts(children)
        self.assertEqual(len(conflicts), 0)

    def test_plan_execution_waves_separates_conflicting_issues(self):
        children = (
            ChildIssue(None, "Dashboard A", "", ("scripts/dashboard.py",), ("scripts/dashboard.py",), "opencode", 1),
            ChildIssue(None, "Tests", "", (), ("tests/",), "opencode", 2),
            ChildIssue(None, "Dashboard B", "", ("scripts/dashboard.py",), ("scripts/dashboard.py",), "opencode", 3),
        )
        waves = plan_execution_waves(children)
        self.assertGreaterEqual(len(waves), 1)
        all_children_in_waves = sum(len(w.issues) for w in waves)
        self.assertEqual(all_children_in_waves, 3)

    def test_create_split_plan_for_narrow_issue(self):
        plan = create_split_plan(
            "demo", 1, "Fix typo", "Fix the spelling error.", ("documentation",),
        )
        self.assertFalse(plan.is_broad)
        self.assertEqual(len(plan.child_issues), 0)

    def test_create_split_plan_for_broad_issue(self):
        body = "\n".join(
            f"- Punkt {i}: Lorem ipsum dolor sit amet consectetur"
            for i in range(15)
        )
        plan = create_split_plan(
            "demo", 2, "Broad refactor", body, ("enhancement",),
        )
        self.assertTrue(plan.is_broad)
        self.assertGreater(len(plan.breadth_reasons), 0)

    def test_render_plan_includes_parent_info(self):
        plan = create_split_plan(
            "demo", 42, "Test issue", "Small body.", (),
        )
        output = render_plan(plan)
        self.assertIn("#42", output)
        self.assertIn("Test issue", output)

    def test_render_plan_for_broad_issue_includes_child_info(self):
        body = "## Dashboard\nAendere das Dashboard.\n" + "\n".join(
            f"- Item {i}" for i in range(12)
        )
        plan = create_split_plan(
            "demo", 7, "Big update", body, ("enhancement",),
        )
        output = render_plan(plan, emit_command=True)
        self.assertIn("BROAD ISSUE erkannt", output)
        self.assertIn("Child-Issues", output)
        self.assertIn("Ausführungswellen", output)

    def test_render_plan_emit_command_includes_create_commands(self):
        body = "## Dashboard\n" + "\n".join(f"- Step {i}" for i in range(12))
        plan = create_split_plan(
            "demo", 10, "Multi-step", body, (),
        )
        output = render_plan(plan, emit_command=True)
        self.assertIn("gh issue create", output)

    def test_render_plan_for_broad_issue_contains_warning(self):
        body = "\n".join(f"- Punkt {i}" for i in range(12))
        plan = create_split_plan(
            "demo", 5, "Broad issue", body, ("feature",),
        )
        output = render_plan(plan)
        self.assertIn("BROAD ISSUE", output)
        self.assertIn("direkt erhalten", output)

    def test_create_split_plan_includes_waves(self):
        body = "## Dashboard\nInhalt.\n## Tests\nInhalt.\n" + "\n".join(
            f"- Item {i}" for i in range(12)
        )
        plan = create_split_plan(
            "demo", 3, "Big refactor", body, ("enhancement",),
        )
        self.assertTrue(plan.is_broad)
        self.assertGreater(plan.total_waves, 0)

    def test_infer_issue_touches_with_file_references(self):
        touches = infer_issue_touches(
            "Betroffen: scripts/split_planning.py, tests/test_split_planning.py"
        )
        self.assertIn("scripts/split_planning.py", touches)
        self.assertIn("tests/test_split_planning.py", touches)

    def test_determine_breadth_with_epic_label(self):
        is_broad, reasons = determine_breadth(
            "Small change", "Just a small fix.", ("epic",),
        )
        self.assertFalse(is_broad)
        self.assertEqual(len(reasons), 1)
        self.assertTrue(any("Breiten-Labels" in r for r in reasons))

    def test_detect_conflicts_respects_no_overlap(self):
        children = (
            ChildIssue(None, "A", "", (), ("docs/README.md",), "opencode", 1),
            ChildIssue(None, "B", "", (), ("tests/",), "opencode", 2),
            ChildIssue(None, "C", "", (), ("scripts/",), "opencode", 3),
        )
        conflicts = detect_conflicts(children)
        self.assertEqual(len(conflicts), 0)


if __name__ == "__main__":
    unittest.main()
