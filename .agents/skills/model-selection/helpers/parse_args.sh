#!/usr/bin/env bash
# Hilfs-Script: parsed die wichtigsten Argumente für den model-selection-Skill.
#
# Verwendung:
#   bash helpers/parse_args.sh --repo-type python --issue-text "Refactor tests"
#   bash helpers/parse_args.sh --issue 42 --max-cost-tier medium
#
# Das Script gibt die normalisierten Argumente zeilenweise aus
# (KEY=VALUE) und bricht bei offensichtlich ungültigen Kombinationen ab.

set -euo pipefail

REPO_TYPE=""
LANGUAGE=""
TASK_TYPE=""
ISSUE=""
ISSUE_TEXT=""
LABELS=""
TOUCHED_FILES=""
MAX_COST_TIER="expensive"
HISTORY=""
MANUAL_MODEL=""
FORMAT="json"

usage() {
  cat <<USAGE
Verwendung: parse_args.sh [--repo-type T] [--language L] [--task-type T] \\
                          [--issue N] [--issue-text TEXT] [--labels A,B] \\
                          [--touched-files A,B] [--max-cost-tier cheap|medium|expensive] \\
                          [--max-cost cheap|medium|expensive] \\
                          [--history PATH] [--manual-model NAME] \\
                          [--format json|text]

Mindestens eine Quelle muss gesetzt sein:
  --repo-type, --language, --task-type, --issue, --issue-text,
  --labels, --touched-files, --history oder --manual-model
USAGE
}

while [ $# -gt 0 ]; do
  case "$1" in
    --repo-type)
      REPO_TYPE="${2:-}"
      shift 2
      ;;
    --language)
      LANGUAGE="${2:-}"
      shift 2
      ;;
    --task-type)
      TASK_TYPE="${2:-}"
      shift 2
      ;;
    --issue)
      ISSUE="${2:-}"
      shift 2
      ;;
    --issue-text)
      ISSUE_TEXT="${2:-}"
      shift 2
      ;;
    --labels)
      LABELS="${2:-}"
      shift 2
      ;;
    --touched-files)
      TOUCHED_FILES="${2:-}"
      shift 2
      ;;
    --max-cost-tier)
      MAX_COST_TIER="${2:-expensive}"
      shift 2
      ;;
    --max-cost)
      MAX_COST_TIER="${2:-expensive}"
      shift 2
      ;;
    --history)
      HISTORY="${2:-}"
      shift 2
      ;;
    --manual-model)
      MANUAL_MODEL="${2:-}"
      shift 2
      ;;
    --format)
      FORMAT="${2:-json}"
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

if [ -n "$ISSUE" ] && ! echo "$ISSUE" | grep -Eq '^[0-9]+$'; then
  echo "--issue muss eine positive Ganzzahl sein (erhalten: $ISSUE)" >&2
  exit 2
fi

case "$MAX_COST_TIER" in
  cheap|medium|expensive) ;;
  *)
    echo "Ungültiges max-cost-tier: $MAX_COST_TIER (erwartet: cheap|medium|expensive)" >&2
    exit 2
    ;;
esac

case "$FORMAT" in
  json|text) ;;
  *)
    echo "Ungültiges --format: $FORMAT (erwartet: json|text)" >&2
    exit 2
    ;;
esac

case "$TASK_TYPE" in
  ""|bug-fix|refactor|docs|tests|feature|ci|chore) ;;
  *)
    echo "Unbekannter task-type: $TASK_TYPE" >&2
    exit 2
    ;;
esac

if [ -z "$REPO_TYPE$ISSUE$ISSUE_TEXT$LABELS$TOUCHED_FILES$LANGUAGE$TASK_TYPE$MANUAL_MODEL$HISTORY" ]; then
  echo "Mindestens eine Quelle (repo-type, language, task-type, issue, issue-text, labels, touched-files, history, manual-model) ist erforderlich" >&2
  exit 2
fi

printf 'REPO_TYPE=%q\n' "$REPO_TYPE"
printf 'LANGUAGE=%q\n' "$LANGUAGE"
printf 'TASK_TYPE=%q\n' "$TASK_TYPE"
printf 'ISSUE=%q\n' "$ISSUE"
printf 'ISSUE_TEXT=%q\n' "$ISSUE_TEXT"
printf 'LABELS=%q\n' "$LABELS"
printf 'TOUCHED_FILES=%q\n' "$TOUCHED_FILES"
printf 'MAX_COST_TIER=%q\n' "$MAX_COST_TIER"
printf 'HISTORY=%q\n' "$HISTORY"
printf 'MANUAL_MODEL=%q\n' "$MANUAL_MODEL"
printf 'FORMAT=%q\n' "$FORMAT"
