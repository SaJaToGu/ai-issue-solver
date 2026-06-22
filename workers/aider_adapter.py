"""
workers.aider_adapter — Adapter für Aider-basierte Provider.

.. deprecated::
    ``workers.aider_adapter`` is deprecated as of the 0.9.0 release and will
    be removed in the next minor release. Use one of the supported worker
    paths instead:

    - ``opencode`` (default model ``opencode/deepseek-v4-flash-free``)
    - ``openrouter_direct``
    - ``codex``

    See issue #411 / §47 in ``docs/BACKLOG/open.md`` and
    ``docs/SETUP_AIDER.md`` for migration guidance.

Kapselt Befehlsaufbau und Ausführung für alle Provider, die Aider als
Worker verwenden: claude, openai, mistral, ollama, openrouter.

Aider-spezifische Konfiguration:
    - Solver-lokale Chat-/Input-History-Dateien (kein ~/.aider/).
    - --no-auto-commits, --no-check-update, --no-analytics, --no-gitignore.
    - --map-tokens 0 (kein repo-lokaler .aider.tags.cache).
    - --subtree-only (Repository-Kontext auf Arbeitsbaum begrenzen).

Secret-Behandlung:
    - ANTHROPIC_API_KEY, OPENAI_API_KEY, MISTRAL_API_KEY je nach Provider.
    - OpenRouter entfernt andere Provider-Keys zur Sicherheit.
    - Ollama setzt OLLAMA_API_BASE aus Config (Standard: http://localhost:11434).
"""

from __future__ import annotations

import os
import shutil
import sys
import warnings
from pathlib import Path
from typing import Any

from workers.base import WorkerAdapter, WorkerRunResult, AdapterDiagnostics
from workers.codex_adapter import _run_subprocess


_AIDER_DEPRECATION_EMITTED = False
_AIDER_DEPRECATION_MESSAGE = (
    "workers.aider_adapter is deprecated and will be removed in the next "
    "minor release. Use opencode (opencode/deepseek-v4-flash-free), "
    "openrouter_direct, or codex instead. "
    "See issue #411 / §47 in docs/BACKLOG/open.md."
)


def _emit_aider_deprecation_warning(stacklevel: int = 3) -> None:
    """Emit the Aider deprecation warning at most once per process."""
    global _AIDER_DEPRECATION_EMITTED
    if _AIDER_DEPRECATION_EMITTED:
        return
    _AIDER_DEPRECATION_EMITTED = True
    warnings.warn(_AIDER_DEPRECATION_MESSAGE, DeprecationWarning, stacklevel=stacklevel)


# ─────────────────────────────────────────────────────────────
# Aider-Modell-Konfigurationen
# ─────────────────────────────────────────────────────────────

# Mapping: Provider-Name → Aider-Flaggen-Template und API-Key-Anforderungen
AIDER_MODEL_CONFIGS: dict[str, dict] = {
    "claude": {
        "display_name": "Anthropic Claude (claude-sonnet-4-20250514)",
        "aider_flags": ["--model", "claude-sonnet-4-20250514"],
        "env_key": "ANTHROPIC_API_KEY",
        "env_var": "ANTHROPIC_API_KEY",
    },
    "openai": {
        "display_name": "OpenAI GPT-4o",
        "aider_flags": ["--model", "gpt-4o"],
        "env_key": "OPENAI_API_KEY",
        "env_var": "OPENAI_API_KEY",
    },
    "mistral": {
        "display_name": "Mistral AI Magistral (magistral-medium-2509)",
        "aider_flags": ["--model", "mistral/{model_name}"],
        "env_key": "MISTRAL_API_KEY",
        "env_var": "MISTRAL_API_KEY",
        "default_model_name": "magistral-medium-2509",
    },
    "ollama": {
        "display_name": "Ollama (lokal)",
        "aider_flags": ["--model", "ollama/{model_name}"],
        "env_key": None,
        "env_var": None,
        "default_model_name": "deepseek-coder:6.7b",
    },
    "openrouter": {
        "display_name": "OpenRouter (aider, legacy)",
        "aider_flags": ["--model", "{model_name}"],
        "env_key": "OPENROUTER_API_KEY",
        "env_var": "OPENROUTER_API_KEY",
        "default_model_name": "openrouter/openai/gpt-4o-mini",
    },
}

# Bekannte Projektverzeichnisse für Datei-Target-Inferenz
KNOWN_PROJECT_DIRS = frozenset({"scripts", "tests", "src", "lib", "app", "config", "docs"})


# ─────────────────────────────────────────────────────────────
# Hilfsfunktionen
# ─────────────────────────────────────────────────────────────

def find_aider_executable() -> str | None:
    """
    Sucht das Aider-Executable in Venv-Pfaden oder PATH.

    Suchreihenfolge:
        1. Gleicher Bin-Pfad wie aktuelles Python (falls in .venv/venv).
        2. .venv/bin/aider und venv/bin/aider im aktuellen Verzeichnis.
        3. site-packages-Pfade der aktuellen Python-Umgebung.
        4. shutil.which("aider")
    """
    candidates = []

    python_executable = sys.executable
    if python_executable:
        python_path = Path(python_executable).resolve()
        venv_bin = python_path.parent
        if venv_bin.exists() and venv_bin.name == "bin":
            venv_path = venv_bin.parent
            if venv_path.name in ("venv", ".venv"):
                aider_path = venv_bin / "aider"
                if aider_path.exists():
                    return str(aider_path)
                candidates.append(str(aider_path))

    for venv_name in (".venv", "venv"):
        venv_path = Path.cwd() / venv_name
        aider_path = venv_path / "bin" / "aider"
        if aider_path.exists():
            return str(aider_path)
        candidates.append(str(aider_path))

    try:
        import site
        user_site = site.getusersitepackages()
        for site_path in site.getsitepackages() + ([user_site] if isinstance(user_site, str) else user_site):
            aider_path = Path(site_path).parent / "bin" / "aider"
            if aider_path.exists():
                return str(aider_path)
    except Exception:
        pass

    return shutil.which("aider")


def build_aider_flags(provider: str, model_name: str) -> list[str]:
    """
    Erzeugt die aider-Flaggen für einen Provider/Modell-Namen.

    Args:
        provider:   Provider-Name (claude, openai, mistral, ollama, openrouter).
        model_name: Konkretisierter Modell-Name (ersetzt {model_name} im Template).

    Returns:
        Liste der Aider-Flaggen (z. B. ["--model", "mistral/magistral-medium-2509"]).
    """
    config = AIDER_MODEL_CONFIGS[provider]
    flags = []
    for flag in config["aider_flags"]:
        if "{model_name}" in flag:
            flags.append(flag.format(model_name=model_name))
        else:
            flags.append(flag)
    return flags


# ─────────────────────────────────────────────────────────────
# Adapter-Klasse
# ─────────────────────────────────────────────────────────────

class AiderAdapter(WorkerAdapter):
    """
    Worker-Adapter für Aider-basierte Provider (claude, openai, mistral, ollama, openrouter).

    Unterstützt:
        - Provider-spezifische Modell-Flaggen.
        - Solver-lokale Chat-/Input-History-Dateien.
        - Datei-Target-Inferenz aus dem Prompt (nur existierende Repo-Dateien).
        - Secret-Bereinigung im Prompt.
        - Provider-spezifische API-Key-Validierung.
    """

    name = "aider"

    def __init__(self, provider: str):
        """
        Args:
            provider: Provider-Name (claude, openai, mistral, ollama, openrouter).

        Raises:
            ValueError: Bei unbekanntem Provider.
        """
        _emit_aider_deprecation_warning(stacklevel=2)
        if provider not in AIDER_MODEL_CONFIGS:
            raise ValueError(
                f"Unbekannter Aider-Provider: '{provider}'. "
                f"Bekannte Provider: {sorted(AIDER_MODEL_CONFIGS)}"
            )
        self.provider = provider
        self._config = AIDER_MODEL_CONFIGS[provider]

    def get_display_name(self) -> str:
        return self._config["display_name"]

    def get_default_model_name(self) -> str:
        """Gibt den Standard-Modell-Namen zurück (leer falls nicht konfiguriert)."""
        return self._config.get("default_model_name", "")

    def build_command(
        self,
        prompt: str,
        repo_path: str,
        model_name: str | None = None,
        file_targets: list[str] | None = None,
        **kwargs: Any,
    ) -> list[str]:
        """
        Baut den Aider-Befehl auf.

        Args:
            prompt:       Sanitierter Prompt für Aider.
            repo_path:    Absoluter Pfad zum Repository.
            model_name:   Optionaler Modell-Override.
            file_targets: Explizite Liste von Datei-Targets; wenn None, werden
                          Targets aus dem Prompt inferiert.

        Raises:
            FileNotFoundError: Wenn das Aider-Executable nicht gefunden wird.
        """
        from workers.opencode_adapter import ensure_solver_directories

        aider = find_aider_executable()
        if not aider:
            raise FileNotFoundError("aider")

        # Effektiven Modell-Namen bestimmen
        effective_model_name = model_name or self.get_default_model_name()
        flags = build_aider_flags(self.provider, effective_model_name)

        # Datei-Targets aus Prompt inferieren wenn nicht explizit übergeben
        if file_targets is None:
            file_targets = _infer_aider_targets(prompt, repo_path)

        # Solver-lokale History-Pfade
        state_dir, _ = ensure_solver_directories()
        chat_history_file = state_dir / "aider.chat.history.md"
        input_history_file = state_dir / "aider.input.history"

        cmd = [
            aider,
            *flags,
            "--yes",
            "--no-auto-commits",
            "--no-check-update",
            "--no-analytics",
            "--no-gitignore",
            "--chat-history-file", str(chat_history_file),
            "--input-history-file", str(input_history_file),
            "--map-tokens", "0",
            "--subtree-only",
            "--message", prompt,
            *file_targets,
        ]

        return cmd

    def build_env(
        self,
        config: dict[str, str],
        base_env: dict[str, str] | None = None,
    ) -> dict[str, str]:
        """
        Erzeugt die Aider-Umgebung mit provider-spezifischen API-Keys.

        Raises:
            SystemExit(1): Wenn ein Pflicht-API-Key fehlt oder ein Platzhalter ist.
        """
        from utils import require_config_value

        env = dict(base_env if base_env is not None else os.environ)
        env_key = self._config.get("env_key")

        if env_key:
            api_key = require_config_value(config, env_key)
            env[self._config["env_var"]] = api_key

        if self.provider == "ollama":
            ollama_host = config.get("OLLAMA_HOST", "http://localhost:11434")
            env["OLLAMA_API_BASE"] = ollama_host

        if self.provider == "openrouter":
            # OpenRouter: andere Provider-Keys entfernen
            env.pop("ANTHROPIC_API_KEY", None)
            env.pop("MISTRAL_API_KEY", None)
            env.pop("OPENAI_API_KEY", None)

        # OpenCode-spezifische Variablen für Aider entfernen
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
        file_targets: list[str] | None = None,
        **kwargs: Any,
    ) -> tuple[WorkerRunResult, AdapterDiagnostics]:
        """
        Führt Aider aus und gibt Ergebnis + Diagnostics zurück.
        """
        diagnostics = AdapterDiagnostics()

        try:
            cmd = self.build_command(prompt, repo_path, model_name, file_targets)
        except FileNotFoundError:
            error_msg = "Aider nicht gefunden (FileNotFoundError)"
            diagnostics.all_outputs.append(error_msg)
            return (
                WorkerRunResult(returncode=127, output=error_msg),
                diagnostics,
            )

        result = _run_subprocess(cmd, repo_path, env, run_report=run_report,
                                 verbosity=verbosity)
        diagnostics.all_outputs.append(result.output)

        return result, diagnostics


# ─────────────────────────────────────────────────────────────
# Interne Hilfsfunktionen für Target-Inferenz
# ─────────────────────────────────────────────────────────────

def _infer_aider_targets(prompt: str, repo_path: str) -> list[str]:
    """
    Inferiert Datei-Targets aus dem Prompt für Aider.

    Delegiert an die entsprechenden Funktionen in solve_issues wenn verfügbar,
    ansonsten leere Liste (kein Fehler).
    """
    try:
        from solve_issues import infer_aider_targets
        return infer_aider_targets(prompt, repo_path)
    except ImportError:
        return []
