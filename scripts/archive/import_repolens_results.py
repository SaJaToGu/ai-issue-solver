#!/usr/bin/env python3
"""
Import RepoLens Markdown reports as GitHub issues.

Usage:
    python scripts/import_repolens_results.py --report-dir reports/repolens --repo ai-issue-solver
    python scripts/import_repolens_results.py --report-dir reports/repolens --repo ai-issue-solver --apply --confirm-create
"""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
from dataclasses import dataclass
from pathlib import Path

try:
    import requests
except ModuleNotFoundError:
    requests = None

sys.path.insert(0, str(Path(__file__).parent))
from utils import (  # noqa: E402
    load_env,
    print_banner,
    print_err,
    print_ok,
    print_step,
    print_warn,
    raise_for_github_response,
    require_config_value,
)


SEVERITIES = ("critical", "high", "medium", "low")
DOMAINS = ("security", "performance", "quality", "architecture", "maintainability", "docs")
REPOLENS_MARKER_RE = re.compile(r"<!--\s*repolens:([a-f0-9]{16})\s*-->")

LABELS = {
    "repolens": {"color": "5319e7", "description": "Imported from RepoLens local reports"},
    "security": {"color": "d93f0b", "description": "Security finding"},
    "performance": {"color": "fbca04", "description": "Performance finding"},
    "quality": {"color": "0e8a16", "description": "Code quality finding"},
    "architecture": {"color": "1d76db", "description": "Architecture finding"},
    "maintainability": {"color": "c5def5", "description": "Maintainability finding"},
    "docs": {"color": "0075ca", "description": "Documentation finding"},
    "severity:critical": {"color": "b60205", "description": "Critical RepoLens severity"},
    "severity:high": {"color": "ee0701", "description": "High RepoLens severity"},
    "severity:medium": {"color": "ff9900", "description": "Medium RepoLens severity"},
    "severity:low": {"color": "0e8a16", "description": "Low RepoLens severity"},
}


@dataclass(frozen=True)
class RepoLensFinding:
    title: str
    severity: str
    domain: str
    source_file: Path
    affected_files: tuple[str, ...]
    evidence: str

    @property
    def key(self) -> str:
        source = f"{self.source_file.as_posix()}|{self.title}|{self.severity}|{self.domain}"
        return hashlib.sha256(source.encode("utf-8")).hexdigest()[:16]

    @property
    def issue_title(self) -> str:
        return f"[RepoLens] {self.severity.title()}: {self.title}"

    @property
    def labels(self) -> list[str]:
        labels = ["repolens", f"severity:{self.severity}"]
        if self.domain:
            labels.append(self.domain)
        return labels


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
        info = LABELS.get(name, {"color": "ededed", "description": name})
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

    def list_open_issues(self, repo: str) -> list[dict]:
        issues_url = f"{self.BASE}/repos/{self.owner}/{repo}/issues"
        resp = self.session.get(issues_url, params={"state": "open", "per_page": 100})
        raise_for_github_response(resp, "Offene Issues prüfen")
        return [item for item in resp.json() if "pull_request" not in item]

    def create_issue(self, repo: str, title: str, body: str, labels: list[str]) -> str:
        issues_url = f"{self.BASE}/repos/{self.owner}/{repo}/issues"
        resp = self.session.post(issues_url, json={"title": title, "body": body, "labels": labels})
        raise_for_github_response(resp, f"Issue erstellen: {title}")
        return resp.json()["html_url"]


def normalize_severity(text: str, default: str = "medium") -> str:
    lowered = text.lower()
    for severity in SEVERITIES:
        if re.search(rf"\b{re.escape(severity)}\b", lowered):
            return severity
    return default


def infer_domain(text: str, path: Path) -> str:
    lowered = f"{path.as_posix()} {text}".lower()
    aliases = {
        "security": ("security", "secret", "token", "auth", "credential", "vulnerability"),
        "performance": ("performance", "slow", "latency", "n+1", "query", "cache"),
        "architecture": ("architecture", "coupling", "boundary", "module", "design"),
        "maintainability": ("maintainability", "complexity", "duplication", "readability"),
        "docs": ("docs", "documentation", "readme"),
        "quality": ("quality", "test", "lint", "typing", "error handling"),
    }
    for domain, words in aliases.items():
        if any(word in lowered for word in words):
            return domain
    return "quality"


def clean_title(title: str) -> str:
    title = re.sub(r"^\s*\[[^\]]+\]\s*", "", title)
    title = re.sub(r"^\s*(critical|high|medium|low)\s*[:/-]\s*", "", title, flags=re.I)
    title = re.sub(r"^\s*(security|performance|quality|architecture|maintainability|docs)\s*[:/-]\s*", "", title, flags=re.I)
    title = re.sub(r"\s+", " ", title).strip(" -:\t")
    return title or "RepoLens finding"


def extract_affected_files(text: str) -> tuple[str, ...]:
    files: list[str] = []
    for line in text.splitlines():
        if re.search(r"\b(affected files?|files?|path)\b\s*:", line, re.I):
            files.extend(re.findall(r"`([^`]+)`", line))
            after_colon = line.split(":", 1)[1]
            files.extend(part.strip(" `") for part in re.split(r"[,;]", after_colon))
        files.extend(re.findall(r"`([^`\n]+\.[A-Za-z0-9_]+)`", line))
    cleaned = []
    for item in files:
        value = item.strip()
        if value and value not in cleaned:
            cleaned.append(value)
    return tuple(cleaned)


def evidence_excerpt(text: str, limit: int = 1200) -> str:
    text = text.strip()
    if not text:
        return "No evidence details were included in the RepoLens report."
    lines = []
    capture_next = False
    for line in text.splitlines():
        if re.match(r"\s*(evidence|impact|recommendation|details?)\s*:", line, re.I):
            lines.append(line.strip())
            capture_next = True
            continue
        if capture_next and (line.startswith(" ") or line.startswith("-") or line.startswith("*")):
            lines.append(line.rstrip())
            continue
        capture_next = False
    excerpt = "\n".join(lines).strip() or text
    if len(excerpt) > limit:
        return excerpt[: limit - 3].rstrip() + "..."
    return excerpt


def iter_heading_blocks(text: str) -> list[tuple[str, str]]:
    matches = list(re.finditer(r"(?m)^(#{1,6})\s+(.+?)\s*$", text))
    blocks: list[tuple[str, str]] = []
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        blocks.append((match.group(2).strip(), text[start:end].strip()))
    return blocks


def parse_heading_findings(path: Path, text: str) -> list[RepoLensFinding]:
    findings = []
    for heading, body in iter_heading_blocks(text):
        combined = f"{heading}\n{body}"
        has_heading_severity = any(re.search(rf"\b{severity}\b", heading, re.I) for severity in SEVERITIES)
        has_body_severity_field = re.search(r"(?m)^\s*severity\s*:", body, re.I)
        has_severity = has_heading_severity or has_body_severity_field
        has_finding_signal = re.search(r"\b(evidence|impact|recommendation|affected files?|files?)\s*:", body, re.I)
        if not (has_severity and has_finding_signal):
            continue
        title = clean_title(heading)
        findings.append(
            RepoLensFinding(
                title=title,
                severity=normalize_severity(combined),
                domain=infer_domain(combined, path),
                source_file=path,
                affected_files=extract_affected_files(body),
                evidence=evidence_excerpt(body),
            )
        )
    return findings


def parse_bullet_findings(path: Path, text: str) -> list[RepoLensFinding]:
    findings = []
    lines = text.splitlines()
    bullet_re = re.compile(r"^\s*[-*]\s+(?:\[(?P<bracket>[^\]]+)\]|(?P<prefix>critical|high|medium|low)\s*[:/-])\s*(?P<title>.+)$", re.I)
    for index, line in enumerate(lines):
        match = bullet_re.match(line)
        if not match:
            continue
        following = []
        for next_line in lines[index + 1 :]:
            if bullet_re.match(next_line) or re.match(r"^#{1,6}\s+", next_line):
                break
            if next_line.strip():
                following.append(next_line)
        body = "\n".join(following)
        combined = f"{line}\n{body}"
        findings.append(
            RepoLensFinding(
                title=clean_title(match.group("title")),
                severity=normalize_severity(match.group("bracket") or match.group("prefix") or line),
                domain=infer_domain(combined, path),
                source_file=path,
                affected_files=extract_affected_files(combined),
                evidence=evidence_excerpt(body),
            )
        )
    return findings


def parse_report_file(path: Path) -> list[RepoLensFinding]:
    text = path.read_text(encoding="utf-8")
    findings = parse_heading_findings(path, text) + parse_bullet_findings(path, text)
    unique: dict[str, RepoLensFinding] = {}
    for finding in findings:
        unique.setdefault(finding.key, finding)
    return list(unique.values())


def collect_findings(report_dir: Path) -> list[RepoLensFinding]:
    findings = []
    for path in sorted(report_dir.rglob("*.md")):
        findings.extend(parse_report_file(path))
    return findings


def build_issue_body(finding: RepoLensFinding, report_dir: Path) -> str:
    source = finding.source_file
    try:
        source = finding.source_file.relative_to(report_dir)
    except ValueError:
        pass
    affected = "\n".join(f"- `{item}`" for item in finding.affected_files) or "- Not specified"
    return f"""<!-- repolens:{finding.key} -->
## RepoLens Finding

{finding.evidence}

### Metadata

| Field | Value |
| --- | --- |
| Source | `{source.as_posix()}` |
| Severity | `{finding.severity}` |
| Domain/Lens | `{finding.domain}` |

### Affected Files

{affected}

---
Imported from a local RepoLens Markdown report by `scripts/import_repolens_results.py`.
"""


def existing_repolens_keys(open_issues: list[dict]) -> set[str]:
    keys = set()
    for issue in open_issues:
        body = issue.get("body") or ""
        match = REPOLENS_MARKER_RE.search(body)
        if match:
            keys.add(match.group(1))
    return keys


def print_issue_preview(repo: str, finding: RepoLensFinding, body: str) -> None:
    print("   [DRY-RUN] Würde RepoLens-Issue erstellen:")
    print(f"      Repo:   {repo}")
    print(f"      Titel:  {finding.issue_title}")
    print(f"      Labels: {', '.join(finding.labels)}")
    print(f"      Quelle: {finding.source_file}")
    print("      Body:")
    for line in body.splitlines():
        print(f"        {line}" if line else "        ")


def import_findings(
    findings: list[RepoLensFinding],
    repo: str,
    report_dir: Path,
    apply: bool,
    client: GitHubClient | None = None,
) -> tuple[int, int]:
    open_issues = client.list_open_issues(repo) if apply and client else []
    open_titles = {issue.get("title") for issue in open_issues}
    open_keys = existing_repolens_keys(open_issues)
    created = 0
    skipped = 0

    for finding in findings:
        body = build_issue_body(finding, report_dir)
        if finding.issue_title in open_titles or finding.key in open_keys:
            print_warn(f"Bereits vorhanden: {finding.issue_title}")
            skipped += 1
            continue

        if not apply:
            print_issue_preview(repo, finding, body)
            created += 1
            continue

        if client is None:
            raise RuntimeError("GitHubClient fehlt für echte Issue-Erstellung")
        for label in finding.labels:
            client.ensure_label(repo, label)
        url = client.create_issue(repo, finding.issue_title, body, finding.labels)
        print_ok(f"{finding.issue_title} -> {url}")
        created += 1

    return created, skipped


def main(argv: list[str] | None = None) -> int:
    print_banner("REPOLENS-REPORTS IMPORTIEREN")

    parser = argparse.ArgumentParser(description="RepoLens Markdown-Reports als GitHub Issues importieren")
    parser.add_argument("--report-dir", default="reports/repolens", help="Verzeichnis mit RepoLens Markdown-Reports")
    parser.add_argument("--repo", default="ai-issue-solver", help="Ziel-Repo ohne Owner")
    parser.add_argument("--owner", help="GitHub Owner, sonst GITHUB_USER aus config/.env")
    parser.add_argument("--apply", action="store_true", help="Echte GitHub-Issues erstellen")
    parser.add_argument("--confirm-create", action="store_true", help="Bestätigt echte GitHub-Issue-Erstellung")
    args = parser.parse_args(argv)

    real_create = args.apply and args.confirm_create
    if args.apply != args.confirm_create:
        parser.error("Echte Erstellung braucht beide Flags: --apply --confirm-create")
    if requests is None and real_create:
        print_err("Python-Abhängigkeit fehlt: requests")
        print("   → Installieren mit: pip install -r requirements.txt")
        return 1

    report_dir = Path(args.report_dir)
    if not report_dir.exists():
        print_err(f"RepoLens-Report-Verzeichnis nicht gefunden: {args.report_dir}")
        return 1

    findings = collect_findings(report_dir)
    if not findings:
        print_warn("Keine RepoLens-Findings in Markdown-Reports gefunden")
        return 0

    print_step(1, f"{len(findings)} RepoLens-Finding(s) gefunden")
    client = None
    if not real_create:
        print_warn("DRY-RUN: Keine echten GitHub-Issues werden erstellt.")
    else:
        config = load_env()
        owner = args.owner or config.get("GITHUB_USER")
        token = require_config_value(config, "GITHUB_TOKEN", "GitHub Token")
        if not owner:
            print_err("GitHub User fehlt oder ist noch ein Platzhalter")
            print("   Erwartet: GITHUB_USER=<dein GitHub Username> oder --owner <username>")
            return 1
        client = GitHubClient(token, owner)

    print_step(2, f"Import nach {args.repo}")
    created, skipped = import_findings(findings, args.repo, report_dir, real_create, client)
    print_step(3, "Fertig")
    label = "Vorschau" if not real_create else "Erstellt"
    print(f"   {label}: {created}")
    print(f"   Übersprungen: {skipped}")
    if not real_create:
        print("   → Echte Issues: python scripts/import_repolens_results.py --apply --confirm-create")
    return 0


if __name__ == "__main__":
    sys.exit(main())
