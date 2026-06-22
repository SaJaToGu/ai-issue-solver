from __future__ import annotations

import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from scripts.validation.models import RunReportData, ValidationMetrics


def compute_metrics(reports: list[RunReportData]) -> ValidationMetrics:
    total_processed = len(reports)
    merged = [r for r in reports if r.pr_merged is True]
    total_merged = len(merged)
    prs_created = len([r for r in reports if r.pr_number is not None])
    total_cost = sum(r.cost_usd for r in reports if r.cost_usd is not None)
    total_duration = sum(r.duration_seconds for r in reports if r.duration_seconds is not None)

    error_counter: Counter[str] = Counter()
    for r in reports:
        if r.error_class:
            error_counter[r.error_class] += 1

    error_list = tuple(sorted(error_counter.items()))
    per_issue = tuple(reports)

    return ValidationMetrics(
        total_processed=total_processed,
        total_merged=total_merged,
        total_prs_created=prs_created,
        total_cost_usd=total_cost,
        total_duration_seconds=total_duration,
        errors=error_list,
        per_issue=per_issue,
    )


def format_duration(seconds: float | None) -> str:
    if seconds is None:
        return "N/A"
    if seconds < 60:
        return f"{seconds:.0f}s"
    minutes = seconds / 60
    if minutes < 60:
        return f"{minutes:.1f}m"
    hours = minutes / 60
    return f"{hours:.1f}h"


def format_cost(usd: float | None) -> str:
    if usd is None:
        return "N/A"
    return f"${usd:.4f}"


def generate_report(metrics: ValidationMetrics, title: str = "validation-0.9.0") -> str:
    lines: list[str] = []
    lines.append(f"# Validation Report: {title}")
    lines.append("")
    lines.append(f"> Generated: {datetime.utcnow().isoformat()}Z")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append(f"| Metric | Value |")
    lines.append(f"|---|---|")
    lines.append(f"| Issues processed | {metrics.total_processed} |")
    lines.append(f"| PRs merged | {metrics.total_merged} |")
    lines.append(f"| PRs created (not merged) | {metrics.total_prs_created - metrics.total_merged} |")
    lines.append(f"| Success rate | {metrics.success_rate:.1%} |")
    lines.append(f"| Cost per solved issue | {format_cost(metrics.cost_per_solved)} |")
    lines.append(f"| Time per solved issue | {format_duration(metrics.time_per_solved)} |")
    lines.append(f"| Total cost | {format_cost(metrics.total_cost_usd)} |")
    lines.append(f"| Total time | {format_duration(metrics.total_duration_seconds)} |")
    lines.append("")

    if metrics.top_errors:
        lines.append("## Top Error Classes")
        lines.append("")
        lines.append("| Error Class | Count |")
        lines.append("|---|---|")
        for error_class, count in metrics.top_errors:
            lines.append(f"| {error_class} | {count} |")
        lines.append("")

    lines.append("## Per-Issue Results")
    lines.append("")
    lines.append("| # | Issue | Status | PR | Merged | CI Green | Cost | Duration | Error |")
    lines.append("|---|---|---|---|---|---|---|---|---|")
    for report in metrics.per_issue:
        issue_link = f"#{report.issue_number}" if report.issue_number else "-"
        status = report.status or "-"
        pr_link = f"#{report.pr_number}" if report.pr_number else "-"
        merged = "yes" if report.pr_merged else ("no" if report.pr_merged is False else "-")
        ci = "yes" if report.ci_green else ("no" if report.ci_green is False else "-")
        cost = format_cost(report.cost_usd)
        duration = format_duration(report.duration_seconds)
        error = report.error_class or "-"
        lines.append(f"| {issue_link} | {report.issue_title[:50]} | {status} | {pr_link} | {merged} | {ci} | {cost} | {duration} | {error} |")
    lines.append("")

    return "\n".join(lines)


def write_validation_report(
    metrics: ValidationMetrics,
    output_path: Path,
    title: str = "validation-0.9.0",
) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    report_text = generate_report(metrics, title=title)
    output_path.write_text(report_text, encoding="utf-8")
    return output_path


def persist_validation_run(
    metrics: ValidationMetrics,
    reports_dir: Path,
    run_id: str | None = None,
) -> Path:
    if run_id is None:
        run_id = datetime.utcnow().strftime("validation-%Y%m%d-%H%M%S")
    reports_dir.mkdir(parents=True, exist_ok=True)
    json_path = reports_dir / f"{run_id}.json"
    data = {
        "run_id": run_id,
        "total_processed": metrics.total_processed,
        "total_merged": metrics.total_merged,
        "total_prs_created": metrics.total_prs_created,
        "total_cost_usd": metrics.total_cost_usd,
        "total_duration_seconds": metrics.total_duration_seconds,
        "success_rate": metrics.success_rate,
        "cost_per_solved": metrics.cost_per_solved,
        "time_per_solved": metrics.time_per_solved,
        "errors": list(metrics.errors),
        "per_issue": [
            {
                "issue_number": r.issue_number,
                "issue_title": r.issue_title,
                "status": r.status,
                "pr_number": r.pr_number,
                "pr_merged": r.pr_merged,
                "ci_green": r.ci_green,
                "cost_usd": r.cost_usd,
                "duration_seconds": r.duration_seconds,
                "error_class": r.error_class,
            }
            for r in metrics.per_issue
        ],
    }
    json_path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    return json_path
