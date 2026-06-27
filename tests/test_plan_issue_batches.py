import unittest
from contextlib import redirect_stdout
from io import StringIO
from unittest.mock import patch

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from plan_issue_batches import (  # noqa: E402
    MODEL_SOURCE_DEFAULT,
    MODEL_SOURCE_CLI,
    PlannedIssue,
    batch_command_for_wave,
    extract_explicit_touches,
    infer_issue_touches,
    issue_from_github,
    main,
    plan_waves,
    render_plan,
    touches_conflict,
)


class PlanIssueBatchesTests(unittest.TestCase):
    def make_issue(self, number, title, touches, repo="demo"):
        return PlannedIssue(
            repo=repo,
            number=number,
            title=title,
            body="",
            labels=(),
            touches=tuple(touches),
        )

    def test_extract_explicit_touches_from_issue_body(self):
        touches = extract_explicit_touches(
            "Touches: `scripts/status_dashboard.py`, tests/test_status_dashboard.py"
        )

        self.assertEqual(
            touches,
            ("scripts/status_dashboard.py", "tests/test_status_dashboard.py"),
        )

    def test_infer_issue_touches_from_keywords_and_labels(self):
        touches = infer_issue_touches(
            "Show recovered failed runs in dashboard",
            "Improve status dashboard lifecycle labels",
            ("workflow",),
        )

        self.assertIn("scripts/status_dashboard.py", touches)
        self.assertIn("tests/test_status_dashboard.py", touches)

    def test_issue_from_github_uses_labels_and_touches(self):
        issue = issue_from_github(
            "demo",
            {
                "number": 64,
                "title": "Add a local conflict-aware issue scheduler",
                "body": "Touches: `scripts/plan_issue_batches.py`",
                "labels": [{"name": "automation"}],
            },
        )

        self.assertEqual(issue.number, 64)
        self.assertIn("automation", issue.labels)
        self.assertIn("scripts/plan_issue_batches.py", issue.touches)

    def test_touches_conflict_matches_directories_and_files(self):
        conflicts = touches_conflict(("tests/test_status_dashboard.py",), ("tests/",))

        self.assertEqual(conflicts, ("tests/test_status_dashboard.py",))

    def test_plan_waves_separates_overlapping_touches(self):
        issues = [
            self.make_issue(1, "Dashboard one", ("scripts/status_dashboard.py",)),
            self.make_issue(2, "Provider", ("scripts/solve_issues.py",)),
            self.make_issue(3, "Dashboard two", ("scripts/status_dashboard.py",)),
        ]

        waves = plan_waves(issues)

        self.assertEqual(len(waves), 2)
        self.assertEqual([issue.number for issue in waves[0].issues], [1, 2])
        self.assertEqual([issue.number for issue in waves[1].issues], [3])

    def test_render_plan_includes_issue_titles_reasons_and_commands(self):
        waves = plan_waves(
            [
                self.make_issue(60, "Add optional fallback", ("scripts/solve_issues_batch.py",)),
                self.make_issue(64, "Add scheduler", ("scripts/solve_issues_batch.py",)),
            ]
        )

        output = render_plan(
            waves,
            emit_commands=True,
            model="codex",
            base_branch="develop",
            model_source=MODEL_SOURCE_DEFAULT,
        )

        self.assertIn("#60 - Add optional fallback", output)
        self.assertIn("#64 - Add scheduler", output)
        self.assertIn("getrennt von Welle 1", output)
        self.assertIn("python scripts/solve_issues_batch.py", output)
        self.assertIn("--issue 60", output)
        self.assertIn("--issue 64", output)

    def test_render_plan_includes_default_model_source(self):
        waves = plan_waves(
            [
                self.make_issue(60, "Add optional fallback", ("scripts/solve_issues_batch.py",)),
            ]
        )

        output = render_plan(
            waves,
            emit_commands=True,
            model="codex",
            base_branch="develop",
            model_source=MODEL_SOURCE_DEFAULT,
        )

        self.assertIn("model_default: codex", output)
        self.assertIn("model_effective: codex", output)
        self.assertIn("model_source: default", output)

    def test_render_plan_rejects_unknown_model_source(self):
        waves = plan_waves(
            [
                self.make_issue(60, "Add optional fallback", ("scripts/solve_issues_batch.py",)),
            ]
        )

        with self.assertRaises(ValueError):
            render_plan(
                waves,
                emit_commands=True,
                model="codex",
                base_branch="develop",
                model_source="env",
            )

    def test_render_plan_includes_cli_model_source(self):
        waves = plan_waves(
            [
                self.make_issue(60, "Add optional fallback", ("scripts/solve_issues_batch.py",)),
            ]
        )

        output = render_plan(
            waves,
            emit_commands=True,
            model="opencode",
            base_branch="develop",
            model_source=MODEL_SOURCE_CLI,
        )

        self.assertIn("model_default: codex", output)
        self.assertIn("model_effective: opencode", output)
        self.assertIn("model_source: cli --model", output)
        self.assertIn("--model opencode", output)

    def test_render_plan_omits_model_source_without_commands(self):
        waves = plan_waves(
            [
                self.make_issue(60, "Add optional fallback", ("scripts/solve_issues_batch.py",)),
            ]
        )

        output = render_plan(
            waves,
            emit_commands=False,
            model="codex",
            base_branch="develop",
            model_source=MODEL_SOURCE_DEFAULT,
        )

        self.assertNotIn("model_effective:", output)
        self.assertNotIn("model_source:", output)

    def test_main_reports_cli_model_source_for_emitted_commands(self):
        issues = [self.make_issue(60, "Add optional fallback", ("scripts/solve_issues_batch.py",))]
        stdout = StringIO()

        with patch("plan_issue_batches.load_open_issues", return_value=issues):
            with redirect_stdout(stdout):
                rc = main(["--repo", "demo", "--emit-commands", "--model", "opencode"])

        self.assertEqual(rc, 0)
        output = stdout.getvalue()
        self.assertIn("model_default: codex", output)
        self.assertIn("model_effective: opencode", output)
        self.assertIn("model_source: cli --model", output)
        self.assertIn("--model opencode", output)

    def test_main_reports_default_model_source_for_emitted_commands(self):
        issues = [self.make_issue(60, "Add optional fallback", ("scripts/solve_issues_batch.py",))]
        stdout = StringIO()

        with patch("plan_issue_batches.load_open_issues", return_value=issues):
            with redirect_stdout(stdout):
                rc = main(["--repo", "demo", "--emit-commands"])

        self.assertEqual(rc, 0)
        output = stdout.getvalue()
        self.assertIn("model_default: codex", output)
        self.assertIn("model_effective: codex", output)
        self.assertIn("model_source: default", output)
        self.assertIn("--model codex", output)

    def test_batch_command_for_wave_uses_issue_numbers_and_repo(self):
        wave = plan_waves(
            [
                self.make_issue(7, "One", ("README.md",), repo="ai-issue-solver"),
                self.make_issue(8, "Two", ("scripts/solve_issues.py",), repo="ai-issue-solver"),
            ]
        )[0]

        command = batch_command_for_wave(wave, model="opencode", base_branch="develop")

        self.assertIn("--model opencode", command)
        self.assertIn("--repo ai-issue-solver", command)
        self.assertIn("--issue 7", command)
        self.assertIn("--issue 8", command)
        self.assertIn("--workers 2", command)


if __name__ == "__main__":
    unittest.main()
