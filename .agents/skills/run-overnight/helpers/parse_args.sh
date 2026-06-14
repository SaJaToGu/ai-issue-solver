#!/usr/bin/env bash
# Hilfs-Script: parsed die wichtigsten Argumente für den run-overnight-Skill.
#
# Verwendung:
#   bash helpers/parse_args.sh --model opencode --workers 2
#   bash helpers/parse_args.sh --model codex --repo myrepo --issue 42
#
# Das Script gibt die normalisierten Argumente zeilenweise aus
# (KEY=VALUE) und bricht bei offensichtlich ungültigen Kombinationen ab.

set -euo pipefail

MODEL=""
MODEL_NAME=""
FALLBACK_MODEL=""
FALLBACK_MODEL_NAME=""
REPO=""
ISSUE=""
LABEL="ai-generated"
BASE_BRANCH="main"
WORKERS="2"
CAFFEINATE="false"
SKIP_PULL="false"
SKIP_TESTS="false"
SKIP_CONGESTION_CHECK="false"
DRY_RUN="false"
CLOSE_ISSUES="false"
WORKER_HEALTH_TIMEOUT_MINUTES=""
UNHEALTHY_ACTION=""
UNHEALTHY_RETRIES=""
VERBOSITY="normal"

usage() {
  cat <<USAGE
Verwendung: parse_args.sh --model <name> [--workers N] [--repo R] [--issue N] \\
                        [--caffeinate] [--skip-pull] [--skip-tests] \\
                        [--skip-congestion-check] [--dry-run] \\
                        [--base-branch B] [--label L] [--verbosity LEVEL]

Pflichtargument: --model
USAGE
}

while [ $# -gt 0 ]; do
  case "$1" in
    --model)
      MODEL="${2:-}"
      shift 2
      ;;
    --model-name)
      MODEL_NAME="${2:-}"
      shift 2
      ;;
    --fallback-model)
      FALLBACK_MODEL="${2:-}"
      shift 2
      ;;
    --fallback-model-name)
      FALLBACK_MODEL_NAME="${2:-}"
      shift 2
      ;;
    --repo)
      REPO="${2:-}"
      shift 2
      ;;
    --issue)
      ISSUE="${2:-}"
      shift 2
      ;;
    --label)
      LABEL="${2:-ai-generated}"
      shift 2
      ;;
    --base-branch)
      BASE_BRANCH="${2:-main}"
      shift 2
      ;;
    --workers)
      WORKERS="${2:-2}"
      shift 2
      ;;
    --caffeinate)
      CAFFEINATE="true"
      shift
      ;;
    --skip-pull)
      SKIP_PULL="true"
      shift
      ;;
    --skip-tests)
      SKIP_TESTS="true"
      shift
      ;;
    --skip-congestion-check)
      SKIP_CONGESTION_CHECK="true"
      shift
      ;;
    --dry-run)
      DRY_RUN="true"
      shift
      ;;
    --close-issues)
      CLOSE_ISSUES="true"
      shift
      ;;
    --worker-health-timeout-minutes)
      WORKER_HEALTH_TIMEOUT_MINUTES="${2:-}"
      shift 2
      ;;
    --unhealthy-action)
      UNHEALTHY_ACTION="${2:-}"
      shift 2
      ;;
    --unhealthy-retries)
      UNHEALTHY_RETRIES="${2:-}"
      shift 2
      ;;
    --verbosity)
      VERBOSITY="${2:-normal}"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unbekanntes Argument: $1" >&2
      usage
      exit 2
      ;;
  esac
done

if [ -z "$MODEL" ]; then
  echo "--model ist erforderlich" >&2
  usage
  exit 2
fi

case "$MODEL" in
  codex|opencode|claude|openai|mistral|mistral-vibe|ollama|openrouter|openrouter_direct) ;;
  *)
    echo "Unbekanntes Modell: $MODEL" >&2
    exit 2
    ;;
esac

if [ -n "$FALLBACK_MODEL" ]; then
  case "$FALLBACK_MODEL" in
    codex|opencode|claude|openai|mistral|mistral-vibe|ollama|openrouter|openrouter_direct) ;;
    *)
      echo "Unbekannter Fallback-Modell: $FALLBACK_MODEL" >&2
      exit 2
      ;;
  esac
fi

case "$VERBOSITY" in
  quiet|normal|verbose) ;;
  *)
    echo "Ungültige Verbosity: $VERBOSITY (erwartet: quiet|normal|verbose)" >&2
    exit 2
    ;;
esac

if ! echo "$WORKERS" | grep -Eq '^[0-9]+$'; then
  echo "--workers muss eine positive Ganzzahl sein (erhalten: $WORKERS)" >&2
  exit 2
fi
if [ "$WORKERS" -lt 1 ]; then
  echo "--workers muss >= 1 sein" >&2
  exit 2
fi
if [ "$WORKERS" -gt 16 ]; then
  echo "--workers wirkt ungewollt hoch; bitte <= 16 verwenden" >&2
  exit 2
fi

if [ -n "$ISSUE" ] && ! echo "$ISSUE" | grep -Eq '^[0-9]+$'; then
  echo "--issue muss eine positive Ganzzahl sein (erhalten: $ISSUE)" >&2
  exit 2
fi

if [ -n "$WORKER_HEALTH_TIMEOUT_MINUTES" ] && ! echo "$WORKER_HEALTH_TIMEOUT_MINUTES" | grep -Eq '^[0-9]+$'; then
  echo "--worker-health-timeout-minutes muss eine positive Ganzzahl sein" >&2
  exit 2
fi

if [ -n "$UNHEALTHY_RETRIES" ] && ! echo "$UNHEALTHY_RETRIES" | grep -Eq '^[0-9]+$'; then
  echo "--unhealthy-retries muss eine positive Ganzzahl sein" >&2
  exit 2
fi

if [ -n "$UNHEALTHY_ACTION" ]; then
  case "$UNHEALTHY_ACTION" in
    warn|stop|retry) ;;
    *)
      echo "Ungültige --unhealthy-action: $UNHEALTHY_ACTION (erwartet: warn|stop|retry)" >&2
      exit 2
      ;;
  esac
fi

if [ "$UNHEALTHY_ACTION" = "retry" ] && { [ -z "$UNHEALTHY_RETRIES" ] || [ "$UNHEALTHY_RETRIES" = "0" ]; }; then
  echo "--unhealthy-action=retry verlangt --unhealthy-retries > 0" >&2
  exit 2
fi

printf 'MODEL=%q\n' "$MODEL"
printf 'MODEL_NAME=%q\n' "$MODEL_NAME"
printf 'FALLBACK_MODEL=%q\n' "$FALLBACK_MODEL"
printf 'FALLBACK_MODEL_NAME=%q\n' "$FALLBACK_MODEL_NAME"
printf 'REPO=%q\n' "$REPO"
printf 'ISSUE=%q\n' "$ISSUE"
printf 'LABEL=%q\n' "$LABEL"
printf 'BASE_BRANCH=%q\n' "$BASE_BRANCH"
printf 'WORKERS=%q\n' "$WORKERS"
printf 'CAFFEINATE=%q\n' "$CAFFEINATE"
printf 'SKIP_PULL=%q\n' "$SKIP_PULL"
printf 'SKIP_TESTS=%q\n' "$SKIP_TESTS"
printf 'SKIP_CONGESTION_CHECK=%q\n' "$SKIP_CONGESTION_CHECK"
printf 'DRY_RUN=%q\n' "$DRY_RUN"
printf 'CLOSE_ISSUES=%q\n' "$CLOSE_ISSUES"
printf 'WORKER_HEALTH_TIMEOUT_MINUTES=%q\n' "$WORKER_HEALTH_TIMEOUT_MINUTES"
printf 'UNHEALTHY_ACTION=%q\n' "$UNHEALTHY_ACTION"
printf 'UNHEALTHY_RETRIES=%q\n' "$UNHEALTHY_RETRIES"
printf 'VERBOSITY=%q\n' "$VERBOSITY"
