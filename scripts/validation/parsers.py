from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from validation.models import RunReportData

SUMMARY_STATUS_RE = re.compile(r"^status:\s*(\S+)", re.MULTILINE)
SUMMARY_ISSUE_RE = re.compile(r"^issue_number:\s*(\d+)", re.MULTILINE)
SUMMARY_TITLE_RE = re.compile(r"^issue_title:\s*(.+)", re.MULTILINE)
SUMMARY_PR_RE = re.compile(r"^pr_number:\s*(\d+)", re.MULTILINE)
SUMMARY_PR_URL_RE = re.compile(r"^pr_url:\s*(\S+)", re.MULTILINE)
SUMMARY_DURATION_RE = re.compile(r"^duration_seconds:\s*([\d.]+)", re.MULTILINE)
SUMMARY_COST_RE = re.compile(r"^cost_usd:\s*([\d.]+)", re.MULTILINE)
SUMMARY_MODEL_RE = re.compile(r"^model:\s*(.+)", re.MULTILINE)
SUMMARY_RUN_ID_RE = re.compile(r"^run_id:\s*(\S+)", re.MULTILINE)
SUMMARY_STARTED_RE = re.compile(r"^started_at:\s*(.+)", re.MULTILINE)
SUMMARY_FINISHED_RE = re.compile(r"^finished_at:\s*(.+)", re.MULTILINE)
SUMMARY_ERROR_CLASS_RE = re.compile(r"^error_class:\s*(.+)", re.MULTILINE)
SUMMARY_ERROR_DETAIL_RE = re.compile(r"^error_detail:\s*(.+)", re.MULTILINE)


def parse_summary_file(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"Summary file not found: {path}")
    text = path.read_text(encoding="utf-8")
    result: dict[str, Any] = {}

    status_match = SUMMARY_STATUS_RE.search(text)
    if status_match:
        result["status"] = status_match.group(1)

    issue_match = SUMMARY_ISSUE_RE.search(text)
    if issue_match:
        result["issue_number"] = int(issue_match.group(1))

    title_match = SUMMARY_TITLE_RE.search(text)
    if title_match:
        result["issue_title"] = title_match.group(1).strip()

    pr_match = SUMMARY_PR_RE.search(text)
    if pr_match:
        result["pr_number"] = int(pr_match.group(1))

    pr_url_match = SUMMARY_PR_URL_RE.search(text)
    if pr_url_match:
        result["pr_url"] = pr_url_match.group(1)

    duration_match = SUMMARY_DURATION_RE.search(text)
    if duration_match:
        result["duration_seconds"] = float(duration_match.group(1))

    cost_match = SUMMARY_COST_RE.search(text)
    if cost_match:
        result["cost_usd"] = float(cost_match.group(1))

    model_match = SUMMARY_MODEL_RE.search(text)
    if model_match:
        result["model"] = model_match.group(1).strip()

    run_id_match = SUMMARY_RUN_ID_RE.search(text)
    if run_id_match:
        result["run_id"] = run_id_match.group(1)

    started_match = SUMMARY_STARTED_RE.search(text)
    if started_match:
        result["started_at"] = started_match.group(1).strip()

    finished_match = SUMMARY_FINISHED_RE.search(text)
    if finished_match:
        result["finished_at"] = finished_match.group(1).strip()

    error_class_match = SUMMARY_ERROR_CLASS_RE.search(text)
    if error_class_match:
        result["error_class"] = error_class_match.group(1).strip()

    error_detail_match = SUMMARY_ERROR_DETAIL_RE.search(text)
    if error_detail_match:
        result["error_detail"] = error_detail_match.group(1).strip()

    return result


def read_run_report(path: Path) -> RunReportData:
    if path.is_dir():
        summary_file = path / "summary.txt"
        if not summary_file.is_file():
            raise FileNotFoundError(f"No summary.txt in run report: {path}")
        parsed = parse_summary_file(summary_file)
    else:
        parsed = parse_summary_file(path)

    return RunReportData(
        issue_number=parsed.get("issue_number", 0),
        issue_title=parsed.get("issue_title", ""),
        status=parsed.get("status", "unknown"),
        pr_number=parsed.get("pr_number"),
        pr_url=parsed.get("pr_url"),
        pr_merged=None,
        ci_green=None,
        duration_seconds=parsed.get("duration_seconds"),
        cost_usd=parsed.get("cost_usd"),
        model=parsed.get("model"),
        error_class=parsed.get("error_class"),
        error_detail=parsed.get("error_detail"),
        started_at=parsed.get("started_at"),
        finished_at=parsed.get("finished_at"),
        run_id=parsed.get("run_id"),
    )


def collect_run_reports(runs_dir: Path) -> list[RunReportData]:
    if not runs_dir.is_dir():
        return []
    reports: list[RunReportData] = []
    for item in sorted(runs_dir.iterdir()):
        if item.is_dir():
            try:
                reports.append(read_run_report(item))
            except (FileNotFoundError, ValueError, json.JSONDecodeError):
                continue
    return reports
