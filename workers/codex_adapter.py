"""
workers.codex_adapter — Adapter für den Codex CLI Worker.

Kapselt Befehlsaufbau, Ausführung, Rate-Limit-Erkennung und Retry-Logik
für den Codex CLI (`codex exec`).

Rate-Limit-Semantik:
    - Erkennt die Codex-Rate-Limit-Meldung im Worker-Output.
    - Schläft bis zur angegebenen Reset-Zeit (oder gibt Kontrolle ab, falls
      defer_rate_limit=True gesetzt ist).
    - Bricht nach CODEX_RATE_LIMIT_RETRY_LIMIT Retries ab.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from workers.base import WorkerAdapter, WorkerRunResult, AdapterDiagnostics


# ─────────────────────────────────────────────────────────────
# Konstanten
# ─────────────────────────────────────────────────────────────

CODEX_RATE_LIMIT_RETRY_LIMIT = 3

CODEX_RATE_LIMIT_RESET_RE = re.compile(
    r"rate limit will be reset on\s+(.+?)(?:\.|\n|$)",
    re.IGNORECASE,
)
CODEX_RATE_LIMIT_MESSAGE_RE = re.compile(
    r"(?:reached the codex message limit|rate limit will be reset)",
    re.IGNORECASE,
)


# ─────────────────────────────────────────────────────────────
# Hilfsdatenklasse für Rate-Limit-Info
# ─────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class CodexRateLimit:
    """Informationen über ein erkanntes Codex Rate-Limit."""
    reset_at: datetime | None
    reset_text: str | None


# ─────────────────────────────────────────────────────────────
# Hilfsfunktionen
# ─────────────────────────────────────────────────────────────

def find_codex_executable() -> str | None:
    """Sucht das Codex CLI-Executable auf dem System oder im Desktop-App-Pfad."""
    candidates = [
        shutil.which("codex"),
        "/Applications/Codex.app/Contents/Resources/codex",
    ]
    return next((path for path in candidates if path and Path(path).exists()), None)


def detect_codex_rate_limit(output: str) -> CodexRateLimit | None:
    """
    Erkennt ein Codex Rate-Limit in der Worker-Ausgabe.

    Returns:
        CodexRateLimit wenn ein Rate-Limit erkannt wurde, sonst None.
    """
    if not CODEX_RATE_LIMIT_MESSAGE_RE.search(output):
        return None

    reset_match = CODEX_RATE_LIMIT_RESET_RE.search(output)
    if not reset_match:
        return CodexRateLimit(reset_at=None, reset_text=None)

    reset_text = reset_match.group(1).strip()
    return CodexRateLimit(
        reset_at=parse_codex_reset_datetime(reset_text),
        reset_text=reset_text,
    )


def parse_codex_reset_datetime(reset_text: str) -> datetime | None:
    """Parst die Reset-Zeit aus der Codex-CLI-Meldung im lokalen Zeitkontext."""
    normalized = re.sub(r"\s+", " ", reset_text.strip())
    normalized = normalized.replace(", at ", " ").replace(" at ", " ")

    formats = (
        "%B %d, %Y %I:%M %p",
        "%b %d, %Y %I:%M %p",
        "%B %d %Y %I:%M %p",
        "%b %d %Y %I:%M %p",
    )
    for date_format in formats:
        try:
            return datetime.strptime(normalized, date_format)
        except ValueError:
            pass
    return None


def sleep_until_codex_reset(
    rate_limit: CodexRateLimit,
    sleep_fn=time.sleep,
    now_fn=datetime.now,
) -> None:
    """Schläft bis zur Codex Rate-Limit-Reset-Zeit (oder gibt Hinweis aus)."""
    from utils import print_warn

    if rate_limit.reset_text:
        print_warn(f"Codex-Rate-Limit erreicht; Reset laut Codex: {rate_limit.reset_text}")
    else:
        print_warn("Codex-Rate-Limit erreicht; keine Reset-Zeit in der Ausgabe gefunden")

    if not rate_limit.reset_at:
        return

    wait_seconds = max(0.0, (rate_limit.reset_at - now_fn()).total_seconds())
    if wait_seconds > 0:
        print(f"      Pausiere bis {rate_limit.reset_at.strftime('%Y-%m-%d %H:%M')} und setze dann fort.")
        sleep_fn(wait_seconds)
    else:
        print("      Reset-Zeit ist bereits erreicht; setze sofort fort.")


# ─────────────────────────────────────────────────────────────
# Adapter-Klasse
# ─────────────────────────────────────────────────────────────

class CodexAdapter(WorkerAdapter):
    """
    Worker-Adapter für den Codex CLI.

    Unterstützt:
        - Sandbox-Modi (workspace-write, etc.)
        - Zusätzliche Verzeichnisse für die Sandbox (--add-dir)
        - Rate-Limit-Erkennung und optionalen Retry-Sleep
        - Vollständige Ausgabe in den Diagnostics
    """

    name = "codex"

    def __init__(
        self,
        sandbox_mode: str = "workspace-write",
        defer_rate_limit: bool = False,
        sleep_fn=time.sleep,
        now_fn=datetime.now,
    ):
        """
        Args:
            sandbox_mode:     Codex-Sandbox-Modus (Standard: "workspace-write").
            defer_rate_limit: True → Rate-Limit nicht ausschlafen; Caller entscheidet.
            sleep_fn:         Ersetzbare Sleep-Funktion für Tests.
            now_fn:           Ersetzbare now()-Funktion für Tests.
        """
        self.sandbox_mode = sandbox_mode
        self.defer_rate_limit = defer_rate_limit
        self.sleep_fn = sleep_fn
        self.now_fn = now_fn

    def get_display_name(self) -> str:
        return "Codex CLI"

    def build_command(
        self,
        prompt: str,
        repo_path: str,
        model_name: str | None = None,
        additional_dirs: list[str] | None = None,
        **kwargs: Any,
    ) -> list[str]:
        """
        Baut den `codex exec`-Befehl auf.

        Args:
            prompt:          Sanitierter Worker-Prompt.
            repo_path:       Absoluter Pfad zum Repository.
            model_name:      Optionaler Modell-Override.
            additional_dirs: Zusätzliche Verzeichnisse für --add-dir.

        Raises:
            FileNotFoundError: Wenn das Codex-Executable nicht gefunden wird.
        """
        codex = find_codex_executable()
        if not codex:
            raise FileNotFoundError("codex")

        cmd = [
            codex,
            "exec",
            "--cd", repo_path,
            "--sandbox", self.sandbox_mode,
        ]
        if model_name:
            cmd.extend(["--model", model_name])
        if additional_dirs:
            for dir_path in additional_dirs:
                cmd.extend(["--add-dir", dir_path])
        cmd.append(prompt)
        return cmd

    def build_env(
        self,
        config: dict[str, str],
        base_env: dict[str, str] | None = None,
    ) -> dict[str, str]:
        """Codex benötigt keine zusätzlichen Umgebungsvariablen."""
        return dict(base_env if base_env is not None else os.environ)

    def run(
        self,
        prompt: str,
        repo_path: str,
        env: dict[str, str],
        model_name: str | None = None,
        verbosity: str = "normal",
        run_report: Any | None = None,
        additional_dirs: list[str] | None = None,
        **kwargs: Any,
    ) -> tuple[WorkerRunResult, AdapterDiagnostics]:
        """
        Führt den Codex CLI aus, inklusive Rate-Limit-Handling.

        Gibt immer das letzte WorkerRunResult zurück; AdapterDiagnostics.all_outputs
        enthält die Ausgaben aller Läufe (bei Retries nach Rate-Limit mehrere Einträge).
        """
        from utils import print_warn

        diagnostics = AdapterDiagnostics()

        try:
            cmd = self.build_command(prompt, repo_path, model_name, additional_dirs)
        except FileNotFoundError:
            error_msg = "Codex CLI nicht gefunden (FileNotFoundError)"
            diagnostics.all_outputs.append(error_msg)
            return (
                WorkerRunResult(returncode=127, output=error_msg),
                diagnostics,
            )

        rate_limit_retries = 0
        result: WorkerRunResult | None = None

        while True:
            result = _run_subprocess(cmd, repo_path, env, run_report=run_report,
                                     verbosity=verbosity)
            diagnostics.all_outputs.append(result.output)

            rate_limit = detect_codex_rate_limit(result.output)
            if not rate_limit:
                break

            if self.defer_rate_limit:
                note = (
                    f"Batch-Runner soll nach {rate_limit.reset_text} neu einplanen"
                    if rate_limit.reset_text
                    else "Batch-Runner soll diesen Job verzögern"
                )
                print_warn(f"Codex-Rate-Limit erreicht; {note}")
                diagnostics.rate_limit_note = note
                break

            if not rate_limit.reset_at:
                diagnostics.rate_limit_note = "Codex-Rate-Limit ohne verwertbare Reset-Zeit"
                sleep_until_codex_reset(rate_limit, self.sleep_fn, self.now_fn)
                break

            rate_limit_retries += 1
            if rate_limit_retries > CODEX_RATE_LIMIT_RETRY_LIMIT:
                diagnostics.rate_limit_note = (
                    f"Codex-Rate-Limit nach {CODEX_RATE_LIMIT_RETRY_LIMIT} "
                    "Retries weiter aktiv"
                )
                print_warn("Codex-Rate-Limit wurde mehrfach erreicht; breche dieses Issue ab")
                break

            sleep_until_codex_reset(rate_limit, self.sleep_fn, self.now_fn)

        assert result is not None
        return result, diagnostics


# ─────────────────────────────────────────────────────────────
# Interne Hilfsfunktion: Subprocess ausführen
# ─────────────────────────────────────────────────────────────

def _run_subprocess(
    cmd: list[str],
    repo_dir: str,
    env: dict[str, str],
    run_report: Any | None = None,
    verbosity: str = "normal",
    process_ref: list | None = None,
) -> WorkerRunResult:
    """
    Führt einen Worker-Befehl als Subprocess aus und gibt das Ergebnis zurück.

    Diese interne Funktion wird von mehreren Adaptern wiederverwendet und
    entspricht der Logik von solve_issues.run_worker_command().

    Args:
        process_ref: Wenn gesetzt (z.B. leere Liste), wird darin der Popen-Prozess
                     abgelegt, damit Aufrufer den Zugriff auf den laufenden Prozess haben.
    """
    from solver_reporting import should_surface_worker_line, write_run_health
    from utils import print_err

    try:
        process = subprocess.Popen(
            cmd,
            cwd=repo_dir,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
    except FileNotFoundError:
        print_err(f"KI-Worker nicht gefunden: {cmd[0]}")
        return WorkerRunResult(returncode=127, output="")

    if process_ref is not None:
        process_ref.append(process)

    output_parts = []
    suppressed_lines = 0
    last_activity_at = datetime.now()
    if run_report:
        write_run_health(
            run_report,
            status="running",
            phase="worker_running",
            worker_pid=process.pid,
        )

    if process.stdout:
        for line in process.stdout:
            output_parts.append(line)
            if verbosity == "verbose":
                if line.strip():
                    print(f"        | {line}", end="")
                last_activity_at = datetime.now()
                if run_report:
                    write_run_health(run_report, "".join(output_parts), last_activity_at,
                                     phase="worker_running", worker_pid=process.pid)
            elif verbosity == "normal":
                if should_surface_worker_line(line):
                    print(f"        | {line}", end="")
                    last_activity_at = datetime.now()
                    if run_report:
                        write_run_health(run_report, "".join(output_parts), last_activity_at,
                                         phase="worker_running", worker_pid=process.pid)
                else:
                    suppressed_lines += 1
            else:
                # quiet: nichts drucken, aber Aktivität tracken
                if should_surface_worker_line(line):
                    last_activity_at = datetime.now()
                    if run_report:
                        write_run_health(run_report, "".join(output_parts), last_activity_at,
                                         phase="worker_running", worker_pid=process.pid)
                else:
                    suppressed_lines += 1
        process.stdout.close()

    if verbosity != "quiet" and suppressed_lines:
        print(
            f"        | ... {suppressed_lines} Detailzeilen ausgeblendet; "
            "Rohoutput bleibt in der Diagnose erhalten"
        )

    return WorkerRunResult(
        returncode=process.wait(),
        output="".join(output_parts),
        last_activity_at=last_activity_at,
    )
