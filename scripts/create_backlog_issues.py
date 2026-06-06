#!/usr/bin/env python3
"""
Create GitHub issues from docs/BACKLOG.md.

Usage:
    python scripts/create_backlog_issues.py --repo ai-issue-solver
    python scripts/create_backlog_issues.py --repo ai-issue-solver --apply --confirm-create
"""

from __future__ import annotations

import argparse
import re
import sys
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


DEFAULT_LABELS = {
    # Theme labels
    "theme/dashboard": {"color": "006b75", "description": "Dashboard UI/UX and data visualization"},
    "theme/model": {"color": "006b75", "description": "Model selection and provider integration"},
    "theme/cost": {"color": "006b75", "description": "Budget tracking and cost analysis"},
    "theme/provider": {"color": "006b75", "description": "Provider-specific features and APIs"},
    "theme/workflow": {"color": "006b75", "description": "Workflow automation and process"},
    "theme/backlog": {"color": "006b75", "description": "Backlog management and prioritization"},
    "theme/supervisor": {"color": "006b75", "description": "Process monitoring and job management"},
    "theme/distributed-workers": {"color": "006b75", "description": "Worker distribution and scaling"},
    "theme/github": {"color": "006b75", "description": "GitHub API and integration"},
    "theme/quality": {"color": "006b75", "description": "Code quality and testing"},
    "theme/research": {"color": "006b75", "description": "Research tasks and evidence collection"},
    "theme/codex": {"color": "006b75", "description": "Codex-specific features and sandboxing"},
    
    # Area labels
    "area/pwa": {"color": "1d76db", "description": "Progressive Web App (dashboard front-end)"},
    "area/reports": {"color": "1d76db", "description": "Run reports and analytics"},
    "area/runs": {"color": "1d76db", "description": "Solver runs and job execution"},
    "area/prs": {"color": "1d76db", "description": "Pull request handling and workflow"},
    "area/issues": {"color": "1d76db", "description": "Issue lifecycle and management"},
    "area/labels": {"color": "1d76db", "description": "Label taxonomy and classification"},
    "area/model-selection": {"color": "1d76db", "description": "Model selection logic and policies"},
    "area/provider-interface": {"color": "1d76db", "description": "Provider abstraction layer"},
    "area/budget": {"color": "1d76db", "description": "Budget tracking and cost controls"},
    "area/worker-node": {"color": "1d76db", "description": "Worker node management"},
    "area/opencode": {"color": "1d76db", "description": "OpenCode CLI integration"},
    "area/openrouter": {"color": "1d76db", "description": "OpenRouter API integration"},
    "area/mistral": {"color": "1d76db", "description": "Mistral provider integration"},
    "area/minimax": {"color": "1d76db", "description": "MiniMax provider integration"},
    "area/anthropic": {"color": "1d76db", "description": "Anthropic (Claude) provider integration"},
    
    # Kind labels
    "kind/feature": {"color": "0e8a16", "description": "New functionality"},
    "kind/bug": {"color": "d73a4a", "description": "Bug fixes"},
    "kind/refactor": {"color": "006b75", "description": "Code refactoring"},
    "kind/docs": {"color": "0075ca", "description": "Documentation updates"},
    "kind/test": {"color": "c5def5", "description": "Test coverage and validation"},
    "kind/analysis": {"color": "1d76db", "description": "Data analysis and metrics"},
    "kind/automation": {"color": "5319e7", "description": "Automation scripts"},
    "kind/research": {"color": "5319e7", "description": "Research tasks"},
    "kind/cleanup": {"color": "fbca04", "description": "Code cleanup and maintenance"},
    
    # State labels
    "state/backlog": {"color": "ededed", "description": "Issue is in the backlog"},
    "state/ready": {"color": "c2e0c6", "description": "Issue is ready for implementation"},
    "state/in-progress": {"color": "c5def5", "description": "Issue is actively being worked on"},
    "state/blocked": {"color": "d93f0b", "description": "Issue is blocked"},
    "state/review": {"color": "fbca04", "description": "Issue is under review"},
    "state/on-hold": {"color": "ededed", "description": "Issue is temporarily paused"},
    "state/duplicate": {"color": "cfd3d7", "description": "Issue is a duplicate"},
    "state/wontfix": {"color": "000000", "description": "Issue will not be addressed"},
    
    # Priority labels
    "priority/1-critical": {"color": "d93f0b", "description": "Critical priority"},
    "priority/2-high": {"color": "d73a4a", "description": "High priority"},
    "priority/3-medium": {"color": "fbca04", "description": "Medium priority"},
    "priority/4-low": {"color": "0e8a16", "description": "Low priority"},
    
    # Agent labels
    "agent/triage": {"color": "5319e7", "description": "Initial classification and routing"},
    "agent/supervisor": {"color": "5319e7", "description": "Process monitoring and job management"},
    "agent/cost": {"color": "5319e7", "description": "Budget tracking and cost analysis"},
    "agent/research": {"color": "5319e7", "description": "Research and evidence collection"},
    "agent/planner": {"color": "5319e7", "description": "Backlog shaping and issue planning"},
    "agent/solver": {"color": "5319e7", "description": "Implementation and coding work"},
    "agent/reviewer": {"color": "5319e7", "description": "PR review and quality assurance"},
    
    # Legacy labels (mapped to new taxonomy)
    "automation": {"color": "5319e7", "description": "Automation and worker behavior (legacy)"},
    "quality": {"color": "0e8a16", "description": "Quality improvements (legacy)"},
    "codex": {"color": "5319e7", "description": "Codex worker integration (legacy)"},
    "documentation": {"color": "0075ca", "description": "Documentation improvements (legacy)"},
    "github": {"color": "24292f", "description": "GitHub API and workflow (legacy)"},
    "good-first-issue": {"color": "7057ff", "description": "Good first issue (legacy)"},
    "safety": {"color": "d93f0b", "description": "Safety and confirmation behavior (legacy)"},
    "setup": {"color": "fbca04", "description": "Setup and configuration (legacy)"},
    "workflow": {"color": "c5def5", "description": "Project workflow (legacy)"},
    "analysis": {"color": "1d76db", "description": "Repository analysis and findings (legacy)"},
}


class GitHubClient:
    BASE = "https://api.github.com"

    def __init__(self, token: str, owner: str):
        self.owner = owner
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"token {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            }
        )

    def ensure_label(self, repo: str, name: str) -> None:
        info = DEFAULT_LABELS.get(name, {"color": "ededed", "description": name})
        labels_url = f"{self.BASE}/repos/{self.owner}/{repo}/labels"
        resp = self.session.get(f"{labels_url}/{name}")
        if resp.status_code == 200:
            return
        if resp.status_code != 404:
            raise_for_github_response(resp, f"Label prüfen: {name}")
        created = self.session.post(
            labels_url,
            json={
                "name": name,
                "color": info["color"],
                "description": info["description"],
            },
        )
        raise_for_github_response(created, f"Label erstellen: {name}")

    def issue_exists(self, repo: str, title: str) -> bool:
        issues_url = f"{self.BASE}/repos/{self.owner}/{repo}/issues"
        resp = self.session.get(issues_url, params={"state": "all", "per_page": 100})
        raise_for_github_response(resp, "Issues prüfen")
        return any(item.get("title") == title for item in resp.json())

    def normalize_title(self, title: str) -> str:
        """Normalisiert einen Titel für den Vergleich: lowercase, ohne Leerzeichen und Sonderzeichen."""
        import re
        return re.sub(r'[^a-z0-9]', '', title.lower())

    def find_matching_issue(self, repo: str, title: str) -> dict | None:
        """Findet ein bestehendes Issue mit exaktem oder normalisiertem Titel."""
        normalized_title = self.normalize_title(title)
        issues_url = f"{self.BASE}/repos/{self.owner}/{repo}/issues"
        page = 1

        while True:
            resp = self.session.get(
                issues_url,
                params={"state": "all", "per_page": 100, "page": page},
            )
            raise_for_github_response(resp, "Issues prüfen")
            items = resp.json()
            if not items:
                break

            for item in items:
                if "pull_request" in item:
                    continue
                item_title = item.get("title", "")
                if item_title == title:
                    return item
                if self.normalize_title(item_title) == normalized_title:
                    return item

            if len(items) < 100:
                break
            page += 1

        return None

    def get_issues_by_title(self, repo: str, titles: list[str]) -> dict[str, dict]:
        wanted = set(titles)
        found: dict[str, dict] = {}
        issues_url = f"{self.BASE}/repos/{self.owner}/{repo}/issues"
        page = 1

        while True:
            resp = self.session.get(
                issues_url,
                params={"state": "all", "per_page": 100, "page": page},
            )
            raise_for_github_response(resp, "Issues prüfen")
            items = resp.json()
            if not items:
                break

            for item in items:
                if "pull_request" in item:
                    continue
                title = item.get("title") or ""
                if title in wanted:
                    found[title] = item

            if len(items) < 100:
                break
            page += 1

        return found

    def create_issue(self, repo: str, title: str, body: str, labels: list[str]) -> str:
        issues_url = f"{self.BASE}/repos/{self.owner}/{repo}/issues"
        resp = self.session.post(
            issues_url,
            json={"title": title, "body": body, "labels": labels},
        )
        raise_for_github_response(resp, f"Issue erstellen: {title}")
        return resp.json()["html_url"]


def find_closed_issues_in_backlog(issues: list[dict], github_issues: dict[str, dict]) -> list[str]:
    """Identify closed GitHub issues still present in the backlog."""
    closed = []
    for issue in issues:
        title = issue["title"]
        if title in github_issues and github_issues[title].get("state") == "closed":
            closed.append(title)
    return closed


def parse_backlog(path: Path) -> list[dict]:
    text = path.read_text(encoding="utf-8")
    sections = re.split(r"(?m)^##\s+\d+\.\s+", text)
    issues = []

    for section in sections[1:]:
        lines = section.strip().splitlines()
        if not lines:
            continue

        title = lines[0].strip()
        body_lines = lines[1:]
        labels = []
        body = []

        for line in body_lines:
            if line.startswith("Labels:"):
                labels = re.findall(r"`([^`]+)`", line)
                continue
            body.append(line)

        issues.append(
            {
                "title": title,
                "labels": labels,
                "body": "\n".join(body).strip()
                + f"\n\n---\nCreated from `{path.as_posix()}`.",
            }
        )

    return issues


def print_issue_preview(repo: str, issue: dict) -> None:
    """Gibt im Dry-Run alle entscheidenden Issue-Daten prüfbar aus."""
    print("   [DRY-RUN] Würde Issue erstellen:")
    print(f"      Repo:   {repo}")
    print(f"      Titel:  {issue['title']}")
    print(f"      Labels: {', '.join(issue['labels'])}")
    print("      Body:")
    for line in issue["body"].splitlines():
        print(f"        {line}" if line else "        ")


def main() -> int:
    print_banner("BACKLOG-ISSUES ERSTELLEN")

    parser = argparse.ArgumentParser(description="GitHub Issues aus docs/BACKLOG.md erstellen")
    parser.add_argument("--backlog", default="docs/BACKLOG.md", help="Pfad zur Backlog-Datei")
    parser.add_argument("--repo", default="ai-issue-solver", help="Ziel-Repo ohne Owner")
    parser.add_argument("--owner", help="GitHub Owner, sonst GITHUB_USER aus config/.env")
    parser.add_argument("--apply", action="store_true", help="Echte GitHub-Issues erstellen")
    parser.add_argument(
        "--confirm-create",
        action="store_true",
        help="Bestätigt bewusst, dass echte GitHub-Issues erstellt werden dürfen",
    )
    parser.add_argument(
        "--only-new",
        action="store_true",
        help="Nur neue Issues erstellen (Standard: true)",
        default=True,
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Erzwingt die Erstellung von Issues, auch wenn sie bereits existieren",
    )
    args = parser.parse_args()

    real_create = args.apply and args.confirm_create

    if requests is None and real_create:
        print_err("Python-Abhängigkeit fehlt: requests")
        print("   → Installieren mit: pip install -r requirements.txt")
        return 1

    backlog_path = Path(args.backlog)
    if not backlog_path.exists():
        print_err(f"Backlog nicht gefunden: {args.backlog}")
        return 1

    issues = parse_backlog(backlog_path)
    if not issues:
        print_warn("Keine Issues im Backlog gefunden")
        return 0

    print_step(1, f"{len(issues)} Backlog-Issue(s) gefunden")
    for issue in issues:
        print_issue_preview(args.repo, issue)

    if not real_create:
        print()
        print_warn("DRY-RUN: Keine echten GitHub-Issues wurden erstellt.")
        if args.apply:
            print("   → --apply ist gesetzt, für echte Issues fehlt zusätzlich --confirm-create")
        print("   → Für echte Issues: python scripts/create_backlog_issues.py --apply --confirm-create")
        print("   → Optionen: --only-new (Standard), --force (erzwingt Erstellung)")
        return 0

    config = load_env()
    owner = args.owner or config.get("GITHUB_USER")
    token = require_config_value(config, "GITHUB_TOKEN", "GitHub Token")

    if not owner:
        print_err("GitHub User fehlt oder ist noch ein Platzhalter")
        print("   Erwartet: GITHUB_USER=<dein GitHub Username> oder --owner <username>")
        return 1

    client = GitHubClient(token, owner)

    print_step(2, f"Prüfe bestehende Issues in {owner}/{args.repo}")
    new_issues = []
    existing_open = []
    existing_closed = []

    for issue in issues:
        matching_issue = client.find_matching_issue(args.repo, issue["title"])
        if matching_issue:
            if matching_issue.get("state") == "open":
                existing_open.append((issue["title"], matching_issue["number"]))
            else:
                existing_closed.append((issue["title"], matching_issue["number"]))
        else:
            new_issues.append(issue)

    # Filter based on flags
    if args.only_new:
        issues_to_create = new_issues
    elif args.force:
        issues_to_create = issues
    else:
        issues_to_create = new_issues

    print_step(3, f"Erstelle Issues in {owner}/{args.repo}")
    created = 0
    skipped = 0

    # Warn about closed issues still in backlog
    if existing_closed:
        print_warn("Geschlossene Issues im Backlog gefunden:")
        for title, number in existing_closed:
            print_warn(f"   - {title} (GitHub #{number})")
        print_warn("Bitte bereinige das Backlog mit scripts/cleanup_backlog.py")

    # Show dry-run summary
    if not real_create:
        print()
        print_warn("DRY-RUN: Keine echten GitHub-Issues wurden erstellt.")
        print(f"   → Würde erstellen: {len(issues_to_create)}")
        print(f"   → Bereits vorhanden (offen): {len(existing_open)}")
        print(f"   → Bereits vorhanden (geschlossen): {len(existing_closed)}")
        if args.only_new:
            print("   → --only-new: Nur neue Issues werden vorgeschlagen")
        if args.force:
            print("   → --force: Alle Issues würden erstellt (auch bestehende)")
        return 0

    # Create issues
    for issue in issues_to_create:
        # Map legacy labels to new taxonomy and ensure they exist
        mapped_labels = []
        for label in issue["labels"]:
            for new_label in LABEL_MAPPING.get(label, [label]):
                client.ensure_label(args.repo, new_label)
                mapped_labels.append(new_label)

        url = client.create_issue(args.repo, issue["title"], issue["body"], mapped_labels)
        print_ok(f"{issue['title']} -> {url}")
        created += 1

    # Log skipped issues
    for title, number in existing_open:
        print_warn(f"Übersprungen (bereits offen): {title} (GitHub #{number})")
        skipped += 1

    print_step(4, "Fertig")
    print(f"   Erstellt: {created}")
    print(f"   Übersprungen: {skipped}")
    if existing_closed:
        print(f"   Geschlossen (nicht erstellt): {len(existing_closed)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
