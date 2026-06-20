#!/usr/bin/env python3
"""
model_selection.py — Automatische Modellauswahl für Issues

Dieses Modul implementiert die Logik zur Auswahl des besten KI-Modells
basierend auf Issue-Typ, Risiko, Kosten und historischen Daten.

Verwendung:
    from model_selection import select_model
    model = select_model(issue_text, labels, touched_files, repo_type)
"""

from __future__ import annotations
import re
from typing import Dict, List, Optional, Tuple

# ────────────────────────────────────────────────────────────────────────────────
# Konfiguration und Konstanten
# ────────────────────────────────────────────────────────────────────────────────

# Issue-Kategorien
ISSUE_CATEGORIES = {
    "docs-only": ["docs", "documentation", "readme", "license", "md", "rst"],
    "tests": ["test", "pytest", "unittest", "spec"],
    "python": ["python", "py", "django", "flask"],
    "r": ["r", "rscript", "tidyverse", "shiny"],
    "dashboard/ui": ["dashboard", "ui", "frontend", "react", "vue"],
    "provider-integration": ["provider", "api", "integration", "codex", "mistral"],
    "refactor": ["refactor", "cleanup", "restructure"],
    "ci-failure": ["ci", "github actions", "travis", "circleci"],
    "low-code-repo": ["low-code", "no-code", "config", "yaml", "json"],
}

# Risiko- und Stärke-Zuordnung
RISK_MAP = {
    "docs-only": "low",
    "tests": "medium",
    "python": "medium",
    "r": "medium",
    "dashboard/ui": "high",
    "provider-integration": "high",
    "refactor": "high",
    "ci-failure": "high",
    "low-code-repo": "low",
}

STRENGTH_MAP = {
    "low": ["mistral-small", "deepseek-coder:6.7b", "qwen-coder",
            "opencode/deepseek-v4-flash-free", "opencode/mimo-v2.5-free", "opencode/minimax-m3-free"],
    "medium": ["mistral-medium", "claude-sonnet-3.5", "gpt-4o-mini",
               "opencode/nemotron-3-ultra-free"],
    "high": ["mistral-large", "claude-sonnet-4", "gpt-4o"],
}

# Modell-Kosten-Tiers (relativ)
COST_TIERS = {
    "mistral-small": "cheap",
    "deepseek-coder:6.7b": "cheap",
    "qwen-coder": "cheap",
    "opencode/deepseek-v4-flash-free": "cheap",
    "opencode/mimo-v2.5-free": "cheap",
    "opencode/minimax-m3-free": "cheap",
    "opencode/nemotron-3-ultra-free": "cheap",
    "mistral-medium": "medium",
    "claude-sonnet-3.5": "medium",
    "gpt-4o-mini": "medium",
    "mistral-large": "expensive",
    "claude-sonnet-4": "expensive",
    "gpt-4o": "expensive",
}

# Standard-Modell-Reihenfolge für Eskalation
MODEL_ESCALATION = [
    "opencode/deepseek-v4-flash-free",
    "opencode/mimo-v2.5-free",
    "opencode/minimax-m3-free",
    "opencode/nemotron-3-ultra-free",
    "mistral-small",
    "mistral-medium",
    "mistral-large",
    "claude-sonnet-3.5",
    "claude-sonnet-4",
    "gpt-4o-mini",
    "gpt-4o",
]

# ────────────────────────────────────────────────────────────────────────────────
# Hilfsfunktionen
# ────────────────────────────────────────────────────────────────────────────────

def normalize_text(text: str) -> str:
    """Normalisiert Text für die Suche (Kleinbuchstaben, ohne Sonderzeichen)."""
    return re.sub(r'[^a-z0-9\s-]', '', text.lower())


def extract_keywords(text: str) -> List[str]:
    """Extrahiert relevante Keywords aus einem Text."""
    normalized = normalize_text(text)
    return re.findall(r'\b\w{3,}\b', normalized)


def match_issue_category(keywords: List[str], labels: List[str], files: List[str]) -> str:
    """Klassifiziert ein Issue basierend auf Keywords, Labels und Dateien."""
    for category, indicators in ISSUE_CATEGORIES.items():
        # Prüfe Labels
        if any(label.lower() in indicators for label in labels):
            return category
        # Prüfe Dateiendungen
        if any(any(f.endswith(f".{ext}") for ext in indicators) for f in files):
            return category
        # Prüfe Keywords
        if any(keyword in indicators for keyword in keywords):
            return category
    return "general"  # Fallback


def get_risk_level(category: str) -> str:
    """Gibt das Risiko-Level für eine Issue-Kategorie zurück."""
    return RISK_MAP.get(category, "medium")  # Fallback: medium


def get_strength_tier(risk: str) -> List[str]:
    """Gibt die Modell-Stärke-Tier für ein Risiko-Level zurück."""
    return STRENGTH_MAP.get(risk, STRENGTH_MAP["medium"])  # Fallback: medium


def get_cost_tier(model: str) -> str:
    """Gibt das Kosten-Tier für ein Modell zurück."""
    return COST_TIERS.get(model, "medium")  # Fallback: medium


def filter_models_by_cost(models: List[str], max_cost: str) -> List[str]:
    """Filtert Modelle nach maximalem Kosten-Tier."""
    cost_order = ["cheap", "medium", "expensive"]
    max_index = cost_order.index(max_cost)
    return [m for m in models if cost_order.index(COST_TIERS.get(m, "medium")) <= max_index]


def _looks_like_repo_path(value: str) -> bool:
    """Return True for conservative repo-relative path candidates."""
    if not value or any(char.isspace() for char in value):
        return False
    if value.startswith(("/", "http://", "https://")):
        return False
    if not re.fullmatch(r"[A-Za-z0-9_./-]+", value):
        return False
    return "/" in value or bool(re.search(r"\.[A-Za-z0-9]+$", value))


def _extract_path_candidates(text: str) -> List[str]:
    paths: List[str] = []
    for raw in re.split(r"[,;\s]+", text):
        candidate = raw.strip().strip("`'\"()[]{}")
        candidate = candidate.removeprefix("-").removeprefix("*").strip()
        if _looks_like_repo_path(candidate) and candidate not in paths:
            paths.append(candidate)
    return paths


def extract_touched_files_from_issue_body(issue_body: str) -> List[str]:
    """Extract clear `Touches:` file hints from an issue body.

    Supported patterns:
    - `Touches: scripts/foo.py, tests/test_foo.py`
    - `Touches:` followed by indented or bulleted path lines.

    The parser is intentionally conservative. If no explicit `Touches:` marker
    is present, or the following text does not look like repo-relative paths, it
    returns an empty list.
    """
    if not issue_body:
        return []

    paths: List[str] = []
    lines = issue_body.splitlines()
    for index, line in enumerate(lines):
        match = re.match(r"^\s*touches\s*:\s*(.*)$", line, re.IGNORECASE)
        if not match:
            continue

        paths.extend(_extract_path_candidates(match.group(1)))
        for continuation in lines[index + 1:]:
            if not continuation.strip():
                break
            if not re.match(r"^\s+(?:[-*]\s*)?|^\s*[-*]\s+", continuation):
                break
            next_paths = _extract_path_candidates(continuation)
            if not next_paths:
                break
            for path in next_paths:
                if path not in paths:
                    paths.append(path)
        break

    return paths

# ────────────────────────────────────────────────────────────────────────────────
# Hauptfunktionen
# ────────────────────────────────────────────────────────────────────────────────

def classify_issue(issue_text: str, labels: List[str], touched_files: List[str], repo_type: str) -> str:
    """
    Klassifiziert ein Issue basierend auf Text, Labels, betroffenen Dateien und Repo-Typ.

    Args:
        issue_text: Der Text des Issues.
        labels: Die Labels des Issues.
        touched_files: Die betroffenen Dateien.
        repo_type: Der Typ des Repositories (z.B. "python", "r", "docs").

    Returns:
        Die Issue-Kategorie (z.B. "docs-only", "tests", "python" etc.).
    """
    keywords = extract_keywords(issue_text)
    category = match_issue_category(keywords, labels, touched_files)
    
    # Repo-Typ als Fallback oder zur Verfeinerung
    if category == "general" and repo_type in ISSUE_CATEGORIES:
        return repo_type
    return category


def estimate_risk_and_strength(issue_category: str) -> Tuple[str, List[str]]:
    """
    Schätzt das Risiko und die benötigte Modell-Stärke für eine Issue-Kategorie.

    Args:
        issue_category: Die Issue-Kategorie.

    Returns:
        Ein Tupel aus (Risiko-Level, Liste der passenden Modelle).
    """
    risk = get_risk_level(issue_category)
    strength_tier = get_strength_tier(risk)
    return risk, strength_tier


def select_model(
    issue_text: str,
    labels: List[str],
    touched_files: List[str],
    repo_type: str,
    max_cost_tier: str = "expensive",
    manual_overrides: Optional[Dict[str, str]] = None,
    run_history: Optional[List[Dict[str, str]]] = None,
) -> Dict[str, str]:
    """
    Wählt das beste Modell für ein Issue basierend auf Kategorie, Risiko, Kosten und Verlauf.

    Args:
        issue_text: Der Text des Issues.
        labels: Die Labels des Issues.
        touched_files: Die betroffenen Dateien.
        repo_type: Der Typ des Repositories.
        max_cost_tier: Das maximale Kosten-Tier ("cheap", "medium", "expensive").
        manual_overrides: Manuelle Übersteuerungen (z.B. {"model": "claude-sonnet-4"}).
        run_history: Verlauf früherer Runs (für Eskalation).

    Returns:
        Ein Dictionary mit:
        - "model": Das ausgewählte Modell.
        - "reason": Der Grund für die Auswahl.
        - "cost_tier": Das Kosten-Tier.
        - "fallback_plan": Mögliche Eskalationsmodelle.
    """
    # 1. Issue klassifizieren
    issue_category = classify_issue(issue_text, labels, touched_files, repo_type)
    
    # 2. Risiko und Stärke schätzen
    risk, strength_tier = estimate_risk_and_strength(issue_category)
    
    # 3. Modelle nach Kosten filtern
    affordable_models = filter_models_by_cost(strength_tier, max_cost_tier)
    
    # 4. Manuelle Übersteuerungen anwenden
    if manual_overrides and "model" in manual_overrides:
        selected_model = manual_overrides["model"]
        reason = f"Manuell übersteuert: {selected_model}"
    else:
        # 5. Eskalation basierend auf Verlauf
        if run_history:
            last_run = run_history[-1]
            if last_run.get("status") in ["no-change", "failed"]:
                # Eskalation: Nächststärkeres Modell wählen
                current_index = MODEL_ESCALATION.index(last_run["model"])
                if current_index + 1 < len(MODEL_ESCALATION):
                    selected_model = MODEL_ESCALATION[current_index + 1]
                    reason = f"Eskalation nach fehlgeschlagenem Run: {selected_model}"
                else:
                    selected_model = affordable_models[0]  # Fallback
                    reason = f"Maximale Eskalation erreicht; nutze {selected_model}"
            else:
                selected_model = affordable_models[0]  # Standard
                reason = f"Erstversuch mit günstigstem passendem Modell: {selected_model}"
        else:
            selected_model = affordable_models[0]  # Standard
            reason = f"Erstversuch mit günstigstem passendem Modell: {selected_model}"
    
    # 6. Metadaten zusammenstellen
    cost_tier = get_cost_tier(selected_model)
    fallback_plan = [m for m in MODEL_ESCALATION if m != selected_model][:2]  # Nächste 2 Modelle
    
    return {
        "model": selected_model,
        "reason": reason,
        "risk": risk,
        "category": issue_category,
        "cost_tier": cost_tier,
        "fallback_plan": fallback_plan,
    }

# ────────────────────────────────────────────────────────────────────────────────
# CLI-Integration (für solve_issues.py)
# ────────────────────────────────────────────────────────────────────────────────

def select_model_for_issue(
    issue: Dict[str, str],
    repo_type: str,
    max_cost_tier: str = "expensive",
    manual_overrides: Optional[Dict[str, str]] = None,
    run_history: Optional[List[Dict[str, str]]] = None,
) -> Dict[str, str]:
    """
    Wählt ein Modell für ein GitHub-Issue aus (CLI-Adapter).

    Args:
        issue: Das GitHub-Issue als Dictionary.
        repo_type: Der Typ des Repositories.
        max_cost_tier: Das maximale Kosten-Tier.
        manual_overrides: Manuelle Übersteuerungen.
        run_history: Verlauf früherer Runs.

    Returns:
        Das Ergebnis der Modellauswahl.
    """
    return select_model(
        issue_text=issue.get("body", ""),
        labels=issue.get("labels", []),
        touched_files=extract_touched_files_from_issue_body(issue.get("body", "")),
        repo_type=repo_type,
        max_cost_tier=max_cost_tier,
        manual_overrides=manual_overrides,
        run_history=run_history,
    )
