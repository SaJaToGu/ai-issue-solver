#!/usr/bin/env python3
"""utils.py — Gemeinsame Hilfsfunktionen für AI Issue Solver"""

import os
from pathlib import Path


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
                "OPENAI_API_KEY", "OLLAMA_HOST", "OLLAMA_MODEL"]:
        if key in os.environ:
            config[key] = os.environ[key]

    return config


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
