"""
workers.openrouter_direct_adapter — Adapter für den OpenRouter Direct Worker.

Kapselt den API-basierten Ausführungspfad über workers.openrouter_worker.OpenRouterWorker
(ohne Aider oder CLI-Wrapper).

Besonderheiten:
    - Kein subprocess – der Worker ruft die OpenRouter API direkt auf.
    - Extrahiert Unified-Diff-Patches aus der Modellantwort und wendet sie an.
    - Gibt vollständige Rohausgabe (Modell-Antwort + Patch-Protokoll) in den Diagnostics.
    - Returncode-Semantik:
        0 → Mindestens ein Patch erfolgreich angewendet.
        1 → Patches gefunden, aber alle fehlgeschlagen oder API-Fehler.
        2 → Modell hat nur Prosa ohne auswertbare Diffs zurückgegeben.

Secret-Behandlung:
    - OPENROUTER_API_KEY wird aus der Konfiguration gelesen.
    - Andere Provider-Keys (ANTHROPIC, MISTRAL, OPENAI) werden aus der Umgebung entfernt.
"""

from __future__ import annotations

import os
from datetime import datetime
from typing import Any

from workers.base import WorkerAdapter, WorkerRunResult, AdapterDiagnostics


# Standard-Modell für OpenRouter Direct
OPENROUTER_DIRECT_DEFAULT_MODEL = "mistralai/mistral-large"


class OpenRouterDirectAdapter(WorkerAdapter):
    """
    Worker-Adapter für den direkten OpenRouter API-Worker.

    Dieser Adapter hat keinen subprocess-Ausführungspfad – er ruft
    workers.openrouter_worker.OpenRouterWorker.run_direct() direkt auf
    und konvertiert das DirectRunResult in ein WorkerRunResult.

    Ausgabe-Filterung und Suppression-Summary werden wie bei subprocess-Adaptern
    durchgeführt, um eine konsistente Benutzererfahrung sicherzustellen.
    """

    name = "openrouter_direct"

    def get_display_name(self) -> str:
        return "OpenRouter (Direct)"

    def build_command(
        self,
        prompt: str,
        repo_path: str,
        model_name: str | None = None,
        **kwargs: Any,
    ) -> None:
        """
        OpenRouter Direct hat keinen CLI-Befehl – gibt None zurück.

        Der Worker wird direkt über run() ausgeführt.
        """
        return None

    def build_env(
        self,
        config: dict[str, str],
        base_env: dict[str, str] | None = None,
    ) -> dict[str, str]:
        """
        Benötigt OPENROUTER_API_KEY in der Konfiguration.

        Entfernt andere Provider-Keys zur Sicherheit (ANTHROPIC, MISTRAL, OPENAI).

        Raises:
            SystemExit(1): Wenn OPENROUTER_API_KEY fehlt oder ein Platzhalter ist.
        """
        from utils import require_config_value

        env = dict(base_env if base_env is not None else os.environ)
        api_key = require_config_value(config, "OPENROUTER_API_KEY")
        env["OPENROUTER_API_KEY"] = api_key

        # Andere Provider-Keys entfernen
        env.pop("ANTHROPIC_API_KEY", None)
        env.pop("MISTRAL_API_KEY", None)
        env.pop("OPENAI_API_KEY", None)

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
        Führt den OpenRouter Direct Worker aus.

        1. Liest OPENROUTER_API_KEY aus der Umgebung oder dem kwargs-Parameter.
        2. Erstellt einen OpenRouterWorker und ruft run_direct() auf.
        3. Zeigt die Ausgabe live gefiltert an (analog zu subprocess-Adaptern).
        4. Gibt WorkerRunResult + AdapterDiagnostics zurück.

        Args:
            prompt:     Sanitierter Prompt.
            repo_path:  Absoluter Pfad zum Repository.
            env:        Umgebung (wird für OPENROUTER_API_KEY genutzt).
            model_name: Modell-Override (Standard: OPENROUTER_DIRECT_DEFAULT_MODEL).
            verbosity:  "quiet", "normal" oder "verbose".
            run_report: Optionaler RunReport (nicht genutzt, da kein subprocess).
            **kwargs:   Optionaler api_key-Override via kwargs["api_key"].
        """
        from solver_reporting import should_surface_worker_line
        from utils import print_err

        diagnostics = AdapterDiagnostics()

        # API-Key bestimmen
        effective_key = kwargs.get("api_key") or env.get("OPENROUTER_API_KEY") or os.getenv("OPENROUTER_API_KEY")
        if not effective_key:
            error_msg = "[openrouter_direct] FEHLER: OPENROUTER_API_KEY ist nicht gesetzt."
            print_err(error_msg)
            diagnostics.all_outputs.append(error_msg)
            return WorkerRunResult(returncode=1, output=error_msg), diagnostics

        # Effektiven Modell-Namen bestimmen
        effective_model = model_name or OPENROUTER_DIRECT_DEFAULT_MODEL

        try:
            from workers.openrouter_worker import OpenRouterWorker
        except ImportError as exc:
            error_msg = f"[openrouter_direct] workers.openrouter_worker nicht importierbar: {exc}"
            print_err(error_msg)
            diagnostics.all_outputs.append(error_msg)
            return WorkerRunResult(returncode=1, output=error_msg), diagnostics

        worker = OpenRouterWorker(api_key=effective_key, model=effective_model)
        file_targets = kwargs.get("file_targets")
        if file_targets is None:
            try:
                from solve_issues import infer_aider_targets
                file_targets = infer_aider_targets(prompt, repo_path)
            except ImportError:
                file_targets = []

        try:
            direct_result = worker.run_direct(
                prompt=prompt,
                repo_dir=repo_path,
                file_targets=file_targets,
            )
        except Exception as exc:
            error_msg = f"[openrouter_direct] Unerwarteter Fehler: {exc}"
            print_err(error_msg)
            diagnostics.all_outputs.append(error_msg)
            return WorkerRunResult(returncode=1, output=error_msg), diagnostics

        diagnostics.all_outputs.append(direct_result.output)

        # Ausgabe live gefiltert anzeigen (konsistent mit subprocess-Adaptern)
        suppressed_lines = 0
        last_activity_at = datetime.now()

        for line in direct_result.output.splitlines(keepends=True):
            if verbosity == "verbose":
                if line.strip():
                    print(f"        | {line}", end="")
                last_activity_at = datetime.now()
            elif verbosity == "normal":
                if should_surface_worker_line(line):
                    print(f"        | {line}", end="")
                    last_activity_at = datetime.now()
                else:
                    suppressed_lines += 1
            else:
                # quiet
                if should_surface_worker_line(line):
                    last_activity_at = datetime.now()
                else:
                    suppressed_lines += 1

        if verbosity != "quiet" and suppressed_lines:
            print(
                f"        | ... {suppressed_lines} Detailzeilen ausgeblendet; "
                "Rohoutput bleibt in der Diagnose erhalten"
            )

        return (
            WorkerRunResult(
                returncode=direct_result.returncode,
                output=direct_result.output,
                last_activity_at=last_activity_at,
            ),
            diagnostics,
        )
