#!/usr/bin/env bash
# Hilfs-Script: dünner Wrapper um `python scripts/plan_issue_batches.py`,
# der die wichtigsten Argumente normalisiert und den Python-Aufruf
# protokolliert.
#
# Verwendung:
#   bash helpers/run_plan.sh --repo ai-issue-solver
#   bash helpers/run_plan.sh --repo ai-issue-solver --emit-commands --model opencode
#   bash helpers/run_plan.sh --repo ai-issue-solver --label agent/planner
#
# Das Script leitet alle Argumente an das Planungs-Script weiter. Es führt
# vorab den Argument-Parser aus, um offensichtliche Fehler abzufangen,
# bevor der Planer gestartet wird.

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/../../.." && pwd)"

if [ "$#" -eq 0 ]; then
  echo "Verwendung: run_plan.sh --repo <name> [--emit-commands] [--model <name>] [-- ...]" >&2
  exit 2
fi

# 1. Argumente parsen und validieren
PARSE_OUT="$(python "$ROOT_DIR/.agents/skills/plan-issue-batches/helpers/parse_args.py" "$@")"
PARSE_RC=$?
if [ "$PARSE_RC" -ne 0 ]; then
  echo "$PARSE_OUT" >&2
  exit "$PARSE_RC"
fi

REPO="$(python -c 'import json,sys; print(json.loads(sys.stdin.read())["repo"])' <<<"$PARSE_OUT")"
LABEL="$(python -c 'import json,sys; print(json.loads(sys.stdin.read())["label"])' <<<"$PARSE_OUT")"
MODEL="$(python -c 'import json,sys; print(json.loads(sys.stdin.read())["model"])' <<<"$PARSE_OUT")"
BASE_BRANCH="$(python -c 'import json,sys; print(json.loads(sys.stdin.read())["base_branch"])' <<<"$PARSE_OUT")"
EMIT_COMMANDS="$(python -c 'import json,sys; print(json.loads(sys.stdin.read())["emit_commands"])' <<<"$PARSE_OUT")"

# 2. Planer starten
PLAN_CMD=("python" "$ROOT_DIR/scripts/plan_issue_batches.py" "--repo" "$REPO" "--model" "$MODEL" "--base-branch" "$BASE_BRANCH")
if [ -n "$LABEL" ]; then
  PLAN_CMD+=("--label" "$LABEL")
fi
if [ "$EMIT_COMMANDS" = "True" ]; then
  PLAN_CMD+=("--emit-commands")
fi

echo "→ Planer-Aufruf: ${PLAN_CMD[*]}"
exec "${PLAN_CMD[@]}"
