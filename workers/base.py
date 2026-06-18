"""
workers.base — Worker-Adapter-Protokoll und gemeinsame Datenstrukturen.

Definiert das WorkerAdapter-Protokoll als abstrakte Basisklasse sowie die
gemeinsamen Datenklassen für Konfiguration, Ausführungsergebnis und Bewertung.

Jeder konkreter Adapter implementiert:
    - build_command(...)   → Befehlszeile als Liste oder None (für API-Worker)
    - run(...)             → WorkerRunResult
    - filter_output(line)  → bool  (True = Zeile anzeigen)
    - classify_result(...) → WorkerOutcome

Gemeinsame Ergebnis-Klassifizierung:
    changed                 → Worker erfolgreich, Dateien geändert
    no_changes              → Worker erfolgreich, keine Änderungen
    nonzero_with_changes    → Worker mit Fehlercode, aber Änderungen vorhanden
    nonzero_without_changes → Worker mit Fehlercode, keine Änderungen
    rate_limit_deferred     → Codex Rate-Limit, kein sofortiger Retry
    failed_worker           → Worker nicht gefunden oder nicht startbar
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


# ─────────────────────────────────────────────────────────────
# Gemeinsame Ergebnis-Datenklassen
# ─────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class WorkerRunResult:
    """Ergebnis eines Worker-Laufs mit Exit-Code, kombinierter Ausgabe und Zeitstempel."""
    returncode: int
    output: str
    last_activity_at: datetime | None = None


@dataclass(frozen=True)
class WorkerOutcome:
    """Bewertung des Worker-Ergebnisses nach Auswertung von Exit-Code und Git-Status."""
    should_continue: bool
    has_changes: bool
    reason: str


@dataclass(frozen=True)
class WorkerValidation:
    """Ergebnis der Validierung der Worker-Änderungen (Syntaxprüfung, Konfliktmarker)."""
    ok: bool
    errors: tuple[str, ...] = ()


@dataclass
class AdapterDiagnostics:
    """Optionale Diagnose-Daten die ein Adapter während des Laufs sammeln kann."""
    # Vibe-Log-Snippet (nur für Mistral Vibe)
    vibe_log_snippet: str = ""
    # Rate-Limit-Hinweis (nur für Codex)
    rate_limit_note: str = ""
    # Rohausgabe aller Runs (für diagnostischen Report)
    all_outputs: list[str] = field(default_factory=list)
    # OpenCode-Session-Totals (nur für OpenCodeAdapter)
    opencode_session_totals: dict | None = None
    # OpenCode-Budget-Ueberschreitung (nur für OpenCodeAdapter)
    opencode_budget_exceeded: str | None = None
    # OpenRouter-Direct Usage (nur für OpenRouterDirectAdapter)
    openrouter_usage: dict | None = None
    # OpenRouter-Direct Budget-Ueberschreitung (nur für OpenRouterDirectAdapter)
    openrouter_budget_exceeded: str | None = None
    # OpenRouter-Direct Request-Timeout (nur für OpenRouterDirectAdapter)
    openrouter_request_timed_out: bool = False


# ─────────────────────────────────────────────────────────────
# Abstrakte Basisklasse
# ─────────────────────────────────────────────────────────────

class WorkerAdapter(ABC):
    """
    Abstrakte Basisklasse für alle Worker-Adapter.

    Jeder Adapter kapselt genau einen Provider (z. B. Codex, OpenCode, Aider)
    und ist für folgende Aufgaben zuständig:
        1. Befehlszeile aufbauen (build_command)
        2. Worker ausführen und Ergebnis zurückgeben (run)
        3. Ausgabezeilen filtern (filter_output_line)
        4. Ergebnis klassifizieren (classify_result)

    Der Adapter stellt sicher, dass:
        - Provider-spezifische Secret-Behandlung und Umgebungsbereinigung
          in der Adapter-Klasse bleibt.
        - Die vollständige Rohausgabe in den Diagnostics verfügbar bleibt.
        - Outcome-Klassifizierung konsistent mit allen anderen Adaptern ist.
    """

    # Kurzname des Adapters (z. B. "codex", "opencode"); wird für Logging verwendet
    name: str = "unknown"

    @abstractmethod
    def build_command(
        self,
        prompt: str,
        repo_path: str,
        model_name: str | None = None,
        **kwargs: Any,
    ) -> list[str] | None:
        """
        Baut die Befehlszeile für den Worker auf.

        Args:
            prompt:     Sanitierter Prompt für den Worker.
            repo_path:  Absoluter Pfad zum geklonten Repository.
            model_name: Optionaler Modell-Override (z. B. "mistral/mistral-small").
            **kwargs:   Provider-spezifische Zusatzparameter.

        Returns:
            list[str]: Befehlszeile als Liste. None für API-Worker (run() direkt).
        """

    @abstractmethod
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
        Führt den Worker aus und gibt Ergebnis + Diagnostics zurück.

        Args:
            prompt:     Sanitierter Prompt für den Worker.
            repo_path:  Absoluter Pfad zum geklonten Repository.
            env:        Umgebung für den Worker-Prozess.
            model_name: Optionaler Modell-Override.
            verbosity:  "quiet", "normal" oder "verbose".
            run_report: Optionaler RunReport für Health-Writes.
            **kwargs:   Provider-spezifische Zusatzparameter.

        Returns:
            Tupel (WorkerRunResult, AdapterDiagnostics).
        """

    def filter_output_line(self, line: str) -> bool:
        """
        Entscheidet, ob eine Worker-Ausgabezeile im normalen Modus angezeigt wird.

        Standardimplementierung: delegiert an den gemeinsamen Filter.
        Adapter können diese Methode überschreiben, um provider-spezifische
        Ausgaben zu unterdrücken oder hervorzuheben.

        Args:
            line: Eine Ausgabezeile des Workers (mit Zeilenumbruch).

        Returns:
            True wenn die Zeile angezeigt werden soll.
        """
        from solver_reporting import should_surface_worker_line
        return should_surface_worker_line(line)

    def build_env(
        self,
        config: dict[str, str],
        base_env: dict[str, str] | None = None,
    ) -> dict[str, str]:
        """
        Erzeugt die Worker-Umgebung mit provider-spezifischen Keys.

        Standardimplementierung: gibt eine Kopie von base_env zurück.
        Adapter mit API-Keys überschreiben diese Methode.

        Args:
            config:   Konfigurationswerte (z. B. API-Keys).
            base_env: Basis-Umgebung (Standard: os.environ).

        Returns:
            Angepasste Umgebungsvariablen-Dict.
        """
        import os
        return dict(base_env if base_env is not None else os.environ)

    def get_display_name(self) -> str:
        """Gibt den Anzeigenamen des Adapters zurück (für Logging und PRs)."""
        return self.name
