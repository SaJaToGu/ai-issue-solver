#!/usr/bin/env bash
# Hilfs-Script: dünner Wrapper um `python scripts/run_overnight.py`, der die
# wichtigsten Argumente normalisiert und den Python-Aufruf protokolliert.
#
# Verwendung:
#   bash helpers/run_overnight.sh --model opencode --workers 2 --caffeinate
#   bash helpers/run_overnight.sh --model codex --repo myrepo --issue 42 --skip-tests
#
# Das Script leitet alle Argumente an das Runner-Script weiter. Es führt
# vorab den Argument-Parser aus, um offensichtliche Fehler abzufangen,
# bevor der Runner gestartet wird.

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/../../.." && pwd)"

if [ "$#" -eq 0 ]; then
  echo "Verwendung: run_overnight.sh --model <name> [--workers N] [--repo R] [--issue N] [--caffeinate] [-- ...]" >&2
  exit 2
fi

# 1. Argumente parsen — bricht bei ungültigen Kombinationen mit Exit 2 ab.
eval "$(bash "$ROOT_DIR/.agents/skills/run-overnight/helpers/parse_args.sh" "$@")"

# 2. Optional: Hinweise je nach Plattform
case "$(uname -s 2>/dev/null || echo unknown)" in
  Darwin)
    if [ "$CAFFEINATE" = "true" ] && ! command -v caffeinate >/dev/null 2>&1; then
      echo "⚠ --caffeinate gesetzt, aber caffeinate-Binary fehlt; macOS wach halten ist deaktiviert" >&2
    fi
    ;;
  Linux|*)
    if [ "$CAFFEINATE" = "true" ]; then
      echo "ℹ --caffeinate ist nur auf macOS wirksam; wird ignoriert" >&2
    fi
    ;;
esac

# 3. Runner starten
RUN_CMD=("python" "$ROOT_DIR/scripts/run_overnight.py" "--model" "$MODEL")
if [ -n "$MODEL_NAME" ]; then
  RUN_CMD+=("--model-name" "$MODEL_NAME")
fi
if [ -n "$FALLBACK_MODEL" ]; then
  RUN_CMD+=("--fallback-model" "$FALLBACK_MODEL")
fi
if [ -n "$FALLBACK_MODEL_NAME" ]; then
  RUN_CMD+=("--fallback-model-name" "$FALLBACK_MODEL_NAME")
fi
if [ -n "$REPO" ]; then
  RUN_CMD+=("--repo" "$REPO")
fi
if [ -n "$ISSUE" ]; then
  RUN_CMD+=("--issue" "$ISSUE")
fi
RUN_CMD+=("--label" "$LABEL")
RUN_CMD+=("--base-branch" "$BASE_BRANCH")
RUN_CMD+=("--workers" "$WORKERS")
RUN_CMD+=("--verbosity" "$VERBOSITY")
if [ "$CAFFEINATE" = "true" ]; then
  RUN_CMD+=("--caffeinate")
fi
if [ "$SKIP_PULL" = "true" ]; then
  RUN_CMD+=("--skip-pull")
fi
if [ "$SKIP_TESTS" = "true" ]; then
  RUN_CMD+=("--skip-tests")
fi
if [ "$SKIP_CONGESTION_CHECK" = "true" ]; then
  RUN_CMD+=("--skip-congestion-check")
fi
if [ "$DRY_RUN" = "true" ]; then
  RUN_CMD+=("--dry-run")
fi
if [ "$CLOSE_ISSUES" = "true" ]; then
  RUN_CMD+=("--close-issues")
fi
if [ -n "$WORKER_HEALTH_TIMEOUT_MINUTES" ]; then
  RUN_CMD+=("--worker-health-timeout-minutes" "$WORKER_HEALTH_TIMEOUT_MINUTES")
fi
if [ -n "$UNHEALTHY_ACTION" ]; then
  RUN_CMD+=("--unhealthy-action" "$UNHEALTHY_ACTION")
fi
if [ -n "$UNHEALTHY_RETRIES" ]; then
  RUN_CMD+=("--unhealthy-retries" "$UNHEALTHY_RETRIES")
fi

echo "→ Overnight-Runner-Aufruf: ${RUN_CMD[*]}"
exec "${RUN_CMD[@]}"
