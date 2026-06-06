#!/usr/bin/env python3
"""test_solver_reporting.py — Tests für Provider-Scorecard-Funktionalität."""

from __future__ import annotations
import json
import tempfile
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock

from scripts.solver_reporting import (
    ProviderScorecard,
    RunReport,
    create_provider_scorecard,
    create_run_report,
    write_run_report,
)


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
        
        # Model Selection Metadata
        model_selection = {
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