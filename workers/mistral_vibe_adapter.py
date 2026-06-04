"""
workers.mistral_vibe_adapter — Adapter für den Mistral Vibe CLI Worker.

Kapselt Befehlsaufbau, Ausführung und Vibe-Log-Snippet-Sammlung für den
Mistral Vibe CLI (`vibe`).

Besonderheiten:
    - Liest nach dem Worker-Lauf ein Snippet aus .vibe/logs/vibe.log.
    - Erkennt das Turn-Limit-Event im Worker-Output (<vibe_stop_event>).
    - Benötigt MISTRAL_API_KEY in der Umgebung.
"""

from __future__ import annotations

import os
import re
import shutil
import sys
from pathlib import Path
from typing import Any

from workers.base import WorkerAdapter, WorkerRunResult, AdapterDiagnostics
from workers.codex_adapter import _run_subprocess


# ─────────────────────────────────────────────────────────────
# Konstanten
# ─────────────────────────────────────────────────────────────

VIBE_LOG_PATH = Path(".vibe") / "logs" / "vibe.log"
VIBE_LOG_SNIPPET_LINES = 15
VIBE_LOG_SNIPPET_CHARS = 2000

VIBE_TURN_LIMIT_RE = re.compile(
    r"<vibe_stop_event>Turn limit of \d+ reached</vibe_stop_event>",
    re.IGNORECASE,
)


# ─────────────────────────────────────────────────────────────
# Hilfsfunktionen
# ─────────────────────────────────────────────────────────────

def find_vibe_executable(repo_path: str | None = None) -> str | None:
    """
    Sucht das Mistral Vibe CLI-Executable in der aktiven Umgebung, Repo-Venv oder PATH.

    Suchreihenfolge:
        1. <repo>/.venv/bin/vibe und <repo>/venv/bin/vibe (falls repo_path angegeben).
        2. Gleicher Bin-Pfad wie aktuelles Python-Executable.
        3. ~/.local/bin/vibe
        4. shutil.which("vibe")
    """
    candidates = []

    if repo_path:
        repo_root = Path(repo_path)
        candidates.extend([
            repo_root / ".venv" / "bin" / "vibe",
            repo_root / "venv" / "bin" / "vibe",
        ])

    if sys.executable:
        candidates.append(Path(sys.executable).with_name("vibe"))

    candidates.append(Path.home() / ".local" / "bin" / "vibe")

    for candidate in candidates:
        if candidate.exists() and os.access(candidate, os.X_OK):
            return str(candidate)

    return shutil.which("vibe")


def read_vibe_log_snippet(repo_dir: str) -> str:
    """
    Liest ein kompaktes Snippet aus der Vibe-Log-Datei, falls vorhanden.

    Returns:
        Snippet-String oder leerer String wenn die Datei nicht existiert.
    """
    from solver_reporting import should_surface_worker_line

    vibe_log = Path(repo_dir) / VIBE_LOG_PATH
    if not vibe_log.exists():
        return ""

    try:
        content = vibe_log.read_text(encoding="utf-8", errors="replace")
    except (OSError, UnicodeDecodeError):
        return ""

    if not content.strip():
        return ""

    lines = content.strip().splitlines()
    relevant_lines = [line for line in lines if line.strip() and should_surface_worker_line(line)]

    if not relevant_lines:
        relevant_lines = lines[-VIBE_LOG_SNIPPET_LINES:] if len(lines) > VIBE_LOG_SNIPPET_LINES else lines
    else:
        relevant_lines = relevant_lines[-VIBE_LOG_SNIPPET_LINES:]

    snippet = "\n".join(relevant_lines)

    if len(snippet) > VIBE_LOG_SNIPPET_CHARS:
        snippet = snippet[-VIBE_LOG_SNIPPET_CHARS:]
        last_newline = snippet.rfind("\n")
        if last_newline > 0:
            snippet = snippet[last_newline + 1:]

    return snippet


# ─────────────────────────────────────────────────────────────
# Adapter-Klasse
# ─────────────────────────────────────────────────────────────

class MistralVibeAdapter(WorkerAdapter):
    """
    Worker-Adapter für den Mistral Vibe CLI.

    Kapselt:
        - Suche nach dem vibe-Executable.
        - Befehlsaufbau mit --workdir, --trust, -p, --max-turns, --output.
        - Lesen des Vibe-Log-Snippets nach dem Lauf.
        - Erkennung des Turn-Limit-Events.
        - MISTRAL_API_KEY-Anforderung in der Umgebung.
    """

    name = "mistral-vibe"

    def __init__(
        self,
        max_turns: int = 30,
        output_format: str = "text",
    ):
        """
        Args:
            max_turns:     Maximale Turn-Anzahl für den Vibe-Worker.
            output_format: Ausgabeformat ("text" oder "json").
        """
        self.max_turns = max_turns
        self.output_format = output_format

    def get_display_name(self) -> str:
        return "Mistral Vibe CLI"

    def build_command(
        self,
        prompt: str,
        repo_path: str,
        model_name: str | None = None,
        **kwargs: Any,
    ) -> list[str]:
        """
        Baut den vibe-Befehl auf.

        Raises:
            FileNotFoundError: Wenn das vibe-Executable nicht gefunden wird.
        """
        vibe = find_vibe_executable(repo_path)
        if not vibe:
            raise FileNotFoundError("vibe")

        return [
            vibe,
            "--workdir", repo_path,
            "--trust",
            "-p", prompt,
            "--max-turns", str(self.max_turns),
            "--output", self.output_format,
        ]

    def build_env(
        self,
        config: dict[str, str],
        base_env: dict[str, str] | None = None,
    ) -> dict[str, str]:
        """
        Benötigt MISTRAL_API_KEY in der Konfiguration.

        Raises:
            SystemExit(1): Wenn MISTRAL_API_KEY fehlt oder ein Platzhalter ist.
        """
        from utils import require_config_value

        env = dict(base_env if base_env is not None else os.environ)
        api_key = require_config_value(config, "MISTRAL_API_KEY")
        env["MISTRAL_API_KEY"] = api_key

        # OpenCode-spezifische Variablen entfernen
        env.pop("OPENCODE_AUTH_FILE", None)
        env.pop("OPENCODE_STATE_DIR", None)
        env.pop("OPENCODE_CACHE_DIR", None)

        return env

    def run(
        self,
        prompt: str,
        repo_path: str,
        env: dict[str, str],
        model_name: str | None = None,
        verbosity: str = "normal",
        run_report: Any | None = None,
        **kwargs: Any,
    ) -> tuple[WorkerRunResult, AdapterDiagnostics]:
        """
        Führt den Mistral Vibe CLI aus und sammelt das Vibe-Log-Snippet.

        Returns:
            Tupel (WorkerRunResult, AdapterDiagnostics mit vibe_log_snippet).
        """
        diagnostics = AdapterDiagnostics()

        try:
            cmd = self.build_command(prompt, repo_path, model_name)
        except FileNotFoundError:
            error_msg = "Mistral Vibe CLI nicht gefunden (FileNotFoundError)"
            diagnostics.all_outputs.append(error_msg)
            return (
                WorkerRunResult(returncode=127, output=error_msg),
                diagnostics,
            )

        result = _run_subprocess(cmd, repo_path, env, run_report=run_report,
                                 verbosity=verbosity)
        diagnostics.all_outputs.append(result.output)

        # Vibe-Log-Snippet sammeln
        vibe_log_snippet = read_vibe_log_snippet(repo_path)
        if vibe_log_snippet:
            print(f"      📝 Vibe-Log-Snippet gesammelt ({len(vibe_log_snippet)} Zeichen)")
        diagnostics.vibe_log_snippet = vibe_log_snippet

        return result, diagnostics
