#!/usr/bin/env python3
"""
Cleanup helper for completed NEXT_BACKLOG items.

Identifies backlog entries whose matching GitHub issues are closed and
provides options to remove or archive them from the backlog file.

Usage:
    python scripts/cleanup_backlog.py --backlog docs/NEXT_BACKLOG.md
    python scripts/cleanup_backlog.py --backlog docs/NEXT_BACKLOG.md --apply --confirm-remove
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

    def get_issues_by_title(self, repo: str, titles: list[str]) -> dict[str, dict]:
        """Fetch all issues from repo and return dict mapped by title."""
        issues_url = f"{self.BASE}/repos/{self.owner}/{repo}/issues"
        all_issues = {}
        page = 1
        per_page = 100

        while True:
            resp = self.session.get(
                issues_url,
                params={"state": "all", "per_page": per_page, "page": page},
            )
            raise_for_github_response(resp, "Issues abrufen")
            page_issues = resp.json()

            if not page_issues:
                break

            for issue in page_issues:
                title = issue.get("title", "")
                if title in titles:
                    all_issues[title] = issue

            # Check if there are more pages
            link_header = resp.headers.get("Link", "")
            if "rel=\"next\"" not in link_header:
                break
            page += 1

        return all_issues


def parse_backlog(path: Path) -> list[dict]:
    """Parse backlog file and extract issues with their sections."""
    text = path.read_text(encoding="utf-8")
    
    # Find all section headers and their positions
    section_pattern = r"(?m)^(##\s+\d+\.\s+)(.+?)$"
    headers = list(re.finditer(section_pattern, text, re.MULTILINE))
    
    issues = []
    
    for i, match in enumerate(headers):
        header_prefix = match.group(1)  # "## 1. "
        title = match.group(2).strip()  # The actual title text
        
        # Find the start and end of this section
        section_start = match.start()
        section_end = len(text)
        
        # If there's a next section, end at its start
        if i + 1 < len(headers):
            section_end = headers[i + 1].start()
        
        section_text = text[section_start:section_end].strip()
        
        # Parse body
        section_lines = section_text.splitlines()
        body_lines = section_lines[1:]  # Skip header line
        labels = []
        body = []

        for line in body_lines:
            stripped = line.strip()
            if stripped.startswith("Labels:"):
                labels = re.findall(r"`([^`]+)`", stripped)
                continue
            body.append(stripped)

        # Store the original section text for potential removal
        issues.append(
            {
                "title": title,
                "labels": labels,
                "body": "\n".join(body).strip(),
                "raw_section": section_text,
            }
        )

    return issues


def find_completed_issues(
    issues: list[dict], github_issues: dict[str, dict]
) -> list[dict]:
    """Identify backlog entries whose GitHub issues are closed."""
    completed = []
    for issue in issues:
        title = issue["title"]
        if title in github_issues:
            gh_issue = github_issues[title]
            # Issue is closed if state is "closed"
            if gh_issue.get("state") == "closed":
                completed.append(
                    {
                        "title": title,
                        "labels": issue.get("labels", []),
                        "number": gh_issue.get("number"),
                        "html_url": gh_issue.get("html_url"),
                        "raw_section": issue.get("raw_section", ""),
                    }
                )
    return completed


def remove_sections_from_backlog(
    backlog_path: Path, completed: list[dict]
) -> tuple[str, int]:
    """Remove completed issue sections from backlog file.
    
    Returns (new_content, count) where count is number of sections removed.
    """
    text = backlog_path.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)
    
    new_lines = []
    removed_count = 0
    skip_until_next_section = False
    
    # Build set of titles to remove, and also track section numbers + titles
    # for matching against "## N. Title" format
    completed_titles = {issue["title"] for issue in completed}
    
    for line in lines:
        # Check if this line starts a new section
        section_match = re.match(r"^##\s+(\d+)\.\s+(.+?)\s*$", line.rstrip())
        
        if section_match:
            section_number = section_match.group(1)
            title = section_match.group(2).strip()
            # Check if this section should be removed
            if title in completed_titles:
                skip_until_next_section = True
                removed_count += 1
                continue
            else:
                skip_until_next_section = False
                new_lines.append(line)
        elif skip_until_next_section:
            # Skip this line as it's part of a completed section
            continue
        else:
            new_lines.append(line)
    
    new_content = "".join(new_lines)
    return new_content, removed_count


def print_completed_preview(completed: list[dict]) -> None:
    """Print preview of completed issues in dry-run mode."""
    if not completed:
        print_warn("Keine abgeschlossenen Issues gefunden")
        return

    print(f"   Gefunden: {len(completed)} abgeschlossene Issue(s)")
    print()
    for issue in completed:
        print(f"   ✓ {issue['title']}")
        print(f"      Labels: {', '.join(issue['labels'])}")
        print(f"      GitHub: #{issue['number']} - {issue['html_url']}")
        print()


def main() -> int:
    print_banner("BACKLOG CLEANUP")

    parser = argparse.ArgumentParser(
        description="Abgeschlossene Issues aus Backlog-Datei entfernen"
    )
    parser.add_argument(
        "--backlog",
        default="docs/NEXT_BACKLOG.md",
        help="Pfad zur Backlog-Datei (Standard: docs/NEXT_BACKLOG.md)",
    )
    parser.add_argument(
        "--repo",
        default="ai-issue-solver",
        help="Ziel-Repo ohne Owner (Standard: ai-issue-solver)",
    )
    parser.add_argument("--owner", help="GitHub Owner, sonst GITHUB_USER aus config/.env")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Backlog-Datei tatsächlich anpassen",
    )
    parser.add_argument(
        "--confirm-remove",
        action="store_true",
        help="Bestätigt bewusst, dass Einträge entfernt werden dürfen",
    )
    args = parser.parse_args()

    real_remove = args.apply and args.confirm_remove

    if requests is None and real_remove:
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

    print_step(1, f"{len(issues)} Backlog-Issue(s) in {args.backlog} gefunden")

    # Get GitHub issues
    config = load_env()
    owner = args.owner or config.get("GITHUB_USER")
    token = config.get("GITHUB_TOKEN")

    if real_remove:
        if not owner:
            print_err("GitHub User fehlt")
            print("   Erwartet: GITHUB_USER=<dein GitHub Username> oder --owner <username>")
            return 1
        if not token or token.strip() in ("", "YOUR_GITHUB_TOKEN", "CHANGEME", "PLACEHOLDER"):
            print_err("GitHub Token fehlt oder ist noch ein Platzhalter")
            print("   Erwartet: GITHUB_TOKEN=<dein Token> in config/.env")
            return 1

        client = GitHubClient(token, owner)
        titles = [issue["title"] for issue in issues]
        github_issues = client.get_issues_by_title(args.repo, titles)
        completed = find_completed_issues(issues, github_issues)

        print_step(2, f"Abgeschlossene Issues prüfen")
        print_completed_preview(completed)

        if not completed:
            print_ok("Keine abgeschlossenen Issues zum Entfernen gefunden")
            return 0

        print_step(3, "Entferne abgeschlossene Issues aus Backlog")
        new_content, removed_count = remove_sections_from_backlog(backlog_path, completed)

        # Write the new content
        backlog_path.write_text(new_content, encoding="utf-8")
        print_ok(f"{removed_count} abgeschlossene(s) Issue(s) aus {args.backlog} entfernt")

    else:
        # Dry-run mode
        if not token or token.strip() in ("", "YOUR_GITHUB_TOKEN", "CHANGEME", "PLACEHOLDER"):
            # No token, can only do dry-run
            print_step(2, "DRY-RUN: Würde GitHub Issues prüfen")
            print_warn("Kein GitHub Token verfügbar - nur lokale Analyse möglich")
            print()
            print("   Um GitHub Issues zu prüfen, füge GITHUB_TOKEN zu config/.env hinzu")
            print("   oder setze die Umgebungsvariable GITHUB_TOKEN.")
            print()
            print("   Beispiel-Inhalt der Backlog-Datei:")
            for issue in issues:
                print(f"   - {issue['title']}")
            print()
            print_warn(
                "DRY-RUN: Keine Änderungen wurden vorgenommen. "
                "Für echte Änderungen: --apply --confirm-remove"
            )
            return 0

        # Try to fetch from GitHub
        try:
            client = GitHubClient(token, owner)
            titles = [issue["title"] for issue in issues]
            github_issues = client.get_issues_by_title(args.repo, titles)
            completed = find_completed_issues(issues, github_issues)
        except SystemExit:
            # GitHub API error, fall back to showing what we would do
            print_step(2, "DRY-RUN: Würde GitHub Issues prüfen")
            print_warn(
                "GitHub API-Aufruf fehlgeschlagen - zeige lokale Backlog-Einträge"
            )
            print()
            print("   Backlog-Einträge in dieser Datei:")
            for issue in issues:
                print(f"   - {issue['title']}")
            print()
            print_warn(
                "DRY-RUN: Keine Änderungen wurden vorgenommen. "
                "Für echte Änderungen: --apply --confirm-remove"
            )
            return 0

        print_step(2, "Abgeschlossene Issues prüfen")
        print_completed_preview(completed)

        if completed:
            print_step(3, "DRY-RUN: Würde folgende Einträge entfernen")
            for issue in completed:
                print(f"   - {issue['title']}")
            print()

        print_warn(
            "DRY-RUN: Keine Änderungen wurden vorgenommen. "
            "Für echte Änderungen: python scripts/cleanup_backlog.py --apply --confirm-remove"
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
