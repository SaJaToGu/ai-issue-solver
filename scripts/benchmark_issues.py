#!/usr/bin/env python3
"""
benchmark_issues.py — Benchmark für nicht-Codex-Solver-Provider

Führt einen Benchmark für ausgewählte OpenCode-Modelle auf einer kleinen, sicheren Issue durch.
Erfasst, ob Änderungen vorgenommen wurden, ein PR erstellt wurde, und ob Tests bestanden wurden.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from utils import (
    load_env,
    print_banner,
    print_err,
    print_step,
    print_warn,
    require_config_value,
)


FREE_OPencode_MODELS = [
    "opencode/deepseek-v4-flash-free",
    "opencode/mimo-v2.5-free",
    "opencode/minimax-m3-free",
    "opencode/nemotron-3-ultra-free",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Benchmark für nicht-Codex-Solver-Provider auf einer Issue"
    )
    parser.add_argument(
        "--issue",
        type=int,
        required=True,
        help="Issue-Nummer für den Benchmark (z.B. 184)",
    )
    parser.add_argument(
        "--models",
        help="Modelle für den Benchmark (Komma-getrennt, z.B. mistral/mistral-large-latest,claude-sonnet-4-20250514). Ohne --models werden alle freien OpenCode-Modelle verwendet.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Nur anzeigen, nichts ändern",
    )
    return parser.parse_args()


def run_benchmark(issue_number: int, models: list[str], dry_run: bool = False) -> dict:
    """Führt den Benchmark für die angegebenen Modelle aus."""
    # OPENCODE_SERVER_PASSWORD wird von OpenCode Desktop gesetzt und verhindert,
    # dass `opencode run` eine neue Session startet. Vor dem Subprozess entfernen,
    # da solve_issues.py die Umgebung vom Parent erbt.
    os.environ.pop("OPENCODE_SERVER_PASSWORD", None)
    results = {}
    full_repo = os.environ.get("GITHUB_REPOSITORY") or "SaJaToGu/ai-issue-solver"
    repo = full_repo.split("/", 1)[1] if "/" in full_repo else full_repo

    for model in models:
        print(f"\n--- Benchmark für Modell: {model} ---")
        
        # Jedes Modell bekommt einen eigenen Branch mit Timestamp,
        # damit Ergebnisse nicht kollidieren und alte Branches ignoriert werden
        model_slug = model.replace("/", "-").replace(":", "-")[:48]
        branch_suffix = f"bench/{datetime.now().strftime('%H%M%S')}/{model_slug}"
        
        # Führe solve_issues.py mit dem aktuellen Modell aus
        cmd = [
            sys.executable,
            "scripts/solve_issues.py",
            "--model", "opencode",
            "--model-name", model,
            "--repo", repo,
            "--issue", str(issue_number),
            "--skip-pr",
            "--branch-suffix", branch_suffix,
        ]
        if dry_run:
            cmd.append("--dry-run")
        
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=False,
            )
            
            # Analysiere die Ausgabe
            output = result.stdout + result.stderr
            has_changes = "no_changes" not in output.lower()
            has_pr = "PR erstellt" in output
            
            # Führe Tests aus
            test_result = subprocess.run(
                [sys.executable, "-m", "unittest", "discover", "-s", "tests"],
                capture_output=True,
                text=True,
                check=False,
            )
            tests_passed = test_result.returncode == 0
            
            results[model] = {
                "changes": has_changes,
                "pr": has_pr,
                "tests_passed": tests_passed,
                "returncode": result.returncode,
                "output": output,
            }
            
        except Exception as e:
            print_err(f"Fehler beim Benchmark für {model}: {e}")
            results[model] = {
                "error": str(e),
                "changes": False,
                "pr": False,
                "tests_passed": False,
            }

    return results


def print_results(results: dict) -> None:
    """Gibt die Benchmark-Ergebnisse aus."""
    print_banner("BENCHMARK-ERGEBNISSE")
    for model, result in results.items():
        print(f"\nModell: {model}")
        print(f"  - Änderungen: {'Ja' if result.get('changes', False) else 'Nein'}")
        print(f"  - PR erstellt: {'Ja' if result.get('pr', False) else 'Nein'}")
        print(f"  - Tests bestanden: {'Ja' if result.get('tests_passed', False) else 'Nein'}")
        if "error" in result:
            print(f"  - Fehler: {result['error']}")


def main() -> int:
    args = parse_args()
    models = args.models.split(",") if args.models else FREE_OPencode_MODELS
    
    print_banner("BENCHMARK FÜR NICHT-CODEX-SOLVER")
    print(f"Issue: {args.issue}")
    print(f"Modelle: {', '.join(models)}")
    print(f"Dry-Run: {'Ja' if args.dry_run else 'Nein'}")
    
    results = run_benchmark(args.issue, models, args.dry_run)
    print_results(results)
    
    # Speichere Ergebnisse als JSON
    output_file = f"benchmark_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"\nErgebnisse gespeichert in: {output_file}")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())