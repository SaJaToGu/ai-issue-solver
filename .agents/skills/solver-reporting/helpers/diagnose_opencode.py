#!/usr/bin/env python3
"""diagnose_opencode.py — filtert OpenCode-Runtime-Befunde aus Worker-Output.

Verwendet ``detect_opencode_runtime_diagnostics`` und
``opencode_runtime_diagnostic_lines`` aus ``scripts/solver_reporting.py``
und gibt die Befunde als Klartext aus. Optional nicht-null Exit-Code
bei Befunden (für CI / Pre-Merge-Checks).

Verwendung:

    python helpers/diagnose_opencode.py \\
        --worker-output reports/runs/<run_id>/worker-output.log
    python helpers/diagnose_opencode.py --stdin < worker-output.log
    python helpers/diagnose_opencode.py --json --strict
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
SCRIPTS_DIR = REPO_ROOT / "scripts"
# ``solver_reporting`` importiert selbst mit ``from scripts.utils import ...``,
# daher muss der Repo-Root (nicht scripts/) im Pfad liegen.
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from scripts.solver_reporting import (  # noqa: E402  (Pfad-Insertion erfolgt oben)
    detect_opencode_runtime_diagnostics,
    opencode_runtime_diagnostic_lines,
)


def read_output(args: argparse.Namespace) -> str:
    if args.worker_output:
        path = Path(args.worker_output)
        if not path.is_absolute():
            path = REPO_ROOT / path
        if not path.is_file():
            print(f"✗ Datei nicht gefunden: {path}", file=sys.stderr)
            sys.exit(2)
        return path.read_text(encoding="utf-8", errors="replace")
    if args.stdin:
        return sys.stdin.read()
    print(
        "✗ Entweder --worker-output oder --stdin angeben",
        file=sys.stderr,
    )
    sys.exit(2)


def render_text(diagnostics, lines: list[str], source: str | None) -> str:
    parts = [
        "=== OpenCode-Runtime-Diagnose ===",
    ]
    if source:
        parts.append(f"Quelle:            {source}")
    parts.extend([
        f"WAL-Fehler:        {'erkannt' if diagnostics.wal_failure else 'keine'}",
        f"Edit-Loop:         {'erkannt' if diagnostics.edit_loop else 'keine'}",
        f"Edit-Failures:     {diagnostics.edit_failure_count}",
        f"Dateien:           {', '.join(diagnostics.edit_failure_files) or '-'}",
    ])
    if lines:
        parts.append("")
        parts.append("Befunde:")
        parts.extend(f"  {line}" for line in lines)
    else:
        parts.append("")
        parts.append("Befunde:           keine")
    parts.append("")
    parts.append("Exit-Code:         0 = keine Befunde, 2 = Befunde vorhanden")
    return "\n".join(parts) + "\n"


def render_json(diagnostics, lines: list[str], source: str | None) -> str:
    payload = {
        "source": source,
        "wal_failure": diagnostics.wal_failure,
        "edit_loop": diagnostics.edit_loop,
        "edit_failure_count": diagnostics.edit_failure_count,
        "edit_failure_files": list(diagnostics.edit_failure_files),
        "diagnostic_lines": lines,
        "has_findings": diagnostics.has_findings,
    }
    return json.dumps(payload, indent=2, ensure_ascii=False) + "\n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="OpenCode-Runtime-Diagnose für einen Worker-Output."
    )
    parser.add_argument(
        "--worker-output",
        default=None,
        help="Pfad zu worker-output.log (relativ zum Repo-Root oder absolut).",
    )
    parser.add_argument(
        "--stdin",
        action="store_true",
        help="Worker-Output von stdin lesen.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Ausgabe als JSON statt Klartext.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit-Code 2, sobald Befunde erkannt wurden.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    output = read_output(args)
    diagnostics = detect_opencode_runtime_diagnostics(output)
    lines = opencode_runtime_diagnostic_lines(diagnostics)
    source = args.worker_output or "<stdin>"
    if args.json:
        sys.stdout.write(render_json(diagnostics, lines, source))
    else:
        sys.stdout.write(render_text(diagnostics, lines, source))
    if args.strict and diagnostics.has_findings:
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
