#!/usr/bin/env python3
"""
parse_args.py — kompakter Python-Validator für die Skill-Argumente.

Wird vom Test-Skript und vom Bash-Helper verwendet, um sicherzustellen, dass
nur unterstützte Modelle, gültige Issue-Nummern und bekannte Verbosity-Stufen
akzeptiert werden. Schreibt das Ergebnis als JSON auf stdout.

Verwendung:
    python helpers/parse_args.py --model opencode --issue 3 --repo myrepo
    echo "$?"  # 0 = ok, 2 = ungültige Argumente
"""

from __future__ import annotations

import argparse
import json
import sys

SUPPORTED_MODELS = (
    "codex",
    "opencode",
    "claude",
    "openai",
    "mistral",
    "mistral-vibe",
    "ollama",
    "openrouter",
    "openrouter_direct",
)
SUPPORTED_VERBOSITY = ("quiet", "normal", "verbose")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Normalisiert und validiert die Argumente des solve-issues-Skills."
    )
    parser.add_argument("--model", required=True, help="Provider-Schlüssel")
    parser.add_argument("--model-name", default="", help="Spezifischer Modellname")
    parser.add_argument("--repo", default="", help="Repository-Name")
    parser.add_argument("--issue", type=int, default=0, help="Issue-Nummer")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Nur Validierung, kein Solver-Aufruf.",
    )
    parser.add_argument(
        "--verbosity",
        choices=SUPPORTED_VERBOSITY,
        default="normal",
        help="Worker-Ausgabe-Lautstärke.",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    errors: list[str] = []
    if args.model not in SUPPORTED_MODELS:
        errors.append(
            f"unbekanntes Modell: {args.model!r} (erwartet eines von "
            f"{', '.join(SUPPORTED_MODELS)})"
        )
    if args.issue < 0:
        errors.append("--issue darf nicht negativ sein")
    if args.dry_run and not args.repo:
        errors.append("--dry-run ist nur zusammen mit --repo sinnvoll")

    result = {
        "model": args.model,
        "model_name": args.model_name,
        "repo": args.repo,
        "issue": args.issue,
        "dry_run": args.dry_run,
        "verbosity": args.verbosity,
        "ok": not errors,
        "errors": errors,
    }
    print(json.dumps(result, indent=2))
    return 0 if not errors else 2


if __name__ == "__main__":
    sys.exit(main())
