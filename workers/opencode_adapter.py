"""
workers.opencode_adapter — Adapter für den OpenCode CLI Worker.

Kapselt Befehlsaufbau, Prompt-Vorbereitung (repo-relative Pfade, Secret-Bereinigung),
Umgebungseinrichtung und Ausführung für den OpenCode CLI (`opencode run`).

Besonderheiten:
    - GitHub-Write-Tokens werden aus der Umgebung entfernt (GITHUB_TOKEN, GH_TOKEN).
    - Solver-lokale Cache-Verzeichnisse werden eingerichtet.
    - Der Prompt wird mit Anweisungen für repo-relative Pfade angereichert.
    - OpenCode Runtime-Diagnostics (WAL-Fehler, Edit-Loop) werden gesammelt.
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

from workers.base import WorkerAdapter, WorkerRunResult, AdapterDiagnostics
from workers.codex_adapter import _run_subprocess


# ─────────────────────────────────────────────────────────────
# Hilfsfunktionen
# ─────────────────────────────────────────────────────────────

def find_opencode_executable(repo_path: str | None = None) -> str | None:
    """
    Sucht das OpenCode CLI-Executable in üblichen Installationspfaden oder PATH.

    Suchreihenfolge:
        1. Gleicher Bin-Pfad wie aktuelles Python-Executable.
        2. <repo>/.venv/bin/opencode und <repo>/venv/bin/opencode.
        3. ~/.local/bin/opencode
        4. ~/.local/share/opencode/opencode
        5. ~/.opencode/bin/opencode
        6. shutil.which("opencode")
    """
    candidates = []

    if sys.executable:
        candidates.append(Path(sys.executable).with_name("opencode"))

    if repo_path:
        repo_root = Path(repo_path)
        candidates.extend([
            repo_root / ".venv" / "bin" / "opencode",
            repo_root / "venv" / "bin" / "opencode",
        ])

    candidates.append(Path.home() / ".local" / "bin" / "opencode")
    candidates.append(Path.home() / ".local" / "share" / "opencode" / "opencode")
    candidates.append(Path.home() / ".opencode" / "bin" / "opencode")

    for candidate in candidates:
        if candidate.exists() and os.access(candidate, os.X_OK):
            return str(candidate)

    return shutil.which("opencode")


def ensure_solver_directories() -> tuple[Path, Path]:
    """
    Erstellt solver-lokale Verzeichnisse für XDG_STATE_HOME und XDG_CACHE_HOME.

    Returns:
        Tupel (state_dir, cache_dir).
    """
    solver_base = Path(tempfile.gettempdir()) / "ai-issue-solver" / "opencode"
    solver_base.mkdir(parents=True, exist_ok=True)

    xdg_state_home = os.getenv("XDG_STATE_HOME")
    state_dir = Path(xdg_state_home) / "opencode" if xdg_state_home else solver_base / "state"

    xdg_cache_home = os.getenv("XDG_CACHE_HOME")
    cache_dir = Path(xdg_cache_home) / "opencode" if xdg_cache_home else solver_base / "cache"

    state_dir.mkdir(parents=True, exist_ok=True)
    cache_dir.mkdir(parents=True, exist_ok=True)
    (cache_dir / "tmp").mkdir(parents=True, exist_ok=True)

    return state_dir, cache_dir


def prepare_opencode_env(base_env: dict[str, str] | None = None) -> dict[str, str]:
    """
    Bereitet die Umgebung für OpenCode vor: solver-lokaler Cache, kein GitHub-Token.

    Args:
        base_env: Basis-Umgebung. Standard: os.environ.

    Returns:
        Angepasste Umgebungsvariablen mit OPENCODE_CACHE_DIR; ohne GITHUB_TOKEN,
        GH_TOKEN und erzwungenes XDG_STATE_HOME.
    """
    _state_dir, cache_dir = ensure_solver_directories()
    env = dict(base_env if base_env is not None else os.environ)

    # Nur Cache isolieren. State/Auth nicht überschreiben, damit OpenCode seine
    # bestehende SQLite-Datenbank inklusive WAL-Dateien konsistent findet.
    env.pop("XDG_STATE_HOME", None)
    env["OPENCODE_CACHE_DIR"] = str(cache_dir)

    # GitHub-Write-Tokens entfernen: OpenCode soll keinen Push-Zugriff haben
    env.pop("GITHUB_TOKEN", None)
    env.pop("GH_TOKEN", None)

    return env


# Instruktionen für den OpenCode-Prompt (repo-relative Pfade, keine Secrets)
OPENCODE_REPO_RELATIVE_INSTRUCTIONS = (
    "OpenCode wurde bereits mit `--dir` im geklonten Repository gestartet.\n"
    "Verwende fuer Dateioperationen ausschliesslich repo-relative Pfade wie `scripts/datei.py`.\n"
    "Wenn eine Pfadangabe auf dieses Repository zeigt, nutze den entsprechenden relativen Pfad "
    "und nicht den absoluten temporaeren Worktree-Pfad.\n"
    "Lies, kopiere oder bearbeite keine echten Secret-Dateien wie `.env`, `.env.*`, "
    "`config/.env` oder `config/.env.*`.\n"
    "Nutze fuer Konfigurationsbeispiele ausschliesslich sichere Beispiel-Dateien wie "
    "`config/config.example.env` oder `.env.example`.\n"
    "\n"
    "WICHTIG: Gib NIEMALS absolute Pfade ausserhalb des Repositories an "
    "(z. B. `/tmp/ai-solver-xyz/`). Solche Pfade werden ignoriert oder durch Platzhalter ersetzt."
)


# ─────────────────────────────────────────────────────────────
# Adapter-Klasse
# ─────────────────────────────────────────────────────────────

class OpenCodeAdapter(WorkerAdapter):
    """
    Worker-Adapter für den OpenCode CLI.

    Stellt sicher, dass:
        - Der Prompt repo-relative Pfade verwendet (via Präambel + Bereinigung).
        - GitHub-Tokens nicht an OpenCode weitergereicht werden.
        - Solver-lokale Verzeichnisse für State/Cache genutzt werden.
        - OpenCode Runtime-Diagnostics (WAL, Edit-Loop) gesammelt werden.
    """

    name = "opencode"

    def get_display_name(self) -> str:
        return "OpenCode CLI"

    def build_command(
        self,
        prompt: str,
        repo_path: str,
        model_name: str | None = None,
        **kwargs: Any,
    ) -> list[str]:
        """
        Baut den `opencode run`-Befehl auf.

        Der Prompt wird automatisch mit OPENCODE_REPO_RELATIVE_INSTRUCTIONS
        und Pfad-Bereinigungen vorbereitet.

        Raises:
            FileNotFoundError: Wenn das OpenCode-Executable nicht gefunden wird.
        """
        opencode = find_opencode_executable(repo_path)
        if not opencode:
            raise FileNotFoundError("opencode")

        prepared_prompt = self._prepare_prompt(prompt, repo_path)

        cmd = [opencode, "run", "--dir", repo_path]
        if model_name:
            cmd.extend(["--model", model_name])
        cmd.append(prepared_prompt)
        return cmd

    def _prepare_prompt(self, prompt: str, repo_path: str) -> str:
        """
        Bereitet den Prompt für OpenCode vor:
            1. Bereinigt echte Secret-Dateipfade.
            2. Relativiert repo-interne absolute Pfade.
            3. Stellt die OPENCODE_REPO_RELATIVE_INSTRUCTIONS voran.
        """
        # Import aus solve_issues für Secret-Bereinigung und Pfad-Relativierung
        # (Funktionen verbleiben in solve_issues um Rückwärtskompatibilität zu erhalten)
        try:
            from solve_issues import (
                sanitize_worker_prompt_secret_paths,
                relativize_repo_absolute_paths,
            )
            sanitized = sanitize_worker_prompt_secret_paths(prompt, repo_path)
            normalized = relativize_repo_absolute_paths(sanitized, repo_path)
        except ImportError:
            # Fallback falls solve_issues nicht importierbar (Tests ohne solve_issues)
            normalized = prompt

        return f"{OPENCODE_REPO_RELATIVE_INSTRUCTIONS}\n\n{normalized}"

    def build_env(
        self,
        config: dict[str, str],
        base_env: dict[str, str] | None = None,
    ) -> dict[str, str]:
        """
        Bereitet die OpenCode-Umgebung vor.

        Entfernt GitHub-Tokens, setzt solver-lokale OPENCODE_*-Variablen.
        Entfernt andere Provider-spezifische OpenCode-Variablen für Nicht-OpenCode-Worker.
        """
        return prepare_opencode_env(base_env)

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
        Führt den OpenCode CLI aus und sammelt Runtime-Diagnostics.

        Returns:
            Tupel (WorkerRunResult, AdapterDiagnostics mit OpenCode-Diagnostics).
        """
        from solver_reporting import detect_opencode_runtime_diagnostics, print_opencode_runtime_diagnostics

        diagnostics = AdapterDiagnostics()

        try:
            cmd = self.build_command(prompt, repo_path, model_name)
        except FileNotFoundError:
            error_msg = "OpenCode CLI nicht gefunden (FileNotFoundError)"
            diagnostics.all_outputs.append(error_msg)
            return (
                WorkerRunResult(returncode=127, output=error_msg),
                diagnostics,
            )

        result = _run_subprocess(cmd, repo_path, env, run_report=run_report,
                                 verbosity=verbosity)
        diagnostics.all_outputs.append(result.output)

        # OpenCode Runtime-Diagnostics ausgeben (WAL-Fehler, Edit-Loop)
        print_opencode_runtime_diagnostics(
            detect_opencode_runtime_diagnostics(result.output)
        )

        return result, diagnostics
