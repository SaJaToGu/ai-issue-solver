#!/usr/bin/env bash
# cleanup_worktrees.sh — löscht abgelaufene Preserved Worktrees.
#
# Liest das Verzeichnis reports/preserved-worktrees/ und entfernt alle
# Unterordner, deren mtime älter als die angegebene Retention ist.
# Standard-Retention ist 14 Tage und entspricht
# PRESERVED_WORKTREE_RETENTION_DAYS aus scripts/solver_reporting.py.
#
# Sicherheit:
#   - Bricht ab, wenn ROOT nicht unter reports/preserved-worktrees liegt.
#   - Standard ist --dry-run; ohne --apply werden keine Daten gelöscht.
#   - Verzeichnisse werden über `python -c "shutil.rmtree(...)"` entfernt.
#
# Verwendung:
#   bash helpers/cleanup_worktrees.sh
#   bash helpers/cleanup_worktrees.sh --retention-days 30
#   bash helpers/cleanup_worktrees.sh --root reports/preserved-worktrees --apply

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../../../.." && pwd)"
DEFAULT_ROOT="$REPO_ROOT/reports/preserved-worktrees"
DEFAULT_RETENTION_DAYS=14
PYTHON="${PYTHON:-python}"

ROOT="$DEFAULT_ROOT"
RETENTION_DAYS="$DEFAULT_RETENTION_DAYS"
APPLY="false"

usage() {
  cat <<USAGE
Verwendung: cleanup_worktrees.sh [--root PFAD] [--retention-days N] [--apply]

  --root            Verzeichnis mit Preserved Worktrees
                    (Standard: $DEFAULT_ROOT)
  --retention-days  Verzeichnisse älter als N Tage werden gelöscht
                    (Standard: $DEFAULT_RETENTION_DAYS)
  --apply           Löscht die Kandidaten tatsächlich (sonst nur Dry-Run).
  -h, --help        Diese Hilfe anzeigen.
USAGE
}

while [ $# -gt 0 ]; do
  case "$1" in
    --root)
      ROOT="${2:-}"
      shift 2
      ;;
    --retention-days)
      RETENTION_DAYS="${2:-}"
      shift 2
      ;;
    --apply)
      APPLY="true"
      shift
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

if ! echo "$RETENTION_DAYS" | grep -Eq '^[0-9]+$'; then
  echo "✗ --retention-days muss eine positive Ganzzahl sein" >&2
  exit 2
fi

# Sicherheits-Check: ROOT muss reports/preserved-worktrees (oder ein
# explizit übergebener Pfad darunter) sein. Für Tests kann der Check
# mit ``SOLVER_REPORTING_ALLOW_UNSAFE_ROOT=1`` deaktiviert werden.
if [ "${SOLVER_REPORTING_ALLOW_UNSAFE_ROOT:-0}" != "1" ]; then
  case "$ROOT" in
    "$DEFAULT_ROOT"|"$DEFAULT_ROOT"/*) ;;
    *)
      echo "✗ Root-Pfad liegt nicht unter reports/preserved-worktrees: $ROOT" >&2
      echo "✗ Aus Sicherheitsgründen verweigert." >&2
      exit 1
      ;;
  esac
fi

if [ ! -d "$ROOT" ]; then
  echo "ℹ Root-Verzeichnis existiert nicht (noch keine Preserved Worktrees): $ROOT"
  exit 0
fi

NOW_EPOCH="$(date +%s)"
CUTOFF_EPOCH=$((NOW_EPOCH - RETENTION_DAYS * 24 * 60 * 60))
CUTOFF_HUMAN="$("$PYTHON" - "$CUTOFF_EPOCH" <<'PY'
import datetime
import sys

print(datetime.datetime.fromtimestamp(int(sys.argv[1])).strftime("%Y-%m-%d %H:%M:%S"))
PY
)"
NOW_HUMAN="$(date '+%Y-%m-%d %H:%M:%S')"

echo "=== solver-reporting: cleanup_worktrees ==="
echo "Root:           $ROOT"
echo "Retention:      $RETENTION_DAYS Tage"
if [ "$APPLY" = "true" ]; then
  echo "Dry-Run:        nein (lösche)"
else
  echo "Dry-Run:        ja"
fi
echo "Aktuelle Zeit:  $NOW_HUMAN"
echo "Cutoff:         $CUTOFF_HUMAN"
echo

# CANDIDATES-Liste kompatibel zu bash 3.2 (macOS) aufbauen — kein mapfile.
CANDIDATES=()
while IFS= read -r line; do
  CANDIDATES+=("$line")
done < <(
  "$PYTHON" - "$ROOT" "$CUTOFF_EPOCH" <<'PY'
import os
import sys

root, cutoff = sys.argv[1], float(sys.argv[2])
if not os.path.isdir(root):
    sys.exit(0)
for entry in sorted(os.listdir(root)):
    full = os.path.join(root, entry)
    if not os.path.isdir(full):
        continue
    try:
        mtime = os.stat(full).st_mtime
    except OSError:
        continue
    if mtime <= cutoff:
        print(full)
PY
)

if [ "${#CANDIDATES[@]}" -eq 0 ]; then
  echo "Keine abgelaufenen Worktrees gefunden."
  exit 0
fi

echo "Kandidaten (älter als $RETENTION_DAYS Tage):"
for path in "${CANDIDATES[@]}"; do
  echo "  $path"
done

if [ "$APPLY" != "true" ]; then
  echo
  echo "→ Dry-Run: keine Aktion. Mit --apply wirklich löschen."
  exit 0
fi

# Tatsächlich löschen — über Python, damit shutil.rmtree genutzt wird.
DELETED=0
FAILED=0
for path in "${CANDIDATES[@]}"; do
  if "$PYTHON" - "$path" <<'PY'
import shutil
import sys

target = sys.argv[1]
shutil.rmtree(target)
PY
  then
    DELETED=$((DELETED + 1))
  else
    FAILED=$((FAILED + 1))
    echo "✗ Konnte $path nicht löschen" >&2
  fi
done

echo
echo "Gelöscht:  $DELETED"
echo "Fehler:    $FAILED"

if [ "$FAILED" -gt 0 ]; then
  exit 1
fi
