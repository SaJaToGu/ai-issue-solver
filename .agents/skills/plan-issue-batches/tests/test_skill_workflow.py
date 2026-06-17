"""End-to-End-Workflow-Test für den `plan-issue-batches`-Skill.

Dieser Test ruft KEINE GitHub-API auf. Er prüft die zentralen
Planungs-Funktionen aus `scripts/plan_issue_batches.py` mit synthetischen
Issues und stellt sicher, dass Priorisierung, Gruppierung und
Ausführungsplanung wie erwartet zusammenspielen.
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPTS_DIR = REPO_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))


def make_issue(repo: str, number: int, title: str, touches, body: str = "", labels=()):
    from plan_issue_batches import PlannedIssue
    return PlannedIssue(
        repo=repo,
        number=number,
        title=title,
        body=body,
        labels=tuple(labels),
        touches=tuple(touches),
    )


class TestPlanWorkflow(unittest.TestCase):
    def test_plan_waves_groups_non_conflicting_issues(self) -> None:
        from plan_issue_batches import plan_waves

        issues = [
            make_issue("demo", 1, "A", ("scripts/solve_issues.py",)),
            make_issue("demo", 2, "B", ("README.md",)),
        ]
        waves = plan_waves(issues)
        self.assertEqual(len(waves), 1)
        self.assertEqual([i.number for i in waves[0].issues], [1, 2])

    def test_plan_waves_separates_conflicting_issues(self) -> None:
        from plan_issue_batches import plan_waves

        issues = [
            make_issue("demo", 1, "A", ("scripts/status_dashboard.py",)),
            make_issue("demo", 2, "B", ("scripts/solve_issues.py",)),
            make_issue("demo", 3, "C", ("scripts/status_dashboard.py",)),
        ]
        waves = plan_waves(issues)
        self.assertEqual(len(waves), 2)
        # Erste Welle: 1 + 2 (konfliktfrei zueinander)
        self.assertEqual([i.number for i in waves[0].issues], [1, 2])
        # Zweite Welle: 3 (Konflikt mit 1)
        self.assertEqual([i.number for i in waves[1].issues], [3])

    def test_render_plan_includes_emit_commands(self) -> None:
        from plan_issue_batches import plan_waves, render_plan

        issues = [
            make_issue("ai-issue-solver", 10, "X", ("README.md",)),
            make_issue("ai-issue-solver", 11, "Y", ("scripts/solve_issues.py",)),
        ]
        waves = plan_waves(issues)
        output = render_plan(waves, emit_commands=True, model="codex", base_branch="develop")
        self.assertIn("#10 - X", output)
        self.assertIn("#11 - Y", output)
        self.assertIn("python scripts/solve_issues_batch.py", output)
        self.assertIn("--model codex", output)
        self.assertIn("--base-branch develop", output)
        self.assertIn("--issue 10", output)
        self.assertIn("--issue 11", output)
        self.assertIn("--workers 2", output)

    def test_render_plan_without_emit_commands(self) -> None:
        from plan_issue_batches import plan_waves, render_plan

        issues = [
            make_issue("demo", 1, "A", ("README.md",)),
            make_issue("demo", 2, "B", ("scripts/solve_issues.py",)),
        ]
        waves = plan_waves(issues)
        output = render_plan(waves, emit_commands=False, model="codex", base_branch="develop")
        self.assertNotIn("Command:", output)
        self.assertNotIn("python scripts/solve_issues_batch.py", output)

    def test_batch_command_uses_repo_and_workers(self) -> None:
        from plan_issue_batches import batch_command_for_wave, plan_waves

        issues = [
            make_issue("ai-issue-solver", 7, "One", ("README.md",)),
            make_issue("ai-issue-solver", 8, "Two", ("scripts/solve_issues.py",)),
        ]
        wave = plan_waves(issues)[0]
        cmd = batch_command_for_wave(wave, model="opencode", base_branch="main")
        self.assertIn("--model opencode", cmd)
        self.assertIn("--repo ai-issue-solver", cmd)
        self.assertIn("--base-branch main", cmd)
        self.assertIn("--issue 7", cmd)
        self.assertIn("--issue 8", cmd)
        self.assertIn("--workers 2", cmd)

    def test_batch_command_without_base_branch(self) -> None:
        from plan_issue_batches import batch_command_for_wave, plan_waves

        issues = [
            make_issue("demo", 1, "A", ("README.md",)),
        ]
        wave = plan_waves(issues)[0]
        cmd = batch_command_for_wave(wave, model="codex", base_branch=None)
        self.assertNotIn("--base-branch", cmd)
        self.assertIn("--workers 1", cmd)

    def test_infer_issue_touches_uses_explicit_hints(self) -> None:
        from plan_issue_batches import infer_issue_touches

        touches = infer_issue_touches(
            "Custom title",
            "Touches: `scripts/foo.py`, `tests/test_foo.py`",
            (),
        )
        self.assertIn("scripts/foo.py", touches)
        self.assertIn("tests/test_foo.py", touches)

    def test_infer_issue_touches_uses_keyword_fallback(self) -> None:
        from plan_issue_batches import infer_issue_touches

        touches = infer_issue_touches(
            "Improve the status dashboard",
            "Lifecycle labels are missing",
            (),
        )
        self.assertIn("scripts/status_dashboard.py", touches)
        self.assertIn("tests/test_status_dashboard.py", touches)

    def test_infer_issue_touches_default_fallback(self) -> None:
        from plan_issue_batches import infer_issue_touches

        touches = infer_issue_touches(
            "Random unclear title",
            "Body without keywords or touches hint",
            (),
        )
        self.assertIn("README.md", touches)
        self.assertIn("scripts/", touches)


class TestSeparationReason(unittest.TestCase):
    def test_separation_reason_lists_conflict(self) -> None:
        from plan_issue_batches import (
            PlannedIssue,
            PlannedWave,
            plan_waves,
            separation_reason,
        )

        wave1 = PlannedWave(
            (PlannedIssue("demo", 1, "A", "", (), ("scripts/foo.py",)),),
            ("scripts/foo.py",),
        )
        issue2 = PlannedIssue("demo", 2, "B", "", (), ("scripts/foo.py",))
        reason = separation_reason(issue2, [wave1])
        self.assertIn("Welle 1", reason)
        self.assertIn("scripts/foo.py", reason)

    def test_separation_reason_no_conflict(self) -> None:
        from plan_issue_batches import (
            PlannedIssue,
            PlannedWave,
            separation_reason,
        )

        wave1 = PlannedWave(
            (PlannedIssue("demo", 1, "A", "", (), ("scripts/foo.py",)),),
            ("scripts/foo.py",),
        )
        issue2 = PlannedIssue("demo", 2, "B", "", (), ("scripts/bar.py",))
        reason = separation_reason(issue2, [wave1])
        self.assertIn("keine Ueberschneidung", reason)


if __name__ == "__main__":
    unittest.main()
