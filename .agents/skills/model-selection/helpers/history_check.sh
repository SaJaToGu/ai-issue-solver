#!/usr/bin/env bash
# Hilfs-Script: listet vorhandene Run-Berichte für eine Issue-Nummer auf,
# damit ein Operator die Eskalationsquelle prüfen kann, ohne ein Modell
# zu empfehlen.
#
# Verwendung:
#   bash helpers/history_check.sh <issue_number>
#   bash helpers/history_check.sh 42
#
# Das Script sucht nach metadata.json unter reports/runs/*/*/metadata.json
# und gibt eine kompakte Tabelle mit Modell, Status und Zeitstempel aus.
# Exit-Codes:
#   0 = mindestens ein Eintrag gefunden oder bewusst "kein Eintrag"
#   2 = ungültige Argumente
#   1 = reports/runs fehlt komplett (Verzeichnis existiert nicht)

set -euo pipefail

if [ "$#" -ne 1 ]; then
  echo "Verwendung: history_check.sh <issue_number>" >&2
  exit 2
fi

ISSUE="$1"

if ! echo "$ISSUE" | grep -Eq '^[0-9]+$'; then
  echo "✗ issue_number muss eine positive Ganzzahl sein (erhalten: $ISSUE)" >&2
  exit 2
fi

ROOT_DIR="$(cd "$(dirname "$0")/../../.." && pwd)"
RUNS_DIR="$ROOT_DIR/reports/runs"

echo "=== model-selection history-check für Issue #$ISSUE ==="
echo "Projekt-Root: $ROOT_DIR"
echo "Suchpfad:     $RUNS_DIR/*/*/metadata.json"

if [ ! -d "$RUNS_DIR" ]; then
  echo "⚠ reports/runs existiert nicht — keine Historie verfügbar."
  exit 1
fi

# Finde alle metadata.json und filtere nach issue_number, falls im JSON enthalten.
matches=$(find "$RUNS_DIR" -mindepth 2 -maxdepth 3 -type f -name metadata.json 2>/dev/null | sort -r || true)

if [ -z "$matches" ]; then
  echo "→ Keine metadata.json unter $RUNS_DIR gefunden."
  exit 0
fi

python - "$ISSUE" <<'PY' "$matches"
import json
import sys
from pathlib import Path

issue = sys.argv[1]
paths = [Path(p) for p in sys.argv[2].splitlines() if p.strip()]

rows = []
for path in paths:
    if not path.exists():
        continue
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"⚠ {path}: nicht lesbar ({exc})")
        continue

    issue_number = (
        data.get("issue")
        or data.get("issue_number")
        or (data.get("result") or {}).get("issue_number")
    )
    if str(issue_number) != str(issue):
        continue

    rows.append({
        "run_id": path.parent.name,
        "model": data.get("model") or data.get("model_name") or "-",
        "status": data.get("status") or data.get("outcome") or "-",
        "issue": issue_number,
        "branch": data.get("branch") or data.get("head_branch") or "-",
        "timestamp": data.get("timestamp") or data.get("finished_at") or "-",
    })

if not rows:
    print(f"→ Keine metadata.json für Issue #{issue} gefunden.")
    sys.exit(0)

print(f"{len(rows)} Einträge:")
for row in rows:
    print(
        f"  • {row['run_id']} | {row['timestamp']} | "
        f"model={row['model']} | status={row['status']} | "
        f"branch={row['branch']}"
    )

print("→ Tipp: mit `bash helpers/recommend_model.sh --issue N --repo-type T` "
      "die Heuristik auf Basis dieser Historie ausführen.")
PY
