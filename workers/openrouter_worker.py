"""
Direkter OpenRouter Worker für OpenAI-kompatible API-Aufrufe.

Verwendet die OpenRouter API (https://openrouter.ai) ohne Aider-Abhängigkeit.
Unterstützt Model-Overrides wie `mistralai/mistral-large`.

Der Worker kann:
- Direkten API-Text generieren (generate)
- Unified-Diff-Patches aus der Modellantwort extrahieren (extract_patches)
- Patches sicher im Zielverzeichnis anwenden (apply_patches)
- Einen kompletten Durchlauf mit Datei-Editierung ausführen (run_direct)
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


@dataclass
class PatchResult:
    """Ergebnis der Patch-Anwendung für eine einzelne Diff-Datei."""
    patch_index: int
    success: bool
    applied_file: Optional[str] = None
    error: Optional[str] = None


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
    """
    returncode: int
    output: str
    patch_results: List[PatchResult] = field(default_factory=list)
    raw_response: str = ""


class OpenRouterWorker:
    """Direkter OpenRouter Worker für OpenAI-kompatible API-Aufrufe."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "mistralai/mistral-large",
        base_url: str = "https://openrouter.ai/api/v1",
        referer: Optional[str] = None,
        x_title: Optional[str] = None,
    ):
        """
        Args:
            api_key: OpenRouter API Key. Wird standardmäßig aus `OPENROUTER_API_KEY` gelesen.
            model: OpenRouter Model-String (z. B. `mistralai/mistral-large`).
            base_url: OpenRouter API Base URL.
            referer: HTTP-Referer für OpenRouter.
            x_title: X-Title für OpenRouter.
        """
        self.api_key = api_key or os.getenv("OPENROUTER_API_KEY")
        if not self.api_key:
            raise ValueError("OPENROUTER_API_KEY ist nicht gesetzt.")

        self.model = model
        self.base_url = base_url
        self.referer = referer or os.getenv("OPENROUTER_REFERER", "https://github.com/anomalyco/opencode")
        self.x_title = x_title or os.getenv("OPENROUTER_X_TITLE", "OpenCode")

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
    ) -> str:
        """
        Führt einen OpenRouter API-Aufruf durch und gibt die Antwort zurück.

        Args:
            prompt: Eingabe-Prompt für das Model.
            temperature: Sampling-Temperatur.
            max_tokens: Maximale Token-Anzahl für die Antwort.

        Returns:
            Generierte Antwort als String.

        Raises:
            ValueError: Bei API-Fehlern oder ungültigen Antworten.
        """
        headers = self.build_headers()
        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        response = requests.post(
            f"{self.base_url}/chat/completions",
            headers=headers,
            json=payload,
        )
        response.raise_for_status()

        result = response.json()
        if "choices" not in result or not result["choices"]:
            raise ValueError("Ungültige Antwort von OpenRouter API.")

        return result["choices"][0]["message"]["content"]

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
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> DirectRunResult:
        """
        Führt einen vollständigen Durchlauf aus: API-Aufruf → Patch-Extraktion → Anwendung.

        1. Ruft das Modell mit dem gegebenen Prompt auf.
        2. Extrahiert Unified-Diff-Patches aus der Antwort.
        3. Wendet alle Patches im Ziel-Repository an.
        4. Gibt ein DirectRunResult mit Returncode, Log und Einzel-Ergebnissen zurück.

        Returncode-Semantik:
            0  — Mindestens ein Patch erfolgreich angewendet.
            1  — Patches gefunden, aber alle fehlgeschlagen (oder kein Patch erkannt).
            2  — Modell hat Prosa ohne auswertbare Diffs zurückgegeben.

        Args:
            prompt: Eingabe-Prompt für das Modell.
            repo_dir: Absoluter Pfad zum Ziel-Repository-Verzeichnis.
            temperature: Sampling-Temperatur.
            max_tokens: Maximale Token-Anzahl für die Antwort.

        Returns:
            DirectRunResult mit Ergebnis-Details.
        """
        log_lines: List[str] = []

        # --- Schritt 1: API-Aufruf ---
        try:
            raw_response = self.generate(
                self.build_patch_prompt(prompt),
                temperature=temperature,
                max_tokens=max_tokens,
            )
        except Exception as exc:
            error_msg = f"[openrouter_direct] API-Fehler: {exc}"
            log_lines.append(error_msg)
            return DirectRunResult(
                returncode=1,
                output="\n".join(log_lines),
                raw_response="",
            )

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
        )
