#!/usr/bin/env python3
"""
rework_workflow.py — Strukturiertes Rework-Workflow mit Sub-Issues und separaten PRs.

Dieses Modul implementiert das Rework-Workflow für den AI Issue Solver:
- Erkennung von Rework-Situationen (User-Review-Feedback, fehlgeschlagene Checks,
  unverändertes Verhalten, partielle Implementierung, überschriebener Ansatz)
- Erstellung von GitHub-Issues mit Checklisten für konkrete Rework-Sub-Tasks
- Verlinkung der Sub-Tasks mit dem Original-Issue, PR, Run-Report und Beobachtungen
- Unterstützung für separate PRs pro Sub-Task wenn die Arbeit trennbar ist
- Fallback auf einzelnen PR für tiny, eng gekoppelte Reworks

Verwendung:
    python scripts/rework_workflow.py --rework-of 220 --rework-reason "tests_failed"
    python scripts/rework_workflow.py --from-pr 12 --dry-run
    python scripts/rework_workflow.py --from-run reports/runs/20250612-abc-issue-7 --dry-run
    python scripts/rework_workflow.py --from-note "tests failing after PR #12 merge" --dry-run
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from enum import Enum
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
    raise_for_github_response,
    require_config_value,
)


REWORK_LABELS = {
    "kind/rework": {"color": "d73a4a", "description": "Rework issue for correcting AI-generated PRs"},
    "kind/test-repair": {"color": "1d76db", "description": "Test validation and repair rework"},
    "kind/impl-correction": {"color": "0e8a16", "description": "Implementation correction rework"},
    "kind/docs-cleanup": {"color": "0075ca", "description": "Documentation or backlog cleanup rework"},
    "kind/dashboard-followup": {"color": "006b75", "description": "Dashboard or reporting follow-up rework"},
    "kind/pr-supersede": {"color": "5319e7", "description": "Closing or replacing a superseded PR"},
    "theme/quality": {"color": "006b75", "description": "Code quality and testing"},
    "theme/workflow": {"color": "006b75", "description": "Workflow automation and process"},
    "theme/github": {"color": "006b75", "description": "GitHub API and integration"},
    "state/rework": {"color": "fbca04", "description": "Issue requires rework"},
    "priority/1-critical": {"color": "d93f0b", "description": "Critical priority"},
    "priority/2-high": {"color": "d73a4a", "description": "High priority"},
    "priority/3-medium": {"color": "fbca04", "description": "Medium priority"},
    "agent/solver": {"color": "5319e7", "description": "Implementation and coding work"},
    "agent/reviewer": {"color": "5319e7", "description": "PR review and quality assurance"},
}


class ReworkReason(Enum):
    USER_REVIEW_FEEDBACK = "user_review_feedback"
    FAILED_CHECKS = "failed_checks"
    RISKY_PR_REWORK = "risky_pr_rework"
    BEHAVIOR_UNCHANGED = "behavior_unchanged"
    PARTIAL_IMPLEMENTATION = "partial_implementation"
    SUPERSEDED_APPROACH = "superseded_approach"
    PR_SHOULD_CLOSE = "pr_should_close"
    VALIDATION_FAILED = "validation_failed"
    TESTS_FAILED = "tests_failed"
    UNKNOWN = "unknown"


REWORK_REASON_LABELS = {
    ReworkReason.USER_REVIEW_FEEDBACK: ["kind/rework", "theme/quality"],
    ReworkReason.FAILED_CHECKS: ["kind/rework", "theme/quality"],
    ReworkReason.RISKY_PR_REWORK: ["kind/rework", "theme/quality", "agent/reviewer"],
    ReworkReason.BEHAVIOR_UNCHANGED: ["kind/rework", "theme/quality"],
    ReworkReason.PARTIAL_IMPLEMENTATION: ["kind/impl-correction", "theme/quality"],
    ReworkReason.SUPERSEDED_APPROACH: ["kind/pr-supersede", "theme/workflow"],
    ReworkReason.PR_SHOULD_CLOSE: ["kind/pr-supersede", "theme/workflow"],
    ReworkReason.VALIDATION_FAILED: ["kind/test-repair", "theme/quality"],
    ReworkReason.TESTS_FAILED: ["kind/test-repair", "theme/quality"],
    ReworkReason.UNKNOWN: ["kind/rework", "theme/quality"],
}


@dataclass
class ReworkSubTask:
    id: str
    title: str
    description: str
    task_type: str
    linked_pr: str | None = None
    linked_check: str | None = None
    linked_run_report: str | None = None
    linked_observation: str | None = None


@dataclass
class ReworkIssueSpec:
    original_issue_number: int
    original_issue_title: str
    original_pr_url: str | None = None
    original_pr_number: int | None = None
    rework_reason: ReworkReason = ReworkReason.UNKNOWN
    rework_details: str = ""
    sub_tasks: list[ReworkSubTask] = field(default_factory=list)
    follow_up_issue: int | None = None
    supersedes_pr: int | None = None
    suggested_single_pr: bool = False
    suggested_single_pr_reason: str = ""


REWORK_ISSUE_BODY_TEMPLATE = """## 🤖 Rework Issue (AI Issue Solver)

Dieses Issue wurde automatisch durch das Rework-Workflow erstellt.

---

### 📋 Original Issue

| Feld | Wert |
|------|------|
| **Original Issue** | #{original_issue_number} — {original_issue_title} |
| **Original PR** | {original_pr_url} |
| **Rework-Grund** | `{rework_reason}` |
| **Details** | {rework_details} |

---

### ✅ Rework Checkliste

{sub_tasks_checklist}

---

### 🔗 Verknüpfungen

- Original Issue: #{original_issue_number}
- Original PR: {original_pr_url}
- Supersedes PR: {supersedes_pr}
- Follow-up Issue: #{follow_up_issue}

---

### 📊 Vorschlag

{single_pr_suggestion}

---

*Dieses Issue wurde automatisch durch [ai-issue-solver](https://github.com/SaJaToGu/ai-issue-solver) erstellt.*
"""


SUBTASK_CHECKBOX_TEMPLATE = """- [ ] **{subtask_id}**: {subtask_title}

  {subtask_description}

  {subtask_links}
"""


SUBTASK_LINK_TEMPLATE = """  - Verknüpft mit: {links}"""


def detect_rework_reason_from_text(text: str) -> ReworkReason:
    """Erkennt den Rework-Grund aus einem Text (Review-Feedback, Note, etc.)."""
    text_lower = text.lower()

    risky_pr_keywords = [
        "green but",
        "ci green but",
        "too large",
        "too big",
        "large pr",
        "big pr",
        "risky pr",
        "not mergeable as-is",
        "not merge as-is",
        "nicht mergebar",
        "zu gross",
        "zu groß",
        "zu breit",
        "rohmaterial",
        "needs content review",
        "needs rework before merge",
    ]
    if any(kw in text_lower for kw in risky_pr_keywords):
        return ReworkReason.RISKY_PR_REWORK

    if any(kw in text_lower for kw in ["test", "failed", "failure", "assertion", "pytest", "unittest"]):
        if any(kw in text_lower for kw in ["fail", "error", "broken"]):
            return ReworkReason.TESTS_FAILED

    if any(kw in text_lower for kw in ["unchanged", "no change", "same behavior", "still broken"]):
        return ReworkReason.BEHAVIOR_UNCHANGED

    if any(kw in text_lower for kw in ["partial", "incomplete", "not fully", "missing implementation"]):
        return ReworkReason.PARTIAL_IMPLEMENTATION

    if any(kw in text_lower for kw in ["superseded", "replaced", "better approach", "close pr"]):
        return ReworkReason.SUPERSEDED_APPROACH

    if any(kw in text_lower for kw in ["review", "feedback", "comment", "suggestion", "requested changes"]):
        return ReworkReason.USER_REVIEW_FEEDBACK

    if any(kw in text_lower for kw in ["check", "ci", "lint", "validation"]):
        return ReworkReason.FAILED_CHECKS

    if any(kw in text_lower for kw in ["close", "close pr", "close this"]):
        return ReworkReason.PR_SHOULD_CLOSE

    return ReworkReason.UNKNOWN


def parse_checklist_from_body(body: str) -> list[ReworkSubTask]:
    """Parst Rework-Sub-Tasks aus einer Issue-Body-Checkliste."""
    tasks = []
    lines = body.splitlines()
    current_task = None

    for line in lines:
        line = line.rstrip()
        if not line:
            continue

        if line.startswith("- [ ]") or line.startswith("- [x]"):
            checkbox_match = re.match(r"- \[.\] \*\*([^*]+):\*\* (.+)", line)
            if checkbox_match:
                if current_task:
                    tasks.append(current_task)

                task_id = checkbox_match.group(1).strip()
                task_title = checkbox_match.group(2).strip()
                current_task = ReworkSubTask(
                    id=task_id,
                    title=task_title,
                    description="",
                    task_type="unknown",
                )

        elif current_task and line.startswith("  "):
            current_task.description += line.strip() + "\n"

    if current_task:
        tasks.append(current_task)

    return tasks


def format_checklist_items(sub_tasks: list[ReworkSubTask]) -> str:
    """Formatiert Sub-Tasks als Markdown-Checkliste."""
    lines = []
    for task in sub_tasks:
        links = []
        if task.linked_pr:
            links.append(f"PR #{task.linked_pr}")
        if task.linked_check:
            links.append(f"Check: {task.linked_check}")
        if task.linked_run_report:
            links.append(f"Run: {task.linked_run_report}")
        if task.linked_observation:
            links.append(f"Observation: {task.linked_observation}")

        link_text = ""
        if links:
            link_text = SUBTASK_LINK_TEMPLATE.format(links=", ".join(links))

        lines.append(SUBTASK_CHECKBOX_TEMPLATE.format(
            subtask_id=task.id,
            subtask_title=task.title,
            subtask_description=task.description.strip() if task.description else "_Keine Details_",
            subtask_links=link_text,
        ))
    return "\n".join(lines)


def format_single_pr_suggestion(spec: ReworkIssueSpec) -> str:
    """Formatiert den Vorschlag für einzelnen oder mehreren PRs."""
    if spec.suggested_single_pr:
        return (
            f"**Empfohlen: Einzelner PR** — {spec.suggested_single_pr_reason}\n\n"
            "Begründung: Die Rework-Aufgaben sind eng gekoppelt und einfacher als "
            "eine kombinierte Änderung zu reviewen."
        )

    task_types = [t.task_type for t in spec.sub_tasks]
    separable_types = {"validation/test repair", "documentation or backlog cleanup",
                      "dashboard/reporting follow-up", "closing or replacing a superseded PR"}

    separable = sum(1 for tt in task_types if tt in separable_types)
    total = len(task_types)

    if separable > 0 and separable == total:
        return (
            "**Empfohlen: Separate PRs pro Sub-Task**\n\n"
            f"Jeder der {total} Sub-Tasks kann unabhängig implementiert und gemergt werden:\n"
            + "\n".join(f"  - {t.id}: {t.title}" for t in spec.sub_tasks)
        )

    return (
        "**Empfohlen: Separate PRs wenn sinnvoll**\n\n"
        "Falls die Sub-Tasks unabhängig voneinander implementiert werden können, "
        "erstelle separate PRs für bessere Reviewbarkeit."
    )


def build_rework_issue_body(spec: ReworkIssueSpec) -> str:
    """Baut den Body für ein Rework-Issue."""
    checklist = format_checklist_items(spec.sub_tasks)
    single_pr_suggestion = format_single_pr_suggestion(spec)

    return REWORK_ISSUE_BODY_TEMPLATE.format(
        original_issue_number=spec.original_issue_number,
        original_issue_title=spec.original_issue_title,
        original_pr_url=spec.original_pr_url or "_Kein PR verknüpft_",
        rework_reason=spec.rework_reason.value,
        rework_details=spec.rework_details or "_Keine Details_",
        sub_tasks_checklist=checklist,
        supersedes_pr=f"#{spec.supersedes_pr}" if spec.supersedes_pr else "_Keiner_",
        follow_up_issue=spec.follow_up_issue or "_Keines_",
        single_pr_suggestion=single_pr_suggestion,
    )


def should_use_single_pr(sub_tasks: list[ReworkSubTask]) -> tuple[bool, str]:
    """Prüft ob die Rework-Aufgaben als einzelner PR gemacht werden sollten."""
    if not sub_tasks:
        return True, "Keine Sub-Tasks definiert"

    total_lines = sum(len(t.description.splitlines()) for t in sub_tasks)
    task_types = [t.task_type for t in sub_tasks]
    if "review and scope reduction" in task_types:
        return False, ""

    if total_lines <= 10 and len(sub_tasks) <= 2:
        return True, "Wenig Code-Änderungen und maximal 2 Sub-Tasks"

    coupled_types = {"implementation correction", "validation/test repair"}
    if all(tt in coupled_types for tt in task_types) and len(sub_tasks) <= 2:
        return True, "Eng gekoppelte Implementierungs- oder Test-Korrekturen"

    return False, ""


def generate_sub_tasks_from_reason(
    reason: ReworkReason,
    original_issue_number: int,
    original_pr_number: int | None = None,
) -> list[ReworkSubTask]:
    """Generiert Sub-Tasks basierend auf dem Rework-Grund."""
    tasks = []

    if reason in (ReworkReason.TESTS_FAILED, ReworkReason.VALIDATION_FAILED):
        tasks.append(ReworkSubTask(
            id="test-repair-1",
            title="Tests validieren und reparieren",
            description=f"Fehlgeschlagene Tests nach dem Merge von Issue #{original_issue_number} analysieren und reparieren.",
            task_type="validation/test repair",
            linked_pr=str(original_pr_number) if original_pr_number else None,
        ))
        tasks.append(ReworkSubTask(
            id="impl-verify-1",
            title="Implementierung verifizieren",
            description="Sicherstellen, dass die Implementierung die ursprünglichen Anforderungen erfüllt.",
            task_type="implementation correction",
        ))

    elif reason == ReworkReason.USER_REVIEW_FEEDBACK:
        tasks.append(ReworkSubTask(
            id="review-address-1",
            title="Review-Feedback adressieren",
            description=f"Die bei der PR-Review #{original_pr_number} gesammelten Anmerkungen umsetzen.",
            task_type="implementation correction",
            linked_pr=str(original_pr_number) if original_pr_number else None,
        ))

    elif reason == ReworkReason.RISKY_PR_REWORK:
        tasks.append(ReworkSubTask(
            id="review-scope-1",
            title="PR-Scope prüfen und begrenzen",
            description=(
                "Den vorhandenen PR auf Diff-Größe, betroffene Dateien, "
                "Issue-Scope und riskante Nebeneffekte prüfen. Nur notwendige "
                "Änderungen behalten; breite oder unklare Teile entfernen oder "
                "in separate Rework-Tasks auslagern."
            ),
            task_type="review and scope reduction",
            linked_pr=str(original_pr_number) if original_pr_number else None,
        ))
        tasks.append(ReworkSubTask(
            id="validation-tighten-1",
            title="Gezielte Validierung nach Scope-Kürzung",
            description=(
                "Fokussierte Tests für den verbleibenden Scope ausführen und "
                "im PR-Kommentar dokumentieren. Keine neuen Features hinzufügen."
            ),
            task_type="validation/test repair",
            linked_pr=str(original_pr_number) if original_pr_number else None,
        ))

    elif reason == ReworkReason.BEHAVIOR_UNCHANGED:
        tasks.append(ReworkSubTask(
            id="behavior-analyze-1",
            title="Verhaltensänderung analysieren",
            description="Analysieren warum das Verhalten unverändert scheint und die Ursache beheben.",
            task_type="implementation correction",
        ))
        tasks.append(ReworkSubTask(
            id="test-verify-1",
            title="Test-basierte Verifikation",
            description="Tests hinzufügen oder aktualisieren die das erwartete Verhalten validieren.",
            task_type="validation/test repair",
        ))

    elif reason == ReworkReason.PARTIAL_IMPLEMENTATION:
        tasks.append(ReworkSubTask(
            id="impl-complete-1",
            title="Implementierung vervollständigen",
            description=f"Die partielle Implementierung für Issue #{original_issue_number} vollständig umsetzen.",
            task_type="implementation correction",
        ))

    elif reason == ReworkReason.SUPERSEDED_APPROACH:
        tasks.append(ReworkSubTask(
            id="pr-close-1",
            title="Überschriebenen PR schließen",
            description=f"PR #{original_pr_number} schließen, da ein besserer Ansatz verfolgt wird.",
            task_type="closing or replacing a superseded PR",
            linked_pr=str(original_pr_number) if original_pr_number else None,
        ))
        tasks.append(ReworkSubTask(
            id="impl-new-approach-1",
            title="Neuen Ansatz implementieren",
            description="Den besseren Ansatz für das ursprüngliche Problem implementieren.",
            task_type="implementation correction",
        ))

    elif reason == ReworkReason.PR_SHOULD_CLOSE:
        tasks.append(ReworkSubTask(
            id="pr-close-1",
            title="PR schließen",
            description=f"PR #{original_pr_number} schließen ohne weitere Änderungen.",
            task_type="closing or replacing a superseded PR",
            linked_pr=str(original_pr_number) if original_pr_number else None,
        ))

    else:
        tasks.append(ReworkSubTask(
            id="rework-1",
            title="Rework analysieren und durchführen",
            description=f"Allgemeiner Rework für Issue #{original_issue_number}.",
            task_type="unknown",
        ))

    return tasks


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

    def ensure_label(self, repo: str, name: str, dry_run: bool = False) -> None:
        """Legt ein Label an, falls es noch nicht existiert."""
        if dry_run:
            return
        info = REWORK_LABELS.get(name, {"color": "ededed", "description": name})
        url = f"{self.BASE}/repos/{self.owner}/{repo}/labels"
        resp = self.session.get(f"{url}/{name}")
        if resp.status_code == 200:
            return
        if resp.status_code != 404:
            raise_for_github_response(resp, f"Label prüfen: {name}")
        created = self.session.post(url, json={
            "name": name,
            "color": info["color"],
            "description": info["description"],
        })
        raise_for_github_response(created, f"Label erstellen: {name}")

    def get_issue(self, repo: str, number: int) -> dict | None:
        """Lädt ein einzelnes Issue."""
        try:
            resp = self.session.get(f"{self.BASE}/repos/{self.owner}/{repo}/issues/{number}")
        except requests.RequestException as exc:
            print_err(f"Issue laden fehlgeschlagen: {exc}")
            return None
        if resp.status_code == 404:
            return None
        raise_for_github_response(resp, f"Issue laden: {repo}#{number}")
        return resp.json()

    def get_pull_request(self, repo: str, number: int) -> dict | None:
        """Lädt eine einzelne Pull Request."""
        try:
            resp = self.session.get(f"{self.BASE}/repos/{self.owner}/{repo}/pulls/{number}")
        except requests.RequestException as exc:
            print_err(f"PR laden fehlgeschlagen: {exc}")
            return None
        if resp.status_code == 404:
            return None
        raise_for_github_response(resp, f"PR laden: {repo}#{number}")
        return resp.json()

    def get_pull_requests_for_issue(self, repo: str, issue_number: int) -> list[dict]:
        """Lädt alle PRs die mit einem Issue verknüpft sind."""
        try:
            resp = self.session.get(
                f"{self.BASE}/repos/{self.owner}/{repo}/pulls",
                params={"state": "all", "per_page": 100},
            )
        except requests.RequestException as exc:
            print_err(f"PRs laden fehlgeschlagen: {exc}")
            return []
        raise_for_github_response(resp, f"PRs laden: {repo}")
        all_prs = resp.json()
        return [pr for pr in all_prs if pull_request_links_issue(pr, issue_number)]

    def create_issue(self, repo: str, title: str, body: str,
                    labels: list[str], dry_run: bool = False) -> dict | None:
        """Erstellt ein GitHub Issue."""
        if dry_run:
            print(f"      [DRY-RUN] Würde Issue erstellen: '{title}'")
            return {"html_url": "https://github.com/dry-run-issue", "number": "DRY-RUN"}

        url = f"{self.BASE}/repos/{self.owner}/{repo}/issues"
        resp = self.session.post(url, json={
            "title": title,
            "body": body,
            "labels": labels,
        })
        if resp.status_code == 201:
            return resp.json()
        raise_for_github_response(resp, f"Issue erstellen: {title}")

    def update_issue(self, repo: str, number: int, body: str,
                    labels: list[str], dry_run: bool = False) -> dict | None:
        """Aktualisiert ein bestehendes GitHub Issue."""
        if dry_run:
            print(f"      [DRY-RUN] Würde Issue aktualisieren: #{number}")
            return {"html_url": "https://github.com/dry-run-issue", "number": "DRY-RUN"}

        url = f"{self.BASE}/repos/{self.owner}/{repo}/issues/{number}"
        resp = self.session.patch(url, json={
            "body": body,
            "labels": labels,
        })
        if resp.status_code == 200:
            return resp.json()
        raise_for_github_response(resp, f"Issue aktualisieren: {repo}#{number}")

    def close_issue(self, repo: str, number: int, dry_run: bool = False) -> None:
        """Schließt ein GitHub Issue."""
        if dry_run:
            print(f"      [DRY-RUN] Würde Issue schließen: #{number}")
            return
        url = f"{self.BASE}/repos/{self.owner}/{repo}/issues/{number}"
        resp = self.session.patch(url, json={"state": "closed"})
        raise_for_github_response(resp, f"Issue schließen: {repo}#{number}")


def load_run_report_metadata(run_report_path: Path) -> dict | None:
    """Lädt Metadaten aus einem Run-Report."""
    metadata_file = run_report_path / "metadata.json"
    if not metadata_file.exists():
        return None
    try:
        with open(metadata_file, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def detect_rework_reason_from_run_report(run_report_path: Path) -> tuple[ReworkReason, str]:
    """Erkennt den Rework-Grund aus einem Run-Report."""
    metadata = load_run_report_metadata(run_report_path)
    if not metadata:
        return ReworkReason.UNKNOWN, "Keine Metadaten im Run-Report gefunden"

    status = metadata.get("status", "")
    test_result = metadata.get("provider_scorecard", {}).get("test_result", "")
    run_outcome = metadata.get("run_outcome", {})

    if status == "validation_failed":
        return ReworkReason.VALIDATION_FAILED, f"Status: {status}"

    if status in {"pr_failed", "pr_failed_from_existing_branch"}:
        if test_result and "fail" in test_result.lower():
            return ReworkReason.TESTS_FAILED, f"Status: {status}, Test result: {test_result}"
        return ReworkReason.FAILED_CHECKS, f"Status: {status}"

    failure_class = run_outcome.get("failure_class", "")
    if failure_class == "validation_failure":
        return ReworkReason.VALIDATION_FAILED, f"Failure class: {failure_class}"
    if failure_class == "model_failure":
        return ReworkReason.PARTIAL_IMPLEMENTATION, f"Model failed with failure class: {failure_class}"
    if failure_class == "noop" and metadata.get("provider_scorecard", {}).get("no_change"):
        return ReworkReason.BEHAVIOR_UNCHANGED, "No changes detected"

    return ReworkReason.UNKNOWN, f"Status: {status}"


def build_rework_spec_from_pr(
    client: GitHubClient,
    repo: str,
    pr_number: int,
    rework_reason: ReworkReason | None = None,
    rework_details: str = "",
) -> ReworkIssueSpec | None:
    """Baut ein ReworkIssueSpec aus einer PR-Nummer."""
    pr = client.get_pull_request(repo, pr_number)
    if not pr:
        print_err(f"PR #{pr_number} nicht gefunden in {repo}")
        return None

    issue_url = pr.get("issue_url", "")
    issue_number = 0
    if issue_url:
        match = re.search(r"/issues/(\d+)$", issue_url)
        if match:
            issue_number = int(match.group(1))

    if not issue_number:
        issue_number = pr.get("body", "").split("#")[-1].split()[0]
        try:
            issue_number = int(issue_number)
        except (ValueError, IndexError):
            issue_number = 0

    if not issue_number:
        print_err(f"Kein Issue für PR #{pr_number} gefunden")
        return None

    issue = client.get_issue(repo, issue_number)
    issue_title = issue.get("title", f"Issue #{issue_number}") if issue else f"Issue #{issue_number}"

    reason = rework_reason or ReworkReason.USER_REVIEW_FEEDBACK
    sub_tasks = generate_sub_tasks_from_reason(reason, issue_number, pr_number)
    single_pr, single_pr_reason = should_use_single_pr(sub_tasks)

    return ReworkIssueSpec(
        original_issue_number=issue_number,
        original_issue_title=issue_title,
        original_pr_url=pr.get("html_url", ""),
        original_pr_number=pr_number,
        rework_reason=reason,
        rework_details=rework_details,
        sub_tasks=sub_tasks,
        supersedes_pr=pr_number,
        suggested_single_pr=single_pr,
        suggested_single_pr_reason=single_pr_reason,
    )


def build_rework_spec_from_run_report(
    run_report_path: Path,
    rework_reason: ReworkReason | None = None,
    rework_details: str = "",
) -> ReworkIssueSpec | None:
    """Baut ein ReworkIssueSpec aus einem Run-Report-Pfad."""
    metadata = load_run_report_metadata(run_report_path)
    if not metadata:
        print_err(f"Keine Metadaten im Run-Report gefunden: {run_report_path}")
        return None

    repo = metadata.get("repo", "")
    issue_number = metadata.get("issue_number", 0)
    issue_title = metadata.get("issue_title", f"Issue #{issue_number}")
    pr_url = metadata.get("pr_url", "")

    pr_number = None
    if pr_url:
        match = re.search(r"/pull/(\d+)$", pr_url)
        if match:
            pr_number = int(match.group(1))

    reason = rework_reason or detect_rework_reason_from_run_report(run_report_path)[0]
    sub_tasks = generate_sub_tasks_from_reason(reason, issue_number, pr_number)
    single_pr, single_pr_reason = should_use_single_pr(sub_tasks)

    return ReworkIssueSpec(
        original_issue_number=issue_number,
        original_issue_title=issue_title,
        original_pr_url=pr_url,
        original_pr_number=pr_number,
        rework_reason=reason,
        rework_details=rework_details,
        sub_tasks=sub_tasks,
        suggested_single_pr=single_pr,
        suggested_single_pr_reason=single_pr_reason,
    )


def build_rework_spec_from_note(
    note: str,
    original_issue_number: int,
    original_issue_title: str = "",
    original_pr_url: str | None = None,
    original_pr_number: int | None = None,
) -> ReworkIssueSpec:
    """Baut ein ReworkIssueSpec aus einer User-Notiz."""
    reason = detect_rework_reason_from_text(note)
    sub_tasks = generate_sub_tasks_from_reason(reason, original_issue_number, original_pr_number)
    single_pr, single_pr_reason = should_use_single_pr(sub_tasks)

    return ReworkIssueSpec(
        original_issue_number=original_issue_number,
        original_issue_title=original_issue_title or f"Issue #{original_issue_number}",
        original_pr_url=original_pr_url,
        original_pr_number=original_pr_number,
        rework_reason=reason,
        rework_details=note,
        sub_tasks=sub_tasks,
        suggested_single_pr=single_pr,
        suggested_single_pr_reason=single_pr_reason,
    )


def extract_issue_number_from_text(text: str) -> int | None:
    """Extract the first GitHub-style issue reference from free text."""
    issue_patterns = [
        r"(?:issue|for|für|fuer|zu)\s+#(\d+)",
        r"#(\d+)\s+(?:issue|ticket)",
    ]
    for pattern in issue_patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return int(match.group(1))

    match = re.search(r"#(\d+)", text)
    if not match:
        return None
    return int(match.group(1))


def unique_labels(labels: list[str]) -> list[str]:
    """Preserve label order while removing duplicates."""
    seen = set()
    unique = []
    for label in labels:
        if label in seen:
            continue
        unique.append(label)
        seen.add(label)
    return unique


def pull_request_links_issue(pr: dict, issue_number: int) -> bool:
    """Return whether a GitHub PR payload references the given issue number."""
    if pr.get("issue_number") == issue_number:
        return True
    text = "\n".join(str(pr.get(field) or "") for field in ("body", "title", "html_url", "issue_url"))
    patterns = (
        rf"(?:^|\s)#\s*{issue_number}\b",
        rf"/issues/{issue_number}\b",
        rf"(?:refs|fixes|closes)\s+#\s*{issue_number}\b",
    )
    return any(re.search(pattern, text, re.IGNORECASE) for pattern in patterns)


def needs_github_client(args, dry_run: bool) -> bool:
    """Return whether this invocation needs GitHub API access before create/update."""
    if not dry_run:
        return True
    return bool(args.from_pr)


def validate_source_args(args) -> str | None:
    """Validate source combinations that argparse cannot express directly."""
    sources = [bool(args.from_pr), bool(args.from_run), bool(args.from_note)]
    if sum(sources) > 1:
        return "Nutze nur eine Quelle: --from-pr, --from-run oder --from-note."
    if not any(sources) and args.rework_of is None:
        return "--rework-of ist erforderlich, wenn keine Quelle angegeben ist."
    if args.from_note and args.rework_of is None and extract_issue_number_from_text(args.from_note) is None:
        return "--from-note braucht --rework-of oder eine Issue-Referenz wie #123 im Text."
    return None


def print_rework_issue_preview(repo: str, spec: ReworkIssueSpec, labels: list[str]) -> None:
    """Gibt im Dry-Run alle entscheidenden Rework-Issue-Daten prüfbar aus."""
    print("      [DRY-RUN] Würde Rework-Issue erstellen:")
    print(f"         Repo:   {repo}")
    print(f"         Titel:  [Rework] #{spec.original_issue_number} — {spec.original_issue_title}")
    print(f"         Labels: {', '.join(labels)}")
    print(f"         Rework-Reason: {spec.rework_reason.value}")
    print(f"         Sub-Tasks: {len(spec.sub_tasks)}")
    for task in spec.sub_tasks:
        print(f"           - [{task.id}] {task.title}")
    if spec.suggested_single_pr:
        print(f"         Single-PR-Empfehlung: {spec.suggested_single_pr_reason}")


def main() -> int:
    print_banner("REWORK WORKFLOW")

    parser = argparse.ArgumentParser(
        description="Strukturiertes Rework-Workflow mit Sub-Issues und separaten PRs"
    )
    parser.add_argument(
        "--rework-of",
        type=int,
        help="Original Issue-Nummer",
    )
    parser.add_argument(
        "--rework-reason",
        choices=[r.value for r in ReworkReason],
        help="Rework-Grund",
    )
    parser.add_argument(
        "--from-pr",
        type=int,
        help="PR-Nummer für Rework-Detektion",
    )
    parser.add_argument(
        "--from-run",
        type=str,
        help="Run-Report-Pfad für Rework-Detektion",
    )
    parser.add_argument(
        "--from-note",
        type=str,
        help="User-Review-Notiz für Rework-Detektion",
    )
    parser.add_argument(
        "--repo",
        default="ai-issue-solver",
        help="Repository ohne Owner",
    )
    parser.add_argument(
        "--owner",
        help="GitHub Owner, sonst GITHUB_USER aus config/.env",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Nur anzeigen, nichts erstellen",
    )
    parser.add_argument(
        "--confirm-create",
        action="store_true",
        help="Bestätigt bewusst, dass echte GitHub-Issues erstellt werden dürfen",
    )
    parser.add_argument(
        "--update-existing",
        type=int,
        metavar="ISSUE_NUMBER",
        help="Bestehendes Rework-Issue aktualisieren statt neu erstellen",
    )
    parser.add_argument(
        "--rework-details",
        type=str,
        default="",
        help="Zusätzliche Details zum Rework",
    )
    args = parser.parse_args()

    dry_run = not args.confirm_create
    if args.dry_run:
        dry_run = True

    validation_error = validate_source_args(args)
    if validation_error:
        parser.error(validation_error)

    if requests is None and needs_github_client(args, dry_run):
        print_err("Python-Abhängigkeit fehlt: requests")
        print("   → Installieren mit: pip install -r requirements.txt")
        return 1

    client = None
    if needs_github_client(args, dry_run):
        config = load_env()
        owner = args.owner or config.get("GITHUB_USER")
        token = require_config_value(config, "GITHUB_TOKEN", "GitHub Token")

        if not owner:
            print_err("GitHub User fehlt oder ist noch ein Platzhalter")
            print("   Erwartet: GITHUB_USER=<dein GitHub Username> oder --owner <username>")
            return 1

        client = GitHubClient(token, owner)

    spec: ReworkIssueSpec | None = None

    if args.from_pr:
        if client is None:
            print_err("--from-pr benötigt GitHub-Zugriff")
            return 1
        spec = build_rework_spec_from_pr(
            client, args.repo, args.from_pr,
            ReworkReason(args.rework_reason) if args.rework_reason else None,
            args.rework_details,
        )
    elif args.from_run:
        spec = build_rework_spec_from_run_report(
            Path(args.from_run),
            ReworkReason(args.rework_reason) if args.rework_reason else None,
            args.rework_details,
        )
    elif args.from_note:
        issue_number = args.rework_of or extract_issue_number_from_text(args.from_note)
        spec = build_rework_spec_from_note(
            args.from_note,
            original_issue_number=issue_number,
        )
    else:
        reason = ReworkReason(args.rework_reason) if args.rework_reason else ReworkReason.UNKNOWN
        sub_tasks = generate_sub_tasks_from_reason(reason, args.rework_of)
        single_pr, single_pr_reason = should_use_single_pr(sub_tasks)
        spec = ReworkIssueSpec(
            original_issue_number=args.rework_of,
            original_issue_title=f"Issue #{args.rework_of}",
            rework_reason=reason,
            rework_details=args.rework_details,
            sub_tasks=sub_tasks,
            suggested_single_pr=single_pr,
            suggested_single_pr_reason=single_pr_reason,
        )

    if not spec:
        print_err("Rework-Issue konnte nicht erstellt werden")
        return 1

    issue_title = f"[Rework] #{spec.original_issue_number} — {spec.original_issue_title}"
    body = build_rework_issue_body(spec)

    reason_labels = REWORK_REASON_LABELS.get(spec.rework_reason, [])
    labels = unique_labels(reason_labels + ["kind/rework", "state/rework", "agent/solver"])

    if dry_run:
        print_rework_issue_preview(args.repo, spec, labels)
        return 0

    print_step(1, "Rework-Issue erstellen")

    if client is None:
        print_err("GitHub-Client fehlt")
        return 1

    if args.update_existing:
        print(f"   Aktualisiere bestehendes Issue #{args.update_existing}")
        result = client.update_issue(args.repo, args.update_existing, body, labels)
    else:
        for label in labels:
            client.ensure_label(args.repo, label)
        result = client.create_issue(args.repo, issue_title, body, labels)

    if result:
        print_ok(f"Rework-Issue erstellt: {result.get('html_url', '')}")
        print(f"   Original Issue: #{spec.original_issue_number}")
        print(f"   Rework-Reason: {spec.rework_reason.value}")
        print(f"   Sub-Tasks: {len(spec.sub_tasks)}")
        if spec.suggested_single_pr:
            print(f"   Single-PR empfohlen: {spec.suggested_single_pr_reason}")
        else:
            print("   Separate PRs pro Sub-Task empfohlen")
    else:
        print_err("Rework-Issue konnte nicht erstellt werden")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
