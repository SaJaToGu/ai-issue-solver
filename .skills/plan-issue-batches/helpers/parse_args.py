#!/usr/bin/env python3
"""
parse_args.py — kompakter Python-Validator für die Argumente des
`plan-issue-batches`-Skills.

Wird vom Test-Skript und vom Bash-Helper verwendet, um sicherzustellen, dass
nur unterstützte Modelle und bekannte Optionen akzeptiert werden. Schreibt
das Ergebnis als JSON auf stdout.

Verwendung:
    python helpers/parse_args.py --repo ai-issue-solver --emit-commands
    echo "$?"  # 0 = ok, 2 = ungültige Argumente
"""

from __future__ import annotations

import argparse
import json
import sys

SUPPORTED_MODELS = (
    "codex",
    "claude",
    "openai",
    "mistral",
    "ollama",
    "mistral-vibe",
    "opencode",
    "openrouter",
    "openrouter_direct",
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Normalisiert und validiert die Argumente des plan-issue-batches-Skills."
    )
    parser.add_argument(
        "--repo",
        default="ai-issue-solver",
        help="GitHub-Repository ohne Owner",
    )
    parser.add_argument(
        "--label",
        default="",
        help="Optionales Issue-Label als Filter",
    )
    parser.add_argument(
        "--model",
        default="codex",
        choices=SUPPORTED_MODELS,
        help="Modell für ausgegebene Batch-Kommandos",
    )
    parser.add_argument(
        "--base-branch",
        default="develop",
        help="Basisbranch für ausgegebene Batch-Kommandos",
    )
    parser.add_argument(
        "--emit-commands",
        action="store_true",
        help="Batch-Kommandos pro Welle ausgeben",
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
    if not args.repo:
        errors.append("--repo darf nicht leer sein")

    result = {
        "repo": args.repo,
        "label": args.label,
        "model": args.model,
        "base_branch": args.base_branch,
        "emit_commands": args.emit_commands,
        "ok": not errors,
        "errors": errors,
    }
    print(json.dumps(result, indent=2))
    return 0 if not errors else 2


if __name__ == "__main__":
    sys.exit(main())
