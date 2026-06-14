#!/usr/bin/env bash
# Hilfs-Script: prüft die wichtigsten Voraussetzungen für den
# run-overnight-Skill, ohne den KI-Worker oder den Batch-Solver zu starten.
#
# - Lädt config/.env (wenn vorhanden) und prüft GITHUB_TOKEN / GITHUB_USER
# - Sucht das Worker-Binary im PATH, sofern --model gesetzt ist
# - Prüft, dass reports/overnight/ beschreibbar ist
# - Auf macOS: prüft, dass caffeinate verfügbar ist, falls --caffeinate gesetzt ist
#
# Verwendung:
#   bash helpers/preflight.sh
#   bash helpers/preflight.sh --model opencode
#   bash helpers/preflight.sh --model codex --caffeinate

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/../../.." && pwd)"
cd "$ROOT_DIR"

MODEL=""
CAFFEINATE="false"

while [ $# -gt 0 ]; do
  case "$1" in
    --model)
      MODEL="${2:-}"
      shift 2
      ;;
    --caffeinate)
      CAFFEINATE="true"
      shift
      ;;
    *)
      echo "Unbekanntes Argument: $1" >&2
      exit 2
      ;;
  esac
done

echo "=== run-overnight Preflight ==="
echo "Projekt-Root: $ROOT_DIR"

# 1. Env-Datei prüfen (Secrets werden NICHT angezeigt).
if [ -f "config/.env" ]; then
  echo "✓ config/.env gefunden"
  set -a
  # shellcheck disable=SC1091
  . config/.env
  set +a
else
  echo "✗ config/.env fehlt (Vorlage: config/config.example.env)"
  exit 1
fi

if [ -z "${GITHUB_TOKEN:-}" ]; then
  echo "✗ GITHUB_TOKEN ist nicht gesetzt"
  exit 1
fi
if [ -z "${GITHUB_USER:-}" ]; then
  echo "✗ GITHUB_USER ist nicht gesetzt"
  exit 1
fi
echo "✓ GITHUB_TOKEN und GITHUB_USER gesetzt (Werte werden nicht angezeigt)"

# 2. Python-Abhängigkeiten grob prüfen
if ! python -c "import requests" 2>/dev/null; then
  echo "✗ Python-Modul 'requests' fehlt"
  echo "  → pip install -r requirements.txt"
  exit 1
fi
echo "✓ Python 'requests' verfügbar"

# 3. Worker-Verfügbarkeit (sofern Modell angegeben)
case "$MODEL" in
  codex|"")
    if [ -n "$MODEL" ] && ! command -v codex >/dev/null 2>&1; then
      echo "✗ codex-Binary fehlt im PATH (--model codex verlangt es)"
      exit 1
    fi
    if [ -z "$MODEL" ]; then
      echo "ℹ Kein --model angegeben; worker-spezifischer Check übersprungen"
    else
      echo "✓ codex-Binary im PATH"
    fi
    ;;
  opencode)
    if ! command -v opencode >/dev/null 2>&1; then
      echo "✗ opencode-Binary fehlt im PATH (--model opencode verlangt es)"
      exit 1
    fi
    echo "✓ opencode-Binary im PATH"
    ;;
  mistral-vibe)
    if ! command -v vibe >/dev/null 2>&1; then
      echo "✗ vibe-Binary fehlt im PATH (--model mistral-vibe verlangt es)"
      exit 1
    fi
    echo "✓ vibe-Binary im PATH"
    ;;
  claude|openai|mistral|ollama|openrouter)
    if ! command -v aider >/dev/null 2>&1; then
      echo "✗ aider-Binary fehlt im PATH (--model $MODEL verlangt es)"
      exit 1
    fi
    echo "✓ aider-Binary im PATH"
    ;;
  openrouter_direct)
    if [ -z "${OPENROUTER_API_KEY:-}" ]; then
      echo "✗ OPENROUTER_API_KEY fehlt (--model openrouter_direct verlangt es)"
      exit 1
    fi
    echo "✓ OPENROUTER_API_KEY gesetzt"
    ;;
  *)
    echo "Unbekanntes Modell: $MODEL" >&2
    exit 2
    ;;
esac

# 4. reports/overnight beschreibbar?
LOG_DIR="$ROOT_DIR/reports/overnight"
if [ ! -d "$LOG_DIR" ]; then
  mkdir -p "$LOG_DIR" || {
    echo "✗ Kann $LOG_DIR nicht anlegen"
    exit 1
  }
  echo "✓ $LOG_DIR angelegt"
elif [ ! -w "$LOG_DIR" ]; then
  echo "✗ $LOG_DIR ist nicht beschreibbar"
  exit 1
else
  echo "✓ $LOG_DIR beschreibbar"
fi

# 5. macOS caffeinate prüfen, falls angefordert
if [ "$CAFFEINATE" = "true" ]; then
  case "$(uname -s 2>/dev/null || echo unknown)" in
    Darwin)
      if ! command -v caffeinate >/dev/null 2>&1; then
        echo "✗ --caffeinate gesetzt, aber caffeinate-Binary fehlt"
        exit 1
      fi
      echo "✓ caffeinate verfügbar (macOS)"
      ;;
    *)
      echo "✗ --caffeinate ist nur auf macOS wirksam (aktuell: $(uname -s))"
      exit 1
      ;;
  esac
fi

# 6. GitHub-API erreichbar?
python - "$GITHUB_USER" "$GITHUB_TOKEN" <<'PY'
import sys
import urllib.error
import urllib.request

user, token = sys.argv[1], sys.argv[2]
req = urllib.request.Request(
    f"https://api.github.com/users/{user}/repos?per_page=1&type=owner",
    headers={
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-API-Version": "2022-11-28",
    },
)
try:
    with urllib.request.urlopen(req, timeout=10) as resp:
        if resp.status == 200:
            print(f"✓ GitHub-API erreichbar für {user}")
        else:
            print(f"⚠ GitHub-API unerwarteter Status: {resp.status}")
            sys.exit(1)
except urllib.error.HTTPError as exc:
    if exc.code == 401:
        print("✗ GitHub-API: 401 Unauthorized (Token prüfen)")
        sys.exit(1)
    if exc.code == 403:
        print("✗ GitHub-API: 403 Forbidden (Rate-Limit oder Scope fehlt)")
        sys.exit(1)
    print(f"✗ GitHub-API Fehler: HTTP {exc.code}")
    sys.exit(1)
except urllib.error.URLError as exc:
    print(f"✗ GitHub-API nicht erreichbar: {exc.reason}")
    sys.exit(1)
PY

echo "=== Preflight OK ==="
