#!/usr/bin/env python3
"""
status_dashboard.py - Lokales HTML-Dashboard fuer Run-Reports
Morpheus-Style AI Issue Solver - github.com/SaJaToGu

Liest reports/runs/*/summary.txt und erzeugt eine statische HTML-Uebersicht
ueber laufende, erfolgreiche, fehlgeschlagene und No-op-Jobs.

Verwendung:
    python scripts/status_dashboard.py
    python scripts/status_dashboard.py --runs-dir reports/runs --output reports/status-dashboard.html
    python scripts/status_dashboard.py --owner SaJaToGu
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timedelta
from html import escape
import os
import re
import sys
from pathlib import Path
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).parent))
from utils import load_env, print_banner, print_step  # noqa: E402


DEFAULT_RUNS_DIR = Path("reports") / "runs"
DEFAULT_OUTPUT = Path("reports") / "status-dashboard.html"
GITHUB_RE = re.compile(r"https://github\.com/([^/\s]+)/([^/\s]+)/")

STATUS_LABELS = {
    "running": "Running",
    "failed": "Failed",
    "successful": "Successful",
    "noop": "No-op",
    "archived": "Archived",
    "unknown": "Unknown",
}

STATUS_ORDER = ("running", "failed", "successful", "noop", "archived", "unknown")
SUCCESS_STATUSES = {
    "pr_created",
    "pr_created_from_existing_branch",
    "cleanup_successful",
}
NOOP_STATUSES = {
    "no_changes",
    "skip_existing_pr",
    "skip_merged_pr",
    "skip_closed_pr",
    "cleanup_noop",
}
FAILED_STATUSES = {
    "branch_create_failed",
    "checkout_failed",
    "clone_failed",
    "nonzero_without_changes",
    "pr_failed",
    "pr_failed_from_existing_branch",
    "push_failed",
    "cleanup_failed",
}
ARCHIVED_STATUSES = {
    "archived",
    "cleanup_archived",
}
CLEANUP_STATUS_VALUES = {
    "successful": "cleanup_successful",
    "failed": "cleanup_failed",
    "noop": "cleanup_noop",
    "archived": "archived",
}


@dataclass(frozen=True)
class DashboardRun:
    path: Path
    name: str
    created_at: datetime | None
    status: str
    category: str
    repo: str
    issue_number: str
    branch: str
    model: str
    worker_exit_code: str
    pr_url: str
    note: str
    output_tail: str


@dataclass(frozen=True)
class CleanupResult:
    candidates: list[DashboardRun]
    changed: list[Path]
    target_status: str
    cutoff: datetime
    dry_run: bool


def parse_summary(path: Path) -> dict[str, str]:
    fields: dict[str, str] = {}
    if not path.exists():
        return fields

    current_multiline_key = None
    multiline_parts: list[str] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        if current_multiline_key:
            multiline_parts.append(raw_line)
            continue

        if not raw_line.strip():
            continue
        key, separator, value = raw_line.partition(":")
        if not separator:
            continue
        key = key.strip()
        value = value.strip()
        if key == "output_tail":
            current_multiline_key = key
            if value:
                multiline_parts.append(value)
            continue
        fields[key] = value

    if current_multiline_key:
        fields[current_multiline_key] = "\n".join(multiline_parts).strip()
    return fields


def parse_created_at(run_dir_name: str) -> datetime | None:
    match = re.match(r"^(\d{8}-\d{6})(?:-(\d{6}))?", run_dir_name)
    if not match:
        return None
    value = "".join(part for part in match.groups(default="") if part)
    fmt = "%Y%m%d-%H%M%S%f" if match.group(2) else "%Y%m%d-%H%M%S"
    try:
        return datetime.strptime(value, fmt)
    except ValueError:
        return None


def classify_status(status: str, worker_exit_code: str = "") -> str:
    if not status:
        return "unknown"
    if status == "started":
        return "running"
    if status in ARCHIVED_STATUSES:
        return "archived"
    if status in SUCCESS_STATUSES:
        return "successful"
    if status in NOOP_STATUSES:
        return "noop"
    if status in FAILED_STATUSES or status.endswith("_failed"):
        return "failed"
    if worker_exit_code and worker_exit_code != "0":
        return "failed"
    return "noop"


def read_runs(runs_dir: Path) -> list[DashboardRun]:
    if not runs_dir.exists():
        return []

    runs = []
    for run_dir in sorted((path for path in runs_dir.iterdir() if path.is_dir()), reverse=True):
        fields = parse_summary(run_dir / "summary.txt")
        status = fields.get("status", "")
        exit_code = fields.get("worker_exit_code", "")
        runs.append(
            DashboardRun(
                path=run_dir,
                name=run_dir.name,
                created_at=parse_created_at(run_dir.name),
                status=status,
                category=classify_status(status, exit_code),
                repo=fields.get("repo") or fields.get("selected_repo", ""),
                issue_number=fields.get("issue_number") or fields.get("issue", ""),
                branch=fields.get("branch", ""),
                model=fields.get("model", ""),
                worker_exit_code=exit_code,
                pr_url=fields.get("pr_url", ""),
                note=fields.get("note") or fields.get("cleanup_note", ""),
                output_tail=fields.get("output_tail", ""),
            )
        )
    return runs


def cleanup_candidates(runs: list[DashboardRun], cutoff: datetime,
                       include_undated: bool = False) -> list[DashboardRun]:
    candidates = []
    for run in runs:
        if run.category not in {"running", "unknown"}:
            continue
        if run.created_at is None:
            if include_undated:
                candidates.append(run)
            continue
        if run.created_at <= cutoff:
            candidates.append(run)
    return candidates


def write_cleanup_status(run: DashboardRun, status: str,
                         cleaned_at: datetime | None = None) -> Path:
    cleaned_at = cleaned_at or datetime.now()
    summary_path = run.path / "summary.txt"
    lines = []
    if summary_path.exists():
        lines = summary_path.read_text(encoding="utf-8").splitlines()

    status_line = f"status: {status}"
    for index, line in enumerate(lines):
        key, separator, _value = line.partition(":")
        if separator and key.strip() == "status":
            lines[index] = status_line
            break
    else:
        lines.insert(0, status_line)

    insert_at = len(lines)
    for index, line in enumerate(lines):
        key, separator, _value = line.partition(":")
        if separator and key.strip() == "output_tail":
            insert_at = index
            break

    cleanup_lines = [
        f"cleanup_at: {cleaned_at.isoformat(timespec='seconds')}",
        "cleanup_note: Dashboard-Cleanup hat diesen alten unvollstaendigen Run markiert.",
    ]
    if insert_at > 0 and lines[insert_at - 1].strip():
        cleanup_lines.insert(0, "")
    if insert_at < len(lines) and lines[insert_at].strip():
        cleanup_lines.append("")
    lines[insert_at:insert_at] = cleanup_lines

    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return summary_path


def cleanup_stale_runs(runs_dir: Path, mark: str = "archived",
                       older_than_days: int = 7,
                       apply: bool = False,
                       include_undated: bool = False,
                       now_fn=datetime.now) -> CleanupResult:
    if mark not in CLEANUP_STATUS_VALUES:
        choices = ", ".join(sorted(CLEANUP_STATUS_VALUES))
        raise ValueError(f"ungueltiger Cleanup-Status {mark!r}; erlaubt: {choices}")
    if older_than_days < 0:
        raise ValueError("--older-than-days darf nicht negativ sein")

    now = now_fn()
    cutoff = now - timedelta(days=older_than_days)
    runs = read_runs(runs_dir)
    candidates = cleanup_candidates(runs, cutoff, include_undated=include_undated)
    target_status = CLEANUP_STATUS_VALUES[mark]
    changed = []
    if apply:
        for run in candidates:
            changed.append(write_cleanup_status(run, target_status, cleaned_at=now))
    return CleanupResult(candidates, changed, target_status, cutoff, dry_run=not apply)


def infer_owner_from_runs(runs: list[DashboardRun]) -> str | None:
    for run in runs:
        match = GITHUB_RE.match(run.pr_url)
        if match:
            return match.group(1)
    return None


def repo_name_for_url(repo: str) -> str:
    return repo.split("/", 1)[1] if "/" in repo else repo


def repo_owner_for_url(repo: str, owner: str | None) -> str | None:
    if "/" in repo:
        return repo.split("/", 1)[0]
    return owner


def github_links(run: DashboardRun, owner: str | None) -> dict[str, str]:
    repo_owner = repo_owner_for_url(run.repo, owner)
    repo_name = repo_name_for_url(run.repo)
    if not repo_owner or not repo_name:
        return {}

    base = f"https://github.com/{quote(repo_owner)}/{quote(repo_name)}"
    links = {}
    if run.issue_number:
        links["issue"] = f"{base}/issues/{quote(run.issue_number)}"
    if run.branch:
        links["branch"] = f"{base}/tree/{quote(run.branch, safe='')}"
    if run.pr_url:
        links["pr"] = run.pr_url
    return links


def format_datetime(value: datetime | None) -> str:
    if not value:
        return "unbekannt"
    return value.strftime("%Y-%m-%d %H:%M:%S")


def render_link(url: str, label: str) -> str:
    return f'<a href="{escape(url, quote=True)}">{escape(label)}</a>'


def render_run_row(run: DashboardRun, owner: str | None, output_path: Path) -> str:
    links = github_links(run, owner)
    run_link = run.path / "summary.txt"
    try:
        href = os.path.relpath(run_link, output_path.parent)
    except ValueError:
        href = str(run_link)

    actions = [render_link(href, "Summary")]
    if "issue" in links:
        actions.append(render_link(links["issue"], f"Issue #{run.issue_number}"))
    if "branch" in links:
        actions.append(render_link(links["branch"], "Branch"))
    if "pr" in links:
        actions.append(render_link(links["pr"], "Pull Request"))

    tail = ""
    if run.output_tail:
        tail = (
            "<details><summary>Output tail</summary>"
            f"<pre>{escape(run.output_tail)}</pre></details>"
        )

    note = f"<div class=\"note\">{escape(run.note)}</div>" if run.note else ""
    return "\n".join([
        "<tr>",
        f'  <td><span class="badge badge-{escape(run.category)}">{escape(STATUS_LABELS[run.category])}</span></td>',
        f"  <td>{escape(format_datetime(run.created_at))}</td>",
        f"  <td>{escape(run.repo or '-')}</td>",
        f"  <td>{escape('#' + run.issue_number if run.issue_number else '-')}</td>",
        f"  <td><code>{escape(run.branch or '-')}</code></td>",
        f"  <td>{escape(run.model or '-')}</td>",
        f"  <td>{escape(run.worker_exit_code or '-')}</td>",
        f"  <td>{escape(run.status)}{note}{tail}</td>",
        f"  <td>{' '.join(actions)}</td>",
        "</tr>",
    ])


def render_dashboard(runs: list[DashboardRun], owner: str | None, output_path: Path,
                     generated_at: datetime | None = None,
                     allow_shutdown: bool = False,
                     refresh_seconds: int | None = None) -> str:
    generated_at = generated_at or datetime.now()
    counts = {category: 0 for category in STATUS_ORDER}
    for run in runs:
        counts[run.category] = counts.get(run.category, 0) + 1

    rows = "\n".join(render_run_row(run, owner, output_path) for run in runs)
    if not rows:
        rows = (
            '<tr><td colspan="9" class="empty">'
            "Keine Run-Reports unter reports/runs/ gefunden."
            "</td></tr>"
        )

    cards = "\n".join(
        f'<section class="metric metric-{category}">'
        f'<span>{escape(STATUS_LABELS[category])}</span>'
        f'<strong>{counts.get(category, 0)}</strong>'
        "</section>"
        for category in STATUS_ORDER
    )

    refresh_meta = ""
    refresh_label = ""
    if refresh_seconds and refresh_seconds > 0:
        refresh_meta = f'<meta http-equiv="refresh" content="{int(refresh_seconds)}">'
        refresh_label = f'<span class="refresh-label">Auto-refresh: {int(refresh_seconds)}s</span>'

    shutdown_button = ""
    shutdown_script = ""
    if allow_shutdown:
        shutdown_button = (
            '<button class="shutdown-button" type="button" onclick="shutdownServer()">'
            'Dashboard-Server beenden'
            '</button>'
        )
        shutdown_script = """
  <script>
    async function shutdownServer() {
      const button = document.querySelector('.shutdown-button');
      if (button) {
        button.disabled = true;
        button.textContent = 'Server wird beendet...';
      }
      try {
        await fetch('/__shutdown__', { method: 'POST' });
        const notice = document.querySelector('.shutdown-notice');
        if (notice) {
          notice.textContent = 'Dashboard-Server wurde beendet. Dieses Fenster kann offen bleiben.';
        }
      } catch (error) {
        const notice = document.querySelector('.shutdown-notice');
        if (notice) {
          notice.textContent = 'Server konnte nicht per Button beendet werden. Terminal mit Ctrl+C stoppen.';
        }
        if (button) {
          button.disabled = false;
          button.textContent = 'Dashboard-Server beenden';
        }
      }
    }
  </script>
"""

    return f"""<!doctype html>
<html lang="de">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>AI Issue Solver Status Dashboard</title>
  {refresh_meta}
  <style>
    :root {{
      color-scheme: light;
      --bg: #f6f7f9;
      --panel: #ffffff;
      --text: #172026;
      --muted: #64707d;
      --line: #d8dee6;
      --running: #276ef1;
      --success: #18794e;
      --failed: #c92a2a;
      --noop: #6b7280;
      --archived: #7c4a03;
      --unknown: #8a63d2;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font: 14px/1.45 system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }}
    header {{
      padding: 28px 32px 18px;
      border-bottom: 1px solid var(--line);
      background: var(--panel);
    }}
    h1 {{ margin: 0 0 6px; font-size: 26px; letter-spacing: 0; }}
    .meta {{ color: var(--muted); }}
    .header-row {{ display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; }}
    .shutdown-button {{
      border: 1px solid #b42318;
      background: #c92a2a;
      color: #fff;
      border-radius: 6px;
      padding: 9px 12px;
      font: inherit;
      cursor: pointer;
    }}
    .shutdown-button:disabled {{ opacity: .65; cursor: default; }}
    .shutdown-notice {{ margin-top: 6px; color: var(--muted); min-height: 20px; }}
    .refresh-label {{ display: inline-block; margin-top: 6px; color: var(--muted); }}
    main {{ padding: 24px 32px 36px; }}
    .metrics {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
      gap: 12px;
      margin-bottom: 22px;
    }}
    .metric {{
      border-left: 5px solid var(--line);
      background: var(--panel);
      padding: 14px 16px;
      border-radius: 6px;
      box-shadow: 0 1px 2px rgb(0 0 0 / 6%);
    }}
    .metric span {{ display: block; color: var(--muted); font-size: 13px; }}
    .metric strong {{ display: block; margin-top: 4px; font-size: 28px; }}
    .metric-running {{ border-color: var(--running); }}
    .metric-successful {{ border-color: var(--success); }}
    .metric-failed {{ border-color: var(--failed); }}
    .metric-noop {{ border-color: var(--noop); }}
    .metric-archived {{ border-color: var(--archived); }}
    .metric-unknown {{ border-color: var(--unknown); }}
    .table-wrap {{
      overflow-x: auto;
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 6px;
    }}
    table {{ width: 100%; border-collapse: collapse; min-width: 980px; }}
    th, td {{ padding: 10px 12px; border-bottom: 1px solid var(--line); text-align: left; vertical-align: top; }}
    th {{ color: var(--muted); font-size: 12px; text-transform: uppercase; letter-spacing: .04em; background: #fbfcfd; }}
    tr:last-child td {{ border-bottom: 0; }}
    code {{ font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 12px; }}
    a {{ color: #1259c3; text-decoration: none; margin-right: 10px; white-space: nowrap; }}
    a:hover {{ text-decoration: underline; }}
    .badge {{
      display: inline-block;
      min-width: 82px;
      padding: 3px 8px;
      border-radius: 999px;
      color: #fff;
      font-size: 12px;
      text-align: center;
    }}
    .badge-running {{ background: var(--running); }}
    .badge-successful {{ background: var(--success); }}
    .badge-failed {{ background: var(--failed); }}
    .badge-noop {{ background: var(--noop); }}
    .badge-archived {{ background: var(--archived); }}
    .badge-unknown {{ background: var(--unknown); }}
    .note {{ margin-top: 4px; color: var(--muted); }}
    details {{ margin-top: 6px; }}
    summary {{ cursor: pointer; color: #1259c3; }}
    pre {{
      max-width: 620px;
      max-height: 260px;
      overflow: auto;
      margin: 8px 0 0;
      padding: 10px;
      background: #111827;
      color: #e5e7eb;
      border-radius: 5px;
      font-size: 12px;
    }}
    .empty {{ text-align: center; color: var(--muted); padding: 28px; }}
    @media (max-width: 720px) {{
      header, main {{ padding-left: 16px; padding-right: 16px; }}
      h1 {{ font-size: 22px; }}
    }}
  </style>
</head>
<body>
  <header>
    <div class="header-row">
      <div>
        <h1>AI Issue Solver Status Dashboard</h1>
        <div class="meta">Generiert: {escape(format_datetime(generated_at))} · Runs: {len(runs)}</div>
        {refresh_label}
        <div class="shutdown-notice" aria-live="polite"></div>
      </div>
      <div>{shutdown_button}</div>
    </div>
  </header>
  <main>
    <section class="metrics" aria-label="Status-Zusammenfassung">
      {cards}
    </section>
    <section class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Status</th>
            <th>Zeit</th>
            <th>Repo</th>
            <th>Issue</th>
            <th>Branch</th>
            <th>Modell</th>
            <th>Exit</th>
            <th>Details</th>
            <th>Links</th>
          </tr>
        </thead>
        <tbody>
          {rows}
        </tbody>
      </table>
    </section>
  </main>
  {shutdown_script}
</body>
</html>
"""


def write_dashboard(runs: list[DashboardRun], output_path: Path,
                    owner: str | None = None,
                    allow_shutdown: bool = False,
                    refresh_seconds: int | None = None) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    effective_owner = owner or infer_owner_from_runs(runs)
    output_path.write_text(
        render_dashboard(
            runs,
            effective_owner,
            output_path,
            allow_shutdown=allow_shutdown,
            refresh_seconds=refresh_seconds,
        ),
        encoding="utf-8",
    )
    return output_path


def print_cleanup_preview(result: CleanupResult) -> None:
    mode = "Dry-run" if result.dry_run else "Apply"
    print(f"   Modus: {mode}")
    print(f"   Zielstatus: {result.target_status}")
    print(f"   Cutoff: {format_datetime(result.cutoff)}")
    print(f"   Kandidaten: {len(result.candidates)}")
    for run in result.candidates:
        print(
            "   - "
            f"{run.name} | {format_datetime(run.created_at)} | "
            f"{run.category} | {run.repo or '-'} | "
            f"Issue {run.issue_number or '-'}"
        )
    if result.dry_run and result.candidates:
        print("   Keine Dateien geaendert. Mit --apply wirklich markieren.")
    if not result.dry_run:
        print(f"   Geaenderte summary.txt-Dateien: {len(result.changed)}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Erzeugt ein lokales HTML-Dashboard aus reports/runs/."
    )
    parser.add_argument("--runs-dir", default=str(DEFAULT_RUNS_DIR), help="Run-Report-Verzeichnis")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="Zielpfad fuer die HTML-Datei")
    parser.add_argument("--owner", help="GitHub Owner fuer Issue- und Branch-Links")
    parser.add_argument(
        "--cleanup-stale",
        action="store_true",
        help="Alte running/unknown Run-Reports zuerst als Dry-run anzeigen",
    )
    parser.add_argument(
        "--mark",
        choices=sorted(CLEANUP_STATUS_VALUES),
        default="archived",
        help="Zielstatus fuer --cleanup-stale, Standard: archived",
    )
    parser.add_argument(
        "--older-than-days",
        type=int,
        default=7,
        help="Nur Runs aelter als diese Anzahl Tage markieren, Standard: 7",
    )
    parser.add_argument(
        "--include-undated",
        action="store_true",
        help="Auch Runs ohne parsbares Datum als Cleanup-Kandidaten aufnehmen",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Cleanup wirklich schreiben; ohne diese Option bleibt es beim Dry-run",
    )
    args = parser.parse_args()

    config = load_env()
    owner = args.owner or config.get("GITHUB_USER")
    runs_dir = Path(args.runs_dir)
    output_path = Path(args.output)

    if args.cleanup_stale:
        print_banner("STALE RUN-REPORTS BEREINIGEN")
        print_step(1, f"Pruefe alte Run-Reports in {runs_dir}")
        try:
            result = cleanup_stale_runs(
                runs_dir,
                mark=args.mark,
                older_than_days=args.older_than_days,
                apply=args.apply,
                include_undated=args.include_undated,
            )
        except ValueError as exc:
            print(f"Fehler: {exc}", file=sys.stderr)
            return 2
        print_cleanup_preview(result)
        return 0

    print_banner("STATUS-DASHBOARD GENERIEREN")
    print_step(1, f"Lese Run-Reports aus {runs_dir}")
    runs = read_runs(runs_dir)
    print(f"   Gefundene Runs: {len(runs)}")

    print_step(2, f"Schreibe HTML nach {output_path}")
    write_dashboard(runs, output_path, owner=owner)
    print(f"   Dashboard: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
