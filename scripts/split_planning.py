#!/usr/bin/env python3
"""
split_planning.py — Mandatory split-planning step before broad solver runs.

Analysiert ein breites Parent-Issue, schlaegt enge Child-Issues vor und
ordnet sie in konfliktarme Ausführungswellen. Der Output ist ein
strukturierter Plan, der als Issue-Kommentar oder als Child-Issues
hinterlegt werden kann.

Usage:
    python scripts/split_planning.py --repo ai-issue-solver --issue 387
    python scripts/split_planning.py --repo ai-issue-solver --issue 387 --dry-run
    python scripts/split_planning.py --repo ai-issue-solver --issue 387 --emit-command
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent))
from utils import (
    load_env,
    print_banner,
    print_err,
    print_step,
    print_warn,
    require_config_value,
)


# — Schwellwerte, ab wann ein Issue als "broad" gilt
BROAD_TOUCH_THRESHOLD = 3          # minimal betroffene Dateigruppen
BROAD_WORD_THRESHOLD = 300         # minimale Body-Laenge in Woertern
BROAD_ASTERISK_THRESHOLD = 5       # minimale Bullet-Items im Body


# — Hinweise, die auf ein breites Issue hindeuten
BROAD_KEYWORDS = (
    "multiple", "verschiedene", "mehrere", "mehrere Bereiche",
    "sowohl", "als auch", "scope creep", "zusaetzlich",
    "follow-up", "umfasst", "beinhaltet", "einzeln",
)

BROAD_LABELS = (
    "enhancement",
    "epic",
    "feature",
)


# — Schluesselwoerter fuer die Child-Issue-Erkennung im Body
CHILD_MARKERS = (
    "- [ ]", "* [ ]", "###", "##",
    "Aufgabe", "Task", "Todo", "TODO",
    "Teilaufgabe", "Unterpunkt", "child issue",
)


@dataclass(frozen=True)
class ChildIssue:
    number: int | None          # None bis zur Erstellung
    title: str
    body: str
    labels: tuple[str, ...]
    touches: tuple[str, ...]
    recommended_model: str
    execution_order: int

    @property
    def label(self) -> str:
        return self.title


@dataclass(frozen=True)
class ExecutionWave:
    issues: tuple[ChildIssue, ...]
    model: str
    reason: str


@dataclass(frozen=True)
class SplitPlan:
    parent_repo: str
    parent_number: int
    parent_title: str
    is_broad: bool
    breadth_reasons: tuple[str, ...]
    child_issues: tuple[ChildIssue, ...]
    execution_waves: tuple[ExecutionWave, ...]
    created_at: str

    @property
    def total_children(self) -> int:
        return len(self.child_issues)

    @property
    def total_waves(self) -> int:
        return len(self.execution_waves)


# ─────────────────────────────────────────────────────────────
# Analyseschritte
# ─────────────────────────────────────────────────────────────

def determine_breadth(title: str, body: str, labels: tuple[str, ...]) -> tuple[bool, tuple[str, ...]]:
    """Ermittelt, ob ein Issue als 'broad' gilt und begruendet die Entscheidung."""
    reasons: list[str] = []

    word_count = len(body.split())
    if word_count > BROAD_WORD_THRESHOLD:
        reasons.append(f"Body-Laenge ({word_count} Woerter > {BROAD_WORD_THRESHOLD})")

    asterisk_count = body.count("- ") + body.count("* ")
    if asterisk_count > BROAD_ASTERISK_THRESHOLD:
        reasons.append(f"Bullet-Items ({asterisk_count} > {BROAD_ASTERISK_THRESHOLD})")

    combined = (title + " " + body).lower()
    found_keywords = [kw for kw in BROAD_KEYWORDS if kw.lower() in combined]
    if found_keywords:
        reasons.append(f"Breiten-Hinweise: {', '.join(found_keywords)}")

    found_labels = [lb for lb in labels if lb.lower() in BROAD_LABELS]
    if found_labels:
        reasons.append(f"Breiten-Labels: {', '.join(found_labels)}")

    section_count = len(re.findall(r"^#{1,6}\s+", body, re.MULTILINE))
    if section_count > 2:
        reasons.append(f"Markdown-Sektionen ({section_count} > 2)")

    is_broad = len(reasons) >= 2 or (
        len(reasons) >= 1 and (word_count > BROAD_WORD_THRESHOLD * 2 or asterisk_count > BROAD_ASTERISK_THRESHOLD * 2)
    )

    return is_broad, tuple(reasons)


def extract_sections(body: str) -> list[tuple[str, str]]:
    """Extrahiert ueberschriftengetrennte Sektionen aus dem Issue-Body."""
    sections: list[tuple[str, str]] = []
    lines = body.split("\n")
    current_heading = "Einleitung"
    current_body: list[str] = []

    for line in lines:
        heading_match = re.match(r"^#{1,3}\s+(.+)$", line)
        if heading_match:
            if current_body:
                sections.append((current_heading, "\n".join(current_body).strip()))
            current_heading = heading_match.group(1).strip()
            current_body = []
        else:
            current_body.append(line)

    if current_body:
        sections.append((current_heading, "\n".join(current_body).strip()))

    return sections


def infer_issue_touches(text: str) -> tuple[str, ...]:
    """Ermittelt betroffene Dateien aus dem Text."""
    touches: list[str] = []

    code_blocks = re.findall(r"`([^`]+)`", text)
    for match in code_blocks:
        match = match.strip()
        if "/" in match and not match.startswith("http"):
            touches.append(match)

    file_refs = re.findall(r"(?<!/)(?:scripts|tests|docs|config|src|workers)/[\w./-]+\.[\w]+", text)
    touches.extend(file_refs)

    seen: list[str] = []
    for touch in touches:
        if touch not in seen:
            seen.append(touch)
    return tuple(seen)


def propose_child_issues(title: str, body: str, labels: tuple[str, ...]) -> tuple[ChildIssue, ...]:
    """Erzeugt Child-Issue-Vorschlaege aus einem breiten Parent-Issue."""
    children: list[ChildIssue] = []
    used_numbers: set[int] = set()
    next_number = 1

    sections = extract_sections(body)

    for section_title, section_body in sections:
        if not section_body.strip():
            continue

        child_title = f"{title} — {section_title}"

        touches = infer_issue_touches(section_body)
        recommended = recommend_model(section_body, labels, touches)

        child = ChildIssue(
            number=None,
            title=child_title,
            body=section_body,
            labels=labels,
            touches=touches,
            recommended_model=recommended,
            execution_order=next_number,
        )
        children.append(child)
        next_number += 1

    if not children:
        children.append(
            ChildIssue(
                number=None,
                title=title,
                body=body,
                labels=labels,
                touches=(),
                recommended_model="opencode",
                execution_order=1,
            )
        )

    return tuple(children)


def recommend_model(body: str, labels: tuple[str, ...], touches: tuple[str, ...]) -> str:
    """Empfiehlt ein Worker-Modell basierend auf Kontext und betroffenen Dateien."""
    combined = body.lower()
    if any(t.startswith("docs/") or t.startswith("README") for t in touches):
        return "opencode"
    if any(t.startswith("config/") for t in touches):
        return "opencode"
    if "test" in combined:
        return "opencode"
    if "architecture" in combined or "design" in combined:
        return "opencode"
    return "opencode"


def _common_dir(path_a: str, path_b: str) -> str | None:
    """Ermittelt das gemeinsame Elternverzeichnis zweier Pfade, falls vorhanden."""
    parts_a = Path(path_a).parts
    parts_b = Path(path_b).parts
    common: list[str] = []
    for pa, pb in zip(parts_a, parts_b):
        if pa == pb:
            common.append(pa)
        else:
            break
    if common and len(common) < min(len(parts_a), len(parts_b)):
        return "/".join(common)
    return None


def detect_conflicts(children: tuple[ChildIssue, ...]) -> list[tuple[int, int, str]]:
    """Ermittelt Konflikte zwischen Child-Issues (gleiche Dateien oder Verzeichnisse)."""
    conflicts: list[tuple[int, int, str]] = []
    for i, a in enumerate(children):
        for j, b in enumerate(children):
            if i >= j:
                continue
            for touch_a in a.touches:
                for touch_b in b.touches:
                    if touch_a == touch_b:
                        conflicts.append((i, j, f"gleiche Datei: {touch_a}"))
                    elif touch_a.startswith(touch_b.rstrip("/") + "/") or touch_b.startswith(touch_a.rstrip("/") + "/"):
                        conflicts.append((i, j, f"gleiches Verzeichnis: {touch_a} vs {touch_b}"))
                    else:
                        common = _common_dir(touch_a, touch_b)
                        if common:
                            conflicts.append((i, j, f"gleicher Elternpfad: {common}"))
    return conflicts


def plan_execution_waves(children: tuple[ChildIssue, ...]) -> tuple[ExecutionWave, ...]:
    """Ordnet Child-Issues in konfliktarme Ausfuehrungswellen."""
    waves: list[ExecutionWave] = []
    conflicts = detect_conflicts(children)
    blocked: set[int] = set()
    used: set[int] = set()
    wave_index = 0

    remaining = list(range(len(children)))

    while remaining:
        wave_indices: list[int] = []
        for idx in remaining:
            if idx in blocked:
                continue
            if any(
                (i == idx and j in used) or (j == idx and i in used)
                for i, j, _ in conflicts
            ):
                continue
            wave_indices.append(idx)

        if not wave_indices:
            wave_indices = [remaining[0]]

        wave_children = tuple(children[idx] for idx in wave_indices)

        used.update(wave_indices)

        if wave_index == 0:
            reason = "Basis: unabhaengige Child-Issues ohne Ueberschneidung"
        else:
            reasons = []
            for idx in wave_indices:
                for i, j, conflict in conflicts:
                    if idx == i and j in used:
                        reasons.append(conflict)
                    elif idx == j and i in used:
                        reasons.append(conflict)
            reason = "; ".join(reasons) if reasons else "getrennt wegen Konflikten in vorheriger Welle"

        wave_model = wave_children[0].recommended_model
        waves.append(
            ExecutionWave(
                issues=wave_children,
                model=wave_model,
                reason=reason,
            )
        )
        wave_index += 1

        remaining = [idx for idx in remaining if idx not in used]
        blocked = {idx for idx in remaining if any(
            (i == idx and j in used) or (j == idx and i in used)
            for i, j, _ in conflicts
        )}

    return tuple(waves)


def create_split_plan(
    repo: str,
    issue_number: int,
    issue_title: str,
    issue_body: str,
    issue_labels: tuple[str, ...],
) -> SplitPlan:
    """Erstellt einen vollstaendigen Split-Plan aus einem Issue."""
    is_broad, breadth_reasons = determine_breadth(issue_title, issue_body, issue_labels)
    child_issues = propose_child_issues(issue_title, issue_body, issue_labels) if is_broad else ()
    execution_waves = plan_execution_waves(child_issues) if is_broad else ()

    return SplitPlan(
        parent_repo=repo,
        parent_number=issue_number,
        parent_title=issue_title,
        is_broad=is_broad,
        breadth_reasons=breadth_reasons,
        child_issues=child_issues,
        execution_waves=execution_waves,
        created_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    )


# ─────────────────────────────────────────────────────────────
# Ausgabe
# ─────────────────────────────────────────────────────────────

def render_plan(plan: SplitPlan, emit_command: bool = False) -> str:
    """Erzeugt einen strukturierten Plan als Text."""
    lines: list[str] = []
    lines.append("═" * 60)
    lines.append(f"  AUFTEILUNGSPLAN (Split Planning)")
    lines.append("═" * 60)
    lines.append(f"")
    lines.append(f"  Parent: #{plan.parent_number} — {plan.parent_title}")
    lines.append(f"  Repo:   {plan.parent_repo}")
    lines.append(f"  Datum:  {plan.created_at}")
    lines.append(f"")

    if not plan.is_broad:
        lines.append(f"  ✅ Issue ist NICHT broad — kein Split notwendig.")
        lines.append(f"     Direkte Uebergabe an den Solver.")
        if emit_command:
            lines.append(f"")
            lines.append(f"  Command:")
            lines.append(f"    python scripts/solve_issues.py \\")
            lines.append(f"      --repo {plan.parent_repo} \\")
            lines.append(f"      --issue {plan.parent_number}")
        lines.append(f"")
        return "\n".join(lines)

    lines.append(f"  ⚠️  BROAD ISSUE erkannt — Split erforderlich")
    lines.append(f"  Gruende:")
    for reason in plan.breadth_reasons:
        lines.append(f"    - {reason}")
    lines.append(f"")

    lines.append(f"  ── Child-Issues ({plan.total_children}) ──")
    for child in plan.child_issues:
        model_info = f"[{child.recommended_model}]"
        lines.append(f"    Rang {child.execution_order}: {child.title} {model_info}")
        if child.touches:
            lines.append(f"      Touches: {', '.join(child.touches)}")
    lines.append(f"")

    lines.append(f"  ── Ausführungswellen ({plan.total_waves}) ──")
    for wave_index, wave in enumerate(plan.execution_waves, start=1):
        lines.append(f"    Welle {wave_index} [{wave.model}]:")
        lines.append(f"      Grund: {wave.reason}")
        for child in wave.issues:
            lines.append(f"      - {child.title}")
        if emit_command:
            issue_flags = " \\\n      ".join(
                f"--issue <CHILD_{child.execution_order}>"
                for child in wave.issues
            )
            lines.append(f"      Command:")
            lines.append(f"        python scripts/solve_issues_batch.py \\")
            lines.append(f"          --model {wave.model} \\")
            lines.append(f"          --repo {plan.parent_repo} \\")
            lines.append(f"          {issue_flags}")
        lines.append(f"")

    if emit_command and plan.child_issues:
        lines.append(f"  ── Erstellungs-Kommandos fuer Child-Issues ──")
        for child in plan.child_issues:
            lines.append(f"    # {child.title}")
            touches_line = f"Touches: `{'`, `'.join(child.touches)}`" if child.touches else ""
            lines.append(f"    gh issue create \\")
            lines.append(f"      --repo {plan.parent_repo} \\")
            lines.append(f"      --title \"{child.title}\" \\")
            lines.append(f"      --label \"child-issue,{','.join(child.labels) if child.labels else 'ai-generated'}\" \\")
            lines.append(f"      --body \"Parent: #{plan.parent_number}{chr(10)}Modell: {child.recommended_model}{chr(10)}{touches_line}\"")
            lines.append(f"")

    lines.append(f"  ── Empfehlung ──")
    lines.append(f"    Uebergebe NUR enge Child-Issues an Minimax Code oder andere Worker.")
    lines.append(f"    Kein Worker darf das breite Parent-Issue (#{plan.parent_number}) direkt erhalten.")
    lines.append(f"")

    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────
# GitHub-Integration (optional, falls requests verfuegbar)
# ─────────────────────────────────────────────────────────────

try:
    import requests
except ModuleNotFoundError:
    requests = None


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

    def get_issue(self, repo: str, number: int) -> dict | None:
        try:
            resp = self.session.get(f"{self.BASE}/repos/{self.owner}/{repo}/issues/{number}")
        except requests.RequestException:
            return None
        if resp.status_code == 404:
            return None
        return resp.json()

    def post_comment(self, repo: str, number: int, body: str) -> bool:
        try:
            resp = self.session.post(
                f"{self.BASE}/repos/{self.owner}/{repo}/issues/{number}/comments",
                json={"body": body},
                timeout=30,
            )
            return resp.status_code == 201
        except requests.RequestException:
            return False


# ─────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────

def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Split-Planning: broad Parent-Issues in enge Child-Issues aufteilen"
    )
    parser.add_argument("--repo", default="ai-issue-solver", help="GitHub Repo ohne Owner")
    parser.add_argument("--issue", type=int, required=True, help="Parent-Issue-Nummer")
    parser.add_argument("--dry-run", action="store_true", help="Nur anzeigen, nichts veraendern")
    parser.add_argument(
        "--emit-command",
        action="store_true",
        help="Worker-Kommandos und ggf. gh-issue-create-Kommandos ausgeben",
    )
    parser.add_argument(
        "--emit-comment",
        action="store_true",
        help="Split-Plan als Issue-Kommentar posten (benoetigt GitHub-Token)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    print_banner("SPLIT PLANNING")
    args = parse_args(argv)

    config = load_env()
    token = require_config_value(config, "GITHUB_TOKEN", "GitHub Token")
    user = require_config_value(config, "GITHUB_USER", "GitHub User")

    client = GitHubClient(token, user)

    print_step(1, f"Lade Issue #{args.issue} von {user}/{args.repo}")
    issue = client.get_issue(args.repo, args.issue)

    if not issue:
        print_err(f"Issue #{args.issue} nicht gefunden in {user}/{args.repo}")
        return 1

    if "pull_request" in issue:
        print_err(f"#{args.issue} ist ein Pull Request, kein Issue")
        return 1

    title = issue.get("title") or "(kein Titel)"
    body = issue.get("body") or ""
    labels = tuple(
        label.get("name", "") if isinstance(label, dict) else str(label)
        for label in issue.get("labels", [])
    )

    print(f"   Titel: {title}")
    print(f"   Labels: {', '.join(labels)}")
    print()

    print_step(2, "Analysiere Issue-Breite")
    plan = create_split_plan(args.repo, args.issue, title, body, labels)

    print()
    print(render_plan(plan, emit_command=args.emit_command))

    if plan.is_broad and args.emit_comment and not args.dry_run:
        print_step(3, "Poste Split-Plan als Issue-Kommentar")
        comment_body = render_plan(plan, emit_command=False)
        success = client.post_comment(args.repo, args.issue, comment_body)
        if success:
            print("   ✅ Kommentar erfolgreich gepostet")
        else:
            print_warn("Kommentar konnte nicht gepostet werden")

    if plan.is_broad:
        print_warn("Dieses Issue ist BROAD — NICHT direkt an einen Worker uebergeben!")
        print(f"   Erstelle zuerst Child-Issues oder folge dem Plan oben.")
        if not args.emit_command:
            print(f"   Wiederholen mit --emit-command fuer konkrete Kommandos.")
        print()

    return 0 if plan.is_broad else 0


if __name__ == "__main__":
    sys.exit(main())
