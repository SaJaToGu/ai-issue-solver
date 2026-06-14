#!/usr/bin/env bash
# Hilfs-Script: liest die finale Summary einer Overnight-Session und
# meldet Erfolg, Fehlschlag oder Hinweise.
#
# Verwendung:
#   bash helpers/summary_check.sh reports/overnight/20260614-020000
#   bash helpers/summary_check.sh --latest
#   bash helpers/summary_check.sh --latest --issues-only
#
# Exit-Codes:
#   0  Session erfolgreich (status: successful)
#   1  Session fehlgeschlagen (status: failed)
#   2  Aufruf-Fehler (Pfad fehlt, keine Session gefunden, …)
#   3  Session nicht abgeschlossen (kein summary.txt vorhanden)

set -euo pipefail

LOG_ROOT_DEFAULT="reports/overnight"
SHOW_ISSUES_ONLY="false"
LATEST="false"
SESSION_DIR=""

usage() {
  cat <<USAGE
Verwendung: summary_check.sh [--latest] [--issues-only] [SESSION_DIR]

Optionen:
  --latest         neueste Session unter ${LOG_ROOT_DEFAULT}/ verwenden
  --issues-only    nur Issue-Outcomes ausgeben
  SESSION_DIR      Pfad zu einer konkreten Session (z. B. reports/overnight/20260614-020000)
USAGE
}

while [ $# -gt 0 ]; do
  case "$1" in
    --latest)
      LATEST="true"
      shift
      ;;
    --issues-only)
      SHOW_ISSUES_ONLY="true"
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    --*)
      echo "Unbekannte Option: $1" >&2
      usage
      exit 2
      ;;
    *)
      SESSION_DIR="$1"
      shift
      ;;
  esac
done

if [ "$LATEST" = "true" ]; then
  if [ ! -d "$LOG_ROOT_DEFAULT" ]; then
    echo "✗ Log-Root fehlt: $LOG_ROOT_DEFAULT" >&2
    exit 2
  fi
  SESSION_DIR="$(ls -1t "$LOG_ROOT_DEFAULT" 2>/dev/null | head -n 1 || true)"
  if [ -z "$SESSION_DIR" ]; then
    echo "✗ Keine Session unter $LOG_ROOT_DEFAULT gefunden" >&2
    exit 2
  fi
  SESSION_DIR="${LOG_ROOT_DEFAULT}/${SESSION_DIR}"
fi

if [ -z "$SESSION_DIR" ]; then
  usage >&2
  exit 2
fi

SUMMARY="${SESSION_DIR}/summary.txt"
if [ ! -f "$SUMMARY" ]; then
  echo "✗ summary.txt fehlt in: $SESSION_DIR" >&2
  echo "  → Session ist möglicherweise nicht abgeschlossen" >&2
  exit 3
fi

if [ "$SHOW_ISSUES_ONLY" = "true" ]; then
  # Nur die Issue-Outcomes ausgeben.
  awk '
    /^issue_outcomes:/ { in_block = 1; print; next }
    in_block && /^[a-z_]+:/ { in_block = 0 }
    in_block { print }
  ' "$SUMMARY"
  exit 0
fi

echo "=== Overnight-Session: $SESSION_DIR ==="

# Status in der ersten Zeile lesen. Wir verwenden sub() statt -F': *',
# weil Zeitstempel wie "2026-06-14T02:00:00" selbst Doppelpunkte enthalten.
STATUS="$(awk '/^status: /{sub(/^status: */, ""); print; exit}' "$SUMMARY" || echo unknown)"
STARTED="$(awk '/^started_at: /{sub(/^started_at: */, ""); print; exit}' "$SUMMARY" || true)"
FINISHED="$(awk '/^finished_at: /{sub(/^finished_at: */, ""); print; exit}' "$SUMMARY" || true)"
DURATION="$(awk '/^duration: /{sub(/^duration: */, ""); print; exit}' "$SUMMARY" || true)"

echo "Status:    $STATUS"
echo "Started:   $STARTED"
echo "Finished:  $FINISHED"
echo "Duration:  $DURATION"
echo

# Schritte kompakt auflisten
echo "--- Schritte ---"
awk '
  /^steps:/ { in_steps = 1; next }
  in_steps && /^- name: / { print; next }
  in_steps && /^  status: / { print; next }
  in_steps && /^  duration: / { print; next }
  in_steps && /^[a-z_]+:/ { in_steps = 0 }
' "$SUMMARY"

# Fehlgeschlagene Schritte hervorheben
FAILED="$(awk '/^failed_steps:/{flag=1; next} flag && /^- /{sub(/^- */, ""); print}' "$SUMMARY" || true)"
if [ -n "$FAILED" ]; then
  echo
  echo "--- Fehlgeschlagene Schritte ---"
  echo "$FAILED" | sed 's/^/  • /'
fi

# Issue-Outcomes
ISSUE_COUNT="$(awk '/^issue_outcomes:/{flag=1; count=0; next} flag && /^- issue: /{count++} END{print count+0}' "$SUMMARY")"
if [ "${ISSUE_COUNT:-0}" -gt 0 ]; then
  echo
  echo "--- Issue-Outcomes ($ISSUE_COUNT) ---"
  awk '
    /^issue_outcomes:/ { in_block = 1; next }
    in_block && /^[a-z_]+:/ { in_block = 0 }
    in_block { print }
  ' "$SUMMARY"
fi

# Exit-Code ableiten
case "$STATUS" in
  successful) exit 0 ;;
  failed) exit 1 ;;
  *) exit 1 ;;
esac
