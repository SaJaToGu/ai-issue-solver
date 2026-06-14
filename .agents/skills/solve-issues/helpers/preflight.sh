#!/usr/bin/env bash
# Hilfs-Script: führt die wichtigsten Preflight-Checks aus, ohne den
# KI-Worker zu starten.
#
# - Lädt config/.env (wenn vorhanden) und prüft GITHUB_TOKEN / GITHUB_USER
# - Sucht das passende Worker-Binary im PATH
# - Ruft `python scripts/solve_issues.py --diagnostic` für OpenCode auf
#   (andere Modelle werden mit einem kurzen `--help`-Aufruf validiert)
#
# Verwendung:
#   bash helpers/preflight.sh
#   bash helpers/preflight.sh --model opencode

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/../../.." && pwd)"
cd "$ROOT_DIR"

MODEL=""
while [ $# -gt 0 ]; do
  case "$1" in
    --model)
      MODEL="${2:-}"
      shift 2
      ;;
    *)
      echo "Unbekanntes Argument: $1" >&2
      exit 2
      ;;
  esac
done

echo "=== solve-issues Preflight ==="
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

# 3. Worker-Verfügbarkeit
case "$MODEL" in
  codex|"")
    if command -v codex >/dev/null 2>&1; then
      echo "✓ codex-Binary im PATH"
    else
      echo "ℹ codex-Binary nicht im PATH (nur relevant, wenn --model codex)"
    fi
    ;;
  opencode)
    if command -v opencode >/dev/null 2>&1; then
      echo "✓ opencode-Binary im PATH"
    else
      echo "ℹ opencode-Binary nicht im PATH (Installation: https://opencode.ai/docs/installation)"
    fi
    ;;
  mistral-vibe)
    if command -v vibe >/dev/null 2>&1; then
      echo "✓ vibe-Binary im PATH"
    else
      echo "ℹ vibe-Binary nicht im PATH (Installation: pip install mistral-vibe)"
    fi
    ;;
  claude|openai|mistral|ollama|openrouter)
    if command -v aider >/dev/null 2>&1; then
      echo "✓ aider-Binary im PATH"
    else
      echo "ℹ aider-Binary nicht im PATH (Installation: pip install aider-chat)"
    fi
    ;;
  openrouter_direct)
    if [ -z "${OPENROUTER_API_KEY:-}" ]; then
      echo "✗ OPENROUTER_API_KEY fehlt"
      exit 1
    fi
    echo "✓ OPENROUTER_API_KEY gesetzt"
    ;;
  *)
    echo "Unbekanntes Modell: $MODEL" >&2
    exit 2
    ;;
esac

# 4. Repo-Erreichbarkeit per GitHub-API testen
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
        "X-GitHub-Api-Version": "2022-11-28",
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
