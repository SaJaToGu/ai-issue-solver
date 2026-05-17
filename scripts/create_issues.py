#!/usr/bin/env python3
"""
create_issues.py — Schritt 2: GitHub Issues erstellen
Morpheus-Style AI Issue Solver — github.com/SaJaToGu

Liest den Analysis-Report und erstellt strukturierte
GitHub Issues für jedes gefundene Problem.

Verwendung:
    python scripts/create_issues.py --report reports/analysis.json --dry-run
    python scripts/create_issues.py --report reports/analysis.json
    python scripts/create_issues.py --report reports/analysis.json --repo BedBoxDrawerRole
"""

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
from utils import load_env, print_banner, print_step, print_ok, print_warn, print_err


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
        self.session.post(url, json={
            "name": name,
            "color": info["color"],
            "description": info["description"],
        })

    def issue_exists(self, repo: str, title: str) -> bool:
        """Prüft ob ein Issue mit diesem Titel schon existiert."""
        url = f"{self.BASE}/repos/{self.owner}/{repo}/issues"
        resp = self.session.get(url, params={"state": "all", "per_page": 100})
        if resp.status_code != 200:
            return False
        existing = [i["title"] for i in resp.json()]
        return title in existing

    def create_issue(self, repo: str, title: str, body: str,
                     labels: list[str], dry_run: bool = False) -> dict | None:
        """Erstellt ein GitHub Issue."""
        if dry_run:
            print(f"      [DRY-RUN] Würde Issue erstellen: '{title}'")
            return {"html_url": "https://github.com/dry-run"}

        url = f"{self.BASE}/repos/{self.owner}/{repo}/issues"
        resp = self.session.post(url, json={
            "title": title,
            "body": body,
            "labels": labels,
        })
        if resp.status_code == 201:
            return resp.json()
        print_warn(f"Issue-Erstellung fehlgeschlagen: {resp.status_code} — {resp.text[:200]}")
        return None


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


def create_issues_for_repo(client: GitHubClient, repo_data: dict,
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
        if not dry_run and client.issue_exists(repo, title):
            print(f"      ⏭️  Bereits vorhanden: {title}")
            continue

        # Labels anlegen
        labels = [issue["label"], "ai-generated", f"priority-{issue['priority']}"]
        for label in labels:
            client.ensure_label(repo, label, dry_run=dry_run)

        # Issue-Body bauen
        body = build_issue_body(issue, now)

        # Issue erstellen
        result = client.create_issue(repo, title, body, labels, dry_run=dry_run)
        if result:
            print(f"      ✅ #{result.get('number', '?')} — {title}")
            print(f"         {result.get('html_url', '')}")
            created += 1

        # Rate-Limit schonen
        if not dry_run:
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
    parser.add_argument("--repo", help="Nur für dieses Repo Issues erstellen")
    parser.add_argument("--priority", choices=["high", "medium", "low"], help="Nur diese Priorität")
    args = parser.parse_args()

    if requests is None:
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

    # Config laden
    config = load_env()
    token = config.get("GITHUB_TOKEN")
    if not token:
        print_err("GITHUB_TOKEN fehlt in config/.env")
        sys.exit(1)

    user = report["user"]
    client = GitHubClient(token, user)

    if args.dry_run:
        print_warn("DRY-RUN Modus: Keine echten Issues werden erstellt\n")

    print_step(1, f"Verarbeite Report: {args.report}")
    print(f"   User: @{user} | Repos: {report['total_repos']} | Findings: {report['total_findings']}")

    print_step(2, "Issues erstellen")

    total_created = 0
    for repo_data in report["repos"]:
        if args.repo and repo_data["repo"] != args.repo:
            continue
        total_created += create_issues_for_repo(
            client, repo_data, dry_run=args.dry_run, priority_filter=args.priority
        )

    # Zusammenfassung
    print("\n" + "─" * 50)
    mode = "[DRY-RUN] " if args.dry_run else ""
    print(f"  {mode}✅ Issues erstellt: {total_created}")
    print("─" * 50)

    if not args.dry_run:
        print(f"\n✅ Weiter mit: python scripts/solve_issues.py --model claude\n")
    else:
        print(f"\n💡 Ohne --dry-run ausführen, um echte Issues zu erstellen.\n")


if __name__ == "__main__":
    main()
