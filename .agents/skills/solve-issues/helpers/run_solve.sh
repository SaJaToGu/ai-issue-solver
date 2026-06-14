#!/usr/bin/env bash
# Hilfs-Script: dünner Wrapper um `python scripts/solve_issues.py`, der die
# wichtigsten Argumente normalisiert und den Python-Aufruf protokolliert.
#
# Verwendung:
#   bash helpers/run_solve.sh --model opencode --issue 3
#   bash helpers/run_solve.sh --model claude --repo myrepo --issue 42 --dry-run
#
# Das Script leitet alle Argumente an das Solver-Script weiter. Es führt
# vorab den Argument-Parser aus, um offensichtliche Fehler abzufangen,
# bevor der Solver gestartet wird.

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/../../.." && pwd)"

if [ "$#" -eq 0 ]; then
  echo "Verwendung: run_solve.sh --model <name> [--repo R] [--issue N] [--dry-run] [-- ...]" >&2
  exit 2
fi

# 1. Argumente parsen
eval "$(bash "$ROOT_DIR/.agents/skills/solve-issues/helpers/parse_args.sh" "$@")"

# 2. Optional: Preflight, falls --model opencode (nur Hinweis)
if [ "$MODEL" = "opencode" ]; then
  echo "ℹ OpenCode-Run: bitte sicherstellen, dass 'opencode' im PATH liegt und authentifiziert ist."
  echo "  Tipp: opencode auth login"
fi

# 3. Solver starten
SOLVE_CMD=("python" "$ROOT_DIR/scripts/solve_issues.py" "--model" "$MODEL")
if [ -n "$MODEL_NAME" ]; then
  SOLVE_CMD+=("--model-name" "$MODEL_NAME")
fi
if [ -n "$REPO" ]; then
  SOLVE_CMD+=("--repo" "$REPO")
fi
if [ -n "$ISSUE" ]; then
  SOLVE_CMD+=("--issue" "$ISSUE")
fi
if [ "$DRY_RUN" = "true" ]; then
  SOLVE_CMD+=("--dry-run")
fi
SOLVE_CMD+=("--verbosity" "$VERBOSITY")

echo "→ Solver-Aufruf: ${SOLVE_CMD[*]}"
exec "${SOLVE_CMD[@]}"
