#!/usr/bin/env python3
"""aggregate_runs.py — aggregiert Run-Reports unter reports/runs/.

Verwendet ``metadata.json`` jedes Run-Verzeichnisses und projiziert die
Felder ``status``, ``run_outcome`` und ``provider_scorecard`` auf eine
flache Tabelle. Optional als Markdown, TSV, JSON oder als reine
Run-Outcome-Verteilung.

Verwendung:

    python helpers/aggregate_runs.py --reports-dir reports/runs
    python helpers/aggregate_runs.py --reports-dir reports/runs --format tsv
    python helpers/aggregate_runs.py --reports-dir reports/runs --format outcome
    python helpers/aggregate_runs.py --reports-dir reports/runs \\
        --run-id 20260614-153038-myrepo-issue-3 --format text
    python helpers/aggregate_runs.py --reports-dir reports/runs \\
        --status-filter pr_created,pr_created_from_existing_branch
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import sys
from pathlib import Path
from typing import Iterable

REPO_ROOT = Path(__file__).resolve().parents[4]
SCRIPTS_DIR = REPO_ROOT / "scripts"
# ``solver_reporting`` importiert selbst mit ``from scripts.utils import ...``,
# daher muss der Repo-Root (nicht scripts/) im Pfad liegen.
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

SCORECARD_COLUMNS = (
    "run_id",
    "status",
    "model_req",
    "model_act",
    "fallback",
    "duration_s",
    "exit",
    "test",
    "cost_usd",
    "cost_src",
)

OUTCOME_FIELDS = (
    "worker_status",
    "has_changes",
    "test_status",
    "delivery_status",
    "failure_class",
    "recovery_status",
)


def load_run_report(reports_dir: Path, run_id: str) -> dict | None:
    """Lädt metadata.json aus einem Run-Verzeichnis."""
    metadata_path = reports_dir / run_id / "metadata.json"
    if not metadata_path.is_file():
        return None
    try:
        return json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def project_scorecard(run_id: str, metadata: dict) -> dict[str, object]:
    """Projiziert metadata.provider_scorecard auf eine flache Zeile."""
    scorecard = metadata.get("provider_scorecard") or {}
    return {
        "run_id": run_id,
        "status": metadata.get("status", ""),
        "model_req": scorecard.get("requested_model", ""),
        "model_act": scorecard.get("actual_model", ""),
        "fallback": scorecard.get("fallback_source", "") or "",
        "duration_s": scorecard.get("duration_seconds", "") or "",
        "exit": scorecard.get("worker_exit_code", "") or "",
        "test": scorecard.get("test_result", "") or "",
        "cost_usd": scorecard.get("estimated_cost", "") or "",
        "cost_src": scorecard.get("cost_source", "") or "",
    }


def list_run_ids(reports_dir: Path) -> list[str]:
    """Liefert alle Run-Verzeichnisse sortiert nach Name."""
    if not reports_dir.is_dir():
        return []
    return sorted(
        entry.name
        for entry in reports_dir.iterdir()
        if entry.is_dir()
    )


def render_markdown(rows: list[dict]) -> str:
    if not rows:
        return "(keine Run-Reports gefunden)"
    header = "| " + " | ".join(SCORECARD_COLUMNS) + " |"
    separator = "|" + "|".join(["--------"] * len(SCORECARD_COLUMNS)) + "|"
    body = []
    for row in rows:
        cells = [str(row.get(col, "")) for col in SCORECARD_COLUMNS]
        body.append("| " + " | ".join(cells) + " |")
    return "\n".join([header, separator, *body]) + "\n"


def render_tsv(rows: list[dict]) -> str:
    if not rows:
        return ""
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer,
        fieldnames=list(SCORECARD_COLUMNS),
        delimiter="\t",
    )
    writer.writeheader()
    for row in rows:
        writer.writerow({col: row.get(col, "") for col in SCORECARD_COLUMNS})
    return buffer.getvalue()


def render_json(rows: list[dict]) -> str:
    return json.dumps(rows, indent=2, ensure_ascii=False) + "\n"


def render_text(metadata: dict) -> str:
    """Rendert einen einzelnen Run-Report als Klartext."""
    scorecard = metadata.get("provider_scorecard") or {}
    outcome = metadata.get("run_outcome") or {}
    runtime = metadata.get("opencode_runtime") or {}
    lines = [
        f"status:                {metadata.get('status', '')}",
        f"repo:                  {metadata.get('repo', '')}",
        f"issue:                 {metadata.get('issue', '')}",
        f"branch:                {metadata.get('branch', '')}",
        f"model:                 {metadata.get('model', '')}",
        f"worker_exit_code:      {metadata.get('worker_exit_code', '')}",
        f"pr_url:                {metadata.get('pr_url', '')}",
        f"preserved_worktree:    {metadata.get('preserved_worktree', '')}",
        "",
        "--- run_outcome ---",
    ]
    for key in OUTCOME_FIELDS:
        lines.append(f"{key:22}{outcome.get(key, '')}")
    lines.append("")
    lines.append("--- provider_scorecard ---")
    for key in (
        "requested_model",
        "actual_model",
        "fallback_source",
        "duration_seconds",
        "worker_exit_code",
        "run_status",
        "pr_url",
        "test_command",
        "test_result",
        "no_change",
        "fallback_used",
        "estimated_cost",
        "cost_currency",
        "cost_confidence",
        "cost_source",
    ):
        lines.append(f"  {key:22}{scorecard.get(key, '')}")
    lines.append("")
    lines.append("--- opencode_runtime ---")
    lines.append(f"  wal_failure:           {runtime.get('wal_failure', '')}")
    lines.append(f"  edit_loop:             {runtime.get('edit_loop', '')}")
    lines.append(f"  edit_failure_count:    {runtime.get('edit_failure_count', '')}")
    files = runtime.get("edit_failure_files", []) or []
    lines.append(f"  edit_failure_files:    {', '.join(files) if files else ''}")
    return "\n".join(lines) + "\n"


def aggregate_outcome(reports: list[dict]) -> dict[str, dict[str, int]]:
    """Aggregiert die run_outcome-Felder zu Verteilungen."""
    distribution: dict[str, dict[str, int]] = {
        field: {} for field in OUTCOME_FIELDS
    }
    for report in reports:
        outcome = (report.get("metadata") or {}).get("run_outcome") or {}
        for field in OUTCOME_FIELDS:
            value = outcome.get(field)
            if value is None:
                continue
            key = str(value)
            distribution[field][key] = distribution[field].get(key, 0) + 1
    return distribution


def render_outcome(reports: list[dict]) -> str:
    if not reports:
        return "(keine Run-Reports gefunden)"
    distribution = aggregate_outcome(reports)
    total = len(reports)
    lines = [f"=== Run-Outcome-Verteilung ({total} Runs) ===", ""]
    for field in OUTCOME_FIELDS:
        counts = distribution[field]
        if not counts:
            lines.append(f"{field:22}(keine Daten)")
            continue
        parts = ", ".join(
            f"{key}={value}" for key, value in sorted(counts.items())
        )
        lines.append(f"{field:22}{parts}")
    return "\n".join(lines) + "\n"


def filter_reports(
    reports: list[dict],
    status_filter: Iterable[str] | None = None,
    repo_filter: str | None = None,
) -> list[dict]:
    filtered = reports
    if status_filter:
        wanted = {s.strip() for s in status_filter if s.strip()}
        if wanted:
            filtered = [
                r for r in filtered
                if (r.get("metadata") or {}).get("status") in wanted
            ]
    if repo_filter:
        filtered = [
            r for r in filtered
            if (r.get("metadata") or {}).get("repo") == repo_filter
        ]
    return filtered


def collect_reports(reports_dir: Path, run_id: str | None = None) -> list[dict]:
    if run_id:
        run_ids = [run_id]
    else:
        run_ids = list_run_ids(reports_dir)
    collected = []
    for rid in run_ids:
        metadata = load_run_report(reports_dir, rid)
        if metadata is None:
            continue
        collected.append({"run_id": rid, "metadata": metadata})
    return collected


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Aggregiert Run-Reports unter reports/runs/."
    )
    parser.add_argument(
        "--reports-dir",
        default="reports/runs",
        help="Verzeichnis mit den Run-Report-Unterordnern (Standard: reports/runs).",
    )
    parser.add_argument(
        "--run-id",
        default=None,
        help="Nur einen einzelnen Run aggregieren (Verzeichnisname).",
    )
    parser.add_argument(
        "--format",
        choices=("markdown", "tsv", "json", "text", "outcome"),
        default="markdown",
        help="Ausgabe-Format (Standard: markdown).",
    )
    parser.add_argument(
        "--status-filter",
        default=None,
        help="Komma-getrennte Liste erlaubter status-Werte.",
    )
    parser.add_argument(
        "--repo-filter",
        default=None,
        help="Nur Reports für ein bestimmtes Repo anzeigen.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    reports_dir = Path(args.reports_dir)
    if not reports_dir.is_absolute():
        reports_dir = REPO_ROOT / reports_dir

    reports = collect_reports(reports_dir, args.run_id)
    if args.format == "text":
        if not reports:
            print("(keine Run-Reports gefunden)", file=sys.stderr)
            return 1
        if args.run_id is None:
            print(
                "--run-id ist für --format text erforderlich",
                file=sys.stderr,
            )
            return 2
        sys.stdout.write(render_text(reports[0]["metadata"]))
        return 0

    status_filter = (
        args.status_filter.split(",") if args.status_filter else None
    )
    filtered = filter_reports(reports, status_filter, args.repo_filter)

    if args.format == "outcome":
        sys.stdout.write(render_outcome(filtered))
        return 0

    rows = [project_scorecard(r["run_id"], r["metadata"]) for r in filtered]
    if args.format == "markdown":
        sys.stdout.write(render_markdown(rows))
    elif args.format == "tsv":
        sys.stdout.write(render_tsv(rows))
    elif args.format == "json":
        sys.stdout.write(render_json(rows))
    return 0


if __name__ == "__main__":
    sys.exit(main())
