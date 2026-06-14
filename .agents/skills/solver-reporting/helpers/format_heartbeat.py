#!/usr/bin/env python3
"""format_heartbeat.py — Heartbeat-Helfer für Solver-Loops.

Verwendet ``format_heartbeat`` und ``format_heartbeat_progress`` aus
``scripts/solver_reporting.py``.

Verwendung:

    python helpers/format_heartbeat.py --issue 223 --elapsed-seconds 1020
    python helpers/format_heartbeat.py --issue 223 --elapsed-seconds 1020 --job-label PR2
    python helpers/format_heartbeat.py --issue 223 --elapsed-seconds 1020 --width 8 --json
"""

from __future__ import annotations

import argparse
import json
import sys
import time
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
    format_heartbeat,
    format_heartbeat_progress,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Heartbeat-Zeile für Solver-Loops formatieren."
    )
    parser.add_argument("--issue", type=int, required=True, help="Issue-Nummer.")
    parser.add_argument(
        "--elapsed-seconds",
        type=float,
        default=None,
        help="Verstrichene Sekunden. Ohne Angabe wird die aktuelle "
             "Laufzeit seit --start verwendet (Default: 0).",
    )
    parser.add_argument(
        "--start",
        type=float,
        default=None,
        help="Start-Zeitpunkt (Unix-Epoch). Überschreibt --elapsed-seconds.",
    )
    parser.add_argument(
        "--job-label",
        default=None,
        help="Optionales Label (z. B. Modellname oder PR-Nummer).",
    )
    parser.add_argument(
        "--width",
        type=int,
        default=None,
        help="Anzahl Progress-Marker (Standard: elapsed_minutes // 2).",
    )
    parser.add_argument(
        "--progress-only",
        action="store_true",
        help="Nur den Progress-String ohne Issue-Präfix ausgeben.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Strukturierte Ausgabe (heartbeat, progress, elapsed_seconds, width).",
    )
    return parser


def resolve_elapsed(args: argparse.Namespace) -> float:
    if args.start is not None:
        return max(0.0, time.time() - float(args.start))
    if args.elapsed_seconds is not None:
        return max(0.0, float(args.elapsed_seconds))
    return 0.0


def main() -> int:
    args = build_parser().parse_args()
    elapsed = resolve_elapsed(args)
    progress = format_heartbeat_progress(elapsed, args.width)
    heartbeat = format_heartbeat(
        issue_number=args.issue,
        elapsed_seconds=elapsed,
        job_label=args.job_label,
        width=args.width,
    )
    if args.progress_only:
        output = progress
    elif args.json:
        payload = {
            "issue": args.issue,
            "elapsed_seconds": elapsed,
            "width": args.width,
            "job_label": args.job_label,
            "progress": progress,
            "heartbeat": heartbeat,
        }
        output = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    else:
        output = heartbeat + "\n"
    sys.stdout.write(output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
