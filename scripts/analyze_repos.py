#!/usr/bin/env python3
"""
analyze_repos.py — Schritt 1: GitHub-Repos analysieren
Morpheus-Style AI Issue Solver — github.com/SaJaToGu

Scannt alle Repos eines GitHub-Users und erstellt einen
detaillierten JSON-Report mit Verbesserungsvorschlägen.

Verwendung:
    python scripts/analyze_repos.py --user SaJaToGu
    python scripts/analyze_repos.py --user SaJaToGu --output reports/analysis.json
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    import requests
except ModuleNotFoundError:
    requests = None

# ── Projektverzeichnis ins sys.path ──────────────────────────
sys.path.insert(0, str(Path(__file__).parent))
from utils import (
    load_env,
    print_banner,
    print_err,
    print_ok,
    print_step,
    print_warn,
    raise_for_github_response,
    require_config_value,
)


# ─────────────────────────────────────────────────────────────
# Analyse-Regeln: Was wird geprüft?
# ─────────────────────────────────────────────────────────────

CHECKS = {
    "missing_readme": {
        "title": "Fehlende oder minimale README-Datei",
        "label": "documentation",
        "priority": "high",
        "description": (
            "Dieses Repo hat keine README.md oder sie ist zu kurz (< 200 Zeichen). "
            "Eine gute README erklärt: Was macht das Projekt? Wie installiert man es? "
            "Wie benutzt man es? Gibt es Beispiele?"
        ),
    },
    "missing_license": {
        "title": "Keine Lizenz-Datei vorhanden",
        "label": "legal",
        "priority": "medium",
        "description": (
            "Es fehlt eine LICENSE-Datei. Ohne Lizenz darf niemand den Code "
            "offiziell nutzen oder weiterentwickeln. "
            "Empfehlung für Open Source: MIT oder Apache 2.0."
        ),
    },
    "missing_gitignore": {
        "title": "Keine .gitignore vorhanden",
        "label": "best-practice",
        "priority": "medium",
        "description": (
            "Es fehlt eine .gitignore-Datei. Ohne sie werden build-Artefakte, "
            "IDE-Dateien und ggf. Secrets ins Repo committed. "
            "Empfehlung: gitignore.io für die passende Vorlage nutzen."
        ),
    },
    "missing_ci": {
        "title": "Keine CI/CD-Pipeline (GitHub Actions) vorhanden",
        "label": "ci-cd",
        "priority": "low",
        "description": (
            "Es gibt keine GitHub Actions Workflows (.github/workflows/). "
            "CI/CD hilft, Fehler früh zu erkennen und Deployments zu automatisieren. "
            "Vorschlag: Einfachen Lint/Test-Workflow hinzufügen."
        ),
    },
    "no_description": {
        "title": "Repo hat keine Beschreibung",
        "label": "documentation",
        "priority": "low",
        "description": (
            "Das Repo hat keine kurze Beschreibung (About-Feld). "
            "Eine Beschreibung macht das Repo in der Suche und im Profil viel übersichtlicher."
        ),
    },
    "no_topics": {
        "title": "Keine Topics/Tags gesetzt",
        "label": "discoverability",
        "priority": "low",
        "description": (
            "Es sind keine GitHub Topics gesetzt. Topics helfen anderen, "
            "dein Projekt zu finden (z.B. 'raspberry-pi', '3d-printing', 'openscad')."
        ),
    },
    "stale_repo": {
        "title": "Repo seit über 2 Jahren nicht aktualisiert",
        "label": "maintenance",
        "priority": "low",
        "description": (
            "Dieses Repo wurde seit mehr als 2 Jahren nicht mehr aktualisiert. "
            "Prüfe ob es noch relevant ist und füge ggf. einen Archiv-Hinweis hinzu "
            "oder archiviere das Repo offiziell auf GitHub."
        ),
    },
    "fork_no_customization": {
        "title": "Fork ohne eigene Anpassungen oder Dokumentation",
        "label": "documentation",
        "priority": "low",
        "description": (
            "Dieses Repo ist ein Fork, hat aber keine eigene README oder Beschreibung, "
            "die erklärt was du daran geändert oder warum du es geforkt hast. "
            "Füge einen kurzen Abschnitt 'Meine Änderungen' in der README hinzu."
        ),
    },
}


# ─────────────────────────────────────────────────────────────
# GitHub API Helper
# ─────────────────────────────────────────────────────────────

class GitHubClient:
    BASE = "https://api.github.com"

    def __init__(self, token: str):
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        })

    def get(self, path: str, **params) -> dict | list:
        url = f"{self.BASE}{path}"
        resp = self.session.get(url, params=params)
        if resp.status_code == 404:
            return None
        raise_for_github_response(resp, f"GET {path}")
        return resp.json()

    def get_all_pages(self, path: str, **params) -> list:
        results = []
        params["per_page"] = 100
        page = 1
        while True:
            params["page"] = page
            data = self.get(path, **params)
            if not data:
                break
            results.extend(data)
            if len(data) < 100:
                break
            page += 1
        return results

    def repo_has_file(self, owner: str, repo: str, filepath: str) -> bool:
        result = self.get(f"/repos/{owner}/{repo}/contents/{filepath}")
        return result is not None

    def repo_has_dir(self, owner: str, repo: str, dirpath: str) -> bool:
        result = self.get(f"/repos/{owner}/{repo}/contents/{dirpath}")
        return isinstance(result, list) and len(result) > 0

    def get_readme_length(self, owner: str, repo: str) -> int:
        result = self.get(f"/repos/{owner}/{repo}/readme")
        if result is None:
            return 0
        return result.get("size", 0)


# ─────────────────────────────────────────────────────────────
# Analyse-Logik
# ─────────────────────────────────────────────────────────────

def analyze_repo(client: GitHubClient, owner: str, repo: dict) -> dict:
    """Analysiert ein einzelnes Repo und gibt Findings zurück."""
    name = repo["name"]
    findings = []

    print(f"   Analysiere: {name} ...", end=" ", flush=True)

    # README prüfen
    readme_size = client.get_readme_length(owner, name)
    if readme_size < 200:
        findings.append("missing_readme")

    # LICENSE prüfen
    has_license = repo.get("license") is not None
    if not has_license:
        # Doppelt prüfen über Contents-API
        has_license = client.repo_has_file(owner, name, "LICENSE") or \
                      client.repo_has_file(owner, name, "LICENSE.md") or \
                      client.repo_has_file(owner, name, "LICENSE.txt")
    if not has_license:
        findings.append("missing_license")

    # .gitignore prüfen
    if not client.repo_has_file(owner, name, ".gitignore"):
        findings.append("missing_gitignore")

    # GitHub Actions prüfen
    if not client.repo_has_dir(owner, name, ".github/workflows"):
        findings.append("missing_ci")

    # Beschreibung
    if not repo.get("description"):
        findings.append("no_description")

    # Topics
    if not repo.get("topics"):
        findings.append("no_topics")

    # Stale (>2 Jahre kein Push)
    pushed_at = repo.get("pushed_at")
    if pushed_at:
        pushed = datetime.fromisoformat(pushed_at.replace("Z", "+00:00"))
        age_days = (datetime.now(timezone.utc) - pushed).days
        if age_days > 730:
            findings.append("stale_repo")

    # Fork ohne Eigendoku
    if repo.get("fork") and readme_size < 300:
        findings.append("fork_no_customization")

    print(f"{'✅' if not findings else f'⚠️  {len(findings)} Findings'}")

    return {
        "repo": name,
        "url": repo["html_url"],
        "language": repo.get("language"),
        "is_fork": repo.get("fork", False),
        "stars": repo.get("stargazers_count", 0),
        "last_push": pushed_at,
        "findings": findings,
        "issues_to_create": [
            {
                "check": f,
                **CHECKS[f],
            }
            for f in findings
            if f in CHECKS
        ],
    }


def analyze_all_repos(client: GitHubClient, user: str) -> dict:
    """Analysiert alle Repos eines Users."""
    print_step(1, f"Lade alle Repos von @{user}")
    repos = client.get_all_pages(f"/users/{user}/repos", type="owner")
    print_ok(f"{len(repos)} Repos gefunden")

    print_step(2, "Analysiere jedes Repo")
    results = []
    total_findings = 0

    for repo in repos:
        if repo.get("archived"):
            print(f"   Überspringe: {repo['name']} (archiviert)")
            continue
        result = analyze_repo(client, user, repo)
        results.append(result)
        total_findings += len(result["findings"])

    return {
        "user": user,
        "analyzed_at": datetime.now(timezone.utc).isoformat(),
        "total_repos": len(results),
        "total_findings": total_findings,
        "repos": results,
    }


# ─────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────

def main():
    print_banner("SCHRITT 1: REPOS ANALYSIEREN")

    parser = argparse.ArgumentParser(description="GitHub Repos analysieren")
    parser.add_argument("--user", required=True, help="GitHub Username (z.B. SaJaToGu)")
    parser.add_argument(
        "--output",
        default="reports/analysis.json",
        help="Pfad für den JSON-Report",
    )
    args = parser.parse_args()

    if requests is None:
        print_err("Python-Abhängigkeit fehlt: requests")
        print("   → Installieren mit: pip install -r requirements.txt")
        sys.exit(1)

    # Config laden
    config = load_env()
    token = require_config_value(config, "GITHUB_TOKEN", "GitHub Token")

    # Output-Verzeichnis anlegen
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Analyse
    client = GitHubClient(token)
    report = analyze_all_repos(client, args.user)

    # Report speichern
    print_step(3, f"Report speichern → {args.output}")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    print_ok(f"Report gespeichert: {args.output}")

    # Zusammenfassung
    print("\n" + "─" * 50)
    print(f"  📊 Repos analysiert:  {report['total_repos']}")
    print(f"  🔍 Findings gesamt:   {report['total_findings']}")
    print("\n  Top-Findings:")
    for repo in report["repos"]:
        if repo["findings"]:
            print(f"    • {repo['repo']}: {', '.join(repo['findings'][:3])}")
    print("─" * 50)
    print(f"\n✅ Weiter mit: python scripts/create_issues.py --report {args.output} --dry-run\n")


if __name__ == "__main__":
    main()
