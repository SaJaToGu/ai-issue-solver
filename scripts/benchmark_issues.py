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
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from model_catalog import OPENCODE_FREE_MODELS
from solver_commands import build_single_solver_command
from solver_reporting import load_run_outcome
from workers.opencode_diagnostics import run_opencode_preflight_guard
from utils import (
    load_env,
    print_banner,
    print_err,
    print_step,
    print_warn,
    require_config_value,
)


FREE_OPENCODE_MODELS = list(OPENCODE_FREE_MODELS)
FREE_OPencode_MODELS = FREE_OPENCODE_MODELS

RUN_REPORT_RE = re.compile(r"Run-Report:\s*(\S+)")


def benchmark_solver_args(dry_run: bool) -> argparse.Namespace:
    return argparse.Namespace(
        model="opencode",
        model_name=None,
        label="ai-generated",
        base_branch=None,
        dry_run=False,
        close_issues=False,
        verbosity=None,
        max_run_cost_usd=None,
        max_run_input_tokens=None,
        max_run_output_tokens=None,
    )


def build_benchmark_command(
    issue_number: int,
    *,
    repo: str,
    dry_run: bool = False,
    model_name: str | None = None,
    branch_suffix: str | None = None,
    ensemble: int | None = None,
    allow_opencode_state_conflict: bool = False,
    solve_script: Path = Path("scripts/solve_issues.py"),
) -> list[str]:
    args = benchmark_solver_args(dry_run)
    command = build_single_solver_command(
        args,
        solve_script,
        repo=repo,
        issue_number=issue_number,
        model="opencode",
        model_name=model_name,
        dry_run=dry_run,
        include_label=False,
        skip_pr=True,
        branch_suffix=branch_suffix,
        ensemble=ensemble,
    )
    if allow_opencode_state_conflict:
        command.append("--allow-opencode-state-conflict")
    return command


def extract_run_report_path(output: str) -> Path | None:
    match = RUN_REPORT_RE.search(output)
    if not match:
        return None
    return Path(match.group(1))


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
    parser.add_argument(
        "--ensemble",
        type=int,
        default=0,
        help="Führe N Modelle parallel aus und wähle die beste Lösung. Beispiel: --ensemble 3",
    )
    parser.add_argument(
        "--allow-opencode-state-conflict",
        action="store_true",
        help=(
            "OpenCode trotz laufendem Versions-/State-Mix starten und an "
            "Benchmark-Worker weiterreichen. Nur verwenden, wenn der Konflikt "
            "bewusst akzeptiert ist."
        ),
    )
    return parser.parse_args()


def run_benchmark(
    issue_number: int,
    models: list[str],
    dry_run: bool = False,
    ensemble: int = 0,
    allow_opencode_state_conflict: bool = False,
) -> dict:
    """Führt den Benchmark für die angegebenen Modelle aus."""
    # OPENCODE_SERVER_PASSWORD wird von OpenCode Desktop gesetzt und verhindert,
    # dass `opencode run` eine neue Session startet. Vor dem Subprozess entfernen,
    # da solve_issues.py die Umgebung vom Parent erbt.
    os.environ.pop("OPENCODE_SERVER_PASSWORD", None)
    results = {}
    full_repo = os.environ.get("GITHUB_REPOSITORY") or "SaJaToGu/ai-issue-solver"
    repo = full_repo.split("/", 1)[1] if "/" in full_repo else full_repo

    if not dry_run and not run_opencode_preflight_guard(
        allow_conflict=allow_opencode_state_conflict,
    ):
        return {
            "error": "opencode_state_preflight_failed",
        }

    if ensemble > 0:
        print(f"\n--- Benchmark für Ensemble mit {ensemble} Modellen ---")
        
        cmd = build_benchmark_command(
            issue_number,
            repo=repo,
            dry_run=dry_run,
            ensemble=ensemble,
            allow_opencode_state_conflict=allow_opencode_state_conflict,
        )
        
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=False,
            )
            
            # Analysiere die Ausgabe
            output = result.stdout + result.stderr
            run_report = extract_run_report_path(output)
            run_outcome = load_run_outcome(run_report)
            has_changes = bool(run_outcome.get("has_changes")) if run_outcome else "no_changes" not in output.lower()
            has_pr = "PR erstellt" in output
            
            # Führe Tests aus
            test_result = subprocess.run(
                [sys.executable, "-m", "unittest", "discover", "-s", "tests"],
                capture_output=True,
                text=True,
                check=False,
            )
            tests_passed = test_result.returncode == 0
            
            results[f"ensemble-{ensemble}"] = {
                "changes": has_changes,
                "pr": has_pr,
                "tests_passed": tests_passed,
                "returncode": result.returncode,
                "run_report": str(run_report) if run_report else "",
                "run_outcome": run_outcome,
                "output": output,
                "ensemble": True,
                "models": models[:ensemble],
            }
            
        except Exception as e:
            print_err(f"Fehler beim Benchmark für Ensemble: {e}")
            results[f"ensemble-{ensemble}"] = {
                "error": str(e),
                "changes": False,
                "pr": False,
                "tests_passed": False,
                "ensemble": True,
                "models": models[:ensemble],
            }
    
    for model in models:
        print(f"\n--- Benchmark für Modell: {model} ---")
        
        # Jedes Modell bekommt einen eigenen Branch mit Timestamp,
        # damit Ergebnisse nicht kollidieren und alte Branches ignoriert werden
        model_slug = model.replace("/", "-").replace(":", "-")[:48]
        branch_suffix = f"bench/{datetime.now().strftime('%H%M%S')}/{model_slug}"
        
        cmd = build_benchmark_command(
            issue_number,
            repo=repo,
            dry_run=dry_run,
            model_name=model,
            branch_suffix=branch_suffix,
            allow_opencode_state_conflict=allow_opencode_state_conflict,
        )
        
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=False,
            )
            
            # Analysiere die Ausgabe
            output = result.stdout + result.stderr
            run_report = extract_run_report_path(output)
            run_outcome = load_run_outcome(run_report)
            has_changes = bool(run_outcome.get("has_changes")) if run_outcome else "no_changes" not in output.lower()
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
                "run_report": str(run_report) if run_report else "",
                "run_outcome": run_outcome,
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
        print(f"\n{'Ensemble' if result.get('ensemble') else 'Modell'}: {model}")
        if result.get('ensemble'):
            print(f"  - Modelle: {', '.join(result.get('models', []))}")
        print(f"  - Änderungen: {'Ja' if result.get('changes', False) else 'Nein'}")
        print(f"  - PR erstellt: {'Ja' if result.get('pr', False) else 'Nein'}")
        print(f"  - Tests bestanden: {'Ja' if result.get('tests_passed', False) else 'Nein'}")
        if "error" in result:
            print(f"  - Fehler: {result['error']}")


def main() -> int:
    args = parse_args()
    models = args.models.split(",") if args.models else FREE_OPENCODE_MODELS
    
    print_banner("BENCHMARK FÜR NICHT-CODEX-SOLVER")
    print(f"Issue: {args.issue}")
    if args.ensemble > 0:
        print(f"Ensemble: {args.ensemble} Modelle parallel")
        print(f"Modelle: {', '.join(models[:args.ensemble])}")
    else:
        print(f"Modelle: {', '.join(models)}")
    print(f"Dry-Run: {'Ja' if args.dry_run else 'Nein'}")
    
    results = run_benchmark(
        args.issue,
        models,
        args.dry_run,
        args.ensemble,
        allow_opencode_state_conflict=args.allow_opencode_state_conflict,
    )
    print_results(results)
    
    # Speichere Ergebnisse als JSON
    output_dir = Path("benchmarks")
    output_dir.mkdir(parents=True, exist_ok=True)
    output_file = output_dir / f"benchmark_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"\nErgebnisse gespeichert in: {output_file}")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
