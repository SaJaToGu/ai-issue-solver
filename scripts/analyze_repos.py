#!/usr/bin/env python3
"""
analyze_repos.py — Schritt 1: GitHub-Repos analysieren
Morpheus-Style AI Issue Solver — github.com/SaJaToGu

Scannt alle Repos eines GitHub-Users und erstellt einen
detaillierten JSON-Report mit Verbesserungsvorschlägen.

Prüft u.a.: README, Lizenz, CI/CD, Tests, Staleness,
Label-Taxonomie (label_taxonomy_exists) und Label-Nutzung
(label_usage_health: ungenutzte/fehlende/inkonsistente Labels).

Verwendung:
    python scripts/analyze_repos.py --user SaJaToGu
    python scripts/analyze_repos.py --user SaJaToGu --output reports/analysis.json
"""

from __future__ import annotations

import argparse
import base64
import fnmatch
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

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
        "priority": "medium",
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
    "very_stale_repo": {
        "title": "Repo seit über 4 Jahren nicht aktualisiert",
        "label": "maintenance",
        "priority": "medium",
        "description": (
            "Dieses Repo wurde seit mehr als 4 Jahren nicht mehr aktualisiert. "
            "Prüfe aktiv, ob es noch gepflegt werden soll. Falls nicht, ergänze "
            "einen klaren Archiv-Hinweis in README und Repo-Beschreibung oder "
            "archiviere das Repo offiziell auf GitHub."
        ),
    },
    "missing_tests": {
        "title": "Keine Tests im Code-Projekt gefunden",
        "label": "testing",
        "priority": "medium",
        "description": (
            "Dieses Repo enthält Code, aber keine erkennbaren Testdateien oder "
            "Testverzeichnisse. Ergänze mindestens Smoke- oder Unit-Tests für die "
            "wichtigsten Funktionen und dokumentiere, wie sie ausgeführt werden."
        ),
    },
    "risky_generated_files": {
        "title": "Riskante generierte Dateien sind im Repo getrackt",
        "label": "best-practice",
        "priority": "medium",
        "description": (
            "Im Repository sind Dateien oder Verzeichnisse eingecheckt, die häufig "
            "generiert werden oder lokal entstehen. Prüfe, ob sie wirklich versioniert "
            "werden müssen. Falls nicht: entfernen und über .gitignore ausschließen."
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
    "label_taxonomy_exists": {
        "title": "Keine Label-Taxonomie dokumentiert",
        "label": "documentation",
        "priority": "medium",
        "description": (
            "Dieses Repo hat keine dokumentierte Label-Taxonomie (z.B. "
            "docs/label_taxonomy.md oder CONTRIBUTING.md mit Labels-Abschnitt). "
            "Eine definierte Taxonomie sorgt für konsistente Issue-Klassifikation "
            "und ermöglicht agentenbasierte Weiterleitung. "
            "Das AIS-Projekt bietet eine Standard-Taxonomie als Startpunkt "
            "und kann eine docs/label_taxonomy.md aus der Vorlage ableiten."
        ),
    },
    "label_usage_health": {
        "title": "Label-Nutzung zeigt Probleme",
        "label": "best-practice",
        "priority": "medium",
        "description": (
            "Die Analyse der Label-Nutzung hat Auffälligkeiten ergeben. "
            "Mögliche Probleme: Label definiert aber nie verwendet, "
            "offene Issues/PRs ohne Label, oder Issue-Labels, die nicht "
            "in der Taxonomie-Dokumentation auftauchen. "
            "Details siehe konkrete Beobachtung."
        ),
    },
}

CODE_FILE_EXTENSIONS = {
    ".c", ".cc", ".cpp", ".cs", ".css", ".go", ".h", ".hpp", ".html", ".java",
    ".js", ".jsx", ".kt", ".m", ".mm", ".php", ".py", ".rb", ".rs", ".scala",
    ".scss", ".sh", ".swift", ".ts", ".tsx", ".vue",
}

PROJECT_MANIFESTS = {
    "Cargo.toml", "composer.json", "go.mod", "package.json", "pom.xml",
    "pyproject.toml", "requirements.txt", "setup.cfg", "setup.py",
}

TEST_PATH_PATTERNS = (
    "test/*", "tests/*", "__tests__/*", "spec/*",
    "*_test.*", "test_*.py", "*.test.*", "*.spec.*",
)

CI_WORKFLOW_PATTERNS = (
    ".github/workflows/*.yml",
    ".github/workflows/*.yaml",
)

RISKY_GENERATED_PATTERNS = (
    ".DS_Store",
    "*.egg-info/*",
    "*.log",
    "*.min.js",
    "*.pyc",
    "*.stl",
    "*.gcode",
    "*.3mf",
    "*.zip",
    "__pycache__/*",
    "build/*",
    "coverage/*",
    "dist/*",
    "node_modules/*",
    "target/*",
)


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

    def get_repo_tree_paths(self, owner: str, repo: str, branch: str | None) -> list[str]:
        if not branch:
            return []
        branch_ref = quote(branch, safe="")
        result = self.get(f"/repos/{owner}/{repo}/git/trees/{branch_ref}", recursive=1)
        if result is None:
            return []
        if result.get("truncated"):
            print_warn(f"{repo}: Repo-Tree ist gekürzt, einige Datei-Checks können unvollständig sein")
        return [
            item["path"]
            for item in result.get("tree", [])
            if item.get("type") == "blob"
        ]


# ─────────────────────────────────────────────────────────────
# Analyse-Logik
# ─────────────────────────────────────────────────────────────

def normalize_path(path: str) -> str:
    """Normalisiert GitHub-Tree-Pfade für einfache Pattern-Matches."""
    return path.strip("/")


def path_matches(path: str, patterns: tuple[str, ...]) -> bool:
    normalized = normalize_path(path)
    return any(fnmatch.fnmatch(normalized, pattern) for pattern in patterns)


def has_ci_workflow(paths: list[str]) -> bool:
    return any(path_matches(path, CI_WORKFLOW_PATTERNS) for path in paths)


def is_code_project(repo: dict, paths: list[str]) -> bool:
    if repo.get("language"):
        return True
    for path in paths:
        name = Path(path).name
        if name in PROJECT_MANIFESTS:
            return True
        if Path(path).suffix.lower() in CODE_FILE_EXTENSIONS:
            return True
    return False


def has_tests(paths: list[str]) -> bool:
    return any(path_matches(path, TEST_PATH_PATTERNS) for path in paths)


def find_risky_generated_files(paths: list[str], limit: int = 10) -> list[str]:
    matches = []
    for path in paths:
        if path_matches(path, RISKY_GENERATED_PATTERNS):
            matches.append(path)
        if len(matches) >= limit:
            break
    return matches


def with_detail(check: str, detail: str | None = None) -> dict:
    issue = {
        "check": check,
        **CHECKS[check],
    }
    if detail:
        issue["description"] = f"{issue['description']}\n\nKonkrete Beobachtung: {detail}"
    return issue


def analyze_repo(client: GitHubClient, owner: str, repo: dict) -> dict:
    """Analysiert ein einzelnes Repo und gibt Findings zurück."""
    name = repo["name"]
    findings = []
    finding_details = {}

    print(f"   Analysiere: {name} ...", end=" ", flush=True)

    tree_paths = client.get_repo_tree_paths(owner, name, repo.get("default_branch"))
    code_project = is_code_project(repo, tree_paths)

    def add_finding(check: str, detail: str | None = None):
        if check not in findings:
            findings.append(check)
        if detail:
            finding_details[check] = detail

    # README prüfen
    readme_size = client.get_readme_length(owner, name)
    if readme_size < 200:
        if readme_size == 0:
            add_finding("missing_readme", "README wurde nicht gefunden.")
        else:
            add_finding("missing_readme", f"README ist nur {readme_size} Bytes groß.")

    # LICENSE prüfen
    has_license = repo.get("license") is not None
    if not has_license:
        # Doppelt prüfen über Contents-API
        has_license = client.repo_has_file(owner, name, "LICENSE") or \
                      client.repo_has_file(owner, name, "LICENSE.md") or \
                      client.repo_has_file(owner, name, "LICENSE.txt")
    if not has_license:
        add_finding("missing_license")

    # .gitignore prüfen
    if not client.repo_has_file(owner, name, ".gitignore"):
        add_finding("missing_gitignore")

    # GitHub Actions prüfen
    if code_project and not has_ci_workflow(tree_paths) and not client.repo_has_dir(owner, name, ".github/workflows"):
        add_finding("missing_ci", "Es wurden Code-Dateien erkannt, aber kein Workflow unter .github/workflows/.")

    # Beschreibung
    if not repo.get("description"):
        add_finding("no_description", "Das GitHub-About-Feld description ist leer.")

    # Topics
    if not repo.get("topics"):
        add_finding("no_topics", "Die GitHub API liefert keine Topics für dieses Repo.")

    # Stale (>2 Jahre kein Push)
    pushed_at = repo.get("pushed_at")
    if pushed_at:
        pushed = datetime.fromisoformat(pushed_at.replace("Z", "+00:00"))
        age_days = (datetime.now(timezone.utc) - pushed).days
        detail = f"Letzter Push: {pushed.date().isoformat()} ({age_days} Tage her)."
        if age_days > 1460:
            add_finding("very_stale_repo", detail)
        elif age_days > 730:
            add_finding("stale_repo", detail)

    # Tests prüfen
    if code_project and tree_paths and not has_tests(tree_paths):
        code_examples = [
            path for path in tree_paths
            if Path(path).suffix.lower() in CODE_FILE_EXTENSIONS or Path(path).name in PROJECT_MANIFESTS
        ][:5]
        detail = "Erkannte Code-/Manifest-Dateien: " + ", ".join(code_examples)
        add_finding("missing_tests", detail)

    # Riskante generierte Dateien prüfen
    generated_files = find_risky_generated_files(tree_paths)
    if generated_files:
        detail = "Beispiele: " + ", ".join(generated_files)
        add_finding("risky_generated_files", detail)

    # Fork ohne Eigendoku
    if repo.get("fork") and readme_size < 300:
        add_finding("fork_no_customization", f"Fork mit README-Größe {readme_size} Bytes.")

    # ── Label-Taxonomie prüfen ─────────────────────────────────
    has_taxonomy_file = any(
        'label_taxonomy' in p.lower() or p.lower().endswith('label_taxonomy.md')
        for p in tree_paths
    )
    has_label_doc = has_taxonomy_file
    if not has_taxonomy_file:
        has_contrib = any(p.lower() == 'contributing.md' for p in tree_paths)
        if has_contrib:
            contrib_resp = client.get(
                f"/repos/{owner}/{name}/contents/CONTRIBUTING.md"
            )
            if isinstance(contrib_resp, dict) and contrib_resp.get("content"):
                try:
                    raw_contrib = base64.b64decode(
                        contrib_resp["content"]
                    ).decode("utf-8")
                    if 'label' in raw_contrib.lower():
                        has_label_doc = True
                except (ValueError, IndexError):
                    pass
    if not has_label_doc:
        add_finding("label_taxonomy_exists",
            "Keine docs/label_taxonomy.md oder CONTRIBUTING.md mit Labels-Abschnitt "
            "gefunden. Das AIS-Projekt kann eine docs/label_taxonomy.md aus der "
            "Standard-Vorlage ableiten.")

    # ── Label-Gesundheit prüfen ─────────────────────────────────
    labels_data = client.get(f"/repos/{owner}/{name}/labels")
    issues_data = client.get_all_pages(
        f"/repos/{owner}/{name}/issues", state="open"
    )
    if isinstance(labels_data, list) and isinstance(issues_data, list):
        defined_labels = {l["name"] for l in labels_data}
        used_labels = set()
        untriaged = []
        for issue in issues_data:
            issue_lbls = {l["name"] for l in issue.get("labels", [])}
            used_labels.update(issue_lbls)
            if not issue_lbls:
                untriaged.append(f"#{issue['number']}")

        health_msgs = []

        unused = defined_labels - used_labels
        if unused:
            sorted_unused = sorted(unused)[:10]
            health_msgs.append(
                f"Label definiert aber nie genutzt: {', '.join(sorted_unused)}"
            )

        if untriaged:
            health_msgs.append(
                f"Offene Issues/PRs ohne Label: {', '.join(untriaged[:10])}"
            )

        # Issue-Labels in Taxonomie-Dokumentation prüfen
        taxonomy_paths = [
            p for p in tree_paths
            if 'label_taxonomy' in p.lower() or p.lower().endswith('label_taxonomy.md')
        ]
        if taxonomy_paths:
            doc_labels = set()
            for tax_path in taxonomy_paths:
                content_resp = client.get(
                    f"/repos/{owner}/{name}/contents/{tax_path}"
                )
                if isinstance(content_resp, dict) and content_resp.get("content"):
                    try:
                        raw = base64.b64decode(
                            content_resp["content"]
                        ).decode("utf-8")
                        for line in raw.splitlines():
                            line = line.strip()
                            if line.startswith("| `") and "` |" in line:
                                lbl = line.split("`")[1].strip()
                                if lbl:
                                    doc_labels.add(lbl)
                    except (ValueError, IndexError):
                        pass
            if doc_labels:
                inconsistent = used_labels - doc_labels
                if inconsistent:
                    sorted_inc = sorted(inconsistent)[:10]
                    health_msgs.append(
                        "Issue-Labels nicht in Taxonomie-Doku: "
                        f"{', '.join(sorted_inc)}"
                    )

        if health_msgs:
            add_finding("label_usage_health", "; ".join(health_msgs))

    print(f"{'✅' if not findings else f'⚠️  {len(findings)} Findings'}")

    return {
        "repo": name,
        "url": repo["html_url"],
        "language": repo.get("language"),
        "is_fork": repo.get("fork", False),
        "stars": repo.get("stargazers_count", 0),
        "last_push": pushed_at,
        "findings": findings,
        "finding_details": finding_details,
        "issues_to_create": [
            with_detail(f, finding_details.get(f))
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
    print(f"\n✅ Weiter mit: python scripts/create_issues.py --report {args.output}\n")


if __name__ == "__main__":
    main()
