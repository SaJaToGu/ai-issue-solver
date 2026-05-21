#!/usr/bin/env python3
"""
solve_issues.py — Schritt 3: Issues mit KI lösen (Morpheus-Methode)
Morpheus-Style AI Issue Solver — github.com/SaJaToGu

Holt offene GitHub Issues, übergibt sie an Codex oder `aider` mit dem
gewählten KI-Modell (Codex / Claude / OpenAI / Ollama), erstellt
einen Branch und einen Commit mit der Lösung.

Verwendung:
    python scripts/solve_issues.py --model codex
    python scripts/solve_issues.py --model claude
    python scripts/solve_issues.py --model openai
    python scripts/solve_issues.py --model ollama --model-name deepseek-coder:6.7b
    python scripts/solve_issues.py --model claude --repo BedBoxDrawerRole
    python scripts/solve_issues.py --model claude --issue 3
    python scripts/solve_issues.py --model claude --dry-run
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.parse import quote

try:
    import requests
except ModuleNotFoundError:
    requests = None

sys.path.insert(0, str(Path(__file__).parent))
from utils import (
    is_placeholder_value,
    load_env,
    print_banner,
    print_err,
    print_step,
    print_warn,
    handle_github_request_error,
    raise_for_github_response,
    require_config_value,
)


# ─────────────────────────────────────────────────────────────
# Modell-Konfigurationen
# ─────────────────────────────────────────────────────────────

MODEL_CONFIGS = {
    "codex": {
        "display_name": "Codex CLI",
        "env_key": None,
        "env_var": None,
    },
    "claude": {
        "display_name": "Anthropic Claude (claude-sonnet-4-20250514)",
        "aider_flags": [
            "--model", "claude-sonnet-4-20250514",
        ],
        "env_key": "ANTHROPIC_API_KEY",
        "env_var": "ANTHROPIC_API_KEY",
    },
    "openai": {
        "display_name": "OpenAI GPT-4o",
        "aider_flags": [
            "--model", "gpt-4o",
        ],
        "env_key": "OPENAI_API_KEY",
        "env_var": "OPENAI_API_KEY",
    },
    "ollama": {
        "display_name": "Ollama (lokal)",
        "aider_flags": [
            "--model", "ollama/{model_name}",
        ],
        "env_key": None,
        "env_var": None,
        "default_model_name": "deepseek-coder:6.7b",
    },
}

WORKER_OUTPUT_TAIL_LINES = 25
WORKER_OUTPUT_TAIL_CHARS = 4000
RUN_REPORTS_ROOT = Path("reports") / "runs"
GIT_SUMMARY_MAX_STATUS_LINES = 20
GIT_SUMMARY_MAX_STAT_LINES = 12
GIT_SUMMARY_MAX_DIFF_LINES = 18
CODEX_RATE_LIMIT_RETRY_LIMIT = 3
COMMON_REPO_FILES = {
    ".dockerignore",
    ".env.example",
    ".gitignore",
    "CHANGELOG.md",
    "Dockerfile",
    "LICENSE",
    "LICENSE.md",
    "LICENSE.txt",
    "Makefile",
    "README.md",
    "compose.yml",
    "docker-compose.yml",
    "package.json",
    "pyproject.toml",
    "requirements.txt",
    "setup.cfg",
    "setup.py",
    "tsconfig.json",
}
PATH_CANDIDATE_RE = re.compile(
    r"(?<![\w:/.-])(?:[A-Za-z0-9_.-]+/)+[A-Za-z0-9_.@+~-]+(?:\.[A-Za-z0-9_.+-]+)?"
)
CODE_SPAN_RE = re.compile(r"`([^`\n]+)`")
CODEX_RATE_LIMIT_RESET_RE = re.compile(
    r"rate limit will be reset on\s+(.+?)(?:\.|\n|$)",
    re.IGNORECASE,
)
CODEX_RATE_LIMIT_MESSAGE_RE = re.compile(
    r"(?:reached the codex message limit|rate limit will be reset)",
    re.IGNORECASE,
)
WORKER_LIVE_OUTPUT_RE = re.compile(
    r"("
    r"\b(task|aufgabe|plan|planung|planning|reasoning|reasoning summary|"
    r"summary|zusammenfassung|warn(?:ing)?|warnung|error|fehler|failed|failure|"
    r"done|fertig|completed|abgeschlossen|result|ergebnis|final|rate limit|"
    r"retry|blocked|blockiert|commit|test|tests)\b"
    r"|^\s*(?:===|##|###|\[.*\])"
    r")",
    re.IGNORECASE,
)
WORKER_NOISY_OUTPUT_RE = re.compile(
    r"("
    r"^\s*(?:diff --git|index [0-9a-f]+\.\.|@@ |[+-]{3}\s|[+-](?!\s*(?:warning|error|failed)\b))"
    r"|^\s*(?:apply_patch|cat >|sed -n|python - <<|npm |pip |git diff|git status)"
    r")",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class WorkerRunResult:
    returncode: int
    output: str


@dataclass(frozen=True)
class WorkerAssessment:
    should_continue: bool
    has_changes: bool
    reason: str


@dataclass(frozen=True)
class RunReport:
    path: Path
    repo: str
    issue_number: int
    branch: str
    model: str


@dataclass(frozen=True)
class CodexRateLimit:
    reset_at: datetime | None
    reset_text: str | None


@dataclass(frozen=True)
class PullRequestState:
    number: int | None
    html_url: str
    state: str
    merged: bool


@dataclass(frozen=True)
class BranchRecoveryPlan:
    action: str
    branch: str
    message: str
    pull_request: PullRequestState | None = None
    found_branches: tuple[str, ...] = ()
    found_pull_requests: tuple[tuple[str, PullRequestState], ...] = ()


# Prompt-Vorlage für Codex/aider
AIDER_PROMPT_TEMPLATE = """Löse das folgende GitHub Issue in diesem Repository.

=== ISSUE #{number}: {title} ===

{body}

=== AUFGABE ===
Analysiere das Problem und implementiere eine saubere, vollständige Lösung.
Halte dich an die bestehende Code-Struktur und Konventionen des Projekts.
Kommentiere deine Änderungen auf Deutsch wenn sinnvoll.
Erstelle oder verbessere Dateien direkt (README, LICENSE, .gitignore, etc.).
Erstelle keinen Commit, pushe nichts und öffne keinen Pull Request. Das übernimmt das Wrapper-Script nach deiner Änderung.

Wenn du Dateien erstellst, achte auf:
- Vollständigkeit (keine Platzhalter wie "TODO" oder "...")
- Korrekte Syntax für die jeweilige Sprache/Format
- Sinnvolle Inhalte die zum Projekt passen
"""


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

    def get_repos(self) -> list:
        try:
            resp = self.session.get(
                f"{self.BASE}/users/{self.owner}/repos",
                params={"type": "owner", "per_page": 100}
            )
        except requests.RequestException as exc:
            handle_github_request_error(exc, "Repos laden")
        raise_for_github_response(resp, "Repos laden")
        return resp.json()

    def get_repo(self, repo: str) -> dict | None:
        try:
            resp = self.session.get(f"{self.BASE}/repos/{self.owner}/{repo}")
        except requests.RequestException as exc:
            handle_github_request_error(exc, f"Repo laden: {repo}")
        if resp.status_code == 404:
            return None
        raise_for_github_response(resp, f"Repo laden: {repo}")
        return resp.json()

    def get_default_branch(self, repo: str) -> str | None:
        repo_info = self.get_repo(repo)
        if not repo_info:
            return None
        return repo_info.get("default_branch")

    def branch_exists(self, repo: str, branch: str) -> bool:
        encoded_branch = quote(branch, safe="")
        try:
            resp = self.session.get(
                f"{self.BASE}/repos/{self.owner}/{repo}/branches/{encoded_branch}"
            )
        except requests.RequestException as exc:
            handle_github_request_error(exc, f"Branch prüfen: {repo}/{branch}")
        if resp.status_code == 404:
            return False
        raise_for_github_response(resp, f"Branch prüfen: {repo}/{branch}")
        return True

    def get_issue_branches(self, repo: str, issue_number: int) -> list[str]:
        branch_prefix = f"ai/fix-issue-{issue_number}"
        branches = []
        page = 1
        while True:
            try:
                resp = self.session.get(
                    f"{self.BASE}/repos/{self.owner}/{repo}/branches",
                    params={"per_page": 100, "page": page},
                )
            except requests.RequestException as exc:
                handle_github_request_error(exc, f"Issue-Branches prüfen: {repo}#{issue_number}")
            if resp.status_code == 404:
                return []
            raise_for_github_response(resp, f"Issue-Branches prüfen: {repo}#{issue_number}")
            page_branches = resp.json()
            for branch in page_branches:
                name = branch.get("name", "")
                if name == branch_prefix or name.startswith(f"{branch_prefix}-"):
                    branches.append(name)
            if len(page_branches) < 100:
                break
            page += 1
        return sorted(set(branches))

    def get_pull_requests_for_branch(self, repo: str, branch: str,
                                     state: str = "all") -> list[PullRequestState]:
        try:
            resp = self.session.get(
                f"{self.BASE}/repos/{self.owner}/{repo}/pulls",
                params={
                    "state": state,
                    "head": f"{self.owner}:{branch}",
                    "per_page": 100,
                },
            )
        except requests.RequestException as exc:
            handle_github_request_error(exc, f"PRs prüfen: {repo}/{branch}")
        if resp.status_code == 404:
            return []
        raise_for_github_response(resp, f"PRs prüfen: {repo}/{branch}")
        pull_requests = []
        for pr in resp.json():
            pull_requests.append(
                PullRequestState(
                    number=pr.get("number"),
                    html_url=pr.get("html_url", ""),
                    state=pr.get("state", ""),
                    merged=bool(pr.get("merged_at")),
                )
            )
        return pull_requests

    def resolve_base_branch(self, repo: str, requested_base: str | None = None) -> str | None:
        """Ermittelt den Zielbranch und nutzt ohne Vorgabe den GitHub-Default-Branch."""
        if requested_base:
            if self.branch_exists(repo, requested_base):
                return requested_base

            default_branch = self.get_default_branch(repo)
            if default_branch and default_branch != requested_base and self.branch_exists(repo, default_branch):
                print_warn(
                    f"Base-Branch '{requested_base}' existiert nicht; nutze Default-Branch '{default_branch}'"
                )
                return default_branch

            return requested_base

        default_branch = self.get_default_branch(repo)
        if default_branch:
            return default_branch

        for candidate in ("main", "master", "develop"):
            if self.branch_exists(repo, candidate):
                return candidate
        return None

    def get_open_issues(self, repo: str, label: str = "ai-generated") -> list:
        try:
            resp = self.session.get(
                f"{self.BASE}/repos/{self.owner}/{repo}/issues",
                params={"state": "open", "labels": label, "per_page": 100}
            )
        except requests.RequestException as exc:
            handle_github_request_error(exc, f"Issues laden: {repo}")
        if resp.status_code == 404:
            return []
        raise_for_github_response(resp, f"Issues laden: {repo}")
        return [i for i in resp.json() if "pull_request" not in i]

    def get_single_issue(self, repo: str, number: int) -> dict | None:
        try:
            resp = self.session.get(f"{self.BASE}/repos/{self.owner}/{repo}/issues/{number}")
        except requests.RequestException as exc:
            handle_github_request_error(exc, f"Issue laden: {repo}#{number}")
        if resp.status_code == 404:
            return None
        raise_for_github_response(resp, f"Issue laden: {repo}#{number}")
        return resp.json()

    def close_issue_with_comment(self, repo: str, number: int,
                                  comment: str, dry_run: bool = False):
        if dry_run:
            return
        # Kommentar hinzufügen
        self.session.post(
            f"{self.BASE}/repos/{self.owner}/{repo}/issues/{number}/comments",
            json={"body": comment}
        )
        # Issue schließen
        self.session.patch(
            f"{self.BASE}/repos/{self.owner}/{repo}/issues/{number}",
            json={"state": "closed"}
        )

    def create_pull_request(self, repo: str, title: str, body: str,
                             head: str, base: str | None = None,
                             dry_run: bool = False) -> dict | None:
        resolved_base = self.resolve_base_branch(repo, base)
        if not resolved_base:
            print_warn("PR konnte nicht erstellt werden: Kein gültiger Base-Branch gefunden")
            return None

        if dry_run:
            print(f"      [DRY-RUN] Würde PR erstellen: '{title}' gegen '{resolved_base}'")
            return {"html_url": "https://github.com/dry-run-pr"}

        resp = self.session.post(
            f"{self.BASE}/repos/{self.owner}/{repo}/pulls",
            json={"title": title, "body": body, "head": head, "base": resolved_base}
        )
        if resp.status_code == 201:
            return resp.json()
        print_warn(f"PR konnte nicht erstellt werden: {resp.status_code}")
        return None


# ─────────────────────────────────────────────────────────────
# Aider Integration
# ─────────────────────────────────────────────────────────────

def check_aider_installed() -> bool:
    return shutil.which("aider") is not None


def find_codex_executable() -> str | None:
    """Find the Codex CLI installed by the desktop app or available on PATH."""
    candidates = [
        shutil.which("codex"),
        "/Applications/Codex.app/Contents/Resources/codex",
    ]
    return next((path for path in candidates if path and Path(path).exists()), None)


def clean_path_candidate(candidate: str) -> str:
    return candidate.strip().strip(" \t\r\n'\"“”‘’.,;:()[]{}<>")


def is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def looks_like_repo_file(path: str) -> bool:
    basename = Path(path).name
    return (
        path in COMMON_REPO_FILES
        or basename in COMMON_REPO_FILES
        or "." in basename
    )


def collect_issue_path_candidates(text: str) -> list[str]:
    """Sammelt plausible Datei-/Pfadangaben aus Issue-Text ohne URLs zu treffen."""
    candidates = []

    for match in CODE_SPAN_RE.finditer(text):
        for part in re.split(r"\s+", match.group(1)):
            candidates.append(part)

    candidates.extend(PATH_CANDIDATE_RE.findall(text))

    for known_file in COMMON_REPO_FILES:
        if re.search(rf"(?<![\w./-]){re.escape(known_file)}(?![\w./-])", text):
            candidates.append(known_file)

    return candidates


def normalize_aider_target(candidate: str, repo_path: str) -> str | None:
    candidate = clean_path_candidate(candidate)
    if not candidate or candidate.startswith("-") or "://" in candidate:
        return None

    path = Path(candidate)
    if path.is_absolute() or any(part in ("", ".", "..", ".git") for part in path.parts):
        return None

    if not looks_like_repo_file(candidate):
        return None

    repo_root = Path(repo_path).resolve()
    target = (repo_root / path).resolve()
    if not is_relative_to(target, repo_root):
        return None

    if target.exists():
        if not target.is_file():
            return None
    elif path.parent != Path(".") and not (repo_root / path.parent).is_dir():
        return None

    return target.relative_to(repo_root).as_posix()


def infer_aider_targets(prompt: str, repo_path: str) -> list[str]:
    targets = []
    seen = set()
    for candidate in collect_issue_path_candidates(prompt):
        target = normalize_aider_target(candidate, repo_path)
        if target and target not in seen:
            targets.append(target)
            seen.add(target)
    return targets


def build_aider_command(model: str, model_name: str, prompt: str, repo_path: str,
                        file_targets: list[str] | None = None) -> list:
    config = MODEL_CONFIGS[model]
    flags = []

    for flag in config["aider_flags"]:
        if "{model_name}" in flag:
            flags.append(flag.format(model_name=model_name))
        else:
            flags.append(flag)

    targets = file_targets if file_targets is not None else infer_aider_targets(prompt, repo_path)

    cmd = [
        "aider",
        *flags,
        "--yes",                   # Automatisch ja sagen
        "--no-auto-commits",       # Wir committen selbst
        "--subtree-only",          # Repo-Kontext auf den geklonten Arbeitsbaum begrenzen
        "--message", prompt,       # Direkt-Prompt (kein interaktiver Modus)
        *targets,
    ]

    return cmd


def build_codex_command(prompt: str, repo_path: str, model_name: str | None = None) -> list:
    codex = find_codex_executable()
    if not codex:
        raise FileNotFoundError("codex")

    cmd = [
        codex,
        "exec",
        "--cd", repo_path,
        "--sandbox", "workspace-write",
    ]
    if model_name:
        cmd.extend(["--model", model_name])
    cmd.append(prompt)
    return cmd


def run_worker_command(cmd: list, repo_dir: str, env: dict) -> WorkerRunResult:
    """Fuehrt den KI-Worker aus, zeigt verdichteten Output und haelt Rohdaten fest."""
    try:
        process = subprocess.Popen(
            cmd,
            cwd=repo_dir,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
    except FileNotFoundError:
        print_err(f"KI-Worker nicht gefunden: {cmd[0]}")
        return WorkerRunResult(returncode=127, output="")

    output_parts = []
    suppressed_lines = 0
    if process.stdout:
        for line in process.stdout:
            output_parts.append(line)
            if should_surface_worker_line(line):
                print(f"        | {line}", end="")
            else:
                suppressed_lines += 1
        process.stdout.close()

    print_worker_suppression_summary(suppressed_lines)

    return WorkerRunResult(
        returncode=process.wait(),
        output="".join(output_parts),
    )


def should_surface_worker_line(line: str) -> bool:
    """Filtert laute Detailausgabe und laesst relevante Statuszeilen live durch."""
    stripped = line.strip()
    if not stripped:
        return False
    if WORKER_NOISY_OUTPUT_RE.search(stripped):
        return False
    return bool(WORKER_LIVE_OUTPUT_RE.search(stripped))


def print_worker_suppression_summary(count: int) -> None:
    if count:
        print(f"        | ... {count} Detailzeilen ausgeblendet; Rohoutput bleibt in der Diagnose erhalten")


def git_status_porcelain(repo_dir: str) -> str:
    result = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=repo_dir, capture_output=True, text=True,
    )
    if result.returncode != 0:
        print_warn("Git-Status konnte nicht gelesen werden")
        return ""
    return result.stdout


def git_output(repo_dir: str, args: list[str]) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo_dir,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def changed_status_paths(status_lines: list[str]) -> list[str]:
    paths = []
    for line in status_lines:
        if len(line) < 4:
            continue
        paths.append(line[3:])
    return paths


def count_file_lines(path: Path) -> int:
    try:
        data = path.read_bytes()
    except OSError:
        return 0
    if not data:
        return 0
    return data.count(b"\n") + (0 if data.endswith(b"\n") else 1)


def pluralize_de(count: int, singular: str, plural: str) -> str:
    return singular if count == 1 else plural


def format_untracked_file_stats(repo_dir: str, status_lines: list[str]) -> tuple[list[str], int]:
    repo_root = Path(repo_dir)
    stats = []
    insertions = 0
    for status_line in status_lines:
        if not status_line.startswith("?? "):
            continue
        relative_path = status_line[3:]
        path = repo_root / relative_path
        if not path.is_file():
            continue
        line_count = count_file_lines(path)
        insertions += line_count
        pluses = "+" * min(max(line_count, 1), 30)
        stats.append(f"{relative_path} | {line_count} {pluses}")
    return stats, insertions


def format_git_diff_preview(repo_dir: str, status_lines: list[str]) -> list[str]:
    preview_lines = []
    diff = git_output(
        repo_dir,
        ["diff", "--unified=3", "--no-ext-diff", "HEAD", "--"],
    )
    for line in diff.splitlines():
        if line.startswith("index "):
            continue
        preview_lines.append(line)
        if len(preview_lines) >= GIT_SUMMARY_MAX_DIFF_LINES:
            break

    if len(preview_lines) < GIT_SUMMARY_MAX_DIFF_LINES:
        for status_line in status_lines:
            if not status_line.startswith("?? "):
                continue
            relative_path = status_line[3:]
            path = Path(repo_dir) / relative_path
            if not path.is_file():
                continue
            line_count = count_file_lines(path)
            preview_lines.append(f"diff --git a/{relative_path} b/{relative_path}")
            preview_lines.append(
                f"new file, {line_count} "
                f"{pluralize_de(line_count, 'eingefuegte Zeile', 'eingefuegte Zeilen')}"
            )
            if len(preview_lines) >= GIT_SUMMARY_MAX_DIFF_LINES:
                break

    return preview_lines


def format_git_change_summary(repo_dir: str, git_status: str | None = None) -> list[str]:
    status = git_status if git_status is not None else git_status_porcelain(repo_dir)
    status_lines = [line for line in status.splitlines() if line.strip()]
    if not status_lines:
        return []

    summary = ["Git-Änderungsübersicht:"]
    summary.append(f"  Dateien geändert: {len(status_lines)}")
    changed_paths = changed_status_paths(status_lines)
    if changed_paths:
        summary.append("  Dateien:")
        for path in changed_paths[:GIT_SUMMARY_MAX_STATUS_LINES]:
            summary.append(f"    {path}")
        if len(changed_paths) > GIT_SUMMARY_MAX_STATUS_LINES:
            summary.append(
                f"    ... {len(changed_paths) - GIT_SUMMARY_MAX_STATUS_LINES} weitere Dateien"
            )

    shortstat = git_output(repo_dir, ["diff", "--shortstat", "HEAD", "--"])
    untracked_stats, untracked_insertions = format_untracked_file_stats(
        repo_dir,
        status_lines,
    )
    if shortstat:
        summary.append(f"  Statistik: {shortstat}")
    if untracked_insertions:
        summary.append(
            f"  Neue Dateien: {len(untracked_stats)} "
            f"{pluralize_de(len(untracked_stats), 'Datei', 'Dateien')}, "
            f"{untracked_insertions} "
            f"{pluralize_de(untracked_insertions, 'eingefuegte Zeile', 'eingefuegte Zeilen')}"
        )

    stat = git_output(repo_dir, ["diff", "--stat", "HEAD", "--"])
    stat_lines = [line for line in stat.splitlines() if line.strip()]
    stat_lines.extend(untracked_stats)
    if stat_lines:
        summary.append("  Diff-Stat:")
        for line in stat_lines[:GIT_SUMMARY_MAX_STAT_LINES]:
            summary.append(f"    {line}")
        if len(stat_lines) > GIT_SUMMARY_MAX_STAT_LINES:
            summary.append(
                f"    ... {len(stat_lines) - GIT_SUMMARY_MAX_STAT_LINES} weitere Stat-Zeilen"
            )

    preview_lines = format_git_diff_preview(repo_dir, status_lines)
    if preview_lines:
        summary.append("  Diff-Vorschau:")
        for line in preview_lines:
            summary.append(f"    {line}")
        if len(preview_lines) == GIT_SUMMARY_MAX_DIFF_LINES:
            summary.append("    ... Diff-Vorschau gekuerzt")

    summary.append("  Status:")
    for line in status_lines[:GIT_SUMMARY_MAX_STATUS_LINES]:
        summary.append(f"    {line}")
    if len(status_lines) > GIT_SUMMARY_MAX_STATUS_LINES:
        summary.append(
            f"    ... {len(status_lines) - GIT_SUMMARY_MAX_STATUS_LINES} weitere Dateien"
        )
    return summary


def print_git_change_summary(repo_dir: str, git_status: str) -> None:
    for line in format_git_change_summary(repo_dir, git_status):
        print(f"      {line}")


def safe_run_repo_name(repo: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", repo).strip("-") or "repo"


def create_run_report(repo: str, issue_number: int, branch: str, model: str,
                      now_fn=datetime.now) -> RunReport | None:
    timestamp = now_fn().strftime("%Y%m%d-%H%M%S-%f")
    run_dir = RUN_REPORTS_ROOT / f"{timestamp}-{safe_run_repo_name(repo)}-issue-{issue_number}"
    try:
        run_dir.mkdir(parents=True, exist_ok=False)
    except OSError as exc:
        print_warn(f"Run-Report konnte nicht angelegt werden: {exc}")
        return None
    return RunReport(run_dir, repo, issue_number, branch, model)


def write_run_report(report: RunReport, status: str,
                     worker_result: WorkerRunResult | None = None,
                     pr_url: str | None = None,
                     note: str | None = None) -> Path | None:
    worker_exit_code = "" if worker_result is None else str(worker_result.returncode)
    worker_output = "" if worker_result is None else worker_result.output
    output_tail = format_worker_output_tail(worker_output)
    pr_value = pr_url or ""

    try:
        if worker_result is not None:
            (report.path / "worker-output.log").write_text(worker_output, encoding="utf-8")
        if output_tail:
            (report.path / "output-tail.log").write_text(output_tail + "\n", encoding="utf-8")

        summary_lines = [
            f"status: {status}",
            f"selected_repo: {report.repo}",
            f"repo: {report.repo}",
            f"issue_number: {report.issue_number}",
            f"issue: {report.issue_number}",
            f"branch: {report.branch}",
            f"model: {report.model}",
            f"worker_exit_code: {worker_exit_code}",
            f"pr_url: {pr_value}",
        ]
        if note:
            summary_lines.extend(["", f"note: {note}"])
        if worker_result is not None:
            summary_lines.extend(["", "Der vollstaendige Worker-Output liegt in worker-output.log."])
        if output_tail:
            summary_lines.extend(["", "output_tail:", output_tail])

        (report.path / "summary.txt").write_text(
            "\n".join(summary_lines) + "\n",
            encoding="utf-8",
        )
    except OSError as exc:
        print_warn(f"Run-Report konnte nicht gespeichert werden: {exc}")
        return None
    return report.path


def write_worker_diagnostics(result: WorkerRunResult, repo: str, issue_number: int,
                             model: str, branch: str = "",
                             pr_url: str | None = None,
                             status: str = "worker_finished") -> Path | None:
    report = create_run_report(repo, issue_number, branch, model)
    if not report:
        return None
    return write_run_report(report, status, worker_result=result, pr_url=pr_url)


def assess_worker_result(result: WorkerRunResult, git_status: str) -> WorkerAssessment:
    has_changes = bool(git_status.strip())
    if result.returncode == 0 and has_changes:
        return WorkerAssessment(True, True, "changed")
    if result.returncode == 0:
        return WorkerAssessment(False, False, "no_changes")
    if has_changes:
        return WorkerAssessment(True, True, "nonzero_with_changes")
    return WorkerAssessment(False, False, "nonzero_without_changes")


def parse_codex_reset_datetime(reset_text: str) -> datetime | None:
    """Parst die Reset-Zeit aus der Codex-CLI-Meldung im lokalen Zeitkontext."""
    normalized = re.sub(r"\s+", " ", reset_text.strip())
    normalized = normalized.replace(", at ", " ").replace(" at ", " ")

    formats = (
        "%B %d, %Y %I:%M %p",
        "%b %d, %Y %I:%M %p",
        "%B %d %Y %I:%M %p",
        "%b %d %Y %I:%M %p",
    )
    for date_format in formats:
        try:
            return datetime.strptime(normalized, date_format)
        except ValueError:
            pass
    return None


def detect_codex_rate_limit(output: str) -> CodexRateLimit | None:
    if not CODEX_RATE_LIMIT_MESSAGE_RE.search(output):
        return None

    reset_match = CODEX_RATE_LIMIT_RESET_RE.search(output)
    if not reset_match:
        return CodexRateLimit(reset_at=None, reset_text=None)

    reset_text = reset_match.group(1).strip()
    return CodexRateLimit(
        reset_at=parse_codex_reset_datetime(reset_text),
        reset_text=reset_text,
    )


def sleep_until_codex_reset(rate_limit: CodexRateLimit,
                            sleep_fn=time.sleep,
                            now_fn=datetime.now) -> None:
    if rate_limit.reset_text:
        print_warn(f"Codex-Rate-Limit erreicht; Reset laut Codex: {rate_limit.reset_text}")
    else:
        print_warn("Codex-Rate-Limit erreicht; keine Reset-Zeit in der Ausgabe gefunden")

    if not rate_limit.reset_at:
        return

    wait_seconds = max(0.0, (rate_limit.reset_at - now_fn()).total_seconds())
    if wait_seconds > 0:
        print(f"      Pausiere bis {rate_limit.reset_at.strftime('%Y-%m-%d %H:%M')} und setze dann fort.")
        sleep_fn(wait_seconds)
    else:
        print("      Reset-Zeit ist bereits erreicht; setze sofort fort.")


def format_worker_output_tail(output: str) -> str:
    cleaned = output.strip()
    if not cleaned:
        return ""

    tail = "\n".join(cleaned.splitlines()[-WORKER_OUTPUT_TAIL_LINES:])
    if len(tail) > WORKER_OUTPUT_TAIL_CHARS:
        tail = tail[-WORKER_OUTPUT_TAIL_CHARS:]
        return f"...\n{tail}"
    return tail


def print_worker_assessment(result: WorkerRunResult, assessment: WorkerAssessment) -> None:
    if assessment.reason == "changed":
        return

    if assessment.reason == "no_changes":
        print_warn("KI-Worker hat erfolgreich beendet, aber keine Änderungen erzeugt")
    elif assessment.reason == "nonzero_with_changes":
        print_warn(
            f"KI-Worker exit code: {result.returncode}; vorhandene Änderungen werden geprüft"
        )
    else:
        print_warn(
            f"KI-Worker exit code: {result.returncode}; keine Änderungen erzeugt"
        )

    tail = format_worker_output_tail(result.output)
    if tail:
        print("      Letzte Worker-Ausgabe:")
        for line in tail.splitlines():
            print(f"        | {line}")


def clone_repo(owner: str, repo: str, token: str, target_dir: str,
               base_branch: str) -> bool:
    url = f"https://{token}@github.com/{owner}/{repo}.git"
    result = subprocess.run(
        ["git", "clone", "--branch", base_branch, "--single-branch", url, target_dir],
        capture_output=True, text=True
    )
    return result.returncode == 0


def create_branch(repo_dir: str, branch_name: str) -> bool:
    result = subprocess.run(
        ["git", "checkout", "-b", branch_name],
        cwd=repo_dir, capture_output=True, text=True
    )
    return result.returncode == 0


def checkout_existing_remote_branch(repo_dir: str, branch_name: str) -> bool:
    fetch = subprocess.run(
        ["git", "fetch", "origin", f"{branch_name}:refs/remotes/origin/{branch_name}"],
        cwd=repo_dir, capture_output=True, text=True
    )
    if fetch.returncode != 0:
        return False

    result = subprocess.run(
        ["git", "checkout", "-B", branch_name, f"origin/{branch_name}"],
        cwd=repo_dir, capture_output=True, text=True
    )
    return result.returncode == 0


def branch_has_changes_against_base(repo_dir: str, base_branch: str) -> bool:
    base_ref = f"origin/{base_branch}"
    verify = subprocess.run(
        ["git", "rev-parse", "--verify", base_ref],
        cwd=repo_dir, capture_output=True, text=True
    )
    if verify.returncode != 0:
        base_ref = base_branch

    result = subprocess.run(
        ["git", "diff", "--quiet", f"{base_ref}...HEAD", "--"],
        cwd=repo_dir, capture_output=True, text=True
    )
    if result.returncode not in (0, 1):
        result = subprocess.run(
            ["git", "diff", "--quiet", base_ref, "HEAD", "--"],
            cwd=repo_dir, capture_output=True, text=True
        )
    return result.returncode == 1


def commit_and_push(repo_dir: str, branch: str, message: str, token: str,
                    owner: str, repo: str) -> bool:
    # Alle Änderungen stagen
    subprocess.run(["git", "add", "-A"], cwd=repo_dir, capture_output=True)

    # Prüfen ob es Änderungen gibt
    result = subprocess.run(
        ["git", "diff", "--cached", "--quiet"],
        cwd=repo_dir, capture_output=True
    )
    if result.returncode == 0:
        print_warn("Keine Änderungen zu committen")
        return False

    # Commit
    result = subprocess.run(
        ["git", "commit", "-m", message],
        cwd=repo_dir, capture_output=True, text=True,
        env={**os.environ,
             "GIT_AUTHOR_NAME": "AI Issue Solver",
             "GIT_AUTHOR_EMAIL": "ai@github.com",
             "GIT_COMMITTER_NAME": "AI Issue Solver",
             "GIT_COMMITTER_EMAIL": "ai@github.com"}
    )
    if result.returncode != 0:
        print_warn("Commit fehlgeschlagen")
        if result.stderr.strip():
            print(f"      Git meldet: {result.stderr.strip().splitlines()[0][:200]}")
        return False

    # Push
    remote_url = f"https://{token}@github.com/{owner}/{repo}.git"
    result = subprocess.run(
        ["git", "push", remote_url, branch],
        cwd=repo_dir, capture_output=True, text=True
    )
    return result.returncode == 0


def retry_branch_name(issue_number: int, now_fn=datetime.now,
                      existing_branches: set[str] | None = None) -> str:
    base_name = f"ai/fix-issue-{issue_number}-{now_fn().strftime('%Y%m%d-%H%M%S')}"
    if not existing_branches or base_name not in existing_branches:
        return base_name

    suffix = 2
    while f"{base_name}-{suffix}" in existing_branches:
        suffix += 1
    return f"{base_name}-{suffix}"


def newest_pull_request(pull_requests: list[PullRequestState]) -> PullRequestState | None:
    return pull_requests[0] if pull_requests else None


def newest_branch(branches: list[str]) -> str:
    return sorted(branches)[-1]


def describe_pull_request(pr: PullRequestState) -> str:
    number = f"#{pr.number}" if pr.number else "(ohne Nummer)"
    url = f" {pr.html_url}" if pr.html_url else ""
    if pr.state == "open":
        state = "offen"
    elif pr.merged:
        state = "gemergt"
    else:
        state = "geschlossen, nicht gemergt"
    return f"PR {number} ({state}){url}"


def choose_recovery_action(prompt_fn=input) -> str:
    print("      Wiederherstellung: bestehenden Branch nicht automatisch weiterverwenden.")
    print("      [n] Neuer Run mit neuem Branch  [s] Issue überspringen")
    while True:
        choice = prompt_fn("      Auswahl [n/s]: ").strip().lower()
        if choice in ("", "n", "new", "neu"):
            return "new"
        if choice in ("s", "skip", "überspringen", "ueberspringen"):
            return "skip"
        print("      Bitte 'n' für neuen Run oder 's' zum Überspringen eingeben.")


def plan_branch_recovery(client: GitHubClient, repo: str, issue_number: int,
                         issue_branch: str,
                         prompt_fn=input,
                         stdin_isatty_fn=sys.stdin.isatty,
                         now_fn=datetime.now) -> BranchRecoveryPlan:
    """Prueft vorhandene Remote-Artefakte und waehlt einen sicheren Branch."""
    discovered_branches = client.get_issue_branches(repo, issue_number)
    default_exists = client.branch_exists(repo, issue_branch)
    existing_branches = set(discovered_branches)
    if default_exists:
        existing_branches.add(issue_branch)

    branches_to_check = sorted(existing_branches | {issue_branch}, reverse=True)
    pull_requests_by_branch = {
        branch: client.get_pull_requests_for_branch(repo, branch, state="all")
        for branch in branches_to_check
    }
    found_pull_requests = tuple(
        (branch, pr)
        for branch in branches_to_check
        for pr in pull_requests_by_branch[branch]
    )

    def recovery_plan(action: str, branch: str, message: str,
                      pull_request: PullRequestState | None = None) -> BranchRecoveryPlan:
        return BranchRecoveryPlan(
            action=action,
            branch=branch,
            message=message,
            pull_request=pull_request,
            found_branches=tuple(sorted(existing_branches)),
            found_pull_requests=found_pull_requests,
        )

    for branch in branches_to_check:
        pr = next((candidate for candidate in pull_requests_by_branch[branch]
                   if candidate.state == "open"), None)
        if pr:
            return recovery_plan(
                "skip_existing_pr",
                branch,
                f"Vorhandener Branch '{branch}' hat bereits einen offenen {describe_pull_request(pr)}.",
                pr,
            )

    for branch in branches_to_check:
        pr = next((candidate for candidate in pull_requests_by_branch[branch]
                   if candidate.merged), None)
        if pr:
            return recovery_plan(
                "skip_merged_pr",
                branch,
                f"Vorhandener Branch '{branch}' wurde bereits über {describe_pull_request(pr)} gemergt.",
                pr,
            )

    reusable_branches = [
        branch for branch in existing_branches
        if not pull_requests_by_branch.get(branch)
    ]
    if reusable_branches:
        branch = newest_branch(reusable_branches)
        return recovery_plan(
            "reuse_branch",
            branch,
            f"Vorhandener Branch '{branch}' ohne PR gefunden; verwende ihn weiter.",
        )

    closed_pr = None
    closed_pr_branch = issue_branch
    for branch in branches_to_check:
        pr = newest_pull_request(pull_requests_by_branch[branch])
        if pr:
            closed_pr = pr
            closed_pr_branch = branch
            break

    if closed_pr:
        if stdin_isatty_fn():
            action = choose_recovery_action(prompt_fn)
            if action == "skip":
                return recovery_plan(
                    "skip_closed_pr",
                    closed_pr_branch,
                    f"Vorhandener Branch '{closed_pr_branch}' gehört zu einem geschlossenen, ungemergten {describe_pull_request(closed_pr)}.",
                    closed_pr,
                )
        new_branch = retry_branch_name(
            issue_number,
            now_fn=now_fn,
            existing_branches=existing_branches,
        )
        return recovery_plan(
            "new",
            new_branch,
            (
                f"Vorhandener Branch '{closed_pr_branch}' gehört zu einem geschlossenen, ungemergten "
                f"{describe_pull_request(closed_pr)}; starte neuen Run auf '{new_branch}'."
            ),
            closed_pr,
        )

    if not existing_branches:
        return recovery_plan(
            "new",
            issue_branch,
            f"Kein vorhandener Branch '{issue_branch}' gefunden; starte neuen Run.",
        )

    branch = newest_branch(list(existing_branches))
    return recovery_plan(
        "reuse_branch",
        branch,
        f"Vorhandener Branch '{branch}' ohne PR gefunden; verwende ihn weiter.",
    )


def print_branch_recovery_plan(plan: BranchRecoveryPlan) -> None:
    print(f"      🔎 Recovery: {plan.message}")
    if plan.found_branches:
        print(f"      Gefundene Branches: {', '.join(plan.found_branches)}")
    if plan.found_pull_requests:
        print("      Gefundene PRs:")
        for branch, pr in plan.found_pull_requests:
            print(f"        - {branch}: {describe_pull_request(pr)}")


def build_issue_pr_body(config_owner: str, repo: str, number: int, title: str,
                        model: str, close_issues: bool) -> str:
    return f"""## 🤖 AI-generierter Fix für Issue #{number}

Dieses PR wurde automatisch durch [ai-issue-solver](https://github.com/{config_owner}/ai-issue-solver) erstellt.

### Gelöstes Issue
{"Closes" if close_issues else "Refs"} #{number}: {title}

### Verwendetes Modell
`{MODEL_CONFIGS[model]['display_name']}`

### Änderungen
*(bitte vor dem Merge reviewen)*

---
*Erstellt mit dem AI Issue Solver (Morpheus-Methode)*
"""


def create_issue_pull_request(client: GitHubClient, repo: str, number: int, title: str,
                              model: str, config: dict, branch_name: str,
                              base_branch: str, close_issues: bool,
                              dry_run: bool = False) -> dict | None:
    pr = client.create_pull_request(
        repo=repo,
        title=f"[AI] Fix: {title}",
        body=build_issue_pr_body(config["owner"], repo, number, title, model, close_issues),
        head=branch_name,
        base=base_branch,
        dry_run=dry_run,
    )
    if pr:
        print(f"      🔀 PR erstellt: {pr.get('html_url', '?')}")

    if close_issues and pr:
        close_comment = (
            "✅ Dieses Issue wurde automatisch durch den AI Issue Solver bearbeitet.\n\n"
            f"PR: {pr.get('html_url', '?') if pr else '(kein PR)'}\n"
            f"Modell: {MODEL_CONFIGS[model]['display_name']}"
        )
        client.close_issue_with_comment(repo, number, close_comment)

    return pr


# ─────────────────────────────────────────────────────────────
# Issue lösen
# ─────────────────────────────────────────────────────────────

def solve_issue(client: GitHubClient, issue: dict, repo: str,
                model: str, model_name: str, config: dict,
                token: str, dry_run: bool, base_branch: str,
                close_issues: bool,
                defer_codex_rate_limit: bool = False) -> bool:
    number = issue["number"]
    title = issue["title"]
    body = issue.get("body", "")
    default_branch_name = f"ai/fix-issue-{number}"

    print(f"\n   🔧 Issue #{number}: {title}")
    print(f"      Modell: {MODEL_CONFIGS[model]['display_name']}")

    if dry_run:
        print(f"      [DRY-RUN] Würde bearbeiten mit {model}")
        print(f"      [DRY-RUN] Zielbranch: {base_branch}")
        recovery_plan = plan_branch_recovery(
            client,
            repo,
            number,
            default_branch_name,
            stdin_isatty_fn=lambda: False,
        )
        print_branch_recovery_plan(recovery_plan)
        print(f"      [DRY-RUN] Geplanter Issue-Branch: {recovery_plan.branch}")
        return True

    recovery_plan = plan_branch_recovery(client, repo, number, default_branch_name)
    print_branch_recovery_plan(recovery_plan)
    run_report = create_run_report(repo, number, recovery_plan.branch, model)
    if run_report:
        write_run_report(run_report, "started")
        print(f"      Run-Report: {run_report.path}")
    if recovery_plan.action.startswith("skip"):
        if recovery_plan.pull_request and recovery_plan.pull_request.html_url:
            print(f"      🔀 Vorhandener PR: {recovery_plan.pull_request.html_url}")
        if run_report:
            write_run_report(
                run_report,
                recovery_plan.action,
                pr_url=recovery_plan.pull_request.html_url if recovery_plan.pull_request else None,
                note=recovery_plan.message,
            )
        return True

    # Repo klonen
    with tempfile.TemporaryDirectory(prefix="ai-solver-") as tmpdir:
        repo_dir = os.path.join(tmpdir, repo)
        print(f"      📥 Klone {repo} ...", end=" ", flush=True)

        if not clone_repo(config["owner"], repo, token, repo_dir, base_branch):
            print_err("Klonen fehlgeschlagen")
            print(f"      Prüfe, ob der Branch '{base_branch}' in {repo} existiert.")
            if run_report:
                write_run_report(run_report, "clone_failed", note=f"base_branch: {base_branch}")
            return False
        print("✅")

        # Branch anlegen
        branch_name = recovery_plan.branch
        if recovery_plan.action == "reuse_branch":
            if not checkout_existing_remote_branch(repo_dir, branch_name):
                print_err(f"Vorhandener Branch konnte nicht ausgecheckt werden: {branch_name}")
                if run_report:
                    write_run_report(run_report, "checkout_failed")
                return False
            if branch_has_changes_against_base(repo_dir, base_branch):
                print(
                    "      Vorhandener Branch enthält bereits Änderungen gegen den Zielbranch; "
                    "erstelle fehlenden PR."
                )
                pr = create_issue_pull_request(
                    client=client,
                    repo=repo,
                    number=number,
                    title=title,
                    model=model,
                    config=config,
                    branch_name=branch_name,
                    base_branch=base_branch,
                    close_issues=close_issues,
                    dry_run=dry_run,
                )
                if run_report:
                    write_run_report(
                        run_report,
                        "pr_created_from_existing_branch" if pr else "pr_failed_from_existing_branch",
                        pr_url=pr.get("html_url") if pr else None,
                    )
                return bool(pr)
        elif not create_branch(repo_dir, branch_name):
            print_err(f"Branch konnte nicht erstellt werden: {branch_name}")
            if run_report:
                write_run_report(run_report, "branch_create_failed")
            return False

        # Prompt bauen
        prompt = AIDER_PROMPT_TEMPLATE.format(
            number=number,
            title=title,
            body=body or "(kein Beschreibungstext)"
        )

        # API-Key setzen
        env = os.environ.copy()
        env_key = MODEL_CONFIGS[model]["env_key"]
        if env_key:
            api_key = require_config_value(config["config"], env_key)
            env[MODEL_CONFIGS[model]["env_var"]] = api_key

        if model == "ollama":
            ollama_host = config["config"].get("OLLAMA_HOST", "http://localhost:11434")
            env["OLLAMA_API_BASE"] = ollama_host

        # KI-Worker ausführen
        if model == "codex":
            print(f"      🤖 Starte Codex ...", flush=True)
            cmd = build_codex_command(prompt, repo_dir, model_name or None)
        else:
            print(f"      🤖 Starte aider ...", flush=True)
            cmd = build_aider_command(model, model_name, prompt, repo_dir)

        rate_limit_retries = 0
        diagnostic_outputs = []
        while True:
            result = run_worker_command(cmd, repo_dir, env)
            diagnostic_outputs.append(result.output)
            rate_limit = detect_codex_rate_limit(result.output) if model == "codex" else None
            if not rate_limit:
                break
            if defer_codex_rate_limit:
                if rate_limit.reset_text:
                    print_warn(
                        "Codex-Rate-Limit erreicht; "
                        f"Batch-Runner soll nach {rate_limit.reset_text} neu einplanen"
                    )
                else:
                    print_warn(
                        "Codex-Rate-Limit erreicht; "
                        "Batch-Runner soll diesen Job verzögern"
                    )
                break
            if not rate_limit.reset_at:
                sleep_until_codex_reset(rate_limit)
                break
            rate_limit_retries += 1
            if rate_limit_retries > CODEX_RATE_LIMIT_RETRY_LIMIT:
                print_warn("Codex-Rate-Limit wurde mehrfach erreicht; breche dieses Issue ab")
                break
            sleep_until_codex_reset(rate_limit)

        diagnostic_result = result
        if len(diagnostic_outputs) > 1:
            combined_output = "\n".join(
                f"--- Worker-Lauf {index} ---\n{output}"
                for index, output in enumerate(diagnostic_outputs, start=1)
            )
            diagnostic_result = WorkerRunResult(result.returncode, combined_output)

        git_status = git_status_porcelain(repo_dir)
        print_git_change_summary(repo_dir, git_status)
        assessment = assess_worker_result(result, git_status)
        print_worker_assessment(result, assessment)
        if not assessment.should_continue:
            if run_report:
                write_run_report(
                    run_report,
                    assessment.reason,
                    worker_result=diagnostic_result,
                )
            return False

        # Committen & pushen
        print(f"      📤 Commit & Push ...", end=" ", flush=True)
        commit_msg = f"fix: Löse Issue #{number} — {title}\n\nAutomatisch gelöst mit AI Issue Solver (Modell: {model})\nIssue: https://github.com/{config['owner']}/{repo}/issues/{number}"

        pushed = commit_and_push(repo_dir, branch_name, commit_msg, token, config["owner"], repo)

        if not pushed:
            print_warn("Push fehlgeschlagen oder keine Änderungen")
            if run_report:
                write_run_report(
                    run_report,
                    "push_failed",
                    worker_result=diagnostic_result,
                )
            return False
        print("✅")

        pr = create_issue_pull_request(
            client=client,
            repo=repo,
            number=number,
            title=title,
            model=model,
            config=config,
            branch_name=branch_name,
            base_branch=base_branch,
            close_issues=close_issues,
            dry_run=dry_run,
        )
        if run_report:
            write_run_report(
                run_report,
                "pr_created" if pr else "pr_failed",
                worker_result=diagnostic_result,
                pr_url=pr.get("html_url") if pr else None,
            )
        return bool(pr)

    return True


# ─────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────

def main():
    print_banner("SCHRITT 3: ISSUES MIT KI LÖSEN")

    parser = argparse.ArgumentParser(description="GitHub Issues automatisch mit KI lösen")
    parser.add_argument(
        "--model", required=True, choices=["codex", "claude", "openai", "ollama"],
        help="KI-Modell: codex, claude, openai oder ollama"
    )
    parser.add_argument(
        "--model-name",
        help="Spezifisches Modell (für Codex optional, für Ollama z.B. 'deepseek-coder:6.7b')"
    )
    parser.add_argument("--repo", help="Nur dieses Repo bearbeiten")
    parser.add_argument("--issue", type=int, help="Nur diese Issue-Nummer lösen")
    parser.add_argument("--dry-run", action="store_true", help="Nur anzeigen, nichts ändern")
    parser.add_argument("--label", default="ai-generated", help="Welche Issues holen (Label)")
    parser.add_argument(
        "--base-branch",
        help="Zielbranch für Klon und PR; ohne Angabe wird der GitHub-Default-Branch genutzt",
    )
    parser.add_argument(
        "--close-issues",
        action="store_true",
        help="Issues nach PR-Erstellung direkt schließen",
    )
    parser.add_argument(
        "--defer-codex-rate-limit",
        action="store_true",
        help="Bei Codex-Rate-Limits nicht schlafen; Batch-Runner kann den Job verzögern",
    )
    args = parser.parse_args()

    if requests is None:
        print_err("Python-Abhängigkeit fehlt: requests")
        print("   → Installieren mit: pip install -r requirements.txt")
        sys.exit(1)

    # Config laden
    cfg = load_env()
    token = require_config_value(cfg, "GITHUB_TOKEN", "GitHub Token")
    user = require_config_value(cfg, "GITHUB_USER", "GitHub User")

    # KI-Worker prüfen
    if args.model == "codex" and not find_codex_executable() and not args.dry_run:
        print_err("Codex CLI wurde nicht gefunden!")
        print("   → Codex Desktop App installieren oder `codex` in PATH verfügbar machen")
        sys.exit(1)

    if args.model != "codex" and not check_aider_installed() and not args.dry_run:
        print_err("aider ist nicht installiert!")
        print("   → Installieren mit: pip install aider-chat")
        print("   → Mehr Infos: docs/SETUP_AIDER.md")
        sys.exit(1)

    # Modell-Name
    model_config = MODEL_CONFIGS[args.model]
    model_name = args.model_name or model_config.get("default_model_name", "")

    env_key = model_config.get("env_key")
    if env_key and args.dry_run and is_placeholder_value(cfg.get(env_key)):
        print_warn(f"{env_key} fehlt oder ist noch ein Platzhalter")
    elif env_key:
        require_config_value(cfg, env_key)

    solver_config = {"owner": user, "config": cfg}
    client = GitHubClient(token, user)

    if args.dry_run:
        print_warn("DRY-RUN Modus aktiv\n")

    print_step(1, f"Modell: {model_config['display_name']}")
    if model_name:
        print(f"   Modell-Name: {model_name}")

    # Repos ermitteln
    if args.repo:
        repos = [args.repo]
    else:
        all_repos = client.get_repos()
        repos = [r["name"] for r in all_repos if not r.get("archived")]

    print_step(2, f"Suche offene Issues in {len(repos)} Repo(s)")

    solved = 0
    failed = 0

    for repo_name in repos:
        if args.issue:
            # Einzelnes Issue
            issue = client.get_single_issue(repo_name, args.issue)
            if not issue:
                continue
            issues = [issue]
        else:
            issues = client.get_open_issues(repo_name, label=args.label)

        if not issues:
            continue

        print(f"\n   📁 {repo_name}: {len(issues)} offene Issue(s)")
        base_branch = client.resolve_base_branch(repo_name, args.base_branch)
        if not base_branch:
            print_warn(f"Kein gültiger Base-Branch für {repo_name} gefunden")
            failed += len(issues)
            continue
        if not args.base_branch:
            print(f"      Zielbranch: {base_branch} (GitHub-Default-Branch)")

        for issue in issues:
            ok = solve_issue(
                client=client,
                issue=issue,
                repo=repo_name,
                model=args.model,
                model_name=model_name,
                config=solver_config,
                token=token,
                dry_run=args.dry_run,
                base_branch=base_branch,
                close_issues=args.close_issues,
                defer_codex_rate_limit=args.defer_codex_rate_limit,
            )
            if ok:
                solved += 1
            else:
                failed += 1
            time.sleep(2)

    # Zusammenfassung
    print("\n" + "─" * 50)
    print(f"  ✅ Gelöst:  {solved}")
    print(f"  ❌ Fehler:  {failed}")
    print("─" * 50 + "\n")


if __name__ == "__main__":
    main()
