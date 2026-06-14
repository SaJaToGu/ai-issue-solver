#!/usr/bin/env bash
# Hilfs-Script: dünner Wrapper um die Heuristik in
# `scripts/model_selection.py`. Validiert die Argumente, lädt optional
# eine `run_history` aus `reports/runs/.../metadata.json` und gibt das
# Ergebnis als JSON (Default) oder als kompakten Textblock aus.
#
# Verwendung:
#   bash helpers/recommend_model.sh --repo-type python --issue-text "Refactor tests"
#   bash helpers/recommend_model.sh --issue 42 --repo-type python --format text
#   bash helpers/recommend_model.sh --issue 42 --manual-model claude-sonnet-4
#
# Exit-Codes:
#   0 = Empfehlung erfolgreich
#   1 = unerwarteter Fehler (z. B. fehlende Heuristik-Datei)
#   2 = ungültige Argumente (parse_args.py hat bereits geprüft)

set -euo pipefail

# Python 3 bevorzugen, damit moderne Type-Hints und pathlib-Features
# funktionieren. Fallback auf `python` für ältere Setups.
PYTHON_BIN="${PYTHON:-python3}"
if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  PYTHON_BIN="python"
fi

ROOT_DIR="$(cd "$(dirname "$0")/../../../.." && pwd)"
SCRIPTS_DIR="$ROOT_DIR/scripts"

if [ ! -f "$SCRIPTS_DIR/model_selection.py" ]; then
  echo "✗ scripts/model_selection.py nicht gefunden unter $SCRIPTS_DIR" >&2
  exit 1
fi

# 1. Argumente parsen (KEY=VALUE). Wenn parse_args.sh fehlschlägt, brechen
# wir mit dessen Exit-Code ab und lassen die Variablen uninitialisiert.
PARSE_OUTPUT="$(bash "$ROOT_DIR/.agents/skills/model-selection/helpers/parse_args.sh" "$@")"
PARSE_RC=$?
if [ $PARSE_RC -ne 0 ]; then
  echo "$PARSE_OUTPUT" >&2
  exit $PARSE_RC
fi
eval "$PARSE_OUTPUT"

# 2. Run-Historie laden, falls --issue oder --history angegeben ist
RUN_HISTORY_JSON="[]"
RUN_ID=""
HISTORY_PATH=""

if [ -n "$HISTORY" ]; then
  HISTORY_PATH="$HISTORY"
elif [ -n "$ISSUE" ]; then
  # Suche den jüngsten metadata.json unter reports/runs/*/*/metadata.json
  if [ -d "$ROOT_DIR/reports/runs" ]; then
    LATEST=$(ls -1t "$ROOT_DIR/reports/runs" 2>/dev/null | head -n 1 || true)
    if [ -n "$LATEST" ]; then
      for meta in "$ROOT_DIR/reports/runs/$LATEST"/*/metadata.json; do
        if [ -f "$meta" ]; then
          # Nur Runs übernehmen, die zur Issue-Nummer passen (falls dokumentiert)
          HISTORY_PATH="$meta"
          RUN_ID=$(basename "$(dirname "$meta")")
          break
        fi
      done
    fi
  fi
fi

if [ -n "$HISTORY_PATH" ] && [ -f "$HISTORY_PATH" ]; then
  # Lese Status und Modell aus metadata.json und forme ein run_history-Dict
  if command -v "$PYTHON_BIN" >/dev/null 2>&1; then
    RUN_HISTORY_JSON=$("$PYTHON_BIN" - "$HISTORY_PATH" <<'PY'
import json
import sys

from pathlib import Path

path = Path(sys.argv[1])
try:
    data = json.loads(path.read_text(encoding="utf-8"))
except (OSError, json.JSONDecodeError) as exc:
    print(f"⚠ metadata.json nicht lesbar: {exc}", file=sys.stderr)
    print("[]")
    sys.exit(0)

status = data.get("status") or data.get("outcome") or data.get("result", {}).get("status")
model = data.get("model") or data.get("model_name") or data.get("result", {}).get("model")
issue = data.get("issue") or data.get("issue_number")
run_id = path.parent.name

if not status or not model:
    print("[]")
else:
    print(json.dumps([
        {
            "model": model,
            "status": status,
            "issue": issue,
            "run_id": run_id,
        }
    ], ensure_ascii=False))
PY
    )
  fi
fi

# 3. Empfehlung über Python-Helfer aufrufen
RESULT=$("$PYTHON_BIN" - "$SCRIPTS_DIR" "$REPO_TYPE" "$LANGUAGE" "$TASK_TYPE" "$ISSUE" \
              "$ISSUE_TEXT" "$LABELS" "$TOUCHED_FILES" "$MAX_COST_TIER" \
              "$MANUAL_MODEL" "$RUN_HISTORY_JSON" "$FORMAT" "$RUN_ID" <<'PY'
from __future__ import annotations
import json
import sys
from pathlib import Path

(
    scripts_dir,
    repo_type,
    language,
    task_type,
    issue,
    issue_text,
    labels_csv,
    touched_csv,
    max_cost_tier,
    manual_model,
    run_history_json,
    fmt,
    run_id,
) = sys.argv[1:]

# scripts/model_selection.py wird über den scripts_dir aus dem Aufrufer
# importiert. Dadurch funktioniert der Aufruf auch über `python - <<EOF`,
# bei dem `__file__` nicht gesetzt ist.
sys.path.insert(0, scripts_dir)

try:
    from model_selection import select_model_for_issue  # type: ignore
except Exception as exc:  # pragma: no cover - defensive
    print(json.dumps({
        "ok": False,
        "errors": [f"model_selection.py konnte nicht importiert werden: {exc}"],
    }, ensure_ascii=False))
    sys.exit(1)

issue_number = int(issue) if issue else 0
labels = [item.strip() for item in labels_csv.split(",") if item.strip()]
touched_files = [item.strip() for item in touched_csv.split(",") if item.strip()]

run_history = []
if run_history_json:
    try:
        run_history = json.loads(run_history_json)
    except json.JSONDecodeError:
        run_history = []

manual_overrides = {}
if manual_model:
    manual_overrides["model"] = manual_model

try:
    selection = select_model_for_issue(
        issue={
            "body": issue_text or "",
            "labels": labels,
        },
        repo_type=repo_type or "general",
        max_cost_tier=max_cost_tier,
        manual_overrides=manual_overrides or None,
        run_history=run_history or None,
    )
except Exception as exc:  # pragma: no cover - defensive
    print(json.dumps({
        "ok": False,
        "errors": [f"select_model_for_issue fehlgeschlagen: {exc}"],
    }, ensure_ascii=False))
    sys.exit(1)

manual_override = bool(manual_model)
escalated = any(
    (entry.get("status") in {"failed", "no-change", "nonzero_with_changes"})
    for entry in run_history
)

payload = {
    "ok": True,
    "model": selection.get("model", ""),
    "reason": selection.get("reason", ""),
    "category": selection.get("category", "general"),
    "risk": selection.get("risk", "medium"),
    "cost_tier": selection.get("cost_tier", "medium"),
    "fallback_plan": selection.get("fallback_plan", []),
    "inputs": {
        "repo_type": repo_type,
        "language": language,
        "task_type": task_type,
        "issue": issue_number,
        "max_cost_tier": max_cost_tier,
    },
    "routing": {
        "manual_override": manual_override,
        "escalated": escalated,
        "history_run_id": run_id or None,
    },
}

if fmt == "text":
    fallback = ", ".join(payload["fallback_plan"]) or "-"
    print("=== model-selection ===")
    print(f"Model:        {payload['model']}")
    print(f"Reason:       {payload['reason']}")
    print(f"Category:     {payload['category']}")
    print(f"Risk:         {payload['risk']}")
    print(f"Cost tier:    {payload['cost_tier']}")
    print(f"Fallback:     {fallback}")
    print(
        "Inputs:       "
        f"repo_type={payload['inputs']['repo_type'] or '-'}, "
        f"language={payload['inputs']['language'] or '-'}, "
        f"task_type={payload['inputs']['task_type'] or '-'}, "
        f"issue={payload['inputs']['issue'] or '-'}"
    )
    print(
        "Routing:      "
        f"manual_override={payload['routing']['manual_override']}, "
        f"escalated={payload['routing']['escalated']}, "
        f"history_run_id={payload['routing']['history_run_id'] or '-'}"
    )
else:
    print(json.dumps(payload, indent=2, ensure_ascii=False))
PY
)

echo "$RESULT"
