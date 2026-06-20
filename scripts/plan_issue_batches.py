#!/usr/bin/env python3
"""
Plan conflict-aware issue batches without running workers.

Usage:
    python scripts/plan_issue_batches.py --repo ai-issue-solver
    python scripts/plan_issue_batches.py --repo ai-issue-solver --emit-commands --model codex
"""

from __future__ import annotations

import argparse
import re
import shlex
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from solve_issues import GitHubClient, MODEL_CONFIGS, requests  # noqa: E402
from utils import load_env, print_banner, print_err, print_step, print_warn, require_config_value  # noqa: E402


DEFAULT_BATCH_MODEL = "codex"
MODEL_SOURCE_DEFAULT = "default"
MODEL_SOURCE_CLI = "cli --model"


KEYWORD_TOUCHES = (
    (("dashboard", "status_dashboard", "status dashboard"), ("scripts/status_dashboard.py", "tests/test_status_dashboard.py")),
    (("batch", "scheduler", "overnight", "rate limit", "fallback", "worker health"), ("scripts/solve_issues_batch.py", "scripts/run_overnight.py", "tests/test_solve_issues_batch.py", "tests/test_run_overnight.py")),
    (("mistral", "opencode", "provider", "worker", "vibe", "aider"), ("scripts/solve_issues.py", "tests/test_solve_issues.py", "README.md", "config/config.example.env")),
    (("docs", "documentation", "readme", "language", "policy"), ("README.md", "docs/")),
    (("repolens",), ("README.md", "scripts/import_repolens_results.py", "scripts/run_repolens_docker.sh", "tests/")),
    (("github api", "pull request", "post merge", "cleanup"), ("scripts/github_summary.py", "scripts/post_merge_cleanup.py", "tests/")),
)


@dataclass(frozen=True)
class PlannedIssue:
    repo: str
    number: int
    title: str
    body: str
    labels: tuple[str, ...]
    touches: tuple[str, ...]

    @property
    def label(self) -> str:
        return f"#{self.number} - {self.title}"


@dataclass(frozen=True)
class PlannedWave:
    issues: tuple[PlannedIssue, ...]
    touches: tuple[str, ...]


def normalize_label(label: dict | str) -> str:
    if isinstance(label, dict):
        return str(label.get("name") or "")
    return str(label)


def extract_explicit_touches(body: str) -> tuple[str, ...]:
    touches: list[str] = []
    for match in re.finditer(r"(?im)^\s*touches\s*:\s*(.+)$", body):
        value = match.group(1)
        touches.extend(re.findall(r"`([^`]+)`", value))
        touches.extend(part.strip(" `") for part in re.split(r"[,;]", value))
    return unique_paths(touches)


def unique_paths(paths: list[str] | tuple[str, ...]) -> tuple[str, ...]:
    cleaned = []
    for path in paths:
        value = path.strip()
        if not value or value.lower().startswith("touches:"):
            continue
        if value not in cleaned:
            cleaned.append(value)
    return tuple(cleaned)


def infer_issue_touches(title: str, body: str, labels: tuple[str, ...]) -> tuple[str, ...]:
    explicit = list(extract_explicit_touches(body))
    text = " ".join([title, body, *labels]).lower()
    inferred: list[str] = []
    for keywords, paths in KEYWORD_TOUCHES:
        if any(keyword in text for keyword in keywords):
            inferred.extend(paths)
    if not explicit and not inferred:
        inferred.extend(("README.md", "scripts/"))
    return unique_paths([*explicit, *inferred])


def issue_from_github(repo: str, issue: dict) -> PlannedIssue:
    labels = tuple(filter(None, (normalize_label(label) for label in issue.get("labels", []))))
    body = issue.get("body") or ""
    title = issue.get("title") or ""
    return PlannedIssue(
        repo=repo,
        number=int(issue["number"]),
        title=title,
        body=body,
        labels=labels,
        touches=infer_issue_touches(title, body, labels),
    )


def touches_conflict(left: tuple[str, ...], right: tuple[str, ...]) -> tuple[str, ...]:
    conflicts = []
    for a in left:
        for b in right:
            if a == b or a.startswith(b.rstrip("/") + "/") or b.startswith(a.rstrip("/") + "/"):
                conflicts.append(a if len(a) >= len(b) else b)
    return unique_paths(conflicts)


def plan_waves(issues: list[PlannedIssue]) -> list[PlannedWave]:
    waves: list[PlannedWave] = []
    for issue in sorted(issues, key=lambda item: (item.repo, item.number)):
        placed = False
        for index, wave in enumerate(waves):
            if touches_conflict(issue.touches, wave.touches):
                continue
            touches = unique_paths([*wave.touches, *issue.touches])
            waves[index] = PlannedWave((*wave.issues, issue), touches)
            placed = True
            break
        if not placed:
            waves.append(PlannedWave((issue,), issue.touches))
    return waves


def separation_reason(issue: PlannedIssue, previous_waves: list[PlannedWave]) -> str:
    for wave_index, wave in enumerate(previous_waves, start=1):
        conflicts = touches_conflict(issue.touches, wave.touches)
        if conflicts:
            return f"getrennt von Welle {wave_index}: {', '.join(conflicts)}"
    return "keine Ueberschneidung in frueheren Wellen"


def batch_command_for_wave(wave: PlannedWave, model: str, base_branch: str | None) -> str:
    repo = wave.issues[0].repo
    command = ["python", "scripts/solve_issues_batch.py", "--model", model, "--repo", repo]
    if base_branch:
        command.extend(["--base-branch", base_branch])
    for issue in wave.issues:
        command.extend(["--issue", str(issue.number)])
    command.extend(["--workers", str(max(1, len(wave.issues)))])
    return " ".join(shlex.quote(part) for part in command)


def render_model_selection(model: str, model_source: str) -> list[str]:
    if model_source not in {MODEL_SOURCE_DEFAULT, MODEL_SOURCE_CLI}:
        raise ValueError(f"unknown model_source: {model_source}")
    return [
        f"model_default: {DEFAULT_BATCH_MODEL}",
        f"model_effective: {model}",
        f"model_source: {model_source}",
    ]


def render_plan(
    waves: list[PlannedWave],
    emit_commands: bool,
    model: str,
    base_branch: str | None,
    model_source: str,
) -> str:
    lines: list[str] = []
    if emit_commands:
        lines.extend(render_model_selection(model, model_source))
        lines.append("")
    previous: list[PlannedWave] = []
    for index, wave in enumerate(waves, start=1):
        lines.append(f"Welle {index}:")
        for issue in wave.issues:
            lines.append(f"  {issue.label}")
            lines.append(f"    Touches: {', '.join(issue.touches)}")
            if index > 1:
                lines.append(f"    Grund: {separation_reason(issue, previous)}")
        if emit_commands:
            lines.append(f"  Command: {batch_command_for_wave(wave, model, base_branch)}")
        lines.append("")
        previous.append(wave)
    return "\n".join(lines).rstrip()


def load_open_issues(repo: str, label: str) -> list[PlannedIssue]:
    if requests is None:
        raise RuntimeError("Python-Abhaengigkeit fehlt: requests")
    config = load_env()
    token = require_config_value(config, "GITHUB_TOKEN", "GitHub Token")
    owner = require_config_value(config, "GITHUB_USER", "GitHub User")
    client = GitHubClient(token, owner)
    issues = [
        issue_from_github(repo, issue)
        for issue in client.get_open_issues(repo, label=label)
        if "pull_request" not in issue
    ]
    return issues


def main(argv: list[str] | None = None) -> int:
    print_banner("ISSUE-BATCHES PLANEN")
    parser = argparse.ArgumentParser(description="Offene Issues konfliktarm in lokale Bearbeitungswellen planen")
    parser.add_argument("--repo", default="ai-issue-solver", help="GitHub Repo ohne Owner")
    parser.add_argument("--label", default="", help="Optionales Issue-Label fuer die Suche")
    parser.add_argument("--model", choices=list(MODEL_CONFIGS.keys()), help="Modell fuer ausgegebene Batch-Kommandos")
    parser.add_argument("--base-branch", default="develop", help="Basisbranch fuer ausgegebene Batch-Kommandos")
    parser.add_argument("--emit-commands", action="store_true", help="Batch-Kommandos pro Welle ausgeben")
    args = parser.parse_args(argv)

    try:
        issues = load_open_issues(args.repo, args.label)
    except RuntimeError as exc:
        print_err(str(exc))
        return 1

    if not issues:
        print_warn("Keine offenen Issues gefunden")
        return 0

    model = args.model or DEFAULT_BATCH_MODEL
    model_source = MODEL_SOURCE_CLI if args.model else MODEL_SOURCE_DEFAULT
    print_step(1, f"{len(issues)} Issue(s) geladen")
    waves = plan_waves(issues)
    print_step(2, f"{len(waves)} konfliktarme Welle(n)")
    print(render_plan(waves, args.emit_commands, model, args.base_branch, model_source))
    return 0


if __name__ == "__main__":
    sys.exit(main())
