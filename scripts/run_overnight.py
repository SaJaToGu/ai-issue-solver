#!/usr/bin/env python3
"""
run_overnight.py - Wrapper fuer laengere unbeaufsichtigte Batch-Laeufe.

Der Runner aktualisiert zuerst den Basis-Branch, fuehrt die Tests aus, startet
danach den begrenzten Batch-Solver und regeneriert abschliessend das Dashboard.
Alle Schritte schreiben eigene Logs in reports/overnight/<timestamp>/.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime
import re
import shlex
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from solve_issues import MODEL_CONFIGS  # noqa: E402
from solve_issues_batch import DEFAULT_WORKERS, positive_int  # noqa: E402
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


def build_batch_command(args: argparse.Namespace, batch_script: Path) -> list[str]:
    command = [
        sys.executable,
        str(batch_script),
        "--model",
        args.model,
        "--workers",
        str(args.workers),
        "--label",
        args.label,
    ]
    if args.model_name:
        command.extend(["--model-name", args.model_name])
    if args.fallback_model:
        command.extend(["--fallback-model", args.fallback_model])
    if args.fallback_model_name:
        command.extend(["--fallback-model-name", args.fallback_model_name])
    if args.repo:
        command.extend(["--repo", args.repo])
    for issue_number in args.issue or []:
        command.extend(["--issue", str(issue_number)])
    if args.base_branch:
        command.extend(["--base-branch", args.base_branch])
    if args.dry_run:
        command.append("--dry-run")
    if args.close_issues:
        command.append("--close-issues")
    return command


def build_dashboard_command(args: argparse.Namespace, dashboard_script: Path) -> list[str]:
    command = [
        sys.executable,
        str(dashboard_script),
        "--output",
        str(args.dashboard_output),
    ]
    if args.runs_dir:
        command.extend(["--runs-dir", str(args.runs_dir)])
    if args.owner:
        command.extend(["--owner", args.owner])
    return command


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


def classify_status(status: str, worker_exit_code: str = "") -> str:
    """Klassifiziert den Status eines Runs (kopiert aus status_dashboard.py)."""
    if not status:
        return "unknown"
    if status == "queued":
        return "queued"
    if status == "started":
        return "running"
    # Erfolgreiche Staende
    if status in {"pr_created", "pr_created_from_existing_branch", "cleanup_successful"}:
        return "successful"
    # No-op Staende
    if status in {"skip_existing_pr", "skip_merged_pr", "skip_closed_pr", "cleanup_noop"}:
        return "noop"
    if status in {"no_changes", "nonzero_without_changes"}:
        return "failed"
    # Fehlgeschlagene Staende
    if status in {
        "branch_create_failed", "checkout_failed", "clone_failed",
        "nonzero_without_changes", "pr_failed", "pr_failed_from_existing_branch",
        "push_failed", "cleanup_failed", "rate_limit_deferred", "validation_failed",
    } or status.endswith("_failed"):
        return "failed"
    # Archiviert
    if status in {"archived", "cleanup_archived"}:
        return "archived"
    if worker_exit_code and worker_exit_code != "0":
        return "failed"
    return "noop"


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


def collect_issue_outcomes(runs_dir: Path) -> list[IssueOutcome]:
    """Sammelt IssueOutcome-Objekte aus allen Run-Reports in runs_dir.

    Sortiert nach Run-Verzeichnisname (zeitlich absteigend).
    """
    outcomes = []

    if not runs_dir.exists():
        return outcomes

    for run_dir in sorted(runs_dir.iterdir(), reverse=True):
        if not run_dir.is_dir():
            continue

        summary_path = run_dir / "summary.txt"
        if not summary_path.exists():
            continue

        fields = parse_summary_file(summary_path)

        status = fields.get("status", "")
        exit_code = fields.get("worker_exit_code", "")
        category = classify_status(status, exit_code)

        # Skip queued/running runs - diese haben noch kein Ergebnis
        if category in {"queued", "running", "unhealthy", "unknown"}:
            continue

        warning_markers = detect_warning_markers(run_dir)

        outcome = IssueOutcome(
            repo=fields.get("repo") or fields.get("selected_repo", ""),
            issue_number=fields.get("issue_number") or fields.get("issue", ""),
            issue_title=fields.get("issue_title", ""),
            status=status,
            category=category,
            worker_exit_code=exit_code,
            pr_url=fields.get("pr_url", ""),
            git_diff_stat=fields.get("git_diff_stat", ""),
            warning_markers=warning_markers,
            branch=fields.get("branch", ""),
            model=fields.get("model", ""),
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
        f"workers: {args.workers}",
        f"base_branch: {args.base_branch}",
        f"repo: {args.repo or ''}",
        f"label: {args.label}",
        f"dry_run: {args.dry_run}",
        f"dashboard: {args.dashboard_output}",
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
        outcomes = collect_issue_outcomes(runs_dir)
        if outcomes:
            lines.extend(["", "issues:"])
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
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    print_banner("UNATTENDED OVERNIGHT RUNNER")
    args = parse_args(argv)
    project_root = Path(__file__).resolve().parents[1]
    started_at = datetime.now()
    session_dir = create_session_dir(project_root / args.log_root)
    steps: list[StepResult] = []

    print_step(1, f"Log-Verzeichnis: {session_dir}")

    if args.skip_pull:
        print_warn("Git-Pull uebersprungen")
        steps.append(skipped_step("pull", session_dir / "pull.log", "--skip-pull"))
    else:
        print_step(2, f"Pull von origin/{args.base_branch}")
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
        print_step(3, f"Tests: {command_to_text(args.test_command)}")
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

    if can_continue:
        print_step(4, f"Batch-Solver mit {args.workers} Worker(n)")
        batch_result = run_logged_command(
            "batch",
            build_batch_command(args, Path("scripts") / "solve_issues_batch.py"),
            project_root,
            session_dir / "batch.log",
        )
        steps.append(batch_result)
    else:
        steps.append(skipped_step("batch", session_dir / "batch.log", "Preflight fehlgeschlagen"))

    print_step(5, "Dashboard regenerieren")
    dashboard_result = run_logged_command(
        "dashboard",
        build_dashboard_command(args, Path("scripts") / "status_dashboard.py"),
        project_root,
        session_dir / "dashboard.log",
    )
    steps.append(dashboard_result)

    finished_at = datetime.now()
    summary_path = session_dir / "summary.txt"
    # Uebergibe args.runs_dir, um Issue-Outcomes in die Summary aufzunehmen
    write_final_summary(summary_path, session_dir, args, steps, started_at, finished_at, args.runs_dir)

    failed_steps = [step for step in steps if not step.ok]
    print_step(6, "Finale Summary")
    if failed_steps:
        print_err("Overnight-Lauf mit Fehlern beendet")
        print(f"   Summary: {summary_path}")
        return 1

    print_ok("Overnight-Lauf erfolgreich beendet")
    print(f"   Summary: {summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
