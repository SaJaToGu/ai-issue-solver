#!/usr/bin/env bash
# Hilfs-Script: prüft, ob es für eine bestimmte Issue-Nummer bereits
# einen Branch oder PR gibt, ohne den Solver zu starten.
#
# Verwendung:
#   bash helpers/recovery_check.sh <owner> <repo> <issue_number>
#
# Voraussetzungen: GITHUB_TOKEN, GITHUB_USER in config/.env.

set -euo pipefail

if [ "$#" -ne 3 ]; then
  echo "Verwendung: recovery_check.sh <owner> <repo> <issue_number>" >&2
  exit 2
fi

OWNER="$1"
REPO="$2"
ISSUE="$3"
ROOT_DIR="$(cd "$(dirname "$0")/../../.." && pwd)"

# Argument-Validierung zuerst, damit Tests auch ohne env-Datei
# sinnvolle Exit-Codes bekommen.
if ! echo "$ISSUE" | grep -Eq '^[0-9]+$'; then
  echo "✗ issue_number muss eine positive Ganzzahl sein" >&2
  exit 2
fi

cd "$ROOT_DIR"

if [ -f "config/.env" ]; then
  set -a
  # shellcheck disable=SC1091
  . config/.env
  set +a
fi

if [ -z "${GITHUB_TOKEN:-}" ]; then
  echo "✗ GITHUB_TOKEN fehlt" >&2
  exit 1
fi

BRANCH_PREFIX="ai/fix-issue-${ISSUE}"
BRANCH_DEFAULT="${BRANCH_PREFIX}"

python - "$OWNER" "$REPO" "$ISSUE" "$BRANCH_PREFIX" "$BRANCH_DEFAULT" "$GITHUB_TOKEN" <<'PY'
import json
import sys
import urllib.error
import urllib.request
from urllib.parse import quote

owner, repo, issue, branch_prefix, branch_default, token = sys.argv[1:]
session_headers = {
    "Authorization": f"token {token}",
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}


def github_get(path, params=None):
    url = f"https://api.github.com{path}"
    if params:
        from urllib.parse import urlencode
        url = f"{url}?{urlencode(params)}"
    req = urllib.request.Request(url, headers=session_headers)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, []


def get_branches():
    matched = []
    page = 1
    while True:
        status, data = github_get(
            f"/repos/{owner}/{repo}/branches",
            {"per_page": 100, "page": page},
        )
        if status != 200:
            return matched
        for entry in data:
            name = entry.get("name", "")
            if name == branch_prefix or name.startswith(f"{branch_prefix}-"):
                matched.append(name)
        if len(data) < 100:
            return matched
        page += 1


def get_pull_requests(branch, state="all"):
    status, data = github_get(
        f"/repos/{owner}/{repo}/pulls",
        {
            "state": state,
            "head": f"{owner}:{branch}",
            "per_page": 100,
        },
    )
    if status != 200:
        return []
    return [
        {
            "number": pr.get("number"),
            "state": pr.get("state"),
            "merged": bool(pr.get("merged_at")),
            "html_url": pr.get("html_url"),
            "title": pr.get("title"),
        }
        for pr in data
    ]


branches = sorted(set(get_branches()))
status_default, _ = github_get(f"/repos/{owner}/{repo}/branches/{quote(branch_default, safe='')}")
branch_default_exists = status_default == 200

print(f"=== Recovery-Check für {owner}/{repo}#{issue} ===")
print(f"Standard-Branch: {branch_default} ({'vorhanden' if branch_default_exists else 'fehlt'})")

if not branches and not branch_default_exists:
    print("→ Kein vorhandener Branch; frischer Branch wird angelegt.")
    sys.exit(0)

candidates = sorted(set(branches + ([branch_default] if branch_default_exists else [])), reverse=True)
print(f"Gefundene Branches: {', '.join(candidates)}")

for branch in candidates:
    prs = get_pull_requests(branch)
    if not prs:
        print(f"  • {branch}: kein PR (kann wiederverwendet werden)")
        continue
    for pr in prs:
        if pr["state"] == "open":
            print(f"  • {branch}: OFFENER PR #{pr['number']} {pr['html_url']} (überspringen)")
        elif pr["merged"]:
            print(f"  • {branch}: GEMERGTER PR #{pr['number']} {pr['html_url']} (Branch aufräumen)")
        else:
            print(f"  • {branch}: GESCHLOSSENER (unmerged) PR #{pr['number']} {pr['html_url']} (Rework prüfen)")

print("→ Empfehlung: in `.skills/recovery` weiterlesen, dann passende Aktion wählen.")
PY
