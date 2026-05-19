#!/usr/bin/env python3
"""
create_issues.py — Schritt 2: GitHub Issues erstellen
Morpheus-Style AI Issue Solver — github.com/SaJaToGu

Liest den Analysis-Report und erstellt strukturierte
GitHub Issues für jedes gefundene Problem.

Verwendung:
    python scripts/create_issues.py --report reports/analysis.json --dry-run
    python scripts/create_issues.py --report reports/analysis.json --confirm-create
    python scripts/create_issues.py --report reports/analysis.json --repo BedBoxDrawerRole
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

try:
    import requests
except ModuleNotFoundError:
    requests = None

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
# Issue-Label Farben (werden einmalig im Repo angelegt)
# ─────────────────────────────────────────────────────────────

LABELS = {
    "documentation":   {"color": "0075ca", "description": "Verbesserungen an Dokumentation"},
    "best-practice":   {"color": "e4e669", "description": "Code- und Projekt-Best-Practices"},
    "ci-cd":           {"color": "d93f0b", "description": "CI/CD und Automatisierung"},
    "legal":           {"color": "b60205", "description": "Lizenz und rechtliche Themen"},
    "maintenance":     {"color": "006b75", "description": "Wartung und Pflege"},
    "discoverability": {"color": "0e8a16", "description": "Auffindbarkeit und Topics"},
    "testing":         {"color": "1d76db", "description": "Tests und Qualitätssicherung"},
    "ai-generated":    {"color": "5319e7", "description": "Von KI generiertes Issue"},
    "priority-high":   {"color": "ee0701", "description": "Hohe Priorität"},
    "priority-medium": {"color": "ff9900", "description": "Mittlere Priorität"},
    "priority-low":    {"color": "0e8a16", "description": "Niedrige Priorität"},
}

# Issue-Text-Vorlage
ISSUE_BODY_TEMPLATE = """## 🤖 Automatisch generiertes Issue (AI Issue Solver)

{description}

---

### 📋 Details

| Feld | Wert |
|------|------|
| **Kategorie** | `{label}` |
| **Priorität** | `{priority}` |
| **Check** | `{check}` |
| **Generiert am** | {generated_at} |

---

### ✅ Aufgaben

- [ ] Problem analysieren und verstehen
- [ ] Lösung implementieren
- [ ] Änderungen testen
- [ ] PR erstellen und mergen

---

### 🔗 Ressourcen

{resources}

---

*Dieses Issue wurde automatisch durch [ai-issue-solver](https://github.com/SaJaToGu/ai-issue-solver) erstellt.*
"""

RESOURCES = {
    "missing_readme": """- [GitHub: About READMEs](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/about-readmes)
- [Awesome README](https://github.com/matiassingers/awesome-readme)
- [README Template](https://gist.github.com/PurpleBooth/109311bb0361f32d87a2)""",

    "missing_license": """- [choosealicense.com](https://choosealicense.com/)
- [GitHub: Lizenz hinzufügen](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/licensing-a-repository)""",

    "missing_gitignore": """- [gitignore.io](https://www.toptal.com/developers/gitignore) — Vorlagen für Python, OpenSCAD, etc.
- [GitHub .gitignore Templates](https://github.com/github/gitignore)""",

    "missing_ci": """- [GitHub Actions Quickstart](https://docs.github.com/en/actions/quickstart)
- [Beispiel: Python CI Workflow](https://github.com/actions/starter-workflows/blob/main/ci/python-package.yml)""",

    "no_description": """- [GitHub Repo Einstellungen](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/managing-repository-settings/managing-repository-metadata)""",

    "no_topics": """- [GitHub: Topics setzen](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/managing-repository-settings/classifying-your-repository-with-topics)
- Für 3D-Druck: `3d-printing`, `openscad`, `raspberry-pi`""",

    "stale_repo": """- [GitHub: Repo archivieren](https://docs.github.com/en/repositories/archiving-a-github-repository/archiving-repositories)""",

    "very_stale_repo": """- [GitHub: Repo archivieren](https://docs.github.com/en/repositories/archiving-a-github-repository/archiving-repositories)
- [GitHub Repo Einstellungen](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/managing-repository-settings/managing-repository-metadata)""",

    "missing_tests": """- [GitHub Actions: Build and test](https://docs.github.com/en/actions/use-cases-and-examples/building-and-testing)
- [pytest: Getting started](https://docs.pytest.org/en/stable/getting-started.html)""",

    "risky_generated_files": """- [gitignore.io](https://www.toptal.com/developers/gitignore)
- [GitHub .gitignore Templates](https://github.com/github/gitignore)""",

    "fork_no_customization": """- Füge einen Abschnitt "Meine Änderungen" oder "Why I forked this" in die README ein""",
}


# ─────────────────────────────────────────────────────────────
# GitHub API Helper
# ─────────────────────────────────────────────────────────────

class GitHubClient:
    BASE = "https://api.github.com"

    def __init__(self, token: str, owner: str):
        self.owner = owner
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        })

    def ensure_label(self, repo: str, name: str, dry_run: bool = False):
        """Legt ein Label an, falls es noch nicht existiert."""
        if dry_run:
            return
        info = LABELS.get(name, {"color": "ededed", "description": name})
        url = f"{self.BASE}/repos/{self.owner}/{repo}/labels"
        # Erst prüfen ob vorhanden
        resp = self.session.get(f"{url}/{name}")
        if resp.status_code == 200:
            return  # Schon vorhanden
        if resp.status_code != 404:
            raise_for_github_response(resp, f"Label prüfen: {name}")
        created = self.session.post(url, json={
            "name": name,
            "color": info["color"],
            "description": info["description"],
        })
        raise_for_github_response(created, f"Label erstellen: {name}")

    def issue_exists(self, repo: str, title: str) -> bool:
        """Prüft ob ein Issue mit diesem Titel schon existiert."""
        url = f"{self.BASE}/repos/{self.owner}/{repo}/issues"
        resp = self.session.get(url, params={"state": "all", "per_page": 100})
        raise_for_github_response(resp, "Issues prüfen")
        existing = [i["title"] for i in resp.json()]
        return title in existing

    def create_issue(self, repo: str, title: str, body: str,
                     labels: list[str]) -> dict:
        """Erstellt ein GitHub Issue."""
        url = f"{self.BASE}/repos/{self.owner}/{repo}/issues"
        resp = self.session.post(url, json={
            "title": title,
            "body": body,
            "labels": labels,
        })
        if resp.status_code == 201:
            return resp.json()
        raise_for_github_response(resp, f"Issue erstellen: {title}")


# ─────────────────────────────────────────────────────────────
# Issue-Erstellung
# ─────────────────────────────────────────────────────────────

def build_issue_body(issue: dict, generated_at: str) -> str:
    check = issue["check"]
    return ISSUE_BODY_TEMPLATE.format(
        description=issue["description"],
        label=issue["label"],
        priority=issue["priority"],
        check=check,
        generated_at=generated_at,
        resources=RESOURCES.get(check, "— keine spezifischen Links —"),
    )


def print_issue_preview(repo: str, title: str, body: str, labels: list[str]) -> None:
    """Gibt im Dry-Run alle entscheidenden Issue-Daten prüfbar aus."""
    print("      [DRY-RUN] Würde Issue erstellen:")
    print(f"         Repo:   {repo}")
    print(f"         Titel:  {title}")
    print(f"         Labels: {', '.join(labels)}")
    print("         Body:")
    for line in body.splitlines():
        print(f"           {line}" if line else "           ")


def create_issues_for_repo(client: GitHubClient | None, repo_data: dict,
                           dry_run: bool, priority_filter: str | None) -> int:
    repo = repo_data["repo"]
    issues = repo_data.get("issues_to_create", [])

    if not issues:
        print(f"   {repo}: keine Issues nötig ✅")
        return 0

    print(f"\n   📁 {repo} ({len(issues)} Issues):")
    created = 0

    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    for issue in issues:
        # Prioritäts-Filter
        if priority_filter and issue["priority"] != priority_filter:
            continue

        title = f"[AI] {issue['title']}"

        # Doppelte vermeiden
        if not dry_run and client and client.issue_exists(repo, title):
            print(f"      ⏭️  Bereits vorhanden: {title}")
            continue

        # Labels anlegen
        labels = [issue["label"], "ai-generated", f"priority-{issue['priority']}"]
        # Issue-Body bauen
        body = build_issue_body(issue, now)

        if dry_run:
            print_issue_preview(repo, title, body, labels)
            created += 1
            continue

        if client is None:
            raise RuntimeError("GitHubClient fehlt für echte Issue-Erstellung")

        # Labels anlegen und Issue erstellen
        for label in labels:
            client.ensure_label(repo, label)

        result = client.create_issue(repo, title, body, labels)
        print(f"      ✅ #{result.get('number', '?')} — {title}")
        print(f"         {result.get('html_url', '')}")
        created += 1

        # Rate-Limit schonen
        time.sleep(1)

    return created


# ─────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────

def main():
    print_banner("SCHRITT 2: ISSUES ERSTELLEN")

    parser = argparse.ArgumentParser(description="GitHub Issues aus Analysis-Report erstellen")
    parser.add_argument("--report", default="reports/analysis.json", help="Pfad zum JSON-Report")
    parser.add_argument("--dry-run", action="store_true", help="Nur anzeigen, nichts erstellen")
    parser.add_argument(
        "--confirm-create",
        action="store_true",
        help="Bestätigt bewusst, dass echte GitHub-Issues erstellt werden dürfen",
    )
    parser.add_argument("--repo", help="Nur für dieses Repo Issues erstellen")
    parser.add_argument("--priority", choices=["high", "medium", "low"], help="Nur diese Priorität")
    args = parser.parse_args()

    if args.dry_run and args.confirm_create:
        parser.error("--dry-run und --confirm-create können nicht kombiniert werden")

    dry_run = not args.confirm_create
    if args.dry_run:
        dry_run = True

    if requests is None and not dry_run:
        print_err("Python-Abhängigkeit fehlt: requests")
        print("   → Installieren mit: pip install -r requirements.txt")
        sys.exit(1)

    # Report laden
    report_path = Path(args.report)
    if not report_path.exists():
        print_err(f"Report nicht gefunden: {args.report}")
        print("   → Zuerst ausführen: python scripts/analyze_repos.py --user SaJaToGu")
        sys.exit(1)

    with open(report_path, encoding="utf-8") as f:
        report = json.load(f)

    user = report["user"]
    client = None

    if dry_run:
        print_warn("DRY-RUN Modus: Keine echten Issues werden erstellt")
        print("   → Echte Issues nur mit: --confirm-create\n")
    else:
        # GitHub-Zugangsdaten erst laden, wenn wirklich geschrieben wird.
        config = load_env()
        token = require_config_value(config, "GITHUB_TOKEN", "GitHub Token")
        client = GitHubClient(token, user)

    print_step(1, f"Verarbeite Report: {args.report}")
    print(f"   User: @{user} | Repos: {report['total_repos']} | Findings: {report['total_findings']}")

    print_step(2, "Issues erstellen")

    total_created = 0
    for repo_data in report["repos"]:
        if args.repo and repo_data["repo"] != args.repo:
            continue
        total_created += create_issues_for_repo(
            client, repo_data, dry_run=dry_run, priority_filter=args.priority
        )

    # Zusammenfassung
    print("\n" + "─" * 50)
    mode = "[DRY-RUN] " if dry_run else ""
    label = "Issues geprüft" if dry_run else "Issues erstellt"
    print(f"  {mode}✅ {label}: {total_created}")
    print("─" * 50)

    if not dry_run:
        print(f"\n✅ Weiter mit: python scripts/solve_issues.py --model claude\n")
    else:
        print(f"\n💡 Nach Review erneut mit --confirm-create ausführen, um echte Issues zu erstellen.\n")


if __name__ == "__main__":
    main()
