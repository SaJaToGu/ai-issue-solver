#!/usr/bin/env python3
"""test_solver_reporting.py — Tests für Provider-Scorecard-Funktionalität und PR-Body-Rendering."""

from __future__ import annotations
import json
import tempfile
import unittest
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock

from scripts.solver_reporting import (
    ProviderScorecard,
    RunReport,
    build_run_outcome,
    create_provider_scorecard,
    create_run_report,
    write_run_report,
    format_heartbeat,
    format_heartbeat_progress,
)
from scripts.solve_issues import build_issue_pr_body
from scripts.solve_issues import build_issue_pr_body


def test_provider_scorecard_creation():
    """Testet die Erstellung einer Provider-Scorecard."""
    scorecard = ProviderScorecard(
        requested_model="mistral/mistral-large-latest",
        actual_model="mistral/mistral-medium-latest",
        fallback_source="rate_limit",
        duration_seconds=120.5,
        worker_exit_code=0,
        run_status="pr_created",
        pr_url="https://github.com/owner/repo/pull/123",
        test_command="pytest",
        test_result="passed",
        no_change=False,
        fallback_used=True,
        estimated_cost=0.15,
        cost_currency="USD",
        cost_confidence="high",
        cost_source="provider_api",
    )

    assert scorecard.requested_model == "mistral/mistral-large-latest"
    assert scorecard.actual_model == "mistral/mistral-medium-latest"
    assert scorecard.fallback_source == "rate_limit"
    assert scorecard.duration_seconds == 120.5
    assert scorecard.worker_exit_code == 0
    assert scorecard.run_status == "pr_created"
    assert scorecard.pr_url == "https://github.com/owner/repo/pull/123"
    assert scorecard.test_command == "pytest"
    assert scorecard.test_result == "passed"
    assert scorecard.no_change is False
    assert scorecard.fallback_used is True
    assert scorecard.estimated_cost == 0.15
    assert scorecard.cost_currency == "USD"
    assert scorecard.cost_confidence == "high"
    assert scorecard.cost_source == "provider_api"


class TestRunOutcomeSkipPr(unittest.TestCase):
    def test_build_run_outcome_skip_pr_with_changes(self):
        """pr_skipped with changes is a successful benchmark push without PR."""
        worker = Mock()
        worker.returncode = 0

        outcome = build_run_outcome(
            "pr_skipped",
            worker_result=worker,
            git_change_summary=["Git-Aenderungsuebersicht:", "  README.md | 1 +"],
            test_result="passed",
        )

        self.assertEqual(outcome["worker_status"], "succeeded")
        self.assertIs(outcome["has_changes"], True)
        self.assertEqual(outcome["test_status"], "passed")
        self.assertEqual(outcome["delivery_status"], "pushed_without_pr")
        self.assertEqual(outcome["failure_class"], "success")
        self.assertEqual(outcome["recovery_status"], "none")

    def test_build_run_outcome_skip_pr_without_changes(self):
        """pr_skipped without changes is treated as noop (defensive case)."""
        worker = Mock()
        worker.returncode = 0

        outcome = build_run_outcome(
            "pr_skipped",
            worker_result=worker,
            git_change_summary=[],
        )

        self.assertEqual(outcome["delivery_status"], "not_applicable")
        self.assertEqual(outcome["failure_class"], "noop")

    def test_build_run_outcome_budget_exceeded_is_control_failure(self):
        """Budget/control aborts are distinct from model and pipeline failures."""
        worker = Mock()
        worker.returncode = 4

        outcome = build_run_outcome(
            "budget_exceeded",
            worker_result=worker,
            git_change_summary=["Git-Aenderungsuebersicht:", "  worker.py | 1 +"],
        )

        self.assertEqual(outcome["worker_status"], "failed")
        self.assertEqual(outcome["delivery_status"], "incomplete")
        self.assertEqual(outcome["failure_class"], "control_failure")
        self.assertEqual(outcome["recovery_status"], "manual_review")

    def test_write_run_report_includes_openrouter_usage_and_cost_scorecard(self):
        """OpenRouter Direct usage is persisted and exposed through scorecards."""
        with tempfile.TemporaryDirectory() as temp_dir:
            report = RunReport(
                path=Path(temp_dir) / "test-run-openrouter",
                repo="test-repo",
                issue_number=46,
                issue_title="OpenRouter Budget",
                branch="test-branch",
                model="openrouter_direct",
            )
            report.path.mkdir(parents=True, exist_ok=True)

            worker = Mock()
            worker.returncode = 4
            worker.output = "budget exceeded"
            worker.last_activity_at = datetime.now()
            worker.duration_seconds = None

            write_run_report(
                report=report,
                status="budget_exceeded",
                worker_result=worker,
                git_change_summary=["Git-Aenderungsuebersicht:", "  worker.py | 1 +"],
                openrouter_usage_metrics={
                    "prompt_tokens": 101,
                    "completion_tokens": 20,
                    "total_tokens": 121,
                    "cost_usd": 0.0123,
                    "model": "minimax/minimax-m3",
                    "request_seconds": 1.5,
                    "timed_out": False,
                    "budget_exceeded": "input_tokens 101 exceeds 100",
                },
            )

            metadata = json.loads((report.path / "metadata.json").read_text(encoding="utf-8"))
            self.assertEqual(metadata["openrouter_usage"]["prompt_tokens"], 101)
            self.assertEqual(metadata["openrouter_usage"]["budget_exceeded"], "input_tokens 101 exceeds 100")
            self.assertEqual(metadata["provider_scorecard"]["estimated_cost"], 0.0123)
            self.assertEqual(metadata["provider_scorecard"]["cost_source"], "provider_api")
            self.assertEqual(metadata["run_outcome"]["failure_class"], "control_failure")

            summary = (report.path / "summary.txt").read_text(encoding="utf-8")
            self.assertIn("openrouter_usage:", summary)
            self.assertIn("budget_exceeded: input_tokens 101 exceeds 100", summary)
            self.assertIn("provider_scorecard_estimated_cost: 0.0123", summary)

    def test_write_run_report_skip_pr_with_changes(self):
        """Run report for pr_skipped with changes yields pushed_without_pr outcome."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            report = RunReport(
                path=temp_path / "test-run-skip-pr",
                repo="test-repo",
                issue_number=45,
                issue_title="Skip PR Issue",
                branch="test-branch",
                model="test-model",
            )
            report.path.mkdir(parents=True, exist_ok=True)

            mock_worker = Mock()
            mock_worker.duration_seconds = 60.0
            mock_worker.returncode = 0
            mock_worker.output = "changes made"
            mock_worker.last_activity_at = datetime.now()

            result_path = write_run_report(
                report=report,
                status="pr_skipped",
                worker_result=mock_worker,
                pr_url=None,
                note="Benchmark skip-pr with changes",
                git_change_summary=["README.md | 1 +"],
                test_result="passed",
            )

            self.assertIsNotNone(result_path)
            metadata_path = report.path / "metadata.json"
            self.assertTrue(metadata_path.exists())

            with open(metadata_path, "r", encoding="utf-8") as f:
                metadata = json.load(f)

            outcome = metadata["run_outcome"]
            self.assertEqual(outcome["delivery_status"], "pushed_without_pr")
            self.assertEqual(outcome["failure_class"], "success")
            self.assertIs(outcome["has_changes"], True)

            summary_path = report.path / "summary.txt"
            self.assertTrue(summary_path.exists())
            summary_content = summary_path.read_text(encoding="utf-8")
            self.assertIn("run_outcome_delivery_status: pushed_without_pr", summary_content)
            self.assertIn("run_outcome_failure_class: success", summary_content)

    def test_write_run_report_persists_repo_profile_metadata_and_summary(self):
        """Repo-Profile-Daten landen in metadata.json und summary.txt."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            report = RunReport(
                path=temp_path / "test-run-repo-profile",
                repo="test-owner/test-repo",
                issue_number=99,
                issue_title="Repo profile",
                branch="ai/fix-issue-99",
                model="opencode",
            )
            report.path.mkdir(parents=True, exist_ok=True)

            repo_profile = {
                "provider": "github",
                "source": "github_rest",
                "repo": "test-owner/test-repo",
                "repo_kind": "python",
                "dominant_language": "python",
                "language_percentages": {"python": 100.0},
                "framework_hints": ["fastapi"],
                "test_hints": ["python -m pytest"],
                "recommended_worker": "opencode",
                "python_required": True,
                "default_branch": "main",
                "is_archived": False,
                "is_private": False,
                "topics": ["fastapi"],
                "marker_files": ["pyproject.toml", "src/app.py"],
                "extra": {
                    "workflows": [{"name": "ci.yml", "path": ".github/workflows/ci.yml"}],
                    "remote_state": {
                        "open_pull_requests": 1,
                        "open_issues": 0,
                        "open_issue_numbers": [],
                        "open_pull_request_numbers": [42],
                        "existing_solver_branches": ["ai/fix-issue-7"],
                    },
                },
            }

            mock_worker = Mock()
            mock_worker.duration_seconds = 12.0
            mock_worker.returncode = 0
            mock_worker.output = "all good"
            mock_worker.last_activity_at = datetime.now()

            write_run_report(
                report=report,
                status="pr_created",
                worker_result=mock_worker,
                pr_url="https://github.com/test-owner/test-repo/pull/42",
                repo_profile=repo_profile,
            )

            with open(report.path / "metadata.json", "r", encoding="utf-8") as f:
                metadata = json.load(f)

            self.assertIn("repo_profile", metadata)
            self.assertEqual(metadata["repo_profile"]["repo_kind"], "python")
            self.assertEqual(metadata["repo_profile"]["source"], "github_rest")
            self.assertEqual(
                metadata["repo_profile"]["extra"]["remote_state"]["open_pull_requests"],
                1,
            )
            self.assertEqual(
                metadata["repo_profile"]["extra"]["workflows"][0]["name"],
                "ci.yml",
            )

            summary_content = (report.path / "summary.txt").read_text(encoding="utf-8")
            self.assertIn("repo_profile:", summary_content)
            self.assertIn("  provider: github", summary_content)
            self.assertIn("  repo_kind: python", summary_content)
            self.assertIn("repo_profile_remote_state:", summary_content)
            self.assertIn("repo_profile_workflows:", summary_content)
            self.assertIn("- ci.yml", summary_content)

    def test_write_run_report_drops_repo_profile_secret_paths(self):
        """Repo-Profile-Serialisierung entfernt Secret-Pfade vor dem Schreiben."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            report = RunReport(
                path=temp_path / "test-run-secret-safety",
                repo="test-owner/test-repo",
                issue_number=100,
                issue_title="Secret safety",
                branch="ai/fix-issue-100",
                model="opencode",
            )
            report.path.mkdir(parents=True, exist_ok=True)

            write_run_report(
                report=report,
                status="no_changes",
                repo_profile={
                    "provider": "github",
                    "repo_kind": "python",
                    "marker_files": [".env", "auth.json", "src/app.py", "secrets/db.yml"],
                },
            )

            with open(report.path / "metadata.json", "r", encoding="utf-8") as f:
                metadata = json.load(f)

            marker_files = metadata["repo_profile"]["marker_files"]
            self.assertIn("src/app.py", marker_files)
            for forbidden in (".env", "auth.json", "secrets/db.yml"):
                self.assertNotIn(forbidden, marker_files)


def test_build_run_outcome_marks_preserved_push_failure_as_pipeline_failure():
    """Push failures with preserved changes are benchmark-relevant pipeline failures."""
    worker = Mock()
    worker.returncode = 0

    outcome = build_run_outcome(
        "push_failed",
        worker_result=worker,
        preserved_worktree_path="reports/preserved-worktrees/run/demo",
        git_change_summary=["Git-Änderungsübersicht:", "  README.md | 1 +"],
        test_result="passed",
    )

    assert outcome["worker_status"] == "succeeded"
    assert outcome["has_changes"] is True
    assert outcome["test_status"] == "passed"
    assert outcome["delivery_status"] == "push_failed"
    assert outcome["failure_class"] == "pipeline_failure"
    assert outcome["recovery_status"] == "preserved_worktree"


def test_provider_scorecard_missing_costs():
    """Testet die Erstellung einer Provider-Scorecard mit fehlenden Kosteninformationen."""
    scorecard = ProviderScorecard(
        requested_model="mistral/mistral-large-latest",
        actual_model="mistral/mistral-medium-latest",
        fallback_source="rate_limit",
        duration_seconds=120.5,
        worker_exit_code=0,
        run_status="pr_created",
        pr_url="https://github.com/owner/repo/pull/123",
        test_command="pytest",
        test_result="passed",
        no_change=False,
        fallback_used=True,
    )

    assert scorecard.estimated_cost is None
    assert scorecard.cost_currency is None
    assert scorecard.cost_confidence is None
    assert scorecard.cost_source is None


def test_create_provider_scorecard():
    """Testet die create_provider_scorecard-Funktion."""
    mock_worker = Mock()
    mock_worker.duration_seconds = 180.0
    mock_worker.returncode = 0

    model_selection = {
        "model": "mistral/mistral-large-latest",
        "fallback_from": "anthropic/claude-sonnet-4-6",
        "reason": "rate_limit"
    }

    model_selection["estimated_cost"] = 0.15
    model_selection["cost_currency"] = "USD"
    model_selection["cost_confidence"] = "high"
    model_selection["cost_source"] = "provider_api"
    
    scorecard = create_provider_scorecard(
        report=Mock(model="mistral/mistral-medium-latest"),
        status="pr_created",
        worker_result=mock_worker,
        pr_url="https://github.com/owner/repo/pull/123",
        model_selection_metadata=model_selection,
        test_command="pytest tests/",
        test_result="all tests passed"
    )

    assert scorecard.requested_model == "mistral/mistral-large-latest"
    assert scorecard.actual_model == "mistral/mistral-medium-latest"
    assert scorecard.fallback_source == "anthropic/claude-sonnet-4-6"
    assert scorecard.duration_seconds == 180.0
    assert scorecard.worker_exit_code == 0
    assert scorecard.run_status == "pr_created"
    assert scorecard.pr_url == "https://github.com/owner/repo/pull/123"
    assert scorecard.test_command == "pytest tests/"
    assert scorecard.test_result == "all tests passed"
    assert scorecard.fallback_used is True
    assert scorecard.estimated_cost == 0.15
    assert scorecard.cost_currency == "USD"
    assert scorecard.cost_confidence == "high"
    assert scorecard.cost_source == "provider_api"


def test_create_provider_scorecard_no_fallback():
    """Testet die Scorecard-Erstellung ohne Fallback."""
    mock_worker = Mock()
    mock_worker.duration_seconds = 90.0
    mock_worker.returncode = 0

    scorecard = create_provider_scorecard(
        report=Mock(model="anthropic/claude-sonnet-4-6"),
        status="pr_created",
        worker_result=mock_worker,
        pr_url="https://github.com/owner/repo/pull/456",
        model_selection_metadata=None,
        test_command="pytest",
        test_result="passed"
    )

    assert scorecard.requested_model == "anthropic/claude-sonnet-4-6"
    assert scorecard.actual_model == "anthropic/claude-sonnet-4-6"
    assert scorecard.fallback_source is None
    assert scorecard.fallback_used is False
    assert scorecard.estimated_cost is None
    assert scorecard.cost_currency is None
    assert scorecard.cost_confidence is None
    assert scorecard.cost_source is None


def test_create_provider_scorecard_no_change():
    """Testet die Scorecard-Erstellung für No-Change-Runs."""
    scorecard = create_provider_scorecard(
        report=Mock(model="mistral/mistral-medium-latest"),
        status="no_changes",
        worker_result=None,
        pr_url=None,
        model_selection_metadata=None,
        test_command=None,
        test_result=None
    )

    assert scorecard.no_change is True
    assert scorecard.duration_seconds is None
    assert scorecard.worker_exit_code is None
    assert scorecard.estimated_cost is None
    assert scorecard.cost_currency is None
    assert scorecard.cost_confidence is None
    assert scorecard.cost_source is None


def test_write_run_report_with_scorecard():
    """Testet das Schreiben eines Run-Reports mit Provider-Scorecard."""
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        report = RunReport(
            path=temp_path / "test-run",
            repo="test-repo",
            issue_number=42,
            issue_title="Test Issue",
            branch="test-branch",
            model="mistral/mistral-medium-latest"
        )

        # Erstelle das Verzeichnis
        report.path.mkdir(parents=True, exist_ok=True)

        # Mock Worker Result
        mock_worker = Mock()
        mock_worker.duration_seconds = 120.0
        mock_worker.returncode = 0
        mock_worker.output = "Test output"
        mock_worker.last_activity_at = datetime.now()

        # Model Selection Metadata mit Kosteninformationen
        model_selection = {
            "estimated_cost": 0.15,
            "cost_currency": "USD",
            "cost_confidence": "high",
            "cost_source": "provider_api",
            "model": "mistral/mistral-large-latest",
            "fallback_from": "anthropic/claude-sonnet-4-6",
            "reason": "rate_limit"
        }

        # Schreibe den Report
        result_path = write_run_report(
            report=report,
            status="pr_created",
            worker_result=mock_worker,
            pr_url="https://github.com/owner/repo/pull/123",
            note="Test note",
            preserved_worktree_path=None,
            base_branch="main",
            git_change_summary=["file1.txt | 2 ++"],
            vibe_log_snippet="Test vibe",
            resource_diagnostics=None,
            model_selection_metadata=model_selection,
            test_command="pytest",
            test_result="passed"
        )

        # Überprüfe die erstellten Dateien
        assert result_path is not None

        # Lese die metadata.json
        metadata_path = report.path / "metadata.json"
        assert metadata_path.exists()

        with open(metadata_path, "r", encoding="utf-8") as f:
            metadata = json.load(f)

        # Überprüfe die Scorecard-Daten
        scorecard_data = metadata["provider_scorecard"]
        assert scorecard_data["requested_model"] == "mistral/mistral-large-latest"
        assert scorecard_data["actual_model"] == "mistral/mistral-medium-latest"
        assert scorecard_data["fallback_source"] == "anthropic/claude-sonnet-4-6"
        assert scorecard_data["duration_seconds"] == 120.0
        assert scorecard_data["worker_exit_code"] == 0
        assert scorecard_data["run_status"] == "pr_created"
        assert scorecard_data["pr_url"] == "https://github.com/owner/repo/pull/123"
        assert scorecard_data["test_command"] == "pytest"
        assert scorecard_data["test_result"] == "passed"
        assert scorecard_data["no_change"] is False
        assert scorecard_data["fallback_used"] is True
        outcome_data = metadata["run_outcome"]
        assert outcome_data["worker_status"] == "succeeded"
        assert outcome_data["has_changes"] is True
        assert outcome_data["test_status"] == "passed"
        assert outcome_data["delivery_status"] == "pr_created"
        assert outcome_data["failure_class"] == "success"
        assert outcome_data["recovery_status"] == "none"

        # Lese die summary.txt
        summary_path = report.path / "summary.txt"
        assert summary_path.exists()

        with open(summary_path, "r", encoding="utf-8") as f:
            summary_content = f.read()

        # Überprüfe die Scorecard-Felder in der Summary
        assert "provider_scorecard_requested_model: mistral/mistral-large-latest" in summary_content
        assert "provider_scorecard_actual_model: mistral/mistral-medium-latest" in summary_content
        assert "provider_scorecard_fallback_source: anthropic/claude-sonnet-4-6" in summary_content
        assert "provider_scorecard_duration_seconds: 120.0" in summary_content
        assert "provider_scorecard_worker_exit_code: 0" in summary_content
        assert "provider_scorecard_run_status: pr_created" in summary_content
        assert "provider_scorecard_pr_url: https://github.com/owner/repo/pull/123" in summary_content
        assert "provider_scorecard_test_command: pytest" in summary_content
        assert "provider_scorecard_test_result: passed" in summary_content
        assert "provider_scorecard_no_change: False" in summary_content
        assert "provider_scorecard_fallback_used: True" in summary_content
        assert "run_outcome_worker_status: succeeded" in summary_content
        assert "run_outcome_has_changes: True" in summary_content
        assert "run_outcome_test_status: passed" in summary_content
        assert "run_outcome_delivery_status: pr_created" in summary_content
        assert "run_outcome_failure_class: success" in summary_content
        assert "run_outcome_recovery_status: none" in summary_content


def test_write_run_report_no_change():
    """Testet das Schreiben eines Run-Reports für No-Change-Runs."""
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        report = RunReport(
            path=temp_path / "test-run-no-change",
            repo="test-repo",
            issue_number=43,
            issue_title="No Change Issue",
            branch="test-branch",
            model="anthropic/claude-sonnet-4-6"
        )

        # Erstelle das Verzeichnis
        report.path.mkdir(parents=True, exist_ok=True)

        # Schreibe den Report
        result_path = write_run_report(
            report=report,
            status="no_changes",
            worker_result=None,
            pr_url=None,
            note="No changes needed",
            preserved_worktree_path=None,
            base_branch="main",
            git_change_summary=[],
            vibe_log_snippet=None,
            resource_diagnostics=None,
            model_selection_metadata=None,
            test_command=None,
            test_result=None
        )

        # Überprüfe die erstellten Dateien
        assert result_path is not None

        # Lese die summary.txt
        summary_path = report.path / "summary.txt"
        assert summary_path.exists()

        with open(summary_path, "r", encoding="utf-8") as f:
            summary_content = f.read()

        # Überprüfe die Scorecard-Felder in der Summary
        assert "provider_scorecard_requested_model: anthropic/claude-sonnet-4-6" in summary_content
        assert "provider_scorecard_actual_model: anthropic/claude-sonnet-4-6" in summary_content
        assert "provider_scorecard_no_change: True" in summary_content
        assert "provider_scorecard_fallback_used: False" in summary_content


class TestBuildIssuePrBody(unittest.TestCase):
    def test_build_issue_pr_body_opencode_adapter_only(self):
        """Testet den PR-Body mit OpenCode Adapter ohne konkreten Modellnamen."""
        pr_body = build_issue_pr_body(
            config_owner="test-owner",
            repo="test-repo",
            number=42,
            title="Test Issue",
            model="opencode",
            model_name=None,
            fallback_from=None
        )
        self.assertIn("OpenCode CLI", pr_body)
        self.assertNotIn("(mistral/", pr_body)
        self.assertNotIn("Fallback von", pr_body)

    def test_build_issue_pr_body_opencode_with_model_name(self):
        """Testet den PR-Body mit OpenCode Adapter und konkretem Modellnamen."""
        pr_body = build_issue_pr_body(
            config_owner="test-owner",
            repo="test-repo",
            number=42,
            title="Test Issue",
            model="opencode",
            model_name="mistral/mistral-medium-latest",
            fallback_from=None
        )
        self.assertIn("OpenCode CLI (mistral/mistral-medium-latest)", pr_body)
        self.assertNotIn("Fallback von", pr_body)

    def test_build_issue_pr_body_opencode_with_provider_model(self):
        """Testet den PR-Body mit OpenCode und Provider-Modellnamen."""
        pr_body = build_issue_pr_body(
            config_owner="test-owner",
            repo="test-repo",
            number=42,
            title="Test Issue",
            model="opencode",
            model_name="mistral/mistral-large-latest",
            fallback_from=None
        )
        self.assertIn("OpenCode CLI (mistral/mistral-large-latest)", pr_body)
        self.assertNotIn("Fallback von", pr_body)

    def test_build_issue_pr_body_opencode_with_fallback(self):
        """Testet den PR-Body mit Fallback-Worker/Modell."""
        pr_body = build_issue_pr_body(
            config_owner="test-owner",
            repo="test-repo",
            number=42,
            title="Test Issue",
            model="opencode",
            model_name="mistral/mistral-medium-latest",
            fallback_from="claude/claude-sonnet-4-6"
        )
        self.assertIn("OpenCode CLI (mistral/mistral-medium-latest) (Fallback von claude/claude-sonnet-4-6)", pr_body)


def test_write_run_report_failed():
    """Testet das Schreiben eines Run-Reports für fehlgeschlagene Runs."""
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        report = RunReport(
            path=temp_path / "test-run-failed",
            repo="test-repo",
            issue_number=44,
            issue_title="Failed Issue",
            branch="test-branch",
            model="mistral/mistral-medium-latest"
        )

        # Erstelle das Verzeichnis
        report.path.mkdir(parents=True, exist_ok=True)

        # Mock Worker Result mit Fehler
        mock_worker = Mock()
        mock_worker.duration_seconds = 60.0
        mock_worker.returncode = 1
        mock_worker.output = "Error output"
        mock_worker.last_activity_at = datetime.now()

        # Schreibe den Report
        result_path = write_run_report(
            report=report,
            status="pr_failed",
            worker_result=mock_worker,
            pr_url=None,
            note="Failed to create PR",
            preserved_worktree_path=None,
            base_branch="main",
            git_change_summary=[],
            vibe_log_snippet=None,
            resource_diagnostics=None,
            model_selection_metadata=None,
            test_command="pytest",
            test_result="failed"
        )

        # Überprüfe die erstellten Dateien
        assert result_path is not None

        # Lese die summary.txt
        summary_path = report.path / "summary.txt"
        assert summary_path.exists()

        with open(summary_path, "r", encoding="utf-8") as f:
            summary_content = f.read()

        # Überprüfe die Scorecard-Felder in der Summary
        assert "provider_scorecard_requested_model: mistral/mistral-medium-latest" in summary_content
        assert "provider_scorecard_actual_model: mistral/mistral-medium-latest" in summary_content
        assert "provider_scorecard_worker_exit_code: 1" in summary_content
        assert "provider_scorecard_run_status: pr_failed" in summary_content
        assert "provider_scorecard_test_result: failed" in summary_content
        assert "provider_scorecard_no_change: False" in summary_content
        assert "provider_scorecard_fallback_used: False" in summary_content


def test_build_issue_pr_body_opencode_adapter_only():
    """Testet den PR-Body mit OpenCode Adapter ohne konkreten Modellnamen."""
    pr_body = build_issue_pr_body(
        config_owner="testowner",
        repo="testrepo",
        number=42,
        title="Test Issue",
        model="opencode",
        model_name=None,
        fallback_from=None
    )

    assert "## 🤖 AI-generierter Fix für Issue #42" in pr_body
    assert "Closes #42: Test Issue" in pr_body
    assert "`OpenCode CLI`" in pr_body
    assert "(Fallback von" not in pr_body


def test_build_issue_pr_body_opencode_with_model_name():
    """Testet den PR-Body mit OpenCode Adapter und konkretem Modellnamen."""
    pr_body = build_issue_pr_body(
        config_owner="testowner",
        repo="testrepo",
        number=43,
        title="Test Issue mit Modell",
        model="opencode",
        model_name="mistral/mistral-medium-latest",
        fallback_from=None
    )

    assert "## 🤖 AI-generierter Fix für Issue #43" in pr_body
    assert "Closes #43: Test Issue mit Modell" in pr_body
    assert "`OpenCode CLI (mistral/mistral-medium-latest)`" in pr_body
    assert "(Fallback von" not in pr_body


def test_build_issue_pr_body_opencode_with_provider_model():
    """Testet den PR-Body mit OpenCode und Provider-Modellnamen."""
    pr_body = build_issue_pr_body(
        config_owner="testowner",
        repo="testrepo",
        number=44,
        title="Test Issue mit Provider-Modell",
        model="opencode",
        model_name="mistral/mistral-large-latest",
        fallback_from=None
    )

    assert "## 🤖 AI-generierter Fix für Issue #44" in pr_body
    assert "Closes #44: Test Issue mit Provider-Modell" in pr_body
    assert "`OpenCode CLI (mistral/mistral-large-latest)`" in pr_body
    assert "(Fallback von" not in pr_body


def test_build_issue_pr_body_opencode_with_fallback():
    """Testet den PR-Body mit Fallback-Worker/Modell."""
    pr_body = build_issue_pr_body(
        config_owner="testowner",
        repo="testrepo",
        number=45,
        title="Test Issue mit Fallback",
        model="opencode",
        model_name="mistral/mistral-medium-latest",
        fallback_from="claude/claude-sonnet-4-6"
    )

    assert "## 🤖 AI-generierter Fix für Issue #45" in pr_body
    assert "Closes #45: Test Issue mit Fallback" in pr_body
    assert "`OpenCode CLI (mistral/mistral-medium-latest) (Fallback von claude/claude-sonnet-4-6)`" in pr_body


class HeartbeatFormatterTests(unittest.TestCase):
    """Tests für die Heartbeat-Formatter-Funktionen."""

    def test_format_heartbeat_progress_every_fifth_char_is_plus(self):
        """Testet, dass jeder 5. Character ein '+' ist."""
        progress = format_heartbeat_progress(elapsed_seconds=300.0, width=20)
        progress_chars = progress.split(" ")[0]
        for i, char in enumerate(progress_chars):
            expected = "+" if (i + 1) % 5 == 0 else "."
            self.assertEqual(char, expected, f"Position {i} sollte '{expected}' sein, ist aber '{char}'")

    def test_format_heartbeat_progress_includes_elapsed_minutes(self):
        """Testet, dass die vergangenen Minuten als Suffix angehängt werden."""
        progress = format_heartbeat_progress(elapsed_seconds=300.0, width=20)
        self.assertTrue(progress.endswith(" 5min"), f"Progress sollte mit ' 5min' enden: {progress}")

        progress_short = format_heartbeat_progress(elapsed_seconds=59.0, width=20)
        self.assertTrue(progress_short.endswith(" 0min"), f"Progress sollte mit ' 0min' enden: {progress_short}")

    def test_format_heartbeat_progress_custom_width(self):
        """Testet den Progress-String mit benutzerdefinierter Breite."""
        progress = format_heartbeat_progress(elapsed_seconds=120.0, width=10)
        self.assertTrue(progress.endswith(" 2min"))
        self.assertEqual(len(progress.split(" ")[0]), 10)

    def test_format_heartbeat_issue_prefix(self):
        """Testet das Issue-Präfix mit '#'."""
        heartbeat = format_heartbeat(issue_number=223, elapsed_seconds=300.0)
        self.assertTrue(heartbeat.startswith("#223"), f"Heartbeat sollte mit '#223' starten: {heartbeat}")

    def test_format_heartbeat_without_job_label(self):
        """Testet Heartbeat ohne Job-Label."""
        heartbeat = format_heartbeat(issue_number=223, elapsed_seconds=300.0)
        parts = heartbeat.split(" ")
        self.assertEqual(parts[0], "#223")
        self.assertEqual(parts[-1], "5min")

    def test_format_heartbeat_with_job_label(self):
        """Testet Heartbeat mit optionalem Job-Label."""
        heartbeat = format_heartbeat(issue_number=223, elapsed_seconds=300.0, job_label="PR2")
        self.assertTrue(heartbeat.startswith("#223"))
        self.assertIn("PR2", heartbeat)
        self.assertTrue(heartbeat.endswith("5min"))

    def test_format_heartbeat_minute_rounding(self):
        """Testet die Minutenrundung (ab 60 Sekunden = 1 Minute)."""
        heartbeat_59s = format_heartbeat(issue_number=1, elapsed_seconds=59.0)
        self.assertTrue(heartbeat_59s.endswith("0min"))

        heartbeat_60s = format_heartbeat(issue_number=1, elapsed_seconds=60.0)
        self.assertTrue(heartbeat_60s.endswith("1min"))

        heartbeat_119s = format_heartbeat(issue_number=1, elapsed_seconds=119.0)
        self.assertTrue(heartbeat_119s.endswith("1min"))

        heartbeat_120s = format_heartbeat(issue_number=1, elapsed_seconds=120.0)
        self.assertTrue(heartbeat_120s.endswith("2min"))

    def test_format_heartbeat_stable_output_multiple_jobs(self):
        """Testet stabile Ausgabe für mehrere parallele Jobs."""
        heartbeats = [
            format_heartbeat(issue_number=100, elapsed_seconds=300.0, job_label="codex"),
            format_heartbeat(issue_number=101, elapsed_seconds=300.0, job_label="codex"),
            format_heartbeat(issue_number=102, elapsed_seconds=300.0, job_label="codex"),
        ]
        for hb in heartbeats:
            self.assertTrue(hb.startswith("#"))
            self.assertIn("codex", hb)

    def test_format_heartbeat_progress_grows_over_time(self):
        """Testet, dass der Progress-String mit der Zeit wächst."""
        progress_5min = format_heartbeat_progress(elapsed_seconds=300.0)
        self.assertEqual(len(progress_5min.split(" ")[0]), 2)

        progress_10min = format_heartbeat_progress(elapsed_seconds=600.0)
        self.assertEqual(len(progress_10min.split(" ")[0]), 5)

        progress_20min = format_heartbeat_progress(elapsed_seconds=1200.0)
        self.assertEqual(len(progress_20min.split(" ")[0]), 10)
