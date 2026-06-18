"""
workers.openrouter_direct_adapter — Adapter für den OpenRouter Direct Worker.

Kapselt den API-basierten Ausführungspfad über workers.openrouter_worker.OpenRouterWorker
(ohne Aider oder CLI-Wrapper).

Besonderheiten:
    - Kein subprocess – der Worker ruft die OpenRouter API direkt auf.
    - Extrahiert Unified-Diff-Patches aus der Modellantwort und wendet sie an.
    - Gibt vollständige Rohausgabe (Modell-Antwort + Patch-Protokoll) in den Diagnostics.
    - Übernimmt die per-Run CLI-Budget-Flags `--max-run-cost-usd`,
      `--max-run-input-tokens`, `--max-run-output-tokens` und
      `--max-run-cache-read-tokens`. Letzteres wird explizit als unsupported
      für OpenRouter Direct markiert.
    - Unterstützt einen konfigurierbaren Request-Timeout (`--max-run-runtime-seconds`).
    - Setzt `--max-run-output-tokens` als `max_tokens` der OpenRouter-Anfrage um.
    - Erzwingt Post-Response Budget-Limits und meldet Budget/Control-Failures
      via `adapter_diagnostics.openrouter_budget_exceeded`.

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

# Standard-Request-Timeout in Sekunden (wird durch kwargs überschrieben).
DEFAULT_OPENROUTER_RUNTIME_SECONDS = 180

# Limitiert das per-Anfrage `max_tokens` für OpenRouter, damit ungewollt hohe
# Output-Token-Anfragen vorab gedeckelt werden. Wird durch
# --max-run-output-tokens überschrieben.
DEFAULT_OPENROUTER_MAX_OUTPUT_TOKENS = 8192


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

    def _extract_budget_kwargs(self, kwargs: dict) -> dict:
        """Holt und entfernt die per-Run Budget-Kwargs aus dem kwargs-Dict."""
        return {
            "max_run_cost_usd": kwargs.pop("max_run_cost_usd", None),
            "max_run_input_tokens": kwargs.pop("max_run_input_tokens", None),
            "max_run_output_tokens": kwargs.pop("max_run_output_tokens", None),
            "max_run_cache_read_tokens": kwargs.pop("max_run_cache_read_tokens", None),
            "max_run_runtime_seconds": kwargs.pop("max_run_runtime_seconds", None),
        }

    def _log_preflight_warnings(self, budget: dict) -> None:
        """Gibt nicht-fataler Warnungen für Felder aus, die OpenRouter Direct
        nicht hard vor dem API-Call durchsetzen kann.
        """
        from utils import print_warn

        unsupported = []
        if budget.get("max_run_cost_usd") is not None:
            unsupported.append("--max-run-cost-usd")
        if budget.get("max_run_input_tokens") is not None:
            unsupported.append("--max-run-input-tokens")
        if budget.get("max_run_cache_read_tokens") is not None:
            unsupported.append("--max-run-cache-read-tokens (strukturell unsupported)")
        if unsupported:
            print_warn(
                "[openrouter_direct] Hinweis: OpenRouter Direct kann die folgenden "
                f"Limits erst nach der API-Antwort prüfen: {', '.join(unsupported)}. "
                "Es findet kein Live-Streaming-Abbruch statt."
            )

    def _format_usage_log_line(self, usage: dict) -> str:
        """Baut eine kompakte Log-Zeile für die erfassten Usage-Metriken."""
        parts = []
        if usage.get("model"):
            parts.append(f"model={usage['model']}")
        if usage.get("prompt_tokens") is not None:
            parts.append(f"prompt_tokens={usage['prompt_tokens']}")
        if usage.get("completion_tokens") is not None:
            parts.append(f"completion_tokens={usage['completion_tokens']}")
        if usage.get("total_tokens") is not None:
            parts.append(f"total_tokens={usage['total_tokens']}")
        if usage.get("cost_usd") is not None:
            parts.append(f"cost_usd=${usage['cost_usd']:.4f}")
        if usage.get("request_seconds") is not None:
            parts.append(f"request_seconds={usage['request_seconds']:.2f}s")
        return "[openrouter_direct] Usage: " + ", ".join(parts) if parts else ""

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
        2. Übernimmt die per-Run Budget-Kwargs.
        3. Erstellt einen OpenRouterWorker und ruft run_direct() auf.
        4. Prüft Post-Response Budget-Limits und meldet Überschreitungen
           über AdapterDiagnostics.openrouter_budget_exceeded.
        5. Zeigt die Ausgabe live gefiltert an (analog zu subprocess-Adaptern).
        6. Gibt WorkerRunResult + AdapterDiagnostics zurück.

        Args:
            prompt:     Sanitierter Prompt.
            repo_path:  Absoluter Pfad zum Repository.
            env:        Umgebung (wird für OPENROUTER_API_KEY genutzt).
            model_name: Modell-Override (Standard: OPENROUTER_DIRECT_DEFAULT_MODEL).
            verbosity:  "quiet", "normal" oder "verbose".
            run_report: Optionaler RunReport (nicht genutzt, da kein subprocess).
            **kwargs:   Optionale api_key- und Budget-Kwargs:
                - api_key: API-Key-Override
                - max_run_cost_usd: Maximale Kosten in USD
                - max_run_input_tokens: Maximale Input-Tokens
                - max_run_output_tokens: Maximale Output-Tokens (→ max_tokens)
                - max_run_cache_read_tokens: Unsupported für OpenRouter Direct
                - max_run_runtime_seconds: Request-Timeout in Sekunden
        """
        from solver_reporting import should_surface_worker_line
        from utils import print_err
        from workers.openrouter_worker import (
            DEFAULT_REQUEST_TIMEOUT_SECONDS,
            OpenRouterBudgetLimits,
            check_openrouter_budget_limits,
            has_openrouter_any_limit,
        )

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

        # Budget-Kwargs extrahieren (und aus kwargs entfernen)
        budget_kwargs = self._extract_budget_kwargs(kwargs)
        self._log_preflight_warnings(budget_kwargs)

        try:
            from workers.openrouter_worker import OpenRouterWorker
        except ImportError as exc:
            error_msg = f"[openrouter_direct] workers.openrouter_worker nicht importierbar: {exc}"
            print_err(error_msg)
            diagnostics.all_outputs.append(error_msg)
            return WorkerRunResult(returncode=1, output=error_msg), diagnostics

        # --max-run-output-tokens → max_tokens Mapping für die OpenRouter-Anfrage.
        # Hard-Pre-Call-Limit: verhindert, dass die Anfrage selbst ein zu hohes
        # Token-Limit anfordert. Die echte Budget-Prüfung erfolgt nach der Antwort.
        requested_max_tokens = budget_kwargs.get("max_run_output_tokens")
        if requested_max_tokens is not None:
            try:
                requested_max_tokens = max(1, int(requested_max_tokens))
            except (TypeError, ValueError):
                requested_max_tokens = None
        if requested_max_tokens is None:
            requested_max_tokens = DEFAULT_OPENROUTER_MAX_OUTPUT_TOKENS

        # Request-Timeout: kwargs-Override oder Default
        runtime_limit = budget_kwargs.get("max_run_runtime_seconds")
        try:
            runtime_limit_f = float(runtime_limit) if runtime_limit is not None else None
        except (TypeError, ValueError):
            runtime_limit_f = None
        if runtime_limit_f is None or runtime_limit_f <= 0:
            runtime_limit_f = float(DEFAULT_REQUEST_TIMEOUT_SECONDS)

        worker = OpenRouterWorker(
            api_key=effective_key,
            model=effective_model,
            request_timeout_seconds=runtime_limit_f,
        )
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
                max_tokens=requested_max_tokens,
                request_timeout=runtime_limit_f,
            )
        except Exception as exc:
            error_msg = f"[openrouter_direct] Unerwarteter Fehler: {exc}"
            print_err(error_msg)
            diagnostics.all_outputs.append(error_msg)
            return WorkerRunResult(returncode=1, output=error_msg), diagnostics

        diagnostics.all_outputs.append(direct_result.output)

        # Usage in Diagnostics übernehmen
        usage_dict: dict | None = None
        if direct_result.usage is not None:
            usage_dict = direct_result.usage.to_dict()
            diagnostics.openrouter_usage = usage_dict

            usage_log = self._format_usage_log_line(usage_dict)
            if usage_log:
                diagnostics.all_outputs.append(usage_log)

            if direct_result.usage.timed_out:
                diagnostics.openrouter_request_timed_out = True

        # Post-Response Budget-Enforcement
        limits = OpenRouterBudgetLimits(
            max_cost_usd=budget_kwargs.get("max_run_cost_usd"),
            max_input_tokens=budget_kwargs.get("max_run_input_tokens"),
            max_output_tokens=budget_kwargs.get("max_run_output_tokens"),
            max_cache_read_tokens=budget_kwargs.get("max_run_cache_read_tokens"),
        )
        if has_openrouter_any_limit(limits):
            check = check_openrouter_budget_limits(direct_result.usage, limits)
            if check.exceeded_reason:
                diagnostics.openrouter_budget_exceeded = check.exceeded_reason
                # Bei Budget-/Control-Failure wird der Returncode auf 4 gesetzt,
                # damit der Solver-Run klar von Modell- oder Patch-Fehlern (0/1/2)
                # und Timeouts (3) abgegrenzt werden kann.
                direct_result.returncode = 4
                budget_log = (
                    f"[openrouter_direct] BUDGET-EXCEEDED: {check.exceeded_reason}"
                )
                diagnostics.all_outputs.append(budget_log)

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
