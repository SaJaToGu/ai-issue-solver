#!/usr/bin/env python3
"""
Script to migrate existing GitHub issues to the new label taxonomy.

Usage:
    python scripts/label_migration.py --repo ai-issue-solver --dry-run
    python scripts/label_migration.py --repo ai-issue-solver --apply --confirm-migrate
"""

from __future__ import annotations

import argparse
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

# Mapping from old labels to new taxonomy labels
LABEL_MAPPING = {
    "automation": ["theme/workflow", "kind/automation"],
    "quality": ["theme/quality", "kind/test"],
    "codex": ["theme/codex", "agent/solver"],
    "documentation": ["kind/docs"],
    "github": ["theme/github", "area/prs", "area/issues"],
    "good-first-issue": ["priority/4-low"],
    "safety": ["theme/quality"],
    "setup": ["kind/feature"],
    "workflow": ["theme/workflow"],
    "analysis": ["theme/research", "kind/analysis"],
    "dashboard": ["theme/dashboard"],
    "provider": ["theme/provider"],
    "research": ["theme/research"],
    "opencode": ["area/opencode"],
    "sandbox": ["theme/codex"],  # theme/codex passt besser als area/sandbox
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

    def get_issues(self, repo: str) -> list[dict]:
        """Fetch all open issues from the repository."""
        issues_url = f"{self.BASE}/repos/{self.owner}/{repo}/issues"
        issues = []
        page = 1

        while True:
            resp = self.session.get(
                issues_url,
                params={"state": "open", "per_page": 100, "page": page},
            )
            raise_for_github_response(resp, "Issues abrufen")
            items = resp.json()
            if not items:
                break
            issues.extend(item for item in items if "pull_request" not in item)
            if len(items) < 100:
                break
            page += 1

        return issues

    def update_issue_labels(self, repo: str, issue_number: int, new_labels: list[str]) -> None:
        """Update labels for a specific issue."""
        url = f"{self.BASE}/repos/{self.owner}/{repo}/issues/{issue_number}"
        resp = self.session.patch(
            url,
            json={"labels": new_labels},
        )
        raise_for_github_response(resp, f"Labels aktualisieren: Issue #{issue_number}")

    def ensure_label(self, repo: str, name: str) -> None:
        """Ensure a label exists in the repository."""
        labels_url = f"{self.BASE}/repos/{self.owner}/{repo}/labels"
        resp = self.session.get(f"{labels_url}/{name}")
        if resp.status_code == 200:
            return
        if resp.status_code != 404:
            raise_for_github_response(resp, f"Label prüfen: {name}")
        
        # Default color and description for new labels
        color = "ededed"
        description = name
        
        # Override with specific values for known labels
        if name.startswith("theme/"):
            color = "006b75"
        elif name.startswith("area/"):
            color = "1d76db"
        elif name.startswith("kind/"):
            color = "0e8a16"
        elif name.startswith("state/"):
            color = "c5def5"
        elif name.startswith("priority/"):
            color = "d93f0b" if "1-critical" in name else "d73a4a" if "2-high" in name else "fbca04" if "3-medium" in name else "0e8a16"
        elif name.startswith("agent/"):
            color = "5319e7"

        created = self.session.post(
            labels_url,
            json={
                "name": name,
                "color": color,
                "description": description,
            },
        )
        raise_for_github_response(created, f"Label erstellen: {name}")


def migrate_issue_labels(issue: dict, mapping: dict[str, list[str]]) -> list[str]:
    """Migrate an issue's labels to the new taxonomy."""
    old_labels = [label["name"] for label in issue.get("labels", [])]
    new_labels = []
    
    for label in old_labels:
        if label in mapping:
            new_labels.extend(mapping[label])
        else:
            # Keep unmapped labels as-is
            new_labels.append(label)
    
    # Deduplicate while preserving order
    seen = set()
    deduped = []
    for label in new_labels:
        if label not in seen:
            seen.add(label)
            deduped.append(label)
    
    return deduped


def print_issue_migration_preview(issue: dict, new_labels: list[str]) -> None:
    """Print a preview of the label migration for an issue."""
    old_labels = [label["name"] for label in issue.get("labels", [])]
    print(f"   Issue #{issue['number']}: {issue['title']}")
    print(f"     Alte Labels: {', '.join(old_labels) if old_labels else 'Keine'}")
    print(f"     Neue Labels: {', '.join(new_labels) if new_labels else 'Keine'}")
    print()


def main() -> int:
    print_banner("LABEL-MIGRATION")

    parser = argparse.ArgumentParser(description="GitHub-Issue-Labels auf neue Taxonomie migrieren")
    parser.add_argument("--repo", default="ai-issue-solver", help="Ziel-Repo ohne Owner")
    parser.add_argument("--owner", help="GitHub Owner, sonst GITHUB_USER aus config/.env")
    parser.add_argument("--apply", action="store_true", help="Labels tatsächlich aktualisieren")
    parser.add_argument(
        "--confirm-migrate",
        action="store_true",
        help="Bestätigt bewusst, dass Labels migriert werden dürfen",
    )
    args = parser.parse_args()

    real_migrate = args.apply and args.confirm_migrate

    if requests is None and real_migrate:
        print_err("Python-Abhängigkeit fehlt: requests")
        print("   → Installieren mit: pip install -r requirements.txt")
        return 1

    print_step(1, "Starte Label-Migration")

    if not real_migrate:
        print_warn("DRY-RUN: Keine echten Änderungen werden vorgenommen.")
        if args.apply:
            print("   → --apply ist gesetzt, für echte Änderungen fehlt zusätzlich --confirm-migrate")
        print("   → Für echte Migration: python scripts/label_migration.py --apply --confirm-migrate")

    config = load_env()
    owner = args.owner or config.get("GITHUB_USER")
    token = require_config_value(config, "GITHUB_TOKEN", "GitHub Token")

    if not owner:
        print_err("GitHub User fehlt oder ist noch ein Platzhalter")
        print("   Erwartet: GITHUB_USER=<dein GitHub Username> oder --owner <username>")
        return 1

    client = GitHubClient(token, owner)
    issues = client.get_issues(args.repo)

    if not issues:
        print_warn("Keine offenen Issues gefunden.")
        return 0

    print_step(2, f"{len(issues)} Issue(s) zur Migration gefunden")

    # Ensure all new labels exist
    all_new_labels = set()
    for mapping in LABEL_MAPPING.values():
        all_new_labels.update(mapping)
    
    for label in sorted(all_new_labels):
        client.ensure_label(args.repo, label)

    migrated = 0
    skipped = 0

    for issue in issues:
        new_labels = migrate_issue_labels(issue, LABEL_MAPPING)
        print_issue_migration_preview(issue, new_labels)

        if not real_migrate:
            continue

        if set(new_labels) == {label["name"] for label in issue.get("labels", [])}:
            print_warn(f"Keine Änderungen für Issue #{issue['number']}")
            skipped += 1
            continue

        client.update_issue_labels(args.repo, issue["number"], new_labels)
        print_ok(f"Issue #{issue['number']} migriert: {issue['title']}")
        migrated += 1

    print_step(3, "Migration abgeschlossen")
    print(f"   Migriert: {migrated}")
    print(f"   Übersprungen: {skipped}")
    return 0


if __name__ == "__main__":
    sys.exit(main())