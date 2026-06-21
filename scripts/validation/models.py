from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ValidationIssue:
    number: int
    title: str
    body: str
    labels: tuple[str, ...] = ()
    state: str = "open"
    html_url: str = ""
    repo: str = ""


@dataclass(frozen=True)
class RunReportData:
    issue_number: int
    issue_title: str
    status: str
    pr_number: int | None = None
    pr_url: str | None = None
    pr_merged: bool | None = None
    ci_green: bool | None = None
    duration_seconds: float | None = None
    cost_usd: float | None = None
    model: str | None = None
    error_class: str | None = None
    error_detail: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    run_id: str | None = None


@dataclass(frozen=True)
class ValidationConfig:
    repo: str = "ai-issue-solver"
    owner: str = "SaJaToGu"
    max_issues: int = 3
    max_run_cost_usd: float = 5.0
    model: str = "opencode"
    model_name: str = "opencode/deepseek-v4-flash-free"
    dry_run: bool = False
    reports_dir: Path = Path("reports/validation")
    runs_dir: Path = Path("reports/runs")
    label: str = "ai-generated"


@dataclass(frozen=True)
class ValidationMetrics:
    total_processed: int = 0
    total_merged: int = 0
    total_prs_created: int = 0
    total_cost_usd: float = 0.0
    total_duration_seconds: float = 0.0
    errors: tuple[tuple[str, int], ...] = ()
    per_issue: tuple[RunReportData, ...] = ()

    @property
    def success_rate(self) -> float:
        if self.total_processed == 0:
            return 0.0
        return self.total_merged / self.total_processed

    @property
    def cost_per_solved(self) -> float | None:
        if self.total_merged == 0:
            return None
        return self.total_cost_usd / self.total_merged

    @property
    def time_per_solved(self) -> float | None:
        if self.total_merged == 0:
            return None
        return self.total_duration_seconds / self.total_merged

    @property
    def top_errors(self) -> tuple[tuple[str, int], ...]:
        sorted_errors = sorted(self.errors, key=lambda x: x[1], reverse=True)
        return sorted_errors[:5]
