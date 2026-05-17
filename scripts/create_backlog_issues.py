#!/usr/bin/env python3
"""
Create GitHub issues from docs/BACKLOG.md.

Usage:
    python scripts/create_backlog_issues.py --repo ai-issue-solver
    python scripts/create_backlog_issues.py --repo ai-issue-solver --apply
"""

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
    "analysis": {"color": "1d76db", "description": "Repository analysis and findings"},
    "automation": {"color": "5319e7", "description": "Automation and worker behavior"},
    "codex": {"color": "5319e7", "description": "Codex worker integration"},
    "documentation": {"color": "0075ca", "description": "Documentation improvements"},
    "github": {"color": "24292f", "description": "GitHub API and workflow"},
    "good-first-issue": {"color": "7057ff", "description": "Good first issue"},
    "quality": {"color": "0e8a16", "description": "Quality improvements"},
    "safety": {"color": "d93f0b", "description": "Safety and confirmation behavior"},
    "setup": {"color": "fbca04", "description": "Setup and configuration"},
    "workflow": {"color": "c5def5", "description": "Project workflow"},
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

    def create_issue(self, repo: str, title: str, body: str, labels: list[str]) -> str:
        issues_url = f"{self.BASE}/repos/{self.owner}/{repo}/issues"
        resp = self.session.post(
            issues_url,
            json={"title": title, "body": body, "labels": labels},
        )
        raise_for_github_response(resp, f"Issue erstellen: {title}")
        return resp.json()["html_url"]


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


def main() -> int:
    print_banner("BACKLOG-ISSUES ERSTELLEN")

    parser = argparse.ArgumentParser(description="GitHub Issues aus docs/BACKLOG.md erstellen")
    parser.add_argument("--backlog", default="docs/BACKLOG.md", help="Pfad zur Backlog-Datei")
    parser.add_argument("--repo", default="ai-issue-solver", help="Ziel-Repo ohne Owner")
    parser.add_argument("--owner", help="GitHub Owner, sonst GITHUB_USER aus config/.env")
    parser.add_argument("--apply", action="store_true", help="Echte GitHub-Issues erstellen")
    args = parser.parse_args()

    if requests is None:
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
        print(f"   - {issue['title']} [{', '.join(issue['labels'])}]")

    if not args.apply:
        print()
        print_warn("DRY-RUN: Keine echten GitHub-Issues wurden erstellt.")
        print("   → Für echte Issues: python scripts/create_backlog_issues.py --apply")
        return 0

    config = load_env()
    owner = args.owner or config.get("GITHUB_USER")
    token = require_config_value(config, "GITHUB_TOKEN", "GitHub Token")

    if not owner:
        print_err("GitHub User fehlt oder ist noch ein Platzhalter")
        print("   Erwartet: GITHUB_USER=<dein GitHub Username> oder --owner <username>")
        return 1

    client = GitHubClient(token, owner)

    print_step(2, f"Erstelle Issues in {owner}/{args.repo}")
    created = 0
    skipped = 0

    for issue in issues:
        if client.issue_exists(args.repo, issue["title"]):
            print_warn(f"Bereits vorhanden: {issue['title']}")
            skipped += 1
            continue

        for label in issue["labels"]:
            client.ensure_label(args.repo, label)

        url = client.create_issue(args.repo, issue["title"], issue["body"], issue["labels"])
        print_ok(f"{issue['title']} -> {url}")
        created += 1

    print_step(3, "Fertig")
    print(f"   Erstellt: {created}")
    print(f"   Übersprungen: {skipped}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
