#!/usr/bin/env python3
"""
run_overnight.py - Wrapper fuer laengere unbeaufsichtigte Batch-Laeufe.

Der Runner aktualisiert zuerst den Basis-Branch, fuehrt die Tests aus, startet
danach den begrenzten Batch-Solver und regeneriert abschliessend das Dashboard.
Alle Schritte schreiben eigene Logs in reports/overnight/<timestamp>/.
"""

from __future__ import annotations

import argparse
import contextlib
import os
import platform
import shutil
from dataclasses import dataclass
from datetime import datetime
import json
import re
import shlex
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from solve_issues import (  # noqa: E402
    MODEL_CONFIGS,
)
from solve_issues_batch import DEFAULT_WORKERS, positive_int  # noqa: E402
import solver_commands  # noqa: E402
from solver_reporting import read_normalized_run_outcome  # noqa: E402
from workers.opencode_diagnostics import (  # noqa: E402
    run_opencode_preflight_guard,
)
from utils import print_banner, print_err, print_ok, print_step, print_warn  # noqa: E402


# Regex zur Erkennung von Konfliktmarkern in Dateien
CONFLICT_MARKER_RE = re.compile(r"^\s*(?:<{7}\s|>{7}\s|={7}\s*$)")


DEFAULT_BASE_BRANCH = "main"
DEFAULT_LABEL = "ai-generated"
DEFAULT_TEST_COMMAND = [sys.executable, "-m", "unittest", "discover", "-s", "tests"]
DEFAULT_OVERNIGHT_DIR = Path("reports") / "overnight"
DEFAULT_DASHBOARD_OUTPUT = Path("reports") / "status-dashboard.html"


@dataclass(frozen=True)
class StepResult:
    name: str
    command: list[str]
    returncode: int
    log_path: Path
    duration_seconds: float
    skipped: bool = False

    @property
    def ok(self) -> bool:
        return self.skipped or self.returncode == 0


def get_step_priority(step: StepResult) -> int:
    """
    Prioritaets-Funktion fuer die Sortierung von Schritten in Summaries.
    
    Rueckgabewert:
        0 = hohe Prioritaet (erfolgreich, clean)
        1 = mittlere Prioritaet (uebersprungen)
        2 = niedrige Prioritaet (fehlgeschlagen)
    
    Sortierreihenfolge: clean runs zuerst, dann skipped, dann failed.
    """
    if step.ok and not step.skipped:
        return 0  # Erfolgreiche Schritte
    if step.skipped:
        return 1  # Uebersprungene Schritte
    return 2  # Fehlerhafte Schritte


def get_step_badge(step: StepResult) -> str:
    """
    Erzeugt ein Status-Badge fuer einen Schritt.
    
    Badges:
        [OK]     - Schritt erfolgreich (exit_code = 0)
        [SKIP]   - Schritt uebersprungen
        [FAIL]   - Schritt fehlgeschlagen (exit_code != 0)
    """
    if step.skipped:
        return "[SKIP]"
    if step.returncode == 0:
        return "[OK]"
    return "[FAIL]"


def shell_words(command: str) -> list[str]:
    try:
        return shlex.split(command)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"ungueltiger Befehl: {exc}") from exc


def command_to_text(command: list[str]) -> str:
    return " ".join(shlex.quote(part) for part in command)


def create_session_dir(root: Path, now_fn=datetime.now) -> Path:
    session_dir = root / now_fn().strftime("%Y%m%d-%H%M%S")
    suffix = 1
    candidate = session_dir
    while candidate.exists():
        suffix += 1
        candidate = root / f"{session_dir.name}-{suffix}"
    candidate.mkdir(parents=True)
    return candidate


def build_pull_command(base_branch: str) -> list[str]:
    return ["git", "pull", "--ff-only", "origin", base_branch]


def build_caffeinate_command(pid: int | None = None) -> list[str]:
    command = ["caffeinate", "-dimsu"]
    if pid is not None:
        command.extend(["-w", str(pid)])
    return command


def can_use_caffeinate(system_name: str | None = None, which_fn=shutil.which) -> bool:
    return (system_name or platform.system()) == "Darwin" and bool(which_fn("caffeinate"))


@contextlib.contextmanager
def keep_awake(enabled: bool, log_path: Path):
    if not enabled:
        yield
        return

    write_log_header(log_path, "caffeinate", build_caffeinate_command(os.getpid()))
    if not can_use_caffeinate():
        with log_path.open("a", encoding="utf-8") as log_file:
            log_file.write("skipped: caffeinate ist nur auf macOS mit installiertem caffeinate verfuegbar\n")
        print_warn("caffeinate nicht verfuegbar; fahre ohne Sleep-Schutz fort")
        yield
        return

    process: subprocess.Popen | None = None
    try:
        with log_path.open("a", encoding="utf-8") as log_file:
            log_file.write("status: started\n")
            log_file.flush()
            process = subprocess.Popen(
                build_caffeinate_command(os.getpid()),
                stdout=log_file,
                stderr=subprocess.STDOUT,
            )
        print_ok("caffeinate aktiv: der Mac bleibt fuer diesen Nachtlauf wach")
        yield
    finally:
        if process and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        with log_path.open("a", encoding="utf-8") as log_file:
            log_file.write(f"finished_at: {datetime.now().isoformat(timespec='seconds')}\n")


def write_log_header(log_path: Path, name: str, command: list[str] | None) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f"step: {name}",
        f"started_at: {datetime.now().isoformat(timespec='seconds')}",
    ]
    if command:
        lines.append(f"command: {command_to_text(command)}")
    lines.append("")
    log_path.write_text("\n".join(lines), encoding="utf-8")


def run_logged_command(
    name: str,
    command: list[str],
    cwd: Path,
    log_path: Path,
    stream_output: bool = True,
) -> StepResult:
    write_log_header(log_path, name, command)
    started_at = time.monotonic()
    try:
        with log_path.open("a", encoding="utf-8") as log_file:
            process = subprocess.Popen(
                command,
                cwd=cwd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
            assert process.stdout is not None
            for line in process.stdout:
                log_file.write(line)
                log_file.flush()
                if stream_output:
                    print(line, end="")
            returncode = process.wait()
    except OSError as exc:
        with log_path.open("a", encoding="utf-8") as log_file:
            log_file.write(f"\nBefehl konnte nicht gestartet werden: {exc}\n")
        returncode = 127

    duration = time.monotonic() - started_at
    with log_path.open("a", encoding="utf-8") as log_file:
        log_file.write(f"\nfinished_at: {datetime.now().isoformat(timespec='seconds')}\n")
        log_file.write(f"duration_seconds: {duration:.1f}\n")
        log_file.write(f"exit_code: {returncode}\n")

    return StepResult(name, command, returncode, log_path, duration)


def skipped_step(name: str, log_path: Path, reason: str) -> StepResult:
    write_log_header(log_path, name, None)
    with log_path.open("a", encoding="utf-8") as log_file:
        log_file.write(f"skipped: {reason}\n")
    return StepResult(name, [], 0, log_path, 0.0, skipped=True)


def format_duration(seconds: float) -> str:
    minutes, secs = divmod(int(round(seconds)), 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}h {minutes}m {secs}s"
    if minutes:
        return f"{minutes}m {secs}s"
    return f"{secs}s"


@dataclass(frozen=True)
class IssueOutcome:
    """Zusammenfassung der Ergebnisse eines einzelnen Issue-Runs."""
    repo: str
    issue_number: str
    issue_title: str
    status: str
    category: str
    worker_exit_code: str
    pr_url: str
    git_diff_stat: str
    warning_markers: str  # "conflict" oder "syntax" oder leer
    branch: str
    model: str
    run_dir: str


def parse_summary_file(summary_path: Path) -> dict[str, str]:
    """Parsed eine summary.txt Datei in ein Dictionary."""
    fields: dict[str, str] = {}
    if not summary_path.exists():
        return fields

    multiline_keys = {"git_diff_stat", "output_tail", "note", "cleanup_note"}
    current_multiline_key = None
    multiline_parts: list[str] = []

    for raw_line in summary_path.read_text(encoding="utf-8").splitlines():
        key, separator, value = raw_line.partition(":")
        key = key.strip()
        value = value.strip()
        starts_multiline_key = bool(separator and key in multiline_keys)

        if current_multiline_key:
            if starts_multiline_key:
                fields[current_multiline_key] = "\n".join(multiline_parts).strip()
                current_multiline_key = key
                multiline_parts = [value] if value else []
                continue
            multiline_parts.append(raw_line)
            continue

        if not raw_line.strip():
            continue
        if not separator:
            continue
        if key in multiline_keys:
            current_multiline_key = key
            if value:
                multiline_parts.append(value)
            continue
        fields[key] = value

    if current_multiline_key:
        fields[current_multiline_key] = "\n".join(multiline_parts).strip()
    return fields



def detect_warning_markers(run_dir: Path) -> str:
    """Erkennt Warnungsmarker in geaenderten Dateien eines Runs.

    Gibt zurueck: "conflict" wenn Konfliktmarker gefunden, "syntax" bei
    Python-Syntaxfehlern, sonst leer.
    """
    markers = []

    # Pruefe auf Konfliktmarker in git_diff_stat oder in den Dateien
    summary_path = run_dir / "summary.txt"
    fields = parse_summary_file(summary_path)

    git_diff_stat = fields.get("git_diff_stat", "")
    if git_diff_stat and "conflict" in git_diff_stat.lower():
        markers.append("conflict")

    # Pruefe output_tail auf Konfliktmarker-Hinweise
    output_tail = fields.get("output_tail", "")
    if output_tail:
        if "Konfliktmarker" in output_tail or "conflict marker" in output_tail.lower():
            markers.append("conflict")
        if "Syntaxpruefung fehlgeschlagen" in output_tail or "Syntaxfehler" in output_tail:
            markers.append("syntax")

    # Pruefe worker-output.log auf Konfliktmarker
    worker_output_path = run_dir / "worker-output.log"
    if worker_output_path.exists():
        try:
            output = worker_output_path.read_text(encoding="utf-8")
            if "enthaelt Git-Konfliktmarker" in output:
                markers.append("conflict")
            if "Python-Syntaxpruefung fehlgeschlagen" in output:
                markers.append("syntax")
        except (OSError, UnicodeDecodeError):
            pass

    return ",".join(sorted(set(markers)))


def parse_run_dir_timestamp(run_dir: Path) -> datetime | None:
    """Liest den Startzeitpunkt aus Run-Verzeichnisnamen wie YYYYMMDD-HHMMSS-..."""
    match = re.match(r"^(\d{8}-\d{6})", run_dir.name)
    if not match:
        return None
    try:
        return datetime.strptime(match.group(1), "%Y%m%d-%H%M%S")
    except ValueError:
        return None


def collect_issue_outcomes(
    runs_dir: Path,
    *,
    repo: str | None = None,
    issue_numbers: set[int] | None = None,
    started_at: datetime | None = None,
    finished_at: datetime | None = None,
    include_incomplete: bool = False,
) -> list[IssueOutcome]:
    """Sammelt IssueOutcome-Objekte aus allen Run-Reports in runs_dir.

    Optional kann die Sammlung auf eine Overnight-Session eingeschraenkt werden:
    Repo, Issue-Nummern und Zeitfenster verhindern, dass alte Reports in der
    finalen Nachtlauf-Summary auftauchen.

    Sortiert nach Run-Verzeichnisname (zeitlich absteigend).
    """
    outcomes = []

    if not runs_dir.exists():
        return outcomes

    for run_dir in sorted(runs_dir.iterdir(), reverse=True):
        if not run_dir.is_dir():
            continue

        run_started_at = parse_run_dir_timestamp(run_dir)
        if started_at and run_started_at and run_started_at < started_at:
            continue
        if finished_at and run_started_at and run_started_at > finished_at:
            continue

        summary_path = run_dir / "summary.txt"
        if not summary_path.exists():
            continue

        normalized = read_normalized_run_outcome(run_dir)
        fields = dict(normalized.summary)
        run_repo = normalized.repo
        issue_number = normalized.issue_number

        if repo and run_repo != repo:
            continue
        if issue_numbers:
            if not issue_number.isdigit() or int(issue_number) not in issue_numbers:
                continue

        status = normalized.status
        exit_code = normalized.worker_exit_code
        category = normalized.category

        # Standardmaessig unvollstaendige Runs aus Dashboards/Reports ausblenden.
        # Die Overnight-Summary blendet sie ein, damit abgebrochene Health-Stopps
        # sichtbar bleiben.
        if not include_incomplete and category in {"queued", "running", "unhealthy", "unknown"}:
            continue

        warning_markers = detect_warning_markers(run_dir)

        outcome = IssueOutcome(
            repo=run_repo,
            issue_number=issue_number,
            issue_title=normalized.issue_title,
            status=status,
            category=category,
            worker_exit_code=exit_code,
            pr_url=normalized.pr_url,
            git_diff_stat=fields.get("git_diff_stat", ""),
            warning_markers=warning_markers,
            branch=normalized.branch,
            model=normalized.model,
            run_dir=run_dir.name,
        )
        outcomes.append(outcome)
    
    # Sortiere nach Issue-Nummer (numerisch) und dann nach Run-Verzeichnis
    return sorted(outcomes, key=lambda o: (int(o.issue_number) if o.issue_number.isdigit() else 999999, o.run_dir))


def write_final_summary(
    summary_path: Path,
    session_dir: Path,
    args: argparse.Namespace,
    steps: list[StepResult],
    started_at: datetime,
    finished_at: datetime,
    runs_dir: Path | None = None,
) -> None:
    """Schreibt die finale Zusammenfassung der Overnight-Session.

    Enthaelt neben den Schritten auch eine detaillierte Uebersicht pro Issue
    mit PR-URL, Worker-Exit-Code, Warnungsmarkern, geaenderten Dateien und Status.
    """
    failed_steps = [step for step in steps if not step.ok]
    status = "failed" if failed_steps else "successful"
    lines = [
        f"status: {status}",
        f"started_at: {started_at.isoformat(timespec='seconds')}",
        f"finished_at: {finished_at.isoformat(timespec='seconds')}",
        f"duration: {format_duration((finished_at - started_at).total_seconds())}",
        f"session_dir: {session_dir}",
        f"model: {args.model}",
        f"model_name: {args.model_name or ''}",
        f"workers: {args.workers}",
        f"worker_health_timeout_minutes: {args.worker_health_timeout_minutes or ''}",
        f"unhealthy_action: {args.unhealthy_action or ''}",
        f"unhealthy_retries: {args.unhealthy_retries or ''}",
        f"verbosity: {args.verbosity or ''}",
        f"base_branch: {args.base_branch}",
        f"repo: {args.repo or ''}",
        f"issues: {', '.join(str(issue) for issue in args.issue or [])}",
        f"label: {args.label}",
        f"dry_run: {args.dry_run}",
        f"dashboard: {args.dashboard_output}",
        "workflow_congestion: see_dashboard_workflow_status",
        "",
        "steps:",
    ]
    for step in steps:
        if step.skipped:
            state = "skipped"
        else:
            state = "ok" if step.returncode == 0 else "failed"
        command = command_to_text(step.command) if step.command else ""
        lines.extend([
            f"- name: {step.name}",
            f"  status: {state}",
            f"  exit_code: {step.returncode}",
            f"  duration: {format_duration(step.duration_seconds)}",
            f"  log: {step.log_path}",
        ])
        if command:
            lines.append(f"  command: {command}")
    if failed_steps:
        lines.extend(["", "failed_steps:"])
        lines.extend(f"- {step.name}" for step in failed_steps)

    # Issue-Outcomes hinzufuegen, falls runs_dir verfuegbar
    if runs_dir and runs_dir.exists():
        issue_numbers = set(args.issue or []) or None
        outcomes = collect_issue_outcomes(
            runs_dir,
            repo=args.repo,
            issue_numbers=issue_numbers,
            started_at=started_at,
            finished_at=finished_at,
            include_incomplete=True,
        )
        if outcomes:
            lines.extend(["", "issue_outcomes:"])
            for outcome in outcomes:
                lines.extend([
                    f"- issue: {outcome.issue_number}",
                    f"  repo: {outcome.repo}",
                    f"  title: {outcome.issue_title}",
                    f"  status: {outcome.status}",
                    f"  category: {outcome.category}",
                    f"  worker_exit_code: {outcome.worker_exit_code}",
                ])
                if outcome.pr_url:
                    lines.append(f"  pr_url: {outcome.pr_url}")
                if outcome.warning_markers:
                    lines.append(f"  warning_markers: {outcome.warning_markers}")
                if outcome.git_diff_stat:
                    # Kompakt halten: nur die Zeilen mit Dateiaenderungen
                    diff_lines = outcome.git_diff_stat.strip().split('\n')
                    # Filtere nur die Zeilen mit tatsaechlichen Aenderungen (entferne Leerzeilen und Header)
                    compact_diff = [line for line in diff_lines if line.strip() and not line.startswith('Git-')]
                    if compact_diff:
                        lines.append(f"  changed_files: {', '.join(compact_diff)}")
                if outcome.branch:
                    lines.append(f"  branch: {outcome.branch}")
                if outcome.model:
                    lines.append(f"  model: {outcome.model}")
                lines.append(f"  run_dir: {outcome.run_dir}")

    summary_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fuehrt einen unbeaufsichtigten Overnight-Batch mit Logs aus."
    )
    parser.add_argument("--model", required=True, choices=list(MODEL_CONFIGS.keys()))
    parser.add_argument("--model-name", help="Spezifisches Modell fuer Codex/Ollama/aider")
    parser.add_argument("--fallback-model", choices=list(MODEL_CONFIGS.keys()), help="Fallback-Provider fuer Codex-Rate-Limits")
    parser.add_argument("--fallback-model-name", help="Optionaler Modellname fuer --fallback-model")
    parser.add_argument("--repo", help="Nur dieses Repo bearbeiten")
    parser.add_argument(
        "--issue",
        type=int,
        action="append",
        help="Nur diese Issue-Nummer loesen; kann mehrfach angegeben werden",
    )
    parser.add_argument("--label", default=DEFAULT_LABEL, help="Welche Issues holen")
    parser.add_argument(
        "--base-branch",
        default=DEFAULT_BASE_BRANCH,
        help=f"Basis-Branch fuer Pull und Solver, Standard: {DEFAULT_BASE_BRANCH}",
    )
    parser.add_argument(
        "--workers",
        type=positive_int,
        default=DEFAULT_WORKERS,
        help=f"Maximale parallele Worker, Standard: {DEFAULT_WORKERS}",
    )
    parser.add_argument("--dry-run", action="store_true", help="Batch-Solver nur simulieren")
    parser.add_argument("--close-issues", action="store_true", help="An Batch-Solver weiterreichen")
    parser.add_argument(
        "--worker-health-timeout-minutes",
        type=positive_int,
        help="An Batch-Solver weiterreichen: Minuten ohne Worker-Ausgabe bis zur Health-Warnung",
    )
    parser.add_argument(
        "--unhealthy-action",
        choices=["warn", "stop", "retry"],
        help="An Batch-Solver weiterreichen: Aktion bei unhealthy Worker",
    )
    parser.add_argument(
        "--unhealthy-retries",
        type=positive_int,
        help="An Batch-Solver weiterreichen: Retry-Versuche fuer unhealthy Jobs",
    )
    parser.add_argument(
        "--verbosity",
        choices=["quiet", "normal", "verbose"],
        help="An Batch-Solver weiterreichen: Worker-Ausgabe",
    )
    parser.add_argument(
        "--allow-opencode-state-conflict",
        action="store_true",
        help=(
            "OpenCode trotz laufendem Versions-/State-Mix starten und an Batch weiterreichen. "
            "Nur bewusst verwenden; Standard ist blockieren."
        ),
    )
    parser.add_argument("--skip-pull", action="store_true", help="Git-Pull des Basis-Branches ueberspringen")
    parser.add_argument("--skip-tests", action="store_true", help="Testlauf vor dem Batch ueberspringen")
    parser.add_argument(
        "--test-command",
        type=shell_words,
        default=DEFAULT_TEST_COMMAND,
        help=f"Testbefehl vor dem Batch, Standard: {command_to_text(DEFAULT_TEST_COMMAND)!r}",
    )
    parser.add_argument(
        "--log-root",
        type=Path,
        default=DEFAULT_OVERNIGHT_DIR,
        help=f"Root-Verzeichnis fuer Overnight-Logs, Standard: {DEFAULT_OVERNIGHT_DIR}",
    )
    parser.add_argument(
        "--runs-dir",
        type=Path,
        default=Path("reports") / "runs",
        help="Run-Report-Verzeichnis fuer das Dashboard",
    )
    parser.add_argument(
        "--dashboard-output",
        type=Path,
        default=DEFAULT_DASHBOARD_OUTPUT,
        help=f"Zielpfad fuer das Dashboard, Standard: {DEFAULT_DASHBOARD_OUTPUT}",
    )
    parser.add_argument("--owner", help="GitHub Owner fuer Dashboard-Links")
    parser.add_argument(
        "--skip-congestion-check",
        action="store_true",
        help="Workflow-Congestion-Check vor dem Batch ueberspringen",
    )
    parser.add_argument(
        "--caffeinate",
        action="store_true",
        help="macOS waehrend des Nachtlaufs mit caffeinate wach halten",
    )
    # OpenCode Budget-Limits (nur fuer --model opencode); an solve_issues_batch.py weitergereicht
    parser.add_argument(
        "--max-run-cost-usd",
        type=float,
        default=None,
        help="An Batch-Solver weiterreichen: Maximale Kosten in USD fuer einen einzelnen OpenCode-Run",
    )
    parser.add_argument(
        "--max-run-input-tokens",
        type=int,
        default=None,
        help="An Batch-Solver weiterreichen: Maximale Input-Tokens fuer einen einzelnen OpenCode-Run",
    )
    parser.add_argument(
        "--max-run-output-tokens",
        type=int,
        default=None,
        help="An Batch-Solver weiterreichen: Maximale Output-Tokens fuer einen einzelnen OpenCode-Run",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    print_banner("UNATTENDED OVERNIGHT RUNNER")
    args = parse_args(argv)
    project_root = Path(__file__).resolve().parents[1]
    started_at = datetime.now()
    session_dir = create_session_dir(project_root / args.log_root)
    steps: list[StepResult] = []

    print_step(1, f"Log-Verzeichnis: {session_dir}")
    next_step = 2

    if args.model == "opencode" and not args.dry_run:
        print_step(next_step, "OpenCode-State-Preflight")
        next_step += 1
        if not run_opencode_preflight_guard(
            allow_conflict=args.allow_opencode_state_conflict,
        ):
            return 1

    with keep_awake(args.caffeinate, session_dir / "caffeinate.log"):
        if args.skip_pull:
            print_warn("Git-Pull uebersprungen")
            steps.append(skipped_step("pull", session_dir / "pull.log", "--skip-pull"))
        else:
            print_step(next_step, f"Pull von origin/{args.base_branch}")
            next_step += 1
            pull_result = run_logged_command(
                "pull",
                build_pull_command(args.base_branch),
                project_root,
                session_dir / "pull.log",
            )
            steps.append(pull_result)
            if not pull_result.ok:
                print_err("Pull fehlgeschlagen; Batch wird nicht gestartet")

        can_continue = all(step.ok for step in steps)

        if args.skip_tests:
            print_warn("Tests uebersprungen")
            steps.append(skipped_step("tests", session_dir / "tests.log", "--skip-tests"))
        elif can_continue:
            print_step(next_step, f"Tests: {command_to_text(args.test_command)}")
            next_step += 1
            test_result = run_logged_command(
                "tests",
                args.test_command,
                project_root,
                session_dir / "tests.log",
            )
            steps.append(test_result)
            if not test_result.ok:
                print_err("Tests fehlgeschlagen; Batch wird nicht gestartet")
        else:
            steps.append(skipped_step("tests", session_dir / "tests.log", "Pull fehlgeschlagen"))

        can_continue = all(step.ok for step in steps)

        # Workflow-Congestion-Check (vor dem Batch)
        if args.skip_congestion_check:
            print_warn("Workflow-Congestion-Check uebersprungen (--skip-congestion-check)")
            steps.append(skipped_step(
                "workflow_congestion",
                session_dir / "workflow_congestion.log",
                "--skip-congestion-check",
            ))
        elif can_continue:
            print_step(next_step, "Workflow-Congestion-Check")
            next_step += 1
            congestion_command = [
                sys.executable,
                str(Path("scripts") / "solve_issues.py"),
                "--model", args.model,
                "--skip-congestion-check",
                "--dry-run",
            ]
            if args.repo:
                congestion_command.extend(["--repo", args.repo])
            if args.issue:
                for issue_number in args.issue:
                    congestion_command.extend(["--issue", str(issue_number)])
            if getattr(args, "label", None):
                congestion_command.extend(["--label", args.label])
            if args.base_branch:
                congestion_command.extend(["--base-branch", args.base_branch])
            if args.verbosity:
                congestion_command.extend(["--verbosity", args.verbosity])
            congestion_result = run_logged_command(
                "workflow_congestion",
                congestion_command,
                project_root,
                session_dir / "workflow_congestion.log",
                stream_output=True,
            )
            steps.append(congestion_result)
            if not congestion_result.ok:
                print_warn("Workflow-Congestion-Check hat Warnungen gefunden; Batch wird trotzdem gestartet")
        else:
            steps.append(skipped_step(
                "workflow_congestion",
                session_dir / "workflow_congestion.log",
                "Vorheriger Schritt fehlgeschlagen",
            ))

        can_continue = all(step.ok for step in steps)

        if can_continue:
            print_step(next_step, f"Batch-Solver mit {args.workers} Worker(n)")
            next_step += 1
            batch_result = run_logged_command(
                "batch",
                solver_commands.build_batch_command(
                    args,
                    Path("scripts") / "solve_issues_batch.py",
                    skip_congestion_check=args.skip_congestion_check,
                ),
                project_root,
                session_dir / "batch.log",
            )
            steps.append(batch_result)
        else:
            steps.append(skipped_step("batch", session_dir / "batch.log", "Preflight fehlgeschlagen"))

        print_step(next_step, "Dashboard regenerieren")
        next_step += 1
        dashboard_result = run_logged_command(
            "dashboard",
            solver_commands.build_dashboard_command(
                Path("scripts") / "status_dashboard.py",
                args.dashboard_output,
                runs_dir=args.runs_dir,
                owner=getattr(args, "owner", None),
            ),
            project_root,
            session_dir / "dashboard.log",
        )
        steps.append(dashboard_result)

    finished_at = datetime.now()
    summary_path = session_dir / "summary.txt"
    write_final_summary(summary_path, session_dir, args, steps, started_at, finished_at, args.runs_dir)

    failed_steps = [step for step in steps if not step.ok]
    print_step(next_step, "Finale Summary")
    if failed_steps:
        print_err("Overnight-Lauf mit Fehlern beendet")
        print(f"   Summary: {summary_path}")
        return 1

    print_ok("Overnight-Lauf erfolgreich beendet")
    print(f"   Summary: {summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
