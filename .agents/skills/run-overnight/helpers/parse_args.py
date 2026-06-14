#!/usr/bin/env python3
"""
parse_args.py — kompakter Python-Validator für die Skill-Argumente.

Wird vom Test-Skript und vom Bash-Helper verwendet, um sicherzustellen, dass
nur unterstützte Modelle, gültige Worker-Zahlen und bekannte Verbosity-Stufen
akzeptiert werden. Schreibt das Ergebnis als JSON auf stdout.

Verwendung:
    python helpers/parse_args.py --model opencode --workers 2
    echo "$?"  # 0 = ok, 2 = ungültige Argumente
"""

from __future__ import annotations

import argparse
import json
import sys

# Muss mit MODEL_CONFIGS in scripts/solve_issues.py synchron bleiben.
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
DEFAULT_BASE_BRANCH = "main"
DEFAULT_LABEL = "ai-generated"


def positive_int(value: str) -> int:
    """Type-Function für argparse, die positive Ganzzahlen erzwingt."""
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"erwartet positive Ganzzahl, erhalten: {value!r}"
        ) from exc
    if parsed <= 0:
        raise argparse.ArgumentTypeError(
            f"Wert muss > 0 sein, erhalten: {parsed}"
        )
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Normalisiert und validiert die Argumente des run-overnight-Skills."
    )
    parser.add_argument("--model", required=True, help="Provider-Schlüssel")
    parser.add_argument("--model-name", default="", help="Spezifischer Modellname")
    parser.add_argument(
        "--fallback-model",
        default="",
        choices=("", *SUPPORTED_MODELS),
        help="Fallback-Provider für Rate-Limits",
    )
    parser.add_argument("--fallback-model-name", default="", help="Optionaler Modellname für --fallback-model")
    parser.add_argument("--repo", default="", help="Nur dieses Repo bearbeiten")
    parser.add_argument(
        "--issue",
        type=positive_int,
        action="append",
        default=[],
        help="Nur diese Issue-Nummer lösen; kann mehrfach angegeben werden",
    )
    parser.add_argument(
        "--label",
        default=DEFAULT_LABEL,
        help=f"Issue-Label (Standard: {DEFAULT_LABEL})",
    )
    parser.add_argument(
        "--base-branch",
        default=DEFAULT_BASE_BRANCH,
        help=f"Basis-Branch für Pull und Solver (Standard: {DEFAULT_BASE_BRANCH})",
    )
    parser.add_argument(
        "--workers",
        type=positive_int,
        default=2,
        help="Maximale parallele Worker (Standard: 2)",
    )
    parser.add_argument(
        "--caffeinate",
        action="store_true",
        help="macOS wach halten",
    )
    parser.add_argument(
        "--skip-pull",
        action="store_true",
        help="Git-Pull überspringen",
    )
    parser.add_argument(
        "--skip-tests",
        action="store_true",
        help="Tests überspringen",
    )
    parser.add_argument(
        "--skip-congestion-check",
        action="store_true",
        help="Workflow-Congestion-Check überspringen",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="An Batch-Solver weiterreichen: nur Simulation",
    )
    parser.add_argument(
        "--close-issues",
        action="store_true",
        help="An Batch-Solver weiterreichen: Issues nach Merge schließen",
    )
    parser.add_argument(
        "--worker-health-timeout-minutes",
        type=positive_int,
        default=None,
        help="An Batch-Solver weiterreichen: Health-Timeout in Minuten",
    )
    parser.add_argument(
        "--unhealthy-action",
        choices=("", "warn", "stop", "retry"),
        default="",
        help="An Batch-Solver weiterreichen: Aktion bei unhealthy Worker",
    )
    parser.add_argument(
        "--unhealthy-retries",
        type=positive_int,
        default=None,
        help="An Batch-Solver weiterreichen: Retry-Versuche",
    )
    parser.add_argument(
        "--verbosity",
        choices=SUPPORTED_VERBOSITY,
        default="normal",
        help="Worker-Ausgabe-Lautstärke",
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
    if args.workers < 1:
        errors.append("--workers muss >= 1 sein")
    if args.workers > 16:
        errors.append(
            "--workers wirkt ungewollt hoch; bitte <= 16 verwenden "
            "(Rate-Limits, parallele Git-Operationen)"
        )
    if args.dry_run and not args.repo:
        errors.append("--dry-run ist nur zusammen mit --repo sinnvoll")
    if args.unhealthy_action and not args.unhealthy_retries:
        # retries=0 ist erlaubt (keine Retries), aber wir signalisieren die
        # Kopplung an den User, falls er warn/stop gewählt hat.
        if args.unhealthy_action in {"retry"}:
            errors.append("--unhealthy-action=retry verlangt --unhealthy-retries > 0")
    if args.issue and not args.repo:
        # erlaubt, aber wir warnen: --issue ohne --repo läuft über alle Repos.
        pass

    result = {
        "model": args.model,
        "model_name": args.model_name,
        "fallback_model": args.fallback_model,
        "fallback_model_name": args.fallback_model_name,
        "repo": args.repo,
        "issue": args.issue,
        "label": args.label,
        "base_branch": args.base_branch,
        "workers": args.workers,
        "caffeinate": args.caffeinate,
        "skip_pull": args.skip_pull,
        "skip_tests": args.skip_tests,
        "skip_congestion_check": args.skip_congestion_check,
        "dry_run": args.dry_run,
        "close_issues": args.close_issues,
        "worker_health_timeout_minutes": args.worker_health_timeout_minutes,
        "unhealthy_action": args.unhealthy_action,
        "unhealthy_retries": args.unhealthy_retries,
        "verbosity": args.verbosity,
        "ok": not errors,
        "errors": errors,
    }
    print(json.dumps(result, indent=2))
    return 0 if not errors else 2


if __name__ == "__main__":
    sys.exit(main())
