#!/usr/bin/env bash
# Hilfs-Script: parsed die wichtigsten Argumente für den solve-issues-Skill.
#
# Verwendung:
#   bash helpers/parse_args.sh --model opencode --issue 3 --repo myrepo
#
# Das Script gibt die normalisierten Argumente zeilenweise aus
# (KEY=VALUE) und bricht bei offensichtlich ungültigen Kombinationen ab.

set -euo pipefail

MODEL=""
MODEL_NAME=""
REPO=""
ISSUE=""
DRY_RUN="false"
VERBOSITY="normal"

usage() {
  cat <<USAGE
Verwendung: parse_args.sh --model <codex|opencode|claude|openai|mistral|mistral-vibe|ollama|openrouter|openrouter_direct> \\
                        [--model-name NAME] [--repo NAME] [--issue N] \\
                        [--dry-run] [--verbosity quiet|normal|verbose]

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
    --repo)
      REPO="${2:-}"
      shift 2
      ;;
    --issue)
      ISSUE="${2:-}"
      shift 2
      ;;
    --dry-run)
      DRY_RUN="true"
      shift
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

case "$VERBOSITY" in
  quiet|normal|verbose) ;;
  *)
    echo "Ungültige Verbosity: $VERBOSITY (erwartet: quiet|normal|verbose)" >&2
    exit 2
    ;;
esac

if [ -n "$ISSUE" ] && ! echo "$ISSUE" | grep -Eq '^[0-9]+$'; then
  echo "--issue muss eine positive Ganzzahl sein (erhalten: $ISSUE)" >&2
  exit 2
fi

printf 'MODEL=%q\n' "$MODEL"
printf 'MODEL_NAME=%q\n' "$MODEL_NAME"
printf 'REPO=%q\n' "$REPO"
printf 'ISSUE=%q\n' "$ISSUE"
printf 'DRY_RUN=%q\n' "$DRY_RUN"
printf 'VERBOSITY=%q\n' "$VERBOSITY"
