"""
Direkter OpenRouter Worker für OpenAI-kompatible API-Aufrufe.

Verwendet die OpenRouter API (https://openrouter.ai) ohne Aider-Abhängigkeit.
Unterstützt Model-Overrides wie `mistralai/mistral-large`.

Der Worker kann:
- Direkten API-Text generieren (generate)
- Unified-Diff-Patches aus der Modellantwort extrahieren (extract_patches)
- Patches sicher im Zielverzeichnis anwenden (apply_patches)
- Einen kompletten Durchlauf mit Datei-Editierung ausführen (run_direct)
- Usage-Metriken aus der API-Antwort extrahieren (prompt_tokens,
  completion_tokens, total_tokens, cost, tatsächlich verwendetes Modell)
- Konfigurierbares Request-Timeout und Post-Response Budget-Enforcement
"""

from __future__ import annotations

import os
import re
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Dict, Any, List

import requests


# Regulärer Ausdruck zum Erkennen von Unified-Diff-Blöcken im Modelloutput.
# Unterstützt optional umrahmende Markdown-Code-Fences (```diff ... ``` oder ``` ... ```).
_DIFF_FENCE_RE = re.compile(
    r"```(?:diff)?\s*\n((?:---\s+\S.*\n|\+\+\+\s+\S.*\n|@@.*\n|[ +\-\\].*\n)+)```",
    re.MULTILINE,
)

# Einfaches Muster für bare Unified-Diff-Blöcke außerhalb von Code-Fences.
_DIFF_BARE_RE = re.compile(
    r"(?:^|\n)(---\s+\S[^\n]*\n\+\+\+\s+\S[^\n]*\n(?:@@[^\n]*\n(?:[ +\-\\][^\n]*\n)*)+)",
    re.MULTILINE,
)


# Standard-Request-Timeout in Sekunden (wird von Adapter überschrieben).
DEFAULT_REQUEST_TIMEOUT_SECONDS = 180


@dataclass
class PatchResult:
    """Ergebnis der Patch-Anwendung für eine einzelne Diff-Datei."""
    patch_index: int
    success: bool
    applied_file: Optional[str] = None
    error: Optional[str] = None


@dataclass
class OpenRouterUsage:
    """Usage-Metriken aus einer OpenRouter API-Antwort.

    Felder sind mit None vorbelegt; nur die tatsächlich von der API gemeldeten
    Werte werden gesetzt. cost ist nur vorhanden, wenn OpenRouter den Preis
    mit ausliefert (typisch bei responses mit usage-Block).
    """
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    total_tokens: Optional[int] = None
    cost_usd: Optional[float] = None
    model: Optional[str] = None
    request_seconds: Optional[float] = None
    timed_out: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "cost_usd": self.cost_usd,
            "model": self.model,
            "request_seconds": self.request_seconds,
            "timed_out": self.timed_out,
        }


@dataclass
class DirectRunResult:
    """
    Vollständiges Ergebnis eines openrouter_direct Worker-Laufs.

    Attributes:
        returncode: 0 bei Erfolg, 1 bei Fehlschlag (kein Patch, alle Patches fehlgeschlagen),
                    2 bei Prosa-Ausgabe ohne auswertbare Edits.
        output: Kombinierter Ausgabe-Text (Modell-Antwort + Patch-Protokoll).
        patch_results: Liste der Einzel-Patch-Ergebnisse.
        raw_response: Rohe Modell-Antwort.
        usage: Extrahierte Usage-Metriken (None wenn keine Antwort erhalten wurde).
    """
    returncode: int
    output: str
    patch_results: List[PatchResult] = field(default_factory=list)
    raw_response: str = ""
    usage: Optional[OpenRouterUsage] = None


class OpenRouterWorker:
    """Direkter OpenRouter Worker für OpenAI-kompatible API-Aufrufe."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "mistralai/mistral-large",
        base_url: str = "https://openrouter.ai/api/v1",
        referer: Optional[str] = None,
        x_title: Optional[str] = None,
        request_timeout_seconds: float = DEFAULT_REQUEST_TIMEOUT_SECONDS,
    ):
        """
        Args:
            api_key: OpenRouter API Key. Wird standardmäßig aus `OPENROUTER_API_KEY` gelesen.
            model: OpenRouter Model-String (z. B. `mistralai/mistral-large`).
            base_url: OpenRouter API Base URL.
            referer: HTTP-Referer für OpenRouter.
            x_title: X-Title für OpenRouter.
            request_timeout_seconds: Timeout für den synchronen API-Aufruf.
        """
        self.api_key = api_key or os.getenv("OPENROUTER_API_KEY")
        if not self.api_key:
            raise ValueError("OPENROUTER_API_KEY ist nicht gesetzt.")

        self.model = model
        self.base_url = base_url
        self.referer = referer or os.getenv("OPENROUTER_REFERER", "https://github.com/anomalyco/opencode")
        self.x_title = x_title or os.getenv("OPENROUTER_X_TITLE", "OpenCode")
        self.request_timeout_seconds = request_timeout_seconds

    def build_headers(self) -> Dict[str, str]:
        """Erzeugt die HTTP-Header für OpenRouter API-Aufrufe."""
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": self.referer,
            "X-Title": self.x_title,
        }

    def generate(
        self,
        prompt: str,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        timeout: Optional[float] = None,
    ) -> str:
        """
        Führt einen OpenRouter API-Aufruf durch und gibt die Antwort zurück.

        Args:
            prompt: Eingabe-Prompt für das Model.
            temperature: Sampling-Temperatur.
            max_tokens: Maximale Token-Anzahl für die Antwort.
            timeout: Optionales Request-Timeout in Sekunden (überschreibt
                den Worker-Default self.request_timeout_seconds).

        Returns:
            Generierte Antwort als String.

        Raises:
            ValueError: Bei API-Fehlern oder ungültigen Antworten.
            requests.Timeout: Wenn der Request das Timeout überschreitet.
            requests.RequestException: Bei anderen HTTP-Fehlern.
        """
        headers = self.build_headers()
        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        effective_timeout = timeout if timeout is not None else self.request_timeout_seconds

        response = requests.post(
            f"{self.base_url}/chat/completions",
            headers=headers,
            json=payload,
            timeout=effective_timeout,
        )
        response.raise_for_status()

        result = response.json()
        if "choices" not in result or not result["choices"]:
            raise ValueError("Ungültige Antwort von OpenRouter API.")

        return result["choices"][0]["message"]["content"]

    def generate_with_usage(
        self,
        prompt: str,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        timeout: Optional[float] = None,
    ) -> tuple[str, OpenRouterUsage]:
        """
        Wie generate(), gibt aber zusätzlich die extrahierten Usage-Metriken zurück.

        Usage-Daten werden aus dem OpenRouter-Response-Block gelesen:
            - response.usage.{prompt_tokens, completion_tokens, total_tokens}
            - response.usage.cost (von OpenRouter berichtet, falls verfügbar)
            - response.model (das tatsächlich genutzte Modell)

        Args:
            prompt: Eingabe-Prompt für das Modell.
            temperature: Sampling-Temperatur.
            max_tokens: Maximale Token-Anzahl für die Antwort.
            timeout: Optionales Request-Timeout in Sekunden.

        Returns:
            Tupel (content, usage). usage enthält alle verfügbaren Felder
            und timed_out=True wenn der Request per Timeout beendet wurde.

        Raises:
            ValueError: Bei API-Fehlern oder ungültigen Antworten.
            requests.Timeout: Wenn der Request das Timeout überschreitet.
            requests.RequestException: Bei anderen HTTP-Fehlern.
        """
        import time

        headers = self.build_headers()
        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        effective_timeout = timeout if timeout is not None else self.request_timeout_seconds

        usage = OpenRouterUsage()
        start = time.monotonic()
        try:
            response = requests.post(
                f"{self.base_url}/chat/completions",
                headers=headers,
                json=payload,
                timeout=effective_timeout,
            )
        except requests.Timeout:
            usage.timed_out = True
            usage.request_seconds = round(time.monotonic() - start, 3)
            raise
        usage.request_seconds = round(time.monotonic() - start, 3)

        response.raise_for_status()
        result = response.json()

        self._populate_usage_from_response(result, usage)

        if "choices" not in result or not result["choices"]:
            raise ValueError("Ungültige Antwort von OpenRouter API.")

        content = result["choices"][0]["message"]["content"]
        return content, usage

    @staticmethod
    def _populate_usage_from_response(result: Dict[str, Any], usage: OpenRouterUsage) -> None:
        """Überträgt usage-bezogene Felder aus dem OpenRouter-JSON in das Usage-Dataclass."""
        if not isinstance(result, dict):
            return
        if "model" in result and isinstance(result["model"], str):
            usage.model = result["model"]
        usage_block = result.get("usage") or {}
        if isinstance(usage_block, dict):
            prompt_tokens = usage_block.get("prompt_tokens")
            completion_tokens = usage_block.get("completion_tokens")
            total_tokens = usage_block.get("total_tokens")
            if isinstance(prompt_tokens, (int, float)):
                usage.prompt_tokens = int(prompt_tokens)
            if isinstance(completion_tokens, (int, float)):
                usage.completion_tokens = int(completion_tokens)
            if isinstance(total_tokens, (int, float)):
                usage.total_tokens = int(total_tokens)
            else:
                # Falls total_tokens fehlt, aus prompt+completion berechnen
                if usage.prompt_tokens is not None and usage.completion_tokens is not None:
                    usage.total_tokens = usage.prompt_tokens + usage.completion_tokens
            cost = usage_block.get("cost")
            if isinstance(cost, (int, float)):
                usage.cost_usd = float(cost)
        # Manche Provider liefern cost_top_level statt in usage
        if usage.cost_usd is None:
            top_cost = result.get("cost")
            if isinstance(top_cost, (int, float)):
                usage.cost_usd = float(top_cost)

    def build_patch_prompt(self, prompt: str) -> str:
        """
        Wrap the Solver prompt so OpenRouter Direct returns machine-applicable patches.

        The direct worker cannot interpret prose. It extracts unified diffs and applies
        them with git/patch tooling, so the model must return a raw diff rather than a
        plan, summary, or Markdown explanation.
        """
        return (
            "You are running in a non-interactive patch application pipeline.\n"
            "Return ONLY one or more unified diff patches that can be applied with "
            "`patch -p1` from the repository root.\n\n"
            "Hard requirements:\n"
            "- Start each file patch with `--- a/<repo-relative-path>` and "
            "`+++ b/<repo-relative-path>`.\n"
            "- Include valid `@@` hunks with enough context to apply cleanly.\n"
            "- Do not wrap the diff in Markdown fences.\n"
            "- Do not include explanations, summaries, plans, headings, or prose.\n"
            "- If no change is needed, return an empty response.\n\n"
            "Original Solver prompt follows:\n\n"
            f"{prompt}"
        )

    def build_file_context(
        self,
        repo_dir: str,
        file_targets: List[str] | None,
        max_chars: int = 24000,
    ) -> str:
        """Build bounded repo-file context for direct patch generation."""
        if not file_targets:
            return ""

        repo_root = Path(repo_dir).resolve()
        parts: List[str] = []
        used_chars = 0

        for target_text in file_targets:
            target_path = (repo_root / target_text).resolve()
            try:
                target_path.relative_to(repo_root)
            except ValueError:
                continue

            if not target_path.is_file():
                continue

            try:
                content = target_path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue

            header = f"\n--- FILE: {target_text} ---\n"
            footer = f"\n--- END FILE: {target_text} ---\n"
            remaining = max_chars - used_chars - len(header) - len(footer)
            if remaining <= 0:
                break

            if len(content) > remaining:
                content = content[:remaining] + "\n[TRUNCATED]\n"

            block = header + content + footer
            parts.append(block)
            used_chars += len(block)

        if not parts:
            return ""

        return (
            "\n\nRelevant repository file context follows. Use this exact current "
            "content when creating hunks:\n"
            + "".join(parts)
        )

    def extract_patches(self, text: str) -> List[str]:
        """
        Extrahiert Unified-Diff-Patches aus dem Modell-Output.

        Sucht zunächst nach Markdown-Code-Fences (```diff ... ``` oder ``` ... ```),
        danach nach nackten Unified-Diff-Blöcken.

        Args:
            text: Roher Modell-Output.

        Returns:
            Liste von Patch-Strings (jeder enthält mindestens --- / +++ / @@ Header).
        """
        patches: List[str] = []

        # 1. Markdown-Code-Fences mit diff-Inhalt suchen
        for match in _DIFF_FENCE_RE.finditer(text):
            patch_body = match.group(1)
            # Nur aufnehmen wenn ein gültiger Unified-Diff-Header vorhanden ist
            if re.search(r"^---\s+\S", patch_body, re.MULTILINE) and \
               re.search(r"^\+\+\+\s+\S", patch_body, re.MULTILINE):
                patches.append(patch_body)

        # 2. Falls keine Fences gefunden: nackte Diffs suchen
        if not patches:
            for match in _DIFF_BARE_RE.finditer(text):
                patches.append(match.group(1))

        return patches

    def apply_patches(
        self,
        patches: List[str],
        repo_dir: str,
    ) -> List[PatchResult]:
        """
        Wendet eine Liste von Unified-Diff-Patches auf das Repository-Verzeichnis an.

        Jeder Patch wird in eine temporäre Datei geschrieben und zuerst via
        `git apply --recount` angewendet. Dadurch können leicht falsche Hunk-Zähler
        aus LLM-generierten Diffs repariert werden. Falls das fehlschlägt, folgt
        ein Fallback auf `patch -p1`. Fehlgeschlagene Patches werden protokolliert,
        brechen aber die verbleibenden Patches nicht ab.

        Args:
            patches: Liste von Patch-Strings (Unified-Diff-Format).
            repo_dir: Absoluter Pfad zum Ziel-Repository-Verzeichnis.

        Returns:
            Liste von PatchResult-Instanzen mit Erfolgs- oder Fehlerstatus.
        """
        results: List[PatchResult] = []

        for index, patch_text in enumerate(patches, start=1):
            # Zieldatei aus dem +++ Header extrahieren (für Protokollierung)
            applied_file: Optional[str] = None
            plus_match = re.search(r"^\+\+\+\s+(\S+)", patch_text, re.MULTILINE)
            if plus_match:
                # b/pfad/zur/datei → pfad/zur/datei (strip leading b/ prefix)
                raw_path = plus_match.group(1)
                applied_file = re.sub(r"^[ab]/", "", raw_path)

            # Patch in temporäre Datei schreiben
            with tempfile.NamedTemporaryFile(
                mode="w",
                suffix=".patch",
                delete=False,
                encoding="utf-8",
            ) as tmp:
                tmp.write(patch_text)
                tmp_path = tmp.name

            try:
                # git apply --recount tolerates wrong hunk line counts, a common
                # LLM diff defect observed in OpenRouter Direct measurements.
                proc = subprocess.run(
                    ["git", "apply", "--recount", "--whitespace=nowarn", tmp_path],
                    cwd=repo_dir,
                    capture_output=True,
                    text=True,
                )
                if proc.returncode != 0:
                    fallback = subprocess.run(
                        ["patch", "-p1", "--forward", "--batch", "-i", tmp_path],
                        cwd=repo_dir,
                        capture_output=True,
                        text=True,
                    )
                    if fallback.returncode == 0:
                        proc = fallback
                    else:
                        proc.stderr = (
                            (proc.stderr or proc.stdout or "").strip()
                            + "\n"
                            + (fallback.stderr or fallback.stdout or "").strip()
                        ).strip()
                if proc.returncode == 0:
                    results.append(PatchResult(
                        patch_index=index,
                        success=True,
                        applied_file=applied_file,
                    ))
                else:
                    # Patch fehlgeschlagen — Fehler aus stderr/stdout extrahieren
                    error_detail = (proc.stderr or proc.stdout or "").strip()
                    results.append(PatchResult(
                        patch_index=index,
                        success=False,
                        applied_file=applied_file,
                        error=error_detail or f"patch exited with code {proc.returncode}",
                    ))
            except FileNotFoundError:
                # `git`/`patch`-Kommando nicht im PATH verfügbar
                results.append(PatchResult(
                    patch_index=index,
                    success=False,
                    applied_file=applied_file,
                    error="`git` oder `patch` binary nicht im PATH gefunden.",
                ))
            finally:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass

        return results

    def run_direct(
        self,
        prompt: str,
        repo_dir: str,
        file_targets: List[str] | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        request_timeout: Optional[float] = None,
    ) -> DirectRunResult:
        """
        Führt einen vollständigen Durchlauf aus: API-Aufruf → Patch-Extraktion → Anwendung.

        1. Ruft das Modell mit dem gegebenen Prompt auf.
        2. Extrahiert Unified-Diff-Patches aus der Antwort.
        3. Wendet alle Patches im Ziel-Repository an.
        4. Gibt ein DirectRunResult mit Returncode, Log, Einzel-Ergebnissen und
           Usage-Metriken zurück.

        Returncode-Semantik:
            0  — Mindestens ein Patch erfolgreich angewendet.
            1  — Patches gefunden, aber alle fehlgeschlagen (oder kein Patch erkannt)
                 oder API-Fehler.
            2  — Modell hat Prosa ohne auswertbare Diffs zurückgegeben.
            3  — Request-Timeout überschritten.

        Args:
            prompt: Eingabe-Prompt für das Modell.
            repo_dir: Absoluter Pfad zum Ziel-Repository-Verzeichnis.
            file_targets: Optionale repo-relative Dateien, deren aktueller Inhalt
                als Kontext in den Prompt aufgenommen wird.
            temperature: Sampling-Temperatur.
            max_tokens: Maximale Token-Anzahl für die Antwort.
            request_timeout: Optionales Override für den Request-Timeout.

        Returns:
            DirectRunResult mit Ergebnis-Details und Usage-Metriken.
        """
        import time

        log_lines: List[str] = []
        usage: Optional[OpenRouterUsage] = None
        request_seconds: Optional[float] = None

        # --- Schritt 1: API-Aufruf (mit Usage-Erfassung) ---
        try:
            context = self.build_file_context(repo_dir, file_targets)
            effective_timeout = (
                request_timeout if request_timeout is not None else self.request_timeout_seconds
            )
            start = time.monotonic()
            try:
                raw_response, usage = self.generate_with_usage(
                    self.build_patch_prompt(prompt + context),
                    temperature=temperature,
                    max_tokens=max_tokens,
                    timeout=effective_timeout,
                )
            except requests.Timeout as timeout_exc:
                request_seconds = round(time.monotonic() - start, 3)
                error_msg = (
                    f"[openrouter_direct] API-Timeout nach {request_seconds:.1f}s "
                    f"(Limit {effective_timeout:.1f}s): {timeout_exc}"
                )
                log_lines.append(error_msg)
                return DirectRunResult(
                    returncode=3,
                    output="\n".join(log_lines),
                    raw_response="",
                    usage=OpenRouterUsage(
                        timed_out=True,
                        request_seconds=request_seconds,
                    ),
                )
            request_seconds = round(time.monotonic() - start, 3)
        except Exception as exc:
            error_msg = f"[openrouter_direct] API-Fehler: {exc}"
            log_lines.append(error_msg)
            return DirectRunResult(
                returncode=1,
                output="\n".join(log_lines),
                raw_response="",
                usage=usage,
            )

        if usage is None:
            usage = OpenRouterUsage()
        if usage.request_seconds is None:
            usage.request_seconds = request_seconds

        log_lines.append(f"[openrouter_direct] Modell: {self.model}")
        log_lines.append(f"[openrouter_direct] Antwort erhalten ({len(raw_response)} Zeichen)")

        # --- Schritt 2: Patches extrahieren ---
        patches = self.extract_patches(raw_response)

        if not patches:
            log_lines.append(
                "[openrouter_direct] WARNUNG: Modell hat keine Unified-Diff-Patches zurückgegeben. "
                "Nur Prosa ohne auswertbare Edits gefunden."
            )
            return DirectRunResult(
                returncode=2,
                output="\n".join(log_lines) + "\n\n--- Modell-Antwort ---\n" + raw_response,
                raw_response=raw_response,
                usage=usage,
            )

        log_lines.append(f"[openrouter_direct] {len(patches)} Patch(es) gefunden")

        # --- Schritt 3: Patches anwenden ---
        patch_results = self.apply_patches(patches, repo_dir)

        successful = [r for r in patch_results if r.success]
        failed = [r for r in patch_results if not r.success]

        for pr in patch_results:
            if pr.success:
                log_lines.append(
                    f"[openrouter_direct] Patch {pr.patch_index} erfolgreich angewendet"
                    + (f": {pr.applied_file}" if pr.applied_file else "")
                )
            else:
                log_lines.append(
                    f"[openrouter_direct] Patch {pr.patch_index} FEHLGESCHLAGEN"
                    + (f" ({pr.applied_file})" if pr.applied_file else "")
                    + (f": {pr.error}" if pr.error else "")
                )

        if successful:
            returncode = 0
            log_lines.append(
                f"[openrouter_direct] {len(successful)}/{len(patch_results)} Patch(es) angewendet."
            )
        else:
            returncode = 1
            log_lines.append(
                f"[openrouter_direct] FEHLER: Alle {len(failed)} Patch(es) fehlgeschlagen."
            )

        return DirectRunResult(
            returncode=returncode,
            output="\n".join(log_lines),
            patch_results=patch_results,
            raw_response=raw_response,
            usage=usage,
        )


# ─────────────────────────────────────────────────────────────
# Budget-Enforcement (Post-Response)
# ─────────────────────────────────────────────────────────────

@dataclass
class OpenRouterBudgetLimits:
    """Per-Run Budget-Limits für OpenRouter Direct.

    Felder mit None werden nicht geprüft. cache_read_tokens_limit ist
    für OpenRouter Direct typischerweise unsupported (None).
    """
    max_cost_usd: Optional[float] = None
    max_input_tokens: Optional[int] = None
    max_output_tokens: Optional[int] = None
    max_cache_read_tokens: Optional[int] = None
    exceeded_reason: Optional[str] = None


def check_openrouter_budget_limits(
    usage: Optional[OpenRouterUsage],
    limits: OpenRouterBudgetLimits,
) -> OpenRouterBudgetLimits:
    """Prüft, ob die Usage einer OpenRouter-Antwort die Limits überschreitet.

    Args:
        usage: Aus der API-Antwort extrahierte Usage-Daten (None wenn keine Antwort kam).
        limits: Konfigurierte Budget-Limits.

    Returns:
        OpenRouterBudgetLimits mit gesetztem exceeded_reason bei Überschreitung.
    """
    exceeded: List[str] = []
    effective = usage or OpenRouterUsage()

    if limits.max_cost_usd is not None and effective.cost_usd is not None:
        if effective.cost_usd > limits.max_cost_usd:
            exceeded.append(
                f"cost ${effective.cost_usd:.4f} exceeds ${limits.max_cost_usd:.4f}"
            )
    if limits.max_input_tokens is not None and effective.prompt_tokens is not None:
        if effective.prompt_tokens > limits.max_input_tokens:
            exceeded.append(
                f"input_tokens {effective.prompt_tokens} exceeds {limits.max_input_tokens}"
            )
    if limits.max_output_tokens is not None and effective.completion_tokens is not None:
        if effective.completion_tokens > limits.max_output_tokens:
            exceeded.append(
                f"output_tokens {effective.completion_tokens} exceeds {limits.max_output_tokens}"
            )
    if limits.max_cache_read_tokens is not None:
        # OpenRouter Direct liefert keine Cache-Read-Tokens im Standard-usage-Block.
        # Wir markieren das Limit explizit als nicht durchsetzbar.
        exceeded.append(
            f"cache_read_tokens unsupported by OpenRouter Direct "
            f"(configured limit {limits.max_cache_read_tokens})"
        )

    return OpenRouterBudgetLimits(
        max_cost_usd=limits.max_cost_usd,
        max_input_tokens=limits.max_input_tokens,
        max_output_tokens=limits.max_output_tokens,
        max_cache_read_tokens=limits.max_cache_read_tokens,
        exceeded_reason="; ".join(exceeded) if exceeded else None,
    )


def has_openrouter_any_limit(limits: OpenRouterBudgetLimits) -> bool:
    """Prüft ob mindestens eine Budgetgrenze konfiguriert ist."""
    return any((
        limits.max_cost_usd is not None,
        limits.max_input_tokens is not None,
        limits.max_output_tokens is not None,
        limits.max_cache_read_tokens is not None,
    ))


def openrouter_unsupported_pre_call_fields() -> tuple[str, ...]:
    """Liefert die Namen der Felder, die OpenRouter Direct nicht hard pre-call durchsetzen kann.

    Token-Limits sind im synchronen Single-Call-Modus erst nach der Antwort
    prüfbar; cache_read_tokens wird strukturell nicht unterstützt; cost ist
    erst nach der API-Antwort verfügbar.
    """
    return (
        "max_cost_usd",
        "max_input_tokens",
        "max_cache_read_tokens",
    )
