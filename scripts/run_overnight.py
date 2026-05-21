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
import shlex
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from solve_issues import MODEL_CONFIGS  # noqa: E402
from solve_issues_batch import DEFAULT_WORKERS, positive_int  # noqa: E402
from utils import print_banner, print_err, print_ok, print_step, print_warn  # noqa: E402


DEFAULT_BASE_BRANCH = "main"
DEFAULT_LABEL = "ai-generated"
DEFAULT_TEST_COMMAND = "{sys.executable} -m unittest discover -s tests"
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


def write_final_summary(
    summary_path: Path,
    session_dir: Path,
    args: argparse.Namespace,
    steps: list[StepResult],
    started_at: datetime,
    finished_at: datetime,
) -> None:
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
    summary_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fuehrt einen unbeaufsichtigten Overnight-Batch mit Logs aus."
    )
    parser.add_argument("--model", required=True, choices=list(MODEL_CONFIGS.keys()))
    parser.add_argument("--model-name", help="Spezifisches Modell fuer Codex/Ollama/aider")
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
        default=shell_words(DEFAULT_TEST_COMMAND),
        help=f"Testbefehl vor dem Batch, Standard: {DEFAULT_TEST_COMMAND!r}",
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
    write_final_summary(summary_path, session_dir, args, steps, started_at, finished_at)

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
