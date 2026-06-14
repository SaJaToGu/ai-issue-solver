#!/usr/bin/env python3
"""
parse_args.py — kompakter Python-Validator für die Skill-Argumente.

Wird vom Test-Skript und vom Bash-Helper verwendet, um sicherzustellen, dass
nur unterstützte Routing-Quellen, gültige Issue-Nummern und bekannte
Kosten-Stufen akzeptiert werden. Schreibt das Ergebnis als JSON auf stdout.

Verwendung:
    python helpers/parse_args.py --repo-type python --issue-text "Refactor tests"
    python helpers/parse_args.py --issue 42 --max-cost-tier medium
    echo "$?"  # 0 = ok, 2 = ungültige Argumente
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import List

SUPPORTED_COST_TIERS = ("cheap", "medium", "expensive")
SUPPORTED_FORMATS = ("json", "text")
SUPPORTED_TASK_TYPES = (
    "bug-fix",
    "refactor",
    "docs",
    "tests",
    "feature",
    "ci",
    "chore",
)
SUPPORTED_LANGUAGES = ("python", "r", "javascript", "typescript", "rust", "go", "ruby")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Normalisiert und validiert die Argumente des model-selection-Skills."
    )
    parser.add_argument("--repo-type", default="", help="Repository-Typ (python, r, docs, …)")
    parser.add_argument("--language", default="", help="Primäre Sprache (Routing-Erweiterung)")
    parser.add_argument("--task-type", default="", help="Aufgabentyp (Routing-Erweiterung)")
    parser.add_argument("--issue", type=int, default=0, help="GitHub-Issue-Nummer")
    parser.add_argument(
        "--issue-text",
        default="",
        help="Issue-Body oder -Titel für die Klassifizierung",
    )
    parser.add_argument(
        "--labels",
        default="",
        help="Komma-getrennte Liste der Labels",
    )
    parser.add_argument(
        "--touched-files",
        default="",
        help="Komma-getrennte Liste der betroffenen Dateien",
    )
    parser.add_argument(
        "--max-cost-tier",
        choices=SUPPORTED_COST_TIERS,
        default="expensive",
        help="Obergrenze für das Kosten-Tier des gewählten Modells",
    )
    parser.add_argument(
        "--max-cost",
        choices=SUPPORTED_COST_TIERS,
        default="",
        help="Alias für --max-cost-tier, behalten für CLI-Kompatibilität",
    )
    parser.add_argument(
        "--history",
        default="",
        help="Pfad auf eine metadata.json mit dem vorherigen Run",
    )
    parser.add_argument(
        "--manual-model",
        default="",
        help="Manuelles Override, gewinnt vor der Heuristik",
    )
    parser.add_argument(
        "--format",
        choices=SUPPORTED_FORMATS,
        default="json",
        help="Ausgabeformat (json oder text)",
    )
    return parser


def _split_csv(value: str) -> List[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    errors: list[str] = []

    if args.issue < 0:
        errors.append("--issue darf nicht negativ sein")

    if args.max_cost and args.max_cost != args.max_cost_tier and args.max_cost_tier == "expensive":
        # still allow the alias to silently win when the explicit tier is default
        args.max_cost_tier = args.max_cost
    elif args.max_cost and args.max_cost != args.max_cost_tier:
        errors.append(
            "--max-cost und --max-cost-tier sind unterschiedlich; bitte nur eines angeben"
        )

    if args.task_type and args.task_type not in SUPPORTED_TASK_TYPES:
        errors.append(
            f"unbekannter --task-type: {args.task_type!r} "
            f"(erwartet eines von {', '.join(SUPPORTED_TASK_TYPES)})"
        )

    if args.language and args.language not in SUPPORTED_LANGUAGES:
        # Unknown languages are warnings, not errors — die Heuristik nutzt
        # die Sprache nur als künftiges Routing-Signal.
        # Wir geben sie trotzdem zurück, aber blockieren den Aufruf nicht.

        pass

    if not any(
        [
            args.issue_text,
            args.labels,
            args.touched_files,
            args.repo_type,
            args.language,
            args.task_type,
            args.manual_model,
            args.issue > 0,
            args.history,
        ]
    ):
        errors.append(
            "Mindestens eine Quelle (issue-text, labels, touched-files, "
            "repo-type, language, task-type, manual-model, issue, history) "
            "ist erforderlich"
        )

    result = {
        "ok": not errors,
        "errors": errors,
        "repo_type": args.repo_type,
        "language": args.language,
        "task_type": args.task_type,
        "issue": args.issue,
        "issue_text": args.issue_text,
        "labels": _split_csv(args.labels),
        "touched_files": _split_csv(args.touched_files),
        "max_cost_tier": args.max_cost_tier,
        "history": args.history,
        "manual_model": args.manual_model,
        "format": args.format,
    }
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if not errors else 2


if __name__ == "__main__":
    sys.exit(main())
