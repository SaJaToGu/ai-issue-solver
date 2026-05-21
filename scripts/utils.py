#!/usr/bin/env python3
"""utils.py — Gemeinsame Hilfsfunktionen für AI Issue Solver"""

from __future__ import annotations

import os
from pathlib import Path

PLACEHOLDER_MARKERS = (
    "DEIN",
    "HIER",
    "YOUR",
    "TODO",
    "CHANGEME",
    "PLACEHOLDER",
)

SECRET_KEYS = {
    "GITHUB_TOKEN",
    "ANTHROPIC_API_KEY",
    "MISTRAL_API_KEY",
    "OPENAI_API_KEY",
}


# ─────────────────────────────────────────────────────────────
# .env laden
# ─────────────────────────────────────────────────────────────

def load_env(env_file: str = None) -> dict:
    """Lädt Konfiguration aus config/.env"""
    if env_file is None:
        # Suche .env relativ zum Projektverzeichnis
        script_dir = Path(__file__).parent
        env_file = script_dir.parent / "config" / ".env"

    config = {}
    env_path = Path(env_file)

    if env_path.exists():
        with open(env_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, _, value = line.partition("=")
                    config[key.strip()] = value.strip().strip('"').strip("'")

    # Umgebungsvariablen haben Vorrang
    for key in ["GITHUB_TOKEN", "GITHUB_USER", "ANTHROPIC_API_KEY",
                "MISTRAL_API_KEY", "OPENAI_API_KEY", "OLLAMA_HOST",
                "OLLAMA_MODEL"]:
        if key in os.environ:
            config[key] = os.environ[key]

    return config


# ─────────────────────────────────────────────────────────────
# Config-Validierung
# ─────────────────────────────────────────────────────────────

def project_env_path() -> Path:
    """Gibt den Standardpfad für die lokale .env zurück."""
    return Path(__file__).parent.parent / "config" / ".env"


def is_placeholder_value(value: str | None) -> bool:
    """Erkennt leere Werte und typische Platzhalter aus config.example.env."""
    if value is None:
        return True
    cleaned = value.strip()
    if not cleaned:
        return True
    upper = cleaned.upper()
    return any(marker in upper for marker in PLACEHOLDER_MARKERS)


def config_source_hint(key: str) -> str:
    """Beschreibt, wo ein Config-Wert gesetzt werden kann, ohne Secrets auszugeben."""
    if key in os.environ:
        return "Umgebungsvariable"
    return str(project_env_path())


def require_config_value(config: dict, key: str, description: str | None = None) -> str:
    """Liest einen Pflichtwert und bricht mit hilfreicher Meldung ab, falls er fehlt."""
    value = config.get(key)
    if not is_placeholder_value(value):
        return value

    label = description or key
    print_err(f"{label} fehlt oder ist noch ein Platzhalter")
    print(f"   Erwartet: {key}=<dein Wert>")
    print(f"   Quelle: {config_source_hint(key)}")
    if key in SECRET_KEYS:
        print("   Hinweis: Der Wert wird aus Sicherheitsgründen nicht angezeigt.")
    raise SystemExit(1)


def require_github_config(config: dict, require_user: bool = True) -> tuple[str, str | None]:
    """Validiert GitHub-Zugangsdaten für API-Aufrufe."""
    token = require_config_value(config, "GITHUB_TOKEN", "GitHub Token")
    user = None
    if require_user:
        user = require_config_value(config, "GITHUB_USER", "GitHub User")
    return token, user


def handle_github_request_error(error, action: str = "GitHub API-Aufruf") -> None:
    """Bricht bei Netzwerkfehlern mit verständlicher Meldung ab."""
    print_err(f"{action} konnte GitHub nicht erreichen")
    print("   Prüfe Netzwerkzugriff und versuche es erneut.")
    message = str(error)
    if message:
        print(f"   Technischer Hinweis: {message.splitlines()[0][:200]}")
    raise SystemExit(1)


def raise_for_github_response(resp, action: str = "GitHub API-Aufruf") -> None:
    """Bricht mit einer verständlichen GitHub-Fehlermeldung ab."""
    if resp.status_code < 400:
        return

    message = ""
    try:
        message = resp.json().get("message", "")
    except ValueError:
        message = resp.text[:200]

    if resp.status_code == 401:
        print_err("GitHub Token ist ungültig oder abgelaufen")
        print("   Prüfe GITHUB_TOKEN in config/.env.")
    elif resp.status_code == 403:
        print_err("GitHub Token hat nicht genug Rechte oder das API-Limit ist erreicht")
        print("   Prüfe, ob der Token Zugriff auf das Ziel-Repository und Issues hat.")
    elif resp.status_code == 404:
        print_err("GitHub Ressource nicht gefunden")
        print("   Prüfe GITHUB_USER, Repository-Name und Token-Zugriff.")
    else:
        print_err(f"{action} fehlgeschlagen: HTTP {resp.status_code}")

    if message:
        print(f"   GitHub meldet: {message}")
    raise SystemExit(1)


# ─────────────────────────────────────────────────────────────
# Terminal-Output
# ─────────────────────────────────────────────────────────────

def print_banner(title: str):
    width = 52
    print("\n" + "═" * width)
    print(f"  🤖 {title}")
    print("═" * width + "\n")


def print_step(n: int, text: str):
    print(f"\n[{n}] {text}")


def print_ok(text: str):
    print(f"    ✅ {text}")


def print_warn(text: str):
    print(f"    ⚠️  {text}")


def print_err(text: str):
    print(f"    ❌ {text}")
