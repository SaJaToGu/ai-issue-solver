#!/usr/bin/env python3
"""
solve_issues.py — Schritt 3: Issues mit KI lösen (Morpheus-Methode)
Morpheus-Style AI Issue Solver — github.com/SaJaToGu

Holt offene GitHub Issues, übergibt sie an Codex oder `aider` mit dem
gewählten KI-Worker (Codex / Mistral Vibe / Claude / OpenAI / Mistral / Ollama), erstellt
einen Branch und einen Commit mit der Lösung.

Verwendung:
    python scripts/solve_issues.py --model codex
    python scripts/solve_issues.py --model claude
    python scripts/solve_issues.py --model openai
    python scripts/solve_issues.py --model mistral-vibe
    python scripts/solve_issues.py --model mistral
    python scripts/solve_issues.py --model mistral --model-name magistral-small-2509
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

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(SCRIPT_DIR))
sys.path.insert(0, str(PROJECT_ROOT))

# Worker-Adapter-Paket liegt im Projekt-Root (nicht in scripts/)
sys.path.insert(0, str(PROJECT_ROOT))

from utils import (
    clean_path_candidate,
    is_placeholder_value,
    load_env,
    print_banner,
    print_err,
    print_step,
    print_warn,
    handle_github_request_error,
    raise_for_github_response,
    require_config_value,
    require_github_config,
)

# Role routing & budget enforcement (optional, no hard import failure)
_ROLE_ROUTING: dict | None = None
_ROLE_ROUTING_LOADED: bool = False
_BUDGET_TRACKING_ACTIVE: bool = False

def _ensure_role_routing() -> dict | None:
    """Lazy-load role routing config. Returns None on failure (non-fatal for CLI)."""
    global _ROLE_ROUTING, _ROLE_ROUTING_LOADED
    if _ROLE_ROUTING_LOADED:
        return _ROLE_ROUTING
    _ROLE_ROUTING_LOADED = True
    try:
        from role_routing_loader import load_role_config
        _ROLE_ROUTING = load_role_config()
        return _ROLE_ROUTING
    except (ImportError, FileNotFoundError, ValueError) as exc:
        print_err(f"Role routing not available: {exc}")
        return None

def _ensure_slug_verification() -> bool:
    """Verify OpenRouter slugs. Returns True if OK or skipped, False on failure."""
    try:
        from verify_openrouter_slugs import verify_configured_slugs
        missing = verify_configured_slugs()
        if missing:
            print_err(
                "OpenRouter model slugs missing from live catalogue:\n"
                + "\n".join(f"    - {s}" for s in sorted(missing))
            )
            print_err("Update config/role_routing.yaml or run:")
            print_err("  python scripts/verify_openrouter_slugs.py --list-models")
            return False
        return True
    except ImportError:
        return True
    except FileNotFoundError:
        return True
    except Exception as exc:
        print_warn(f"Slug verification skipped: {exc}")
        return True
from solver_repository import (
    branch_has_changes_against_base,
    checkout_existing_remote_branch,
    clone_repo,
    commit_and_push,
    create_branch,
    git_status_porcelain,
)
from solver_reporting import (  # noqa: F401 (re-exports used by tests/batch)
    PRESERVED_WORKTREE_RETENTION_DAYS,
    POST_PUSH_INCOMPLETE_STATUSES,
    RUN_REPORTS_ROOT,
    RunReport,
    cleanup_preserved_worktrees,
    create_run_report,
    detect_opencode_runtime_diagnostics,
    format_git_change_summary,
    format_post_push_recovery_note,
    format_worker_output_tail,
    preserve_worker_worktree,
    print_opencode_runtime_diagnostics,
    pr_recovery_command,
    safe_run_repo_name,
    should_preserve_worktree,
    should_surface_worker_line,
    write_run_health,
    write_run_report,
    write_worker_diagnostics,
)
from solver_run_resources import (  # noqa: F401 (re-exports used by tests)
    LOCKS_ROOT,
    LOCK_STALE_SECONDS,
    RunResources,
    RunResourceDiagnostics,
    ResourceLock,
    cleanup_stale_locks,
    create_run_resources,
    detect_branch_name_conflict,
    format_resource_diagnostics_summary_lines,
    make_run_id,
    write_resource_diagnostics_to_report,
)
from repo_profile import (  # noqa: F401 (re-exports used by tests)
    RepoProfile,
    build_repo_profile,
    serialize_repo_profile,
)
from model_catalog import (  # noqa: E402
    OPENCODE_DEFAULT_MODEL,
    OPENCODE_FREE_MODELS,
    OPENROUTER_DIRECT_DEFAULT_MODEL,
)
from workflow_congestion import (  # noqa: F401
    WorkflowPullRequest,
    WorkflowIssue,
    WorkflowCongestionSummary,
    analyze_workflow_congestion,
    issue_has_open_pr,
    parse_issue_references,
    pull_request_from_github,
    issue_from_github,
)
from workers.opencode_diagnostics import (  # noqa: F401 (re-exports used by tests/batch)
    OpenCodeStatePreflight,
    check_opencode_auth,
    check_opencode_state_guard,
    find_opencode_executable,
    _looks_like_opencode_executable,
    _print_opencode_state_preflight,
)


def ensure_solver_directories() -> tuple[Path, Path]:
    """
    Erstellt und verwaltet solver-lokale Verzeichnisse für XDG_STATE_HOME und XDG_CACHE_HOME.

    Falls XDG_*_HOME-Umgebungsvariablen nicht gesetzt sind, werden solver-lokale Verzeichnisse
    unter einem temporären Präfix (z. B. /tmp/opencode/state bzw. /tmp/opencode/cache) erstellt.

    Returns:
        Tuple[Path, Path]: Pfade zu (state_dir, cache_dir)
    """
    # Temporäres Verzeichnis für solver-lokale Daten (beschreibbar und plattformneutral)
    solver_base = Path(tempfile.gettempdir()) / "ai-issue-solver" / "opencode"
    solver_base.mkdir(parents=True, exist_ok=True)

    # XDG_STATE_HOME (für Zustandsdateien wie Chat-History, Authentifizierung)
    xdg_state_home = os.getenv("XDG_STATE_HOME")
    if xdg_state_home:
        state_dir = Path(xdg_state_home) / "opencode"
    else:
        state_dir = solver_base / "state"

    # XDG_CACHE_HOME (für Cache-Dateien wie Modelle, temporäre Daten)
    xdg_cache_home = os.getenv("XDG_CACHE_HOME")
    if xdg_cache_home:
        cache_dir = Path(xdg_cache_home) / "opencode"
    else:
        cache_dir = solver_base / "cache"

    # Verzeichnisse erstellen, falls nicht vorhanden
    state_dir.mkdir(parents=True, exist_ok=True)
    cache_dir.mkdir(parents=True, exist_ok=True)
    (cache_dir / "tmp").mkdir(parents=True, exist_ok=True)

    return state_dir, cache_dir


def prepare_opencode_worker_environment(base_env: dict[str, str] | None = None) -> dict[str, str]:
    """
    Bereitet die Umgebung für OpenCode vor, inklusive solver-lokalem Cache.

    Args:
        base_env: Basis-Umgebung, falls vorhanden. Standardmäßig wird os.environ verwendet.

    Returns:
        dict[str, str]: Angepasste Umgebung mit solver-lokalem Cache-Pfad.
    """
    _state_dir, cache_dir = ensure_solver_directories()
    env = dict(base_env if base_env is not None else os.environ)

    # Nur Cache isolieren. State/Auth nicht überschreiben, damit OpenCode seine
    # bestehende SQLite-Datenbank inklusive WAL-Dateien konsistent findet.
    # OPENCODE_SERVER_PASSWORD wird von OpenCode Desktop gesetzt und verhindert,
    # dass CLI `opencode run` eine neue Session startet (GitHub issue #24747).
    env.pop("XDG_STATE_HOME", None)
    env.pop("OPENCODE_SERVER_PASSWORD", None)
    env["OPENCODE_CACHE_DIR"] = str(cache_dir)

    return env


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
    "mistral": {
        "display_name": "Mistral AI Magistral (magistral-medium-2509)",
        "aider_flags": [
            "--model", "mistral/{model_name}",
        ],
        "env_key": "MISTRAL_API_KEY",
        "env_var": "MISTRAL_API_KEY",
        "default_model_name": "magistral-medium-2509",
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
    "mistral-vibe": {
        "display_name": "Mistral Vibe CLI",
        "env_key": "MISTRAL_API_KEY",
        "env_var": "MISTRAL_API_KEY",
    },
    "opencode": {
        "display_name": "OpenCode CLI",
        "env_key": None,
        "env_var": None,
        "default_model_name": OPENCODE_DEFAULT_MODEL,
        "free_models": list(OPENCODE_FREE_MODELS),
    },
    "openrouter": {
        "display_name": "OpenRouter (aider, legacy)",
        "aider_flags": [
            "--model", "{model_name}",
        ],
        "env_key": "OPENROUTER_API_KEY",
        "env_var": "OPENROUTER_API_KEY",
        "default_model_name": "openrouter/openai/gpt-4o-mini",
    },
    "openrouter_direct": {
        "display_name": "OpenRouter (Direct)",
        "env_key": "OPENROUTER_API_KEY",
        "env_var": "OPENROUTER_API_KEY",
        "default_model_name": OPENROUTER_DIRECT_DEFAULT_MODEL,
    },
}

VIBE_LOG_PATH = Path(".vibe") / "logs" / "vibe.log"
VIBE_LOG_SNIPPET_LINES = 15
VIBE_LOG_SNIPPET_CHARS = 2000
CODEX_RATE_LIMIT_RETRY_LIMIT = 3
# Standard-Post-Solve-Testbefehl nach erfolgreichem Commit & Push.
# Wird in run_post_solve_tests() ausgefuehrt; Status landet in PR-Body und Run-Report.
POST_SOLVE_TEST_COMMAND = [sys.executable, "-m", "unittest", "discover", "-s", "tests"]
POST_SOLVE_TEST_TIMEOUT_SECONDS = 300
# Post-Worker-Phasen (Issue #350): Validierung, Tests, Commit, Push, PR.
# Diese Phasen laufen _nach_ dem eigentlichen KI-Worker, koennen aber in der
# Praxis blockieren (z.B. GitHub-API haengt). Wir setzen fuer jede Phase
# explizite Health-Updates und eine harte Watchdog-Obergrenze, damit ein
# stiller Single-Run nicht endlos haengt.
POST_WORKER_PHASES: tuple[str, ...] = (
    "validating",
    "post_solve_tests",
    "committing",
    "pushing",
    "creating_pr",
)
# Default-Budget fuer die _gesamte_ Post-Worker-Phase (Validierung bis
# PR-Erstellung). Wird durch ``--max-post-worker-runtime-seconds``
# ueberschrieben.
DEFAULT_POST_WORKER_RUNTIME_SECONDS = 600
# Watchdog-Heartbeat-Intervall fuer die Post-Worker-Health-Datei.
POST_WORKER_HEARTBEAT_SECONDS = 15
CONFLICT_MARKER_RE = re.compile(r"^\s*(?:<{7}\s|>{7}\s|={7}\s*$)")
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
SECRET_WORKER_PATHS = {
    ".env",
    "config/.env",
}
SECRET_WORKER_PREFIXES = (
    ".env.",
    "config/.env.",
)
SAFE_SECRET_EXAMPLE_PATHS = {
    ".env.example",
    "config/config.example.env",
}
SECRET_WORKER_PATH_REPLACEMENT = "config/config.example.env"
WORKER_SIDE_EFFECT_PATTERNS = {
    ".aider*",
    ".aider/**",
    ".aider.tags.cache.v4/**",
    ".DS_Store",
    "**/.DS_Store",
}
NONZERO_GENERIC_SIDE_EFFECT_FILES = {
    ".gitignore",
    "LICENSE",
    "LICENSE.md",
    "LICENSE.txt",
}
PATH_CANDIDATE_RE = re.compile(
    r"(?<![\w:/.-])(?:[A-Za-z0-9_.-]+/)+[A-Za-z0-9_.@+~-]+(?:\.[A-Za-z0-9_.+-]+)?"
)
ABSOLUTE_PATH_RE = re.compile(r"(?<![\w:/.-])/[^\s`'\"<>|]+")
CODE_SPAN_RE = re.compile(r"`([^`\n]+)`")
CODEX_RATE_LIMIT_RESET_RE = re.compile(
    r"rate limit will be reset on\s+(.+?)(?:\.|\n|$)",
    re.IGNORECASE,
)
CODEX_RATE_LIMIT_MESSAGE_RE = re.compile(
    r"(?:reached the codex message limit|rate limit will be reset)",
    re.IGNORECASE,
)
VIBE_TURN_LIMIT_RE = re.compile(
    r"<vibe_stop_event>Turn limit of \d+ reached</vibe_stop_event>",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class WorkerRunResult:
    returncode: int
    output: str
    last_activity_at: datetime | None = None


@dataclass(frozen=True)
class WorkerAssessment:
    should_continue: bool
    has_changes: bool
    reason: str


@dataclass(frozen=True)
class WorkerValidation:
    ok: bool
    errors: tuple[str, ...] = ()


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
    head_ref: str | None = None
    base_ref: str | None = None


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

    def are_issues_enabled(self, repo: str) -> bool:
        """Prüft, ob Issues für das Repository aktiviert sind."""
        try:
            resp = self.session.get(f"{self.BASE}/repos/{self.owner}/{repo}")
            raise_for_github_response(resp, f"Repo-Status prüfen: {repo}")
            repo_data = resp.json()
            return repo_data.get("has_issues", False)
        except requests.RequestException as exc:
            handle_github_request_error(exc, f"Repo-Status prüfen: {repo}")
            return False

    def validate_token_permissions(self) -> bool:
        """Prüft, ob das Token die erforderlichen Berechtigungen hat (z. B. 'repo')."""
        try:
            resp = self.session.get(f"{self.BASE}/user")
            raise_for_github_response(resp, "Token-Berechtigungen prüfen")
            scopes = resp.headers.get("X-OAuth-Scopes", "")
            return "repo" in scopes
        except requests.RequestException as exc:
            handle_github_request_error(exc, "Token-Berechtigungen prüfen")
            return False

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
                    head_ref=(pr.get("head") or {}).get("ref"),
                    base_ref=(pr.get("base") or {}).get("ref"),
                )
            )
        return pull_requests

    def resolve_base_branch(self, repo: str, requested_base: str | None = None) -> str | None:
        """Ermittelt den Zielbranch und nutzt ohne Vorgabe den GitHub-Default-Branch."""
        if requested_base:
            if self.branch_exists(repo, requested_base):
                return requested_base

            print_err(
                f"Angeforderter Base-Branch '{requested_base}' existiert nicht remote"
            )
            return None

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
            json={"body": comment},
            timeout=30,
        )
        # Issue schließen
        self.session.patch(
            f"{self.BASE}/repos/{self.owner}/{repo}/issues/{number}",
            json={"state": "closed"},
            timeout=30,
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
            json={"title": title, "body": body, "head": head, "base": resolved_base},
            timeout=30,
        )
        if resp.status_code == 201:
            return resp.json()
        print_warn(f"PR konnte nicht erstellt werden: {resp.status_code}")
        return None


def build_repo_profile_for_run(repo: str,
                              config: dict,
                              branch: str | None = None,
                              offline: bool = False,
                              prefer: str = "github") -> tuple[RepoProfile | None, dict | None]:
    """Build a provider-aware :class:`RepoProfile` for the current solver run.

    The function prefers the GitHub REST API (when a token is configured) and
    falls back to a local marker-file scan for offline or non-GitHub
    repositories. The result is also serialized into a JSON-safe dict so
    callers can persist it directly in run reports.

    Secret files (``.env`` variants, ``auth.json``, ``secrets/*``) are never
    read by the local provider and never propagated through the profile's
    ``extra`` payload.
    """
    try:
        token = config.get("GITHUB_TOKEN") if isinstance(config, dict) else None
        owner = config.get("GITHUB_OWNER") if isinstance(config, dict) else None
        profile = build_repo_profile(
            repo,
            token=token,
            owner=owner,
            local_root=Path.cwd(),
            branch=branch,
            offline=offline,
            prefer=prefer,
            logger=None,
        )
    except Exception as exc:  # pragma: no cover - defensive against GitHub 404s
        print_warn(f"Repo-Profile konnte nicht erstellt werden: {exc}")
        return None, None
    return profile, serialize_repo_profile(profile)


def repo_type_from_profile(profile: RepoProfile | None) -> str:
    """Map a :class:`RepoProfile` to a string accepted by ``model_selection``."""
    if profile is None:
        return "python"
    # r-shiny und node haben keinen eigenen Eintrag in ISSUE_CATEGORIES und
    # fallen daher auf den naechsten passenden Wert zurueck.
    if profile.repo_kind == "r-shiny":
        return "r"
    if profile.repo_kind in {"python", "r", "node", "docs-only", "unknown"}:
        return profile.repo_kind
    return profile.dominant_language or "python"


def preflight_checks(config: dict, repo: str, issue_number: int | None = None) -> tuple[str, str | None]:
    """Prueft GitHub-Zugang, Ziel-Repo und optional die konkrete Issue vor dem Worker-Start."""
    print_step(0, "Preflight-Checks")
    token, user = require_github_config(config, require_user=True)
    client = GitHubClient(token, user)

    repo_info = client.get_repo(repo)
    if not repo_info:
        print_err(f"Ziel-Repository nicht gefunden: {user}/{repo}")
        raise SystemExit(1)
    print(f"   ✅ Repo erreichbar: {user}/{repo}")

    if not repo_info.get("has_issues", False):
        print_err(f"Issues sind fuer {user}/{repo} nicht aktiviert")
        raise SystemExit(1)
    print("   ✅ Issues sind aktiviert")

    if issue_number is not None:
        issue = client.get_single_issue(repo, issue_number)
        if not issue or "pull_request" in issue:
            print_err(f"Issue nicht gefunden: {repo}#{issue_number}")
            raise SystemExit(1)
        if issue.get("state") != "open":
            print_err(f"Issue ist nicht offen: {repo}#{issue_number}")
            raise SystemExit(1)
        print(f"   ✅ Issue offen: #{issue_number} {issue.get('title', '')}")

    return token, user


def _run_local_git(args: list[str], *, project_root: Path = PROJECT_ROOT) -> subprocess.CompletedProcess:
    """Run a local git command for pre-solver hygiene checks."""
    return subprocess.run(
        ["git", *args],
        cwd=project_root,
        capture_output=True,
        text=True,
        check=False,
    )


def _parse_gone_branches(branch_vv_output: str) -> list[str]:
    """Extract local branches whose upstream is gone from `git branch -vv` output."""
    gone_branches: list[str] = []
    for line in branch_vv_output.splitlines():
        stripped = line.strip()
        if not stripped or ": gone]" not in stripped:
            continue
        if stripped.startswith("* "):
            stripped = stripped[2:].strip()
        branch_name = stripped.split(maxsplit=1)[0]
        if branch_name:
            gone_branches.append(branch_name)
    return gone_branches


def collect_pre_solver_hygiene_findings(project_root: Path = PROJECT_ROOT) -> list[str]:
    """
    Collect non-destructive local hygiene findings before a real Solver run.

    The check focuses on operator-side leftovers that can distort measurement
    runs. It never deletes files or branches.
    """
    findings: list[str] = []

    if (project_root / ".git").exists():
        status = _run_local_git(["status", "--porcelain"], project_root=project_root)
        if status.returncode == 0 and status.stdout.strip():
            findings.append("working tree has uncommitted changes")
        elif status.returncode != 0:
            details = (status.stderr or status.stdout).strip()
            findings.append(f"git status failed: {details}")

        branches = _run_local_git(
            ["branch", "-vv", "--sort=-committerdate"],
            project_root=project_root,
        )
        if branches.returncode == 0:
            for branch_name in _parse_gone_branches(branches.stdout):
                findings.append(f"local branch '{branch_name}' tracks a gone upstream")
        else:
            details = (branches.stderr or branches.stdout).strip()
            findings.append(f"git branch -vv failed: {details}")

    operator_artifacts = sorted((project_root / "reports" / "tmp").glob("validation-issue-*.md"))
    for artifact in operator_artifacts:
        findings.append(f"operator artifact remains: {artifact.relative_to(project_root)}")

    return findings


def run_pre_solver_hygiene_check(*, dry_run: bool = False, project_root: Path = PROJECT_ROOT) -> bool:
    """Print and evaluate the pre-solver hygiene gate."""
    print_step(0, "Pre-Solver Hygiene")
    findings = collect_pre_solver_hygiene_findings(project_root)
    if not findings:
        print("   ✅ Lokale Solver-Hygiene sauber")
        return True

    for finding in findings:
        print_warn(finding)

    if dry_run:
        print_warn("Dry-run: Hygiene-Funde werden gemeldet, blockieren aber nicht.")
        return True

    print_err(
        "Solverlauf blockiert: lokale Hygiene-Funde zuerst bereinigen "
        "oder --skip-hygiene-check bewusst setzen."
    )
    return False


# ─────────────────────────────────────────────────────────────
# Aider Integration
# ─────────────────────────────────────────────────────────────

# Bekannte Projektverzeichnisse, in denen Dateien bevorzugt werden
KNOWN_PROJECT_DIRS = frozenset({"scripts", "tests", "src", "lib", "app", "config", "docs"})


def find_aider_executable() -> str | None:
    """Find the aider executable, checking venv-local paths first, then PATH.

    Suchreihenfolge:
    1. .venv/bin/aider (wenn aktueller Python in .venv ist)
    2. venv/bin/aider (Standard-Venv-Pfad)
    3. <python_prefix>/bin/aider (für die aktuelle Python-Umgebung)
    4. PATH via shutil.which()

    Returns:
        Pfad zum aider-Executable oder None
    """
    candidates = []

    # Prüfe ob aktueller Python aus einem venv kommt
    python_executable = sys.executable
    if python_executable:
        python_path = Path(python_executable).resolve()
        # .venv/bin/python -> .venv/bin/aider
        venv_bin = python_path.parent
        if venv_bin.exists() and venv_bin.name == "bin":
            venv_path = venv_bin.parent
            if venv_path.name in ("venv", ".venv"):
                aider_path = venv_bin / "aider"
                if aider_path.exists():
                    return str(aider_path)
                candidates.append(str(aider_path))

    # Standard venv Pfade
    for venv_name in (".venv", "venv"):
        venv_path = Path.cwd() / venv_name
        aider_path = venv_path / "bin" / "aider"
        if aider_path.exists():
            return str(aider_path)
        candidates.append(str(aider_path))

    # Prüfe site-packages Pfad der aktuellen Python-Umgebung
    try:
        import site
        for site_path in site.getsitepackages() + site.getusersitepackages():
            aider_path = Path(site_path).parent / "bin" / "aider"
            if aider_path.exists():
                return str(aider_path)
            candidates.append(str(aider_path))
    except Exception:
        pass

    # PATH
    path_aider = shutil.which("aider")
    if path_aider:
        return path_aider

    return None


def check_aider_installed() -> bool:
    """Prüfe ob aider verfügbar ist (inkl. venv-lokaler Installation)."""
    return find_aider_executable() is not None


def find_codex_executable() -> str | None:
    """Find the Codex CLI installed by the desktop app or available on PATH."""
    candidates = [
        shutil.which("codex"),
        "/Applications/Codex.app/Contents/Resources/codex",
    ]
    return next((path for path in candidates if path and Path(path).exists()), None)


def find_vibe_executable(repo_path: str | None = None) -> str | None:
    """Find the Mistral Vibe CLI in the active environment, repo venv, or PATH."""
    candidates = []

    if repo_path:
        repo_root = Path(repo_path)
        candidates.extend([
            repo_root / ".venv" / "bin" / "vibe",
            repo_root / "venv" / "bin" / "vibe",
        ])

    if sys.executable:
        candidates.append(Path(sys.executable).with_name("vibe"))

    candidates.append(Path.home() / ".local" / "bin" / "vibe")

    for candidate in candidates:
        if candidate.exists() and os.access(candidate, os.X_OK):
            return str(candidate)

    return shutil.which("vibe")


def run_opencode_diagnostic() -> int:
    """Führt eine strukturierte OpenCode-Diagnose aus und gibt das Ergebnis aus.

    Prüft:
    1. Ob das opencode-Executable gefunden wird
    2. Ob es ausführbar ist (opencode --version)
    3. Ob der Benutzer authentifiziert ist (opencode auth list)

    Returns:
        0 wenn alles ok, 1 bei Problemen
    """
    print("OpenCode Diagnostic")
    print("=" * 50)

    opencode_exe = find_opencode_executable()
    if not opencode_exe:
        print_err("OpenCode CLI nicht gefunden")
        print("   Installieren: https://opencode.ai/docs/installation")
        print("   Danach `opencode` im PATH verfügbar machen")
        return 1

    print(f"  Executable: {opencode_exe}")

    try:
        version_result = subprocess.run(
            [opencode_exe, "--version"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if version_result.returncode == 0:
            version = (version_result.stdout or version_result.stderr).strip()
            print(f"  Version:    {version or '(keine Ausgabe)'}")
        else:
            print_warn("OpenCode --version fehlgeschlagen")
            print(f"    exit code: {version_result.returncode}")
            print(f"    stderr:    {version_result.stderr[:200]}")
            return 1
    except (OSError, subprocess.TimeoutExpired) as exc:
        print_err(f"OpenCode --version fehlgeschlagen: {exc}")
        return 1

    _print_opencode_state_preflight(opencode_exe, version)

    try:
        auth_result = subprocess.run(
            [opencode_exe, "auth", "list"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        auth_stdout = (auth_result.stdout or "").strip()
        auth_stderr = (auth_result.stderr or "").strip()
        combined = (auth_stdout + auth_stderr).lower()

        if auth_result.returncode == 0 and "credentials" in combined and "0 credentials" not in combined:
            print("  Auth:       ✅ Authentifiziert")
            if auth_stdout:
                for line in auth_stdout.splitlines():
                    print(f"    {line}")
        elif auth_result.returncode == 0 and "0 credentials" in combined:
            print("  Auth:       ⚠️  Nicht authentifiziert")
            print("    → opencode auth login")
        else:
            print_warn(f"OpenCode Auth-Status unbekannt (exit {auth_result.returncode})")
            if auth_stderr:
                print(f"    {auth_stderr[:200]}")
    except (OSError, subprocess.TimeoutExpired) as exc:
        print_warn(f"OpenCode Auth-Check fehlgeschlagen: {exc}")

    print()
    print("  Verwendung:")
    print(f"    python scripts/solve_issues.py --model opencode")
    print(f"    python scripts/solve_issues.py --model opencode --model-name opencode/deepseek-v4-flash-free")
    print(f"    python scripts/solve_issues.py --model opencode --model-name mistral/mistral-small-2603")
    print(f"    python scripts/solve_issues.py --model opencode --model-name claude-sonnet-4-20250514")
    print(f"    python scripts/solve_issues.py --model opencode --model-name gpt-4o")
    print(f"    python scripts/solve_issues.py --model opencode --dry-run")
    print(f"  Freie OpenCode-Modelle (kein API-Key nötig): opencode/deepseek-v4-flash-free, opencode/mimo-v2.5-free, opencode/minimax-m3-free, opencode/nemotron-3-ultra-free")
    print("=" * 50)

    return 0


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


def normalize_repo_relative_path_text(path_text: str) -> str:
    normalized = Path(path_text).as_posix()
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized


def clean_worker_secret_path_candidate(candidate: str) -> str:
    return candidate.strip().strip(" \t\r\n'\"“”‘’,;:()[]{}<>")


def is_secret_worker_path(path_text: str) -> bool:
    normalized = normalize_repo_relative_path_text(clean_worker_secret_path_candidate(path_text))
    if not normalized or normalized in SAFE_SECRET_EXAMPLE_PATHS:
        return False
    return (
        normalized in SECRET_WORKER_PATHS
        or any(normalized.startswith(prefix) for prefix in SECRET_WORKER_PREFIXES)
    )


def sanitize_worker_prompt_secret_paths(text: str, repo_path: str) -> str:
    """Entfernt echte Secret-Dateipfade aus Worker-Prompts."""
    repo_root = Path(repo_path).resolve()

    def replacement(path_text: str, trailing: str = "") -> str:
        return f"{SECRET_WORKER_PATH_REPLACEMENT}{trailing}"

    def replace_absolute(match: re.Match) -> str:
        raw_path, trailing = _split_trailing_path_punctuation(match.group(0))
        candidate = Path(raw_path)
        if not candidate.is_absolute():
            return match.group(0)

        resolved = candidate.resolve(strict=False)
        if not is_relative_to(resolved, repo_root):
            return match.group(0)

        relative = resolved.relative_to(repo_root).as_posix()
        if is_secret_worker_path(relative):
            return replacement(relative, trailing)
        return match.group(0)

    sanitized = ABSOLUTE_PATH_RE.sub(replace_absolute, text)

    for candidate in sorted(
        collect_issue_path_candidates(sanitized),
        key=len,
        reverse=True,
    ):
        cleaned = clean_worker_secret_path_candidate(candidate)
        if not is_secret_worker_path(cleaned):
            continue
        sanitized = re.sub(
            rf"(?<![\w./-]){re.escape(cleaned)}(?![\w./-])",
            SECRET_WORKER_PATH_REPLACEMENT,
            sanitized,
        )

    return sanitized


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

    if is_secret_worker_path(candidate):
        return None

    repo_root = Path(repo_path).resolve()
    target = (repo_root / path).resolve()
    if not is_relative_to(target, repo_root):
        return None

    if target.exists():
        if not target.is_file():
            return None
    else:
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

    aider = find_aider_executable() or "aider"

    # Solver-lokale Pfade für Chat- und Input-History verwenden
    state_dir, _ = ensure_solver_directories()
    chat_history_file = state_dir / "aider.chat.history.md"
    input_history_file = state_dir / "aider.input.history"

    cmd = [
        aider,
        *flags,
        "--yes",                   # Automatisch ja sagen
        "--no-auto-commits",       # Wir committen selbst
        "--no-check-update",       # Kein Schreibzugriff auf ~/.aider/caches nötig
        "--no-analytics",          # Keine Telemetrie im nicht-interaktiven Worker
        "--no-gitignore",          # Keine automatischen .gitignore-Nebenwirkungen
        "--chat-history-file", str(chat_history_file),
        "--input-history-file", str(input_history_file),
        "--map-tokens", "0",       # Kein repo-lokaler .aider.tags.cache
        "--subtree-only",          # Repo-Kontext auf den geklonten Arbeitsbaum begrenzen
        "--message", prompt,       # Direkt-Prompt (kein interaktiver Modus)
        *targets,
    ]

    return cmd


def build_worker_env(model: str, config: dict, base_env: dict[str, str] | None = None) -> dict[str, str]:
    """Erzeugt die Worker-Umgebung und validiert provider-spezifische Pflichtwerte."""
    env = dict(base_env if base_env is not None else os.environ)
    model_config = MODEL_CONFIGS[model]
    env_key = model_config.get("env_key")
    if env_key:
        api_key = require_config_value(config, env_key)
        env[model_config["env_var"]] = api_key

    if model == "ollama":
        ollama_host = config.get("OLLAMA_HOST", "http://localhost:11434")
        env["OLLAMA_API_BASE"] = ollama_host

    if model == "opencode":
        env = prepare_opencode_worker_environment(env)
        env.pop("GITHUB_TOKEN", None)
        env.pop("GH_TOKEN", None)
    else:
        # Entferne OpenCode-spezifische Variablen für nicht-OpenCode-Worker
        env.pop("OPENCODE_AUTH_FILE", None)
        env.pop("OPENCODE_STATE_DIR", None)
        env.pop("OPENCODE_CACHE_DIR", None)

    if model in ("openrouter", "openrouter_direct"):
        # OpenRouter benoetigt explizit OPENROUTER_API_KEY in der Umgebung
        # und wir entfernen andere Provider-Keys zur Sicherheit
        env.pop("ANTHROPIC_API_KEY", None)
        env.pop("MISTRAL_API_KEY", None)
        env.pop("OPENAI_API_KEY", None)

    return env


def build_codex_command(
    prompt: str,
    repo_path: str,
    model_name: str | None = None,
    additional_dirs: list[str] | None = None,
    sandbox_mode: str = "workspace-write",
) -> list:
    codex = find_codex_executable()
    if not codex:
        raise FileNotFoundError("codex")

    cmd = [
        codex,
        "exec",
        "--cd", repo_path,
        "--sandbox", sandbox_mode,
    ]
    if model_name:
        cmd.extend(["--model", model_name])
    if additional_dirs:
        for dir_path in additional_dirs:
            cmd.extend(["--add-dir", dir_path])
    cmd.append(prompt)
    return cmd

def build_vibe_command(prompt: str, repo_path: str,
                       max_turns: int = 30,
                       output: str = "text") -> list:
    vibe = find_vibe_executable(repo_path)
    if not vibe:
        raise FileNotFoundError("vibe")

    return [
        vibe,
        "--workdir", repo_path,
        "--trust",
        "-p", prompt,
        "--max-turns", str(max_turns),
        "--output", output,
    ]


OPENCODE_REPO_RELATIVE_INSTRUCTIONS = """OpenCode wurde bereits mit `--dir` im geklonten Repository gestartet.
Verwende fuer Dateioperationen ausschliesslich repo-relative Pfade wie `scripts/datei.py`.
Wenn eine Pfadangabe auf dieses Repository zeigt, nutze den entsprechenden relativen Pfad und nicht den absoluten temporaeren Worktree-Pfad.
Lies, kopiere oder bearbeite keine echten Secret-Dateien wie `.env`, `.env.*`, `config/.env` oder `config/.env.*`.
Nutze fuer Konfigurationsbeispiele ausschliesslich sichere Beispiel-Dateien wie `config/config.example.env` oder `.env.example`.

WICHTIG: Gib NIEMALS absolute Pfade ausserhalb des Repositories an (z. B. `/tmp/ai-solver-xyz/`). Solche Pfade werden ignoriert oder durch Platzhalter ersetzt."""


def _split_trailing_path_punctuation(path_text: str) -> tuple[str, str]:
    trailing = ""
    while path_text and path_text[-1] in ".,;:)]}":
        trailing = path_text[-1] + trailing
        path_text = path_text[:-1]
    return path_text, trailing


def relativize_repo_absolute_paths(text: str, repo_path: str) -> str:
    """Ersetzt absolute repo-interne Pfade im Prompt durch repo-relative Pfade.
    Entfernt absolute Pfade ausserhalb des Repos (z. B. temporaere Worktree-Pfade),
    behält aber URLs und Backticks bei. Repo-interne Pfade in /var/folders/ werden relativiert."""
    repo_root = Path(repo_path).resolve()

    def replace_match(match: re.Match) -> str:
        raw_path, trailing = _split_trailing_path_punctuation(match.group(0))
        # Backticks extrahieren und später wieder hinzufügen
        leading_backtick = "`" if match.group(0).startswith("`") else ""
        trailing_backtick = "`" if match.group(0).endswith("`") else ""
        raw_path = raw_path.strip("`")

        candidate = Path(raw_path)
        if not candidate.is_absolute():
            return match.group(0)

        # URLs behalten, aber /var/folders/ nur, wenn sie außerhalb des Repos liegen
        if raw_path.startswith(('http://', 'https://')):
            return match.group(0)

        resolved = candidate.resolve(strict=False)
        if not is_relative_to(resolved, repo_root):
            # Alle externen Pfade entfernen, einschließlich /var/folders/
            return f"{leading_backtick}<EXTERNAL_PATH_REMOVED>{trailing_backtick}{trailing}"

        relative = resolved.relative_to(repo_root).as_posix()
        if is_secret_worker_path(relative):
            return f"{leading_backtick}{SECRET_WORKER_PATH_REPLACEMENT}{trailing_backtick}{trailing}"
        return f"{leading_backtick}{relative}{trailing_backtick}{trailing}"

    return ABSOLUTE_PATH_RE.sub(replace_match, text)


def build_opencode_prompt(prompt: str, repo_path: str) -> str:
    """Bereitet den Prompt so vor, dass OpenCode repo-relative Pfade nutzt."""
    sanitized_prompt = sanitize_worker_prompt_secret_paths(prompt, repo_path)
    normalized_prompt = relativize_repo_absolute_paths(sanitized_prompt, repo_path)
    return f"{OPENCODE_REPO_RELATIVE_INSTRUCTIONS}\n\n{normalized_prompt}"


def build_opencode_command(prompt: str, repo_path: str,
                           model_name: str | None = None) -> list:
    opencode = find_opencode_executable(repo_path)
    if not opencode:
        raise FileNotFoundError("opencode")

    cmd = [
        opencode,
        "run",
        "--dir", repo_path,
    ]
    if model_name:
        cmd.extend(["--model", model_name])
    cmd.append(build_opencode_prompt(prompt, repo_path))
    return cmd


def get_worker_display_name(model: str) -> str:
    """Gibt den Anzeigenamen für ein Worker-Modell zurück."""
    return MODEL_CONFIGS[model]["display_name"]


def preflight_temp_dir_check(temp_dir: str) -> list[str]:
    """Prüft Schreibrechte im Temp-Verzeichnis und gibt zusätzliche --add-dir-Pfade zurück."""
    additional_dirs = []
    if not os.access(temp_dir, os.W_OK):
        # Versuche, workspace-temp im ursprünglichen Verzeichnis zu erstellen
        workspace_temp = os.path.join(temp_dir, "workspace-temp")
        try:
            os.makedirs(workspace_temp, exist_ok=True)
            if os.access(workspace_temp, os.W_OK):
                additional_dirs.append(workspace_temp)
        except OSError as exc:
            print_warn(f"Konnte workspace-temp nicht erstellen: {exc}")
            # Fallback auf /tmp, falls das ursprüngliche Verzeichnis nicht beschreibbar ist
            fallback_temp = os.path.join("/tmp", "ai-issue-solver-workspace")
            try:
                os.makedirs(fallback_temp, exist_ok=True)
                if os.access(fallback_temp, os.W_OK):
                    additional_dirs.append(fallback_temp)
                    print_warn(f"Verwende Fallback-Verzeichnis: {fallback_temp}")
            except OSError as fallback_exc:
                print_warn(f"Konnte Fallback-Verzeichnis nicht erstellen: {fallback_exc}")
    return additional_dirs


# ─────────────────────────────────────────────────────────────
# Codex Environment Preflight (gh + Python requests)
# ─────────────────────────────────────────────────────────────

# Schmale Auswahl von Befehlen, die im Codex-Sandbox häufig als
# Eskalations-Prefix empfohlen werden. Bewusst kurz gehalten, damit
# die Empfehlungen task-spezifisch bleiben und nicht zu einer breiten
# Allowlist auswachsen.
SANDBOX_ESCALATION_COMMANDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "git pull --ff-only",
        ("git pull --ff-only",),
    ),
    (
        "git switch",
        ("git switch",),
    ),
    (
        "gh pr checks",
        ("gh pr checks",),
    ),
    (
        "gh run view",
        ("gh run view",),
    ),
)

# Substrings, die auf einen DNS- bzw. Netzwerkfehler hindeuten.
SANDBOX_NETWORK_ERROR_PATTERNS: tuple[str, ...] = (
    "Could not resolve host",
    "Name or service not known",
    "Temporary failure in name resolution",
    "Failed to connect to",
    "Connection refused",
    "Connection reset",
    "Network is unreachable",
    "getaddrinfo failed",
    "nodename nor servname provided",
    "TLS connect error",
    "ssl3_get_record: wrong version number",
    "Network unreachable",
    "ENETUNREACH",
    "EAI_AGAIN",
)

# Substrings, die auf einen fehlgeschlagenen Schreibzugriff innerhalb
# von `.git/` hinweisen (z. B. blockierte FETCH_HEAD-Datei oder ein
# hängender index.lock).
GIT_WRITE_PERMISSION_PATTERNS: tuple[tuple[str, str], ...] = (
    ("FETCH_HEAD", ".git/FETCH_HEAD konnte nicht geschrieben werden"),
    ("index.lock", "Bestehende .git/index.lock blockiert den Index-Update"),
    ("Permission denied", "Fehlende Schreibrechte im .git/-Verzeichnis"),
    ("Read-only file system", ".git/-Verzeichnis ist schreibgeschützt gemountet"),
    ("Operation not permitted", "Sandbox blockiert Schreibzugriff auf .git/"),
)


@dataclass(frozen=True)
class CodexEnvPreflight:
    """Ergebnis des Codex-Environment-Preflights.

    Attributes:
        gh_ok: True, wenn `gh api user` mit Exit 0 antwortet (oder gh fehlt).
        gh_skipped: True, wenn `gh` nicht installiert ist; dann ist gh_ok = False.
        requests_ok: True, wenn der requests-basierte API-Ping 200/401/403 liefert.
        api_user: Antwort der requests-Probe (soweit extrahierbar).
        error: Fehlermeldung der requests-Probe, falls aufgetreten.
    """

    gh_ok: bool
    gh_skipped: bool
    requests_ok: bool
    api_user: str | None = None
    error: str | None = None


@dataclass(frozen=True)
class SandboxFailureDiagnosis:
    """Klassifiziert eine Sandbox- oder Git-Fehlermeldung.

    Attributes:
        kind: "network", "git_write" oder "unknown".
        matched_pattern: Erkanntes Muster (oder None).
        hint: Kurze, task-spezifische Eskalations-Empfehlung.
    """

    kind: str
    matched_pattern: str | None
    hint: str


def _run_gh_api_user_probe(timeout: float = 8.0) -> tuple[bool, bool, str | None]:
    """Probiert `gh api user` und liefert (ok, skipped, error)."""
    gh_path = shutil.which("gh")
    if not gh_path:
        return False, True, "gh nicht im PATH"

    try:
        result = subprocess.run(
            [gh_path, "api", "user"],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        return False, False, f"gh api user fehlgeschlagen: {exc}"

    if result.returncode == 0:
        return True, False, None
    error_text = (result.stderr or result.stdout or "").strip()
    return False, False, error_text or f"gh exit {result.returncode}"


def _run_requests_api_user_probe(
    token: str,
    timeout: float = 8.0,
) -> tuple[bool, str | None, str | None]:
    """Probiert die GitHub-API via Python-requests und liefert (ok, user, error)."""
    if requests is None:
        return False, None, "Python-Modul 'requests' ist nicht installiert"

    try:
        resp = requests.get(
            "https://api.github.com/user",
            headers={
                "Authorization": f"token {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            timeout=timeout,
        )
    except requests.RequestException as exc:
        return False, None, str(exc)

    if resp.status_code == 200:
        try:
            payload = resp.json()
        except ValueError:
            payload = {}
        user_login = payload.get("login") if isinstance(payload, dict) else None
        return True, user_login, None

    return False, None, f"HTTP {resp.status_code}: {(resp.text or '').strip()[:200]}"


def run_codex_environment_preflight(
    config: dict,
    *,
    timeout: float = 8.0,
    runner=None,
) -> CodexEnvPreflight:
    """Führt einen leichten Codex-Environment-Preflight aus.

    Prüft parallel den GitHub-Zugang über `gh api user` (sofern verfügbar)
    und über Python-`requests`. Beide Pfade werden unabhängig ausgewertet,
    damit ein Sandbox-DNS-Fehler nicht automatisch den anderen Pfad
    mit-abbricht.

    Args:
        config: Solver-Konfiguration mit GITHUB_TOKEN/GITHUB_USER.
        timeout: Timeout pro Probe in Sekunden.
        runner: Optional austauschbare Probe-Funktion für Tests; muss
            ``(token: str, timeout: float) -> tuple[bool, str | None, str | None]``
            zurückgeben.

    Returns:
        CodexEnvPreflight mit dem zusammengefassten Ergebnis.
    """
    token, _user = require_github_config(config, require_user=False)

    gh_ok, gh_skipped, _gh_error = _run_gh_api_user_probe(timeout=timeout)

    requests_runner = runner or _run_requests_api_user_probe
    requests_ok, api_user, requests_error = requests_runner(token, timeout=timeout)

    return CodexEnvPreflight(
        gh_ok=gh_ok,
        gh_skipped=gh_skipped,
        requests_ok=requests_ok,
        api_user=api_user,
        error=requests_error,
    )


def print_codex_environment_preflight(
    preflight: CodexEnvPreflight,
    *,
    user: str | None = None,
) -> None:
    """Gibt das Ergebnis des Codex-Environment-Preflights kompakt aus."""
    if preflight.gh_skipped:
        gh_line = "ℹ️  gh-CLI nicht installiert (übersprungen)"
    elif preflight.gh_ok:
        gh_line = "✅ gh api user erreichbar"
    else:
        gh_line = "⚠️  gh api user fehlgeschlagen (siehe Hinweis oben)"

    if preflight.requests_ok:
        login = preflight.api_user or "(unbekannt)"
        target = f" für {user}" if user else ""
        requests_line = f"✅ requests /user ok{target} (Login: {login})"
    elif preflight.error:
        requests_line = f"⚠️  requests /user fehlgeschlagen: {preflight.error}"
    else:
        requests_line = "⚠️  requests /user fehlgeschlagen (ohne Detail)"

    print(f"   {gh_line}")
    print(f"   {requests_line}")

    if not preflight.requests_ok and "Could not resolve" in (preflight.error or ""):
        print(
            "   → Eskalations-Hinweis: Sandbox-DNS blockiert; "
            "siehe Beispiel 08 (helpers/escalation_recommendation.md)."
        )


# ─────────────────────────────────────────────────────────────
# Sandbox-/Git-Fehlerklassifizierung (Issue #217)
# ─────────────────────────────────────────────────────────────

# Bewusst klein gehaltene Empfehlungen, die nur den jeweils passenden
# Escalation-Prefix vorschlagen. Sie wachsen NICHT zu einer breiten
# Allowlist.
_NETWORK_HINT = (
    "Sandbox-Block: DNS/Netzwerk fehlgeschlagen. "
    "Erneut mit '--sandbox danger-full-access' oder ausserhalb der Sandbox versuchen."
)
_GIT_WRITE_HINT_FETCH_HEAD = (
    "Sandbox-Block: .git/FETCH_HEAD nicht beschreibbar. "
    "Mit '--sandbox danger-full-access' erneut versuchen oder vor dem Pull `git remote set-head origin -a` ausführen."
)
_GIT_WRITE_HINT_INDEX_LOCK = (
    "Bestehende .git/index.lock blockiert den Index-Update. "
    "Vor erneutem Run `rm -f .git/index.lock` ausführen oder `--sandbox danger-full-access` verwenden."
)
_GIT_WRITE_HINT_PERMISSION = (
    "Schreibrechte im .git/-Verzeichnis fehlen. "
    "Mit '--sandbox danger-full-access' erneut versuchen oder Sandbox-Mounts prüfen."
)
_GIT_WRITE_HINT_READONLY = (
    ".git/-Verzeichnis ist schreibgeschützt gemountet. "
    "Repo-Klon in ein beschreibbares Verzeichnis legen (siehe helper preflight_temp_dir_check)."
)
_GIT_WRITE_HINT_OPERATION = (
    "Sandbox blockiert Schreiboperationen im .git/. "
    "Mit '--sandbox danger-full-access' oder ausserhalb der Sandbox wiederholen."
)
_UNKNOWN_HINT = (
    "Fehlerursache unbekannt; vollständigen Worker-Output prüfen und ggf. "
    "Beispiel 08 (helpers/escalation_recommendation.md) konsultieren."
)


def classify_sandbox_failure(text: str) -> SandboxFailureDiagnosis:
    """Klassifiziert einen Sandbox-/Git-Fehler-String.

    Die Klassifizierung ist absichtlich schmal: Sie erkennt nur die
    häufigsten DNS/Netzwerk- und .git-Schreibrechte-Muster und liefert
    eine konkrete Escalation-Empfehlung. Alles andere wird als
    ``unknown`` markiert.

    Args:
        text: Fehlermeldung oder Worker-Output-Snippet.

    Returns:
        SandboxFailureDiagnosis mit ``kind``, ``matched_pattern`` und ``hint``.
    """
    if not text:
        return SandboxFailureDiagnosis("unknown", None, _UNKNOWN_HINT)

    normalized = text.lower()

    for pattern in SANDBOX_NETWORK_ERROR_PATTERNS:
        if pattern.lower() in normalized:
            return SandboxFailureDiagnosis(
                "network", pattern, _NETWORK_HINT
            )

    for needle, description in GIT_WRITE_PERMISSION_PATTERNS:
        if needle.lower() in normalized:
            if needle == "FETCH_HEAD":
                hint = _GIT_WRITE_HINT_FETCH_HEAD
            elif needle == "index.lock":
                hint = _GIT_WRITE_HINT_INDEX_LOCK
            elif needle == "Permission denied":
                hint = _GIT_WRITE_HINT_PERMISSION
            elif needle == "Read-only file system":
                hint = _GIT_WRITE_HINT_READONLY
            else:
                hint = _GIT_WRITE_HINT_OPERATION
            return SandboxFailureDiagnosis("git_write", description, hint)

    return SandboxFailureDiagnosis("unknown", None, _UNKNOWN_HINT)


def recommend_escalation_prefix(command: str) -> str | None:
    """Gibt einen schmalen Escalation-Prefix für bekannte Kommandos zurück.

    Die Empfehlungen sind bewusst task-spezifisch; unbekannte Kommandos
    liefern ``None``. Damit soll verhindert werden, dass sich über die
    Zeit eine breite Allowlist ansammelt.
    """
    if not command:
        return None
    stripped = command.strip()
    if not stripped:
        return None
    for prefix, options in SANDBOX_ESCALATION_COMMANDS:
        if any(stripped == opt or stripped.startswith(opt + " ") for opt in options):
            return prefix
    return None


def format_escalation_recommendation(diagnosis: SandboxFailureDiagnosis) -> str:
    """Formatiert die Eskalations-Empfehlung für einen Diagnose-Eintrag."""
    if diagnosis.kind == "network":
        return (
            "DNS/Netzwerk erkannt → "
            + diagnosis.hint
        )
    if diagnosis.kind == "git_write":
        return (
            "Git-Schreibrechte erkannt → "
            + diagnosis.hint
        )
    return diagnosis.hint


def get_worker_adapter(model: str):
    """
    Factory-Funktion: Gibt den passenden WorkerAdapter für ein Modell zurück.

    Kapselt die Zuordnung von Modell-Namen zu Adapter-Klassen, sodass
    ``solve_issue()`` provider-agnostisch arbeiten kann.

    Args:
        model: Provider-Name (codex, opencode, mistral-vibe, openrouter_direct
               oder ein Aider-Provider: claude, openai, mistral, ollama, openrouter).

    Returns:
        WorkerAdapter-Instanz für den angegebenen Provider.

    Raises:
        ValueError: Bei unbekanntem Provider-Namen.
    """
    from workers.codex_adapter import CodexAdapter
    from workers.opencode_adapter import OpenCodeAdapter
    from workers.mistral_vibe_adapter import MistralVibeAdapter
    from workers.openrouter_direct_adapter import OpenRouterDirectAdapter
    from workers.aider_adapter import AiderAdapter, AIDER_MODEL_CONFIGS

    if model == "codex":
        return CodexAdapter()
    elif model == "opencode":
        return OpenCodeAdapter()
    elif model == "mistral-vibe":
        return MistralVibeAdapter()
    elif model == "openrouter_direct":
        return OpenRouterDirectAdapter()
    elif model in AIDER_MODEL_CONFIGS:
        return AiderAdapter(provider=model)
    else:
        raise ValueError(f"Unbekannter Worker-Provider: '{model}'")


def build_worker_command(
    model: str,
    model_name: str,
    prompt: str,
    repo_path: str,
    file_targets: list[str] | None = None,
    additional_dirs: list[str] | None = None,
    config: dict | None = None,
) -> list[str] | str:
    """Baut den KI-Worker-Befehl basierend auf dem Modell.

    Zentralisiert die Command-Konstruktion für alle unterstützten Worker.
    Für aider kann optional eine Liste von Dateizielen übergeben werden.
    Für model_name wird None an die Builder weitergegeben, falls nicht gesetzt.

    Args:
        model: Das zu verwendende Modell (codex, claude, openai, mistral, ollama, mistral-vibe, opencode, openrouter_direct)
        model_name: Spezifischer Modellname oder leerer String
        prompt: Der Prompt für den Worker
        repo_path: Pfad zum Repository
        file_targets: Optionale Liste von Dateizielen (nur für aider relevant)
        additional_dirs: Zusätzliche Verzeichnisse für Codex Sandbox (nur für codex relevant)
        config: Konfigurationsdaten für API-Keys und Einstellungen

    Returns:
        list[str]: Die Befehlszeile als Liste von String-Argumenten (für CLI-Worker).

    Raises:
        ValueError: Wenn model == "openrouter_direct" — dieser Worker hat einen eigenen
                    Ausführungspfad über run_openrouter_direct_worker().
    """
    effective_model_name = model_name if model_name else None
    safe_prompt = sanitize_worker_prompt_secret_paths(prompt, repo_path)
    config = config or {}

    if model == "codex":
        return build_codex_command(safe_prompt, repo_path, effective_model_name, additional_dirs)
    elif model == "mistral-vibe":
        return build_vibe_command(safe_prompt, repo_path)
    elif model == "opencode":
        return build_opencode_command(safe_prompt, repo_path, effective_model_name)
    elif model == "openrouter_direct":
        # openrouter_direct hat einen eigenen Ausführungspfad — siehe run_openrouter_direct_worker()
        raise ValueError(
            "openrouter_direct darf nicht über build_worker_command aufgerufen werden. "
            "Verwende stattdessen run_openrouter_direct_worker()."
        )
    else:
        return build_aider_command(model, model_name, safe_prompt, repo_path, file_targets)


def run_worker_command(cmd: list, repo_dir: str, env: dict,
                       run_report: RunReport | None = None,
                       verbosity: str = "normal") -> WorkerRunResult:
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
    last_activity_at = datetime.now()
    if run_report:
        write_run_health(
            run_report,
            status="running",
            phase="worker_running",
            worker_pid=process.pid,
        )
    if process.stdout:
        for line in process.stdout:
            output_parts.append(line)
            if verbosity == "verbose":
                if line.strip():
                    print(f"        | {line}", end="")
                last_activity_at = datetime.now()
                if run_report:
                    write_run_health(run_report, "".join(output_parts), last_activity_at,
                                     phase="worker_running", worker_pid=process.pid)
            elif verbosity == "normal":
                if should_surface_worker_line(line):
                    print(f"        | {line}", end="")
                    last_activity_at = datetime.now()
                    if run_report:
                        write_run_health(run_report, "".join(output_parts), last_activity_at,
                                         phase="worker_running", worker_pid=process.pid)
                else:
                    suppressed_lines += 1
            else:
                # quiet: nichts drucken, aber Aktivitaet tracken
                if should_surface_worker_line(line):
                    last_activity_at = datetime.now()
                    if run_report:
                        write_run_health(run_report, "".join(output_parts), last_activity_at,
                                         phase="worker_running", worker_pid=process.pid)
                else:
                    suppressed_lines += 1
        process.stdout.close()

    if verbosity != "quiet":
        print_worker_suppression_summary(suppressed_lines)

    return WorkerRunResult(
        returncode=process.wait(),
        output="".join(output_parts),
        last_activity_at=last_activity_at,
    )


def run_openrouter_direct_worker(
    prompt: str,
    repo_dir: str,
    model_name: str,
    api_key: str | None = None,
    verbosity: str = "normal",
) -> WorkerRunResult:
    """Fuehrt den OpenRouter-Direct-Worker aus und gibt ein WorkerRunResult zurueck.

    Dieser Worker ruft die OpenRouter API direkt auf, extrahiert Unified-Diff-Patches
    aus der Modellantwort und wendet sie im Repository-Verzeichnis an.

    Returncode-Semantik (aus DirectRunResult):
        0  — Mindestens ein Patch erfolgreich angewendet.
        1  — Patches gefunden, aber alle fehlgeschlagen oder API-Fehler.
        2  — Modell hat Prosa ohne auswertbare Diffs zurueckgegeben.

    Args:
        prompt: Eingabe-Prompt fuer das Modell (bereits sanitiert).
        repo_dir: Absoluter Pfad zum Ziel-Repository-Verzeichnis.
        model_name: OpenRouter Modell-String (z. B. "mistralai/mistral-large").
        api_key: Optionaler API-Key; wird sonst aus OPENROUTER_API_KEY gelesen.

    Returns:
        WorkerRunResult mit Returncode und kombiniertem Log-Output.
    """
    from workers.openrouter_worker import OpenRouterWorker, DirectRunResult

    # Fehlender API-Key fruehzeitig abfangen
    effective_key = api_key or os.getenv("OPENROUTER_API_KEY")
    if not effective_key:
        error_msg = "[openrouter_direct] FEHLER: OPENROUTER_API_KEY ist nicht gesetzt."
        print_err(error_msg)
        return WorkerRunResult(returncode=1, output=error_msg)

    worker = OpenRouterWorker(api_key=effective_key, model=model_name)

    direct_result: DirectRunResult = worker.run_direct(
        prompt=prompt,
        repo_dir=repo_dir,
    )

    # Ausgabe live anzeigen (zeilenweise gefiltert)
    suppressed_lines = 0
    last_activity_at = datetime.now()
    for line in direct_result.output.splitlines(keepends=True):
        if verbosity == "verbose":
            if line.strip():
                print(f"        | {line}", end="")
            last_activity_at = datetime.now()
        elif verbosity == "normal":
            if should_surface_worker_line(line):
                print(f"        | {line}", end="")
                last_activity_at = datetime.now()
            else:
                suppressed_lines += 1
        else:
            if should_surface_worker_line(line):
                last_activity_at = datetime.now()
            else:
                suppressed_lines += 1
    if verbosity != "quiet":
        print_worker_suppression_summary(suppressed_lines)

    return WorkerRunResult(
        returncode=direct_result.returncode,
        output=direct_result.output,
        last_activity_at=last_activity_at,
    )


def print_worker_suppression_summary(count: int) -> None:
    if count:
        print(f"        | ... {count} Detailzeilen ausgeblendet; Rohoutput bleibt in der Diagnose erhalten")


def read_vibe_log_snippet(repo_dir: str) -> str:
    """Liest ein kompakter Snippet aus der Vibe-Log-Datei, falls vorhanden.

    Sucht nach .vibe/logs/vibe.log im Arbeitsverzeichnis und extrahiert die
    letzten relevanten Zeilen. Gibt einen leeren String zurueck, wenn die
    Datei nicht existiert oder nicht lesbar ist.
    """
    vibe_log = Path(repo_dir) / VIBE_LOG_PATH
    if not vibe_log.exists():
        return ""

    try:
        content = vibe_log.read_text(encoding="utf-8", errors="replace")
    except (OSError, UnicodeDecodeError):
        return ""

    if not content.strip():
        return ""

    lines = content.strip().splitlines()
    # Filtere relevante Zeilen (aehnlich wie bei Worker-Output)
    relevant_lines = [line for line in lines if line.strip() and should_surface_worker_line(line)]

    if not relevant_lines:
        # Falls keine relevanten Zeilen gefunden, nimm die letzten Zeilen
        relevant_lines = lines[-VIBE_LOG_SNIPPET_LINES:] if len(lines) > VIBE_LOG_SNIPPET_LINES else lines
    else:
        # Nimm die letzten relevanten Zeilen
        relevant_lines = relevant_lines[-VIBE_LOG_SNIPPET_LINES:]

    snippet = "\n".join(relevant_lines)

    # Begrenze auf maximale Laenge
    if len(snippet) > VIBE_LOG_SNIPPET_CHARS:
        snippet = snippet[-VIBE_LOG_SNIPPET_CHARS:]
        # Versuche, an einer Zeilengrenze zu schneiden
        last_newline = snippet.rfind("\n")
        if last_newline > 0:
            snippet = snippet[last_newline + 1:]

    return snippet


def changed_paths_from_status(git_status: str) -> list[Path]:
    paths: list[Path] = []
    for line in git_status.splitlines():
        if len(line) < 4:
            continue
        path_text = line[3:].strip()
        if " -> " in path_text:
            path_text = path_text.rsplit(" -> ", 1)[1]
        path_text = path_text.strip('"')
        if path_text:
            paths.append(Path(path_text))
    return paths


def issue_mentions_generic_path(path: Path, issue_text: str) -> bool:
    normalized = issue_text.lower()
    name = path.name.lower()
    if name == ".gitignore":
        return "gitignore" in normalized or ".gitignore" in normalized
    if name.startswith("license"):
        return "license" in normalized or "lizenz" in normalized
    return False


def is_worker_side_effect_path(path: Path) -> bool:
    path_text = path.as_posix()
    return any(path.match(pattern) or path_text == pattern for pattern in WORKER_SIDE_EFFECT_PATTERNS)


def is_empty_file(repo_dir: str, path: Path) -> bool:
    try:
        return (Path(repo_dir) / path).is_file() and (Path(repo_dir) / path).stat().st_size == 0
    except OSError:
        return False


def is_nonzero_side_effect_path(path: Path, repo_dir: str | None = None,
                                issue_text: str = "") -> bool:
    if is_worker_side_effect_path(path):
        return True
    if path.as_posix() in NONZERO_GENERIC_SIDE_EFFECT_FILES:
        if issue_mentions_generic_path(path, issue_text):
            return False
        return True
    if repo_dir and path.name in NONZERO_GENERIC_SIDE_EFFECT_FILES and is_empty_file(repo_dir, path):
        return not issue_mentions_generic_path(path, issue_text)
    return False


def meaningful_changed_paths_for_worker(git_status: str, repo_dir: str | None = None,
                                        issue_text: str = "",
                                        worker_returncode: int = 0) -> list[Path]:
    paths = changed_paths_from_status(git_status)
    if worker_returncode == 0:
        return paths
    return [
        path for path in paths
        if not is_nonzero_side_effect_path(path, repo_dir=repo_dir, issue_text=issue_text)
    ]


def conflict_marker_line(path: Path) -> int | None:
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                if CONFLICT_MARKER_RE.match(line.rstrip("\n")):
                    return line_number
    except (OSError, UnicodeDecodeError):
        return None
    return None


def validate_worker_changes(repo_dir: str, git_status: str | None = None) -> WorkerValidation:
    status = git_status if git_status is not None else git_status_porcelain(repo_dir)
    repo_root = Path(repo_dir)
    errors: list[str] = []
    changed_paths = changed_paths_from_status(status)

    for relative_path in changed_paths:
        path = repo_root / relative_path
        if not path.exists():
            errors.append(f"{relative_path}: Datei konnte nicht erstellt werden (Schreibrechte?)")
            continue
        if not os.access(path, os.W_OK):
            errors.append(f"{relative_path}: Keine Schreibrechte")
            continue
        if not path.is_file():
            continue
        marker_line = conflict_marker_line(path)
        if marker_line is not None:
            errors.append(f"{relative_path}:{marker_line}: enthaelt Git-Konfliktmarker")

    python_files = [
        str(repo_root / relative_path)
        for relative_path in changed_paths
        if relative_path.suffix == ".py" and (repo_root / relative_path).is_file()
    ]
    if python_files:
        result = subprocess.run(
            [sys.executable, "-m", "py_compile", *python_files],
            cwd=repo_dir,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            first_line = (result.stderr or result.stdout).strip().splitlines()[0]
            errors.append(f"Python-Syntaxpruefung fehlgeschlagen: {first_line[:240]}")

    return WorkerValidation(ok=not errors, errors=tuple(errors))


@dataclass(frozen=True)
class PostSolveTestResult:
    """Kompaktes Ergebnis eines Post-Solve-Testlaufs.

    Felder:
        status: ``"passed"``, ``"failed"`` oder ``"not_run"``.
        command: Vollstaendige Befehlszeile (fuer PR-Body und Run-Report).
        returncode: Exit-Code des Testbefehls oder ``None``, wenn der Test
            nicht ausgefuehrt werden konnte.
        note: Optionale Zusatzinfo (z. B. Grund fuer ``not_run``).
    """
    status: str
    command: list[str]
    returncode: int | None
    note: str | None = None

    @property
    def summary(self) -> str:
        """Einzeilige Darstellung fuer PR-Body und Logs."""
        command_text = " ".join(self.command)
        prefix = f"Tests: {self.status}"
        if self.status == "not_run" and self.note:
            return f"{prefix} ({command_text}; {self.note})"
        return f"{prefix} ({command_text})"


class PostWorkerTimeoutError(RuntimeError):
    """Wird ausgeloest, wenn eine Post-Worker-Phase das Zeitbudget ueberschreitet.

    Der Solver faengt diesen Fehler in ``solve_issue`` ab, schreibt einen
    ``pr_creation_timeout``-bzw. ``pushed_without_pr``-Run-Report und
    hinterlegt einen Recovery-Hinweis inkl. PR-Befehl.
    """


@dataclass(frozen=True)
class PostWorkerPhaseResult:
    """Ergebnis einer einzelnen Post-Worker-Phase (Issue #350)."""
    phase: str
    started_at: datetime
    finished_at: datetime
    timed_out: bool = False
    error: str | None = None

    @property
    def duration_seconds(self) -> float:
        return (self.finished_at - self.started_at).total_seconds()


def _post_worker_phase_started(phase: str) -> datetime:
    """Heartbeat fuer den Watchdog: Phase + Start-Zeitpunkt festhalten.

    Wird am Anfang _jeder_ Post-Worker-Phase aufgerufen. Der externe
    Watchdog-Cron liest ``health.json`` und kann so eine haengende Phase
    erkennen.
    """
    if phase not in POST_WORKER_PHASES:
        raise ValueError(
            f"Unbekannte Post-Worker-Phase: {phase!r} (erwartet: {POST_WORKER_PHASES})"
        )
    print(f"      ▶ Post-Worker-Phase: {phase}")
    return datetime.now()


def _post_worker_phase_finished(
    run_report: RunReport | None,
    phase: str,
    started_at: datetime,
    *,
    note: str | None = None,
    last_activity: str = "",
) -> PostWorkerPhaseResult:
    """Heartbeat fuer den Watchdog: Phase sauber abschliessen."""
    finished_at = datetime.now()
    if run_report is not None:
        # Health-Datei mit aktuellem Stand aktualisieren, damit das
        # Batch-Watchdog weiss, dass diese Phase sauber durchgelaufen ist.
        write_run_health(
            run_report,
            last_activity,
            finished_at,
            status="running",
            phase=phase,
        )
    return PostWorkerPhaseResult(
        phase=phase,
        started_at=started_at,
        finished_at=finished_at,
        error=note,
    )


def _check_post_worker_deadline(
    started_at: datetime,
    deadline_seconds: float,
    phase: str,
) -> None:
    """Wirft :class:`PostWorkerTimeoutError`, wenn das Post-Worker-Budget
    ueberschritten ist.
    """
    if deadline_seconds <= 0:
        return
    elapsed = (datetime.now() - started_at).total_seconds()
    if elapsed > deadline_seconds:
        raise PostWorkerTimeoutError(
            f"Post-Worker-Phase '{phase}' ueberschritt das Zeitbudget "
            f"({int(elapsed)}s > {int(deadline_seconds)}s)"
        )


def compute_post_worker_deadline(
    run_started_at: datetime,
    max_run_runtime_seconds: float | None,
    max_post_worker_runtime_seconds: float | None,
) -> float:
    """Berechnet das verbleibende Post-Worker-Budget in Sekunden.

    Beruecksichtigt sowohl das globale ``--max-run-runtime-seconds`` als
    auch das dedizierte ``--max-post-worker-runtime-seconds``. Wenn beide
    gesetzt sind, gewinnt der kleinere Wert.
    """
    candidates: list[float] = []
    if max_post_worker_runtime_seconds and max_post_worker_runtime_seconds > 0:
        candidates.append(float(max_post_worker_runtime_seconds))
    if max_run_runtime_seconds and max_run_runtime_seconds > 0:
        elapsed = (datetime.now() - run_started_at).total_seconds()
        remaining = float(max_run_runtime_seconds) - elapsed
        if remaining > 0:
            candidates.append(remaining)
    if not candidates:
        return 0.0
    return min(candidates)


def _run_post_worker_with_watchdog(
    run_report: RunReport | None,
    phase: str,
    post_worker_started_at: datetime,
    post_worker_deadline_seconds: float,
    operation,
):
    """Fuehrt eine Post-Worker-Phase unter Watchdog-Schutz aus (Issue #350).

    Aktualisiert vor dem Start die Health-Datei (Phase + Heartbeat) und
    wirft :class:`PostWorkerTimeoutError`, sobald das Budget ueberschritten
    ist. So hinterlaesst eine haengende Phase (commit, push, PR) immer
    einen klaren ``last_phase``-Eintrag im Health-File und einen
    ``pr_creation_timeout``- bzw. ``pushed_without_pr``-Status, der im
    Watchdog als terminal und recovery-faehig erkannt wird.
    """
    phase_started = _post_worker_phase_started(phase)
    _check_post_worker_deadline(
        post_worker_started_at,
        post_worker_deadline_seconds,
        phase,
    )
    if run_report is not None:
        write_run_health(
            run_report,
            status="running",
            phase=phase,
        )
    result = operation()
    _post_worker_phase_finished(
        run_report,
        phase,
        phase_started,
    )
    return result



def format_post_solve_test_command(command: list[str] | None = None) -> list[str]:
    """Gibt den auszufuehrenden Post-Solve-Testbefehl zurueck.

    Args:
        command: Optionale Override-Liste. Fallback ist ``POST_SOLVE_TEST_COMMAND``.

    Returns:
        Befehlsliste ohne ``shell=True``-Risiko.
    """
    if command is None:
        return list(POST_SOLVE_TEST_COMMAND)
    return [str(part) for part in command]


def run_post_solve_tests(repo_dir: str,
                         command: list[str] | None = None,
                         timeout_seconds: int = POST_SOLVE_TEST_TIMEOUT_SECONDS,
                         run_fn=subprocess.run) -> PostSolveTestResult:
    """Fuehrt den Standard-Testbefehl nach einem erfolgreichen Commit aus.

    Der Befehl wird bewusst ohne ``shell=True`` gestartet. Ergebnis-Status:
        ``"passed"``  - Exit-Code 0.
        ``"failed"``  - Exit-Code != 0.
        ``"not_run"`` - Befehl konnte nicht gestartet werden oder Timeout.

    Args:
        repo_dir: Arbeitsverzeichnis, in dem der Test laufen soll.
        command: Optionaler Override des Standard-Testbefehls.
        timeout_seconds: Maximale Laufzeit; bei Ueberschreitung wird der Test
            abgebrochen und ``"not_run"`` zurueckgegeben.
        run_fn: Injizierbarer subprocess-Wrapper fuer Tests.

    Returns:
        :class:`PostSolveTestResult` mit Befehl, Status und optionaler Notiz.
    """
    effective_command = format_post_solve_test_command(command)
    try:
        completed = run_fn(
            effective_command,
            cwd=repo_dir,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return PostSolveTestResult(
            status="not_run",
            command=effective_command,
            returncode=None,
            note=f"timeout nach {timeout_seconds}s",
        )
    except (OSError, FileNotFoundError) as exc:
        return PostSolveTestResult(
            status="not_run",
            command=effective_command,
            returncode=None,
            note=f"Befehl nicht startbar: {exc}",
        )
    except Exception as exc:  # noqa: BLE001 - Tests sollen jeden Runner-Fehler abfangen
        return PostSolveTestResult(
            status="not_run",
            command=effective_command,
            returncode=None,
            note=f"unerwarteter Fehler: {exc}",
        )

    if completed.returncode == 0:
        return PostSolveTestResult(
            status="passed",
            command=effective_command,
            returncode=completed.returncode,
        )
    return PostSolveTestResult(
        status="failed",
        command=effective_command,
        returncode=completed.returncode,
    )


def assess_worker_result(result: WorkerRunResult, git_status: str,
                         repo_dir: str | None = None,
                         issue_text: str = "") -> WorkerAssessment:
    changed_paths = changed_paths_from_status(git_status)
    meaningful_paths = meaningful_changed_paths_for_worker(
        git_status,
        repo_dir=repo_dir,
        issue_text=issue_text,
        worker_returncode=result.returncode,
    )
    has_changes = bool(changed_paths)
    has_meaningful_changes = bool(meaningful_paths)
    if result.returncode == 0 and has_changes:
        return WorkerAssessment(True, True, "changed")
    if result.returncode == 0:
        return WorkerAssessment(False, False, "no_changes")
    if has_meaningful_changes:
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
        if assessment.reason == "nonzero_without_changes" and "Schreibrechte" in "\n".join(result.output.splitlines()):
            print_warn("  → Mögliche Ursache: Fehlende Schreibrechte im Sandbox-Verzeichnis")

    tail = format_worker_output_tail(result.output)
    if tail:
        print("      Letzte Worker-Ausgabe:")
        for line in tail.splitlines():
            print(f"        | {line}")


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
                         now_fn=datetime.now,
                         rework: bool = False,
                         base_branch: str | None = None) -> BranchRecoveryPlan:
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

    open_pr_matches = tuple(
        (branch, pr)
        for branch in branches_to_check
        for pr in pull_requests_by_branch[branch]
        if pr.state == "open"
    )
    if open_pr_matches:
        if rework and len(open_pr_matches) == 1:
            branch, pr = open_pr_matches[0]
            head_matches = not pr.head_ref or pr.head_ref == branch
            base_matches = not base_branch or not pr.base_ref or pr.base_ref == base_branch
            if head_matches and base_matches:
                return recovery_plan(
                    "rework_existing_pr",
                    branch,
                    f"Rework-Modus: vorhandenen offenen {describe_pull_request(pr)} auf Branch '{branch}' weiterbearbeiten.",
                    pr,
                )

        if rework:
            branch, pr = open_pr_matches[0]
            return recovery_plan(
                "skip_rework_ineligible",
                branch,
                (
                    "Rework-Modus verweigert: offener PR ist nicht eindeutig "
                    "dem erwarteten Issue-Branch/Base-Branch zuordenbar."
                ),
                pr,
            )

        branch, pr = open_pr_matches[0]
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
                        model: str, model_name: str | None = None, close_issues: bool = True,
                        fallback_from: str | None = None,
                        ensemble_summary: str | None = None,
                        test_result_summary: str | None = None) -> str:
    display_name = MODEL_CONFIGS[model]['display_name']
    effective_model_name = model_name or MODEL_CONFIGS[model].get('default_model_name') or model

    # Konkreten Modellnamen anhängen, falls nicht bereits im Display-Namen enthalten
    if effective_model_name and effective_model_name not in display_name:
        display_name = f"{display_name} ({effective_model_name})"

    # Fallback-Informationen hinzufügen, falls zutreffend
    if fallback_from:
        display_name = f"{display_name} (Fallback von {fallback_from})"

    body = f"""## 🤖 AI-generierter Fix für Issue #{number}

Dieses PR wurde automatisch durch [ai-issue-solver](https://github.com/{config_owner}/ai-issue-solver) erstellt.

### Gelöstes Issue
{"Closes" if close_issues else "Refs"} #{number}: {title}

### Verwendetes Modell
`{display_name}`
"""

    # Ensemble-Zusammenfassung hinzufügen, falls vorhanden
    if ensemble_summary:
        body += f"""
### Ensemble-Zusammenfassung
{ensemble_summary}
"""

    # Post-Solve-Testergebnis hinzufügen, falls vorhanden (Issue #281)
    if test_result_summary:
        body += f"""
### Tests
{test_result_summary}
"""

    body += f"""

### Änderungen
*(bitte vor dem Merge reviewen)*

---
*Erstellt mit dem AI Issue Solver (Morpheus-Methode)*
"""
    return body


def create_issue_pull_request(client: GitHubClient, repo: str, number: int, title: str,
                                model: str, config: dict, branch_name: str,
                                base_branch: str, close_issues: bool,
                                model_name: str | None = None,
                                fallback_from: str | None = None,
                                dry_run: bool = False,
                                ensemble_summary: str | None = None,
                                test_result_summary: str | None = None) -> dict | None:
    pr = client.create_pull_request(
        repo=repo,
        title=f"[AI] Fix: {title}",
        body=build_issue_pr_body(config["owner"], repo, number, title, model, model_name, close_issues, fallback_from, ensemble_summary, test_result_summary),
        head=branch_name,
        base=base_branch,
        dry_run=dry_run,
    )
    if pr:
        print(f"      🔀 PR erstellt: {pr.get('html_url', '?')}")

    if close_issues and pr:
        display_name = MODEL_CONFIGS[model]['display_name']
        effective_model_name = model_name or MODEL_CONFIGS[model].get('default_model_name') or model
        if effective_model_name and effective_model_name not in display_name:
            display_name = f"{display_name} ({effective_model_name})"
        if fallback_from:
            display_name = f"{display_name} (Fallback von {fallback_from})"

        close_comment = (
            "✅ Dieses Issue wurde automatisch durch den AI Issue Solver bearbeitet.\n\n"
            f"PR: {pr.get('html_url', '?') if pr else '(kein PR)'}\n"
            f"Modell: {display_name}"
        )
        client.close_issue_with_comment(repo, number, close_comment)

    return pr


# ─────────────────────────────────────────────────────────────
# Issue lösen
# ─────────────────────────────────────────────────────────────

def create_ensemble_branches(issue_number: int, models: list[str]) -> dict[str, str]:
    """Erstellt Branch-Namen für jedes Modell im Ensemble."""
    branches = {}
    for model in models:
        model_slug = model.replace("/", "-").replace(":", "-")
        if len(model_slug) > 50:
            model_slug = model_slug[:50]
        branches[model] = f"ai/fix-issue-{issue_number}-{model_slug}"
    return branches


def _run_single_model(
    client: GitHubClient,
    issue: dict,
    repo: str,
    model: str,
    model_name: str,
    config: dict,
    token: str,
    dry_run: bool,
    base_branch: str,
    repo_dir: str,
    branch_name: str,
    prompt: str,
    verbosity: str,
    run_report_dir: Path | str | None = None,
) -> WorkerRunResult:
    """Führt einen einzelnen Modelllauf im Ensemble-Modus aus."""
    # Branch erstellen oder auschecken
    if not create_branch(repo_dir, branch_name):
        print_err(f"Branch konnte nicht erstellt werden: {branch_name}")
        return WorkerRunResult(returncode=1, output=f"Branch creation failed: {branch_name}")

    # Worker-Umgebung vorbereiten
    adapter = get_worker_adapter(model)
    env = adapter.build_env(config["config"])
    effective_model_name = model_name or MODEL_CONFIGS[model].get("default_model_name") or None

    # Worker ausführen
    result, _ = adapter.run(
        prompt=sanitize_worker_prompt_secret_paths(prompt, repo_dir),
        repo_path=repo_dir,
        env=env,
        model_name=effective_model_name,
        verbosity=verbosity,
        run_report=create_run_report(repo, issue["number"], branch_name, model, issue_title=issue["title"], run_dir=run_report_dir) if run_report_dir else None,
    )
    
    # Änderungen committen und pushen
    if not dry_run:
        commit_msg = f"fix: Löse Issue #{issue['number']} — {issue['title']}\n\nAutomatisch gelöst mit AI Issue Solver (Modell: {model_name})"
        commit_and_push(repo_dir, branch_name, commit_msg, token, config["owner"], repo)
    
    return result


def evaluate_results(results: dict[str, WorkerRunResult], git_statuses: dict[str, str],
                    repo_dir: str, issue_text: str) -> tuple[str, str]:
    """Bewertet die Ergebnisse der Modelle und wählt das beste aus."""
    best_model = None
    best_score = -1
    best_reason = ""
    best_has_changes = False

    for model, result in results.items():
        git_status = git_statuses.get(model, "")
        assessment = assess_worker_result(
            result,
            git_status,
            repo_dir=repo_dir,
            issue_text=issue_text,
        )
        score = 0
        reason = assessment.reason

        # Bewertungskriterien
        if assessment.has_changes:
            score += 3  # Änderungen sind das wichtigste Kriterium
            best_has_changes = True
        if result.returncode == 0:
            score += 2  # Erfolgreicher Exit-Code ist wichtig
        if assessment.should_continue:
            score += 1  # Sollte weiterverwendet werden
        
        # Anzahl der geänderten Dateien als zusätzliches Kriterium
        changed_files = len(changed_paths_from_status(git_status)) if git_status else 0
        score += min(changed_files, 5)  # Maximal 5 Punkte für viele Änderungen

        if score > best_score:
            best_score = score
            best_model = model
            best_reason = (
                f"{reason}, Exit Code: {result.returncode}, "
                f"Änderungen: {'Ja' if assessment.has_changes else 'Nein'}, "
                f"Geänderte Dateien: {changed_files}"
            )

    if not best_model:
        best_model = next(iter(results.keys()))
        best_reason = "Kein Modell hat Änderungen erzeugt, wähle erstes Modell als Fallback."
    elif not best_has_changes:
        best_model = next(iter(results.keys()))
        best_reason = f"Kein Modell hat Änderungen erzeugt. Wähle {best_model} als Fallback (Exit Code: {results[best_model].returncode})."

    return best_model, best_reason


def solve_issue(client: GitHubClient, issue: dict, repo: str,
                model: str, model_name: str, config: dict,
                token: str, dry_run: bool, base_branch: str,
                close_issues: bool,
                defer_codex_rate_limit: bool = False,
                run_report_dir: Path | str | None = None,
                verbosity: str = "normal",
                auto_model: bool = False,
                max_cost: str = "expensive",
                skip_pr: bool = False,
                branch_suffix: str | None = None,
                continue_: bool = False,
                max_run_cost_usd: float | None = None,
                max_run_input_tokens: int | None = None,
                max_run_output_tokens: int | None = None,
                max_run_cache_read_tokens: int | None = None,
                max_run_runtime_seconds: float | None = None,
                max_post_worker_runtime_seconds: float | None = None,
                ensemble: int = 0,
                role_routing: dict | None = None,
                rework: bool = False) -> bool:
    number = issue["number"]
    title = issue["title"]
    body = issue.get("body", "")
    if ensemble > 0:
        # Ensemble-Modus: Modelle auswählen
        from concurrent.futures import ThreadPoolExecutor, as_completed
        models = [
            "opencode/deepseek-v4-flash-free",
            "opencode/mimo-v2.5-free",
            "claude-sonnet-4-20250514",
            "gpt-4o",
            "mistral/mistral-small-2603"
        ][:ensemble]
        print(f"      🤖 Ensemble-Modus: Führe {len(models)} Modelle parallel aus: {', '.join(models)}")
        
        # Branches für jedes Modell erstellen
        ensemble_branches = create_ensemble_branches(number, models)
        
        # Ergebnisse sammeln
        results = {}
        git_statuses = {}
        
        # Temporäres Verzeichnis für das Repository erstellen
        tmpdir = tempfile.mkdtemp(prefix="ai-solver-ensemble-", dir=str(cache_dir / "tmp"))
        repo_dir = os.path.join(tmpdir, repo)
        
        # Repository klonen
        print(f"      📥 Klone {repo} für Ensemble-Modus ...", end=" ", flush=True)
        clone_result = clone_repo(config["owner"], repo, token, repo_dir, base_branch)
        if not clone_result:
            print_err("Klonen fehlgeschlagen")
            return False
        print("✅")
        
        # Modelle parallel ausführen
        with ThreadPoolExecutor() as executor:
            futures = {}
            for model_name in models:
                branch_name = ensemble_branches[model_name]
                future = executor.submit(
                    _run_single_model,
                    client=client,
                    issue=issue,
                    repo=repo,
                    model="opencode",
                    model_name=model_name,
                    config=config,
                    token=token,
                    dry_run=dry_run,
                    base_branch=base_branch,
                    repo_dir=repo_dir,
                    branch_name=branch_name,
                    prompt=prompt,
                    verbosity=verbosity,
                    run_report_dir=run_report_dir,
                )
                futures[future] = model_name
            
            for future in as_completed(futures):
                model_name = futures[future]
                try:
                    result = future.result()
                    results[model_name] = result
                    git_statuses[model_name] = git_status_porcelain(repo_dir)
                    print(f"      ✅ Modell {model_name} abgeschlossen (Exit Code: {result.returncode})")
                except Exception as e:
                    print(f"      ❌ Modell {model_name} mit Fehler: {e}")
                    results[model_name] = WorkerRunResult(returncode=1, output=str(e))
                    git_statuses[model_name] = ""
        
        # Bestes Ergebnis auswählen
        best_model, best_reason = evaluate_results(results, git_statuses, repo_dir, f"{title}\n\n{body or ''}")
        print(f"      🏆 Bestes Modell: {best_model} ({best_reason})")
        
        # Ensemble-Zusammenfassung generieren
        ensemble_summary = f"Dieses PR wurde aus einem Ensemble von {len(models)} Modellen ausgewählt:\n"
        ensemble_summary += "| Modell | Exit Code | Änderungen | Geänderte Dateien |\n"
        ensemble_summary += "|--------|-----------|------------|-------------------|\n"
        
        for model_name in models:
            result = results[model_name]
            git_status = git_statuses.get(model_name, "")
            assessment = assess_worker_result(
                result,
                git_status,
                repo_dir=repo_dir,
                issue_text=f"{title}\n\n{body or ''}",
            )
            changed_files = len(changed_paths_from_status(git_status)) if git_status else 0
            ensemble_summary += (
                f"| {model_name} | {result.returncode} | {'Ja' if assessment.has_changes else 'Nein'} "
                f"| {changed_files} |")
            if model_name == best_model:
                ensemble_summary += " ← **Ausgewählt**"
            ensemble_summary += "\n"
        
        # Besten Branch auswählen und PR erstellen
        best_branch = ensemble_branches[best_model]
        if not skip_pr:
            pr = create_issue_pull_request(
                client=client,
                repo=repo,
                number=number,
                title=title,
                model="opencode",
                config=config,
                branch_name=best_branch,
                base_branch=base_branch,
                close_issues=close_issues,
                model_name=best_model,
                fallback_from=None,
                dry_run=dry_run,
                ensemble_summary=ensemble_summary,
            )
            return bool(pr)
        return True
    
    default_branch_name = f"ai/fix-issue-{number}"
    if branch_suffix:
        default_branch_name = f"{default_branch_name}/{branch_suffix}"

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
            rework=rework,
            base_branch=base_branch,
        )
        print_branch_recovery_plan(recovery_plan)
        print(f"      [DRY-RUN] Geplanter Issue-Branch: {recovery_plan.branch}")
        return True

    recovery_plan = plan_branch_recovery(
        client,
        repo,
        number,
        default_branch_name,
        rework=rework,
        base_branch=base_branch,
    )
    print_branch_recovery_plan(recovery_plan)
    run_report = create_run_report(
        repo,
        number,
        recovery_plan.branch,
        model,
        issue_title=title,
        run_dir=run_report_dir,
        rework_of=(
            recovery_plan.pull_request.number
            if recovery_plan.action == "rework_existing_pr" and recovery_plan.pull_request
            else None
        ),
        rework_reason="existing_open_pr" if recovery_plan.action == "rework_existing_pr" else None,
    )
    if run_report:
        write_run_report(run_report, "started")
        write_run_health(run_report, status="running", phase="clone")
        print(f"      Run-Report: {run_report.path}")
    # Issue #350: Zeitpunkt fuer das Post-Worker-Watchdog-Budget festhalten.
    # Der Watchdog misst die _gesamte_ Post-Worker-Phase (Validierung bis
    # PR-Erstellung) gegen ``--max-post-worker-runtime-seconds`` bzw. das
    # verbleibende ``--max-run-runtime-seconds``.
    run_started_at = datetime.now()
    post_worker_started_at: datetime | None = None
    post_worker_deadline_seconds: float = 0.0
    # Fruehes Repo-Profil fuer Skip-Pfade (vorhandener PR, geschlossene Issue)
    early_repo_profile_obj, early_repo_profile_dict = build_repo_profile_for_run(
        repo, config["config"], branch=base_branch,
    )
    if early_repo_profile_dict:
        print(
            f"      🛰️ Repo-Profil-Quelle: {early_repo_profile_dict.get('source', 'unknown')}, "
            f"Typ: {early_repo_profile_dict.get('repo_kind', 'unknown')}, "
            f"Sprache: {early_repo_profile_dict.get('dominant_language') or 'unbekannt'}"
        )
    if recovery_plan.action.startswith("skip"):
        if recovery_plan.pull_request and recovery_plan.pull_request.html_url:
            print(f"      🔀 Vorhandener PR: {recovery_plan.pull_request.html_url}")
        if run_report:
            write_run_report(
                run_report,
                recovery_plan.action,
                pr_url=recovery_plan.pull_request.html_url if recovery_plan.pull_request else None,
                note=recovery_plan.message,
                vibe_log_snippet=None,
                repo_profile=early_repo_profile_dict,
            )
        return True

    # Solver-lokale Verzeichnisse vorbereiten
    state_dir, cache_dir = ensure_solver_directories()

    # Ressourcen-Diagnosen für Locking-Ereignisse
    resource_diagnostics = RunResourceDiagnostics()

    # Temporäres Verzeichnis im solver-lokalen Cache erstellen
    tmpdir = tempfile.mkdtemp(prefix="ai-solver-", dir=str(cache_dir / "tmp"))
    preserved_worktree: Path | None = None

    # Per-Run-Ressourcenmodell aufbauen
    provider_label = f"{model}/{model_name}" if model_name else model
    run_resources = create_run_resources(
        repo=repo,
        issue_number=number,
        branch_name=recovery_plan.branch,
        provider=provider_label,
        base_branch=base_branch,
        temp_base=Path(tmpdir).parent,
        report_path=run_report.path if run_report else Path(tmpdir),
        cleanup_on_exit=True,
    )

    # Branch-Namens-Konflikt frühzeitig erkennen (parallele Runs auf gleichem Branch)
    branch_conflict = detect_branch_name_conflict(
        branch_name=recovery_plan.branch,
        repo=repo,
        issue_number=number,
        own_run_id=run_resources.run_id,
    )
    if branch_conflict:
        resource_diagnostics.branch_conflict_detected = True
        resource_diagnostics.branch_conflict_message = branch_conflict
        print_warn(f"Branch-Konflikt erkannt: {branch_conflict}")
        if run_report:
            write_resource_diagnostics_to_report(
                run_report.path, run_resources, resource_diagnostics
            )
            write_run_report(
                run_report,
                "branch_conflict",
                note=branch_conflict,
            )
        return False

    # Issue-Level-Lock erwerben (verhindert doppelten PR bei parallelen Same-Issue-Runs)
    issue_lock = ResourceLock(
        key=run_resources.issue_key,
        resources=run_resources,
    )

    try:
        # Issue-Level-Lock erwerben: verhindert parallele PR-Erstellung für dasselbe Issue
        with issue_lock.acquire(resource_diagnostics) as lock_acquired:
            if not lock_acquired:
                lock_failure_msg = (
                    f"Lock-Akquisition fehlgeschlagen für {run_resources.issue_key}: "
                    "ein anderer Run arbeitet möglicherweise an demselben Issue"
                )
                print_warn(lock_failure_msg)
                if run_report:
                    write_resource_diagnostics_to_report(
                        run_report.path, run_resources, resource_diagnostics
                    )
                    write_run_report(
                        run_report,
                        "lock_failed",
                        note=lock_failure_msg,
                        resource_diagnostics=resource_diagnostics,
                    )
                return False

        repo_dir = os.path.join(tmpdir, repo)
        print(f"      📥 Klone {repo} ...", end=" ", flush=True)

        # Preflight-Check für Schreibrechte im Temp-Verzeichnis
        additional_dirs = []
        if model == "codex":
            additional_dirs = preflight_temp_dir_check(tmpdir)
            if additional_dirs:
                print(f"      📁 Zusätzliche Verzeichnisse für Codex Sandbox: {additional_dirs}")

        clone_result = clone_repo(config["owner"], repo, token, repo_dir, base_branch)
        if not clone_result:
            print_err("Klonen fehlgeschlagen")
            clone_error = clone_result.stderr.strip() or clone_result.stdout.strip()
            if clone_error:
                print("      Git-Clone-Ausgabe:")
                for line in clone_error.splitlines()[-8:]:
                    print(f"        | {line}")
            print(f"      Prüfe, ob der Branch '{base_branch}' in {repo} existiert.")
            if run_report:
                note = f"base_branch: {base_branch}"
                if clone_error:
                    note = f"{note}\nclone_output:\n{clone_error}"
                write_run_report(run_report, "clone_failed", note=note, vibe_log_snippet=None,
                                 resource_diagnostics=resource_diagnostics)
            return False
        print("✅")

        # Provider-Profil fuer Planung, Modellauswahl und Reporting aufbauen
        # (GitHub-first, lokaler Marker-Fallback, ohne Secret-Dateien zu lesen)
        repo_profile_obj, repo_profile_dict = build_repo_profile_for_run(
            repo, config["config"], branch=base_branch,
        )
        if repo_profile_dict:
            print(
                f"      🛰️ Repo-Profil-Quelle: {repo_profile_dict.get('source', 'unknown')}, "
                f"Typ: {repo_profile_dict.get('repo_kind', 'unknown')}, "
                f"Sprache: {repo_profile_dict.get('dominant_language') or 'unbekannt'}"
            )

        # Branch anlegen
        branch_name = recovery_plan.branch
        if recovery_plan.action in {"reuse_branch", "rework_existing_pr"}:
            if not checkout_existing_remote_branch(repo_dir, branch_name):
                print_err(f"Vorhandener Branch konnte nicht ausgecheckt werden: {branch_name}")
                if run_report:
                    write_run_report(run_report, "checkout_failed",
                                     resource_diagnostics=resource_diagnostics)
                return False
            if branch_has_changes_against_base(repo_dir, base_branch):
                if continue_:
                    print(
                        "      [CONTINUE] Vorhandene Änderungen gefunden; "
                        "setze Arbeit auf bestehendem Branch fort..."
                    )
                elif recovery_plan.action == "rework_existing_pr":
                    print(
                        "      [REWORK] Vorhandene PR-Änderungen gefunden; "
                        "setze Arbeit auf bestehendem Branch fort..."
                    )
                else:
                    git_status = git_status_porcelain(repo_dir)
                    git_change_summary = format_git_change_summary(repo_dir, git_status)
                    print(
                        "      Vorhandener Branch enthält bereits Änderungen gegen den Zielbranch; "
                        "erstelle fehlenden PR."
                    )
                    if skip_pr:
                        print("      [SKIP_PR] Überspringe PR-Erstellung (Benchmark-Modus)")
                        pr = None
                        status = "pr_skipped"
                    else:
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
                            model_name=model_name,
                            dry_run=dry_run,
                        )
                        status = "pr_created_from_existing_branch" if pr else "pr_failed_from_existing_branch"
                    if not pr and run_report and should_preserve_worktree(
                        status,
                        repo_dir,
                        base_branch,
                        changes_exist=True,
                    ):
                        preserved_worktree = preserve_worker_worktree(
                            repo_dir=repo_dir,
                            report=run_report,
                            owner=config["owner"],
                            repo=repo,
                            issue_number=number,
                            branch=branch_name,
                            status=status,
                            base_branch=base_branch,
                        )
                    if run_report:
                        write_run_report(
                            run_report,
                            status,
                            pr_url=pr.get("html_url") if pr else None,
                            preserved_worktree_path=preserved_worktree,
                            base_branch=base_branch,
                            git_change_summary=git_change_summary,
                            resource_diagnostics=resource_diagnostics,
                            repo_profile=repo_profile_dict,
                        )
                    return bool(pr)
        elif not create_branch(repo_dir, branch_name):
            print_err(f"Branch konnte nicht erstellt werden: {branch_name}")
            if run_report:
                write_run_report(run_report, "branch_create_failed",
                                 resource_diagnostics=resource_diagnostics,
                                 repo_profile=repo_profile_dict)
            return False

        # Provider-Profil wurde bereits vor dem Branch-Schritt erstellt
        # (siehe oben) und steht fuer alle weiteren Phasen bereit.

        # Prompt bauen
        prompt = AIDER_PROMPT_TEMPLATE.format(
            number=number,
            title=title,
            body=body or "(kein Beschreibungstext)"
        )

        # Worker-Adapter instanziieren und Umgebung vorbereiten
        adapter = get_worker_adapter(model)
        env = adapter.build_env(config["config"])

        # KI-Worker ausführen
        display_name = adapter.get_display_name()
        print(f"      🤖 Starte {display_name} ...", flush=True)

        if run_report:
            write_run_health(run_report, status="running", phase="worker_running")

        # Adapter-spezifische Parameter
        adapter_kwargs: dict = {}
        if model == "codex":
            adapter_kwargs["additional_dirs"] = additional_dirs
        if model in ("opencode", "openrouter_direct"):
            if max_run_cost_usd is not None:
                adapter_kwargs["max_run_cost_usd"] = max_run_cost_usd
            if max_run_input_tokens is not None:
                adapter_kwargs["max_run_input_tokens"] = max_run_input_tokens
            if max_run_output_tokens is not None:
                adapter_kwargs["max_run_output_tokens"] = max_run_output_tokens
            if max_run_cache_read_tokens is not None:
                adapter_kwargs["max_run_cache_read_tokens"] = max_run_cache_read_tokens
            if max_run_runtime_seconds is not None:
                adapter_kwargs["max_run_runtime_seconds"] = max_run_runtime_seconds
        if model == "codex" and defer_codex_rate_limit:
            from workers.codex_adapter import CodexAdapter
            adapter = CodexAdapter(defer_rate_limit=True)
            # Umgebung neu aufbauen (Adapter wurde ersetzt)
            env = adapter.build_env(config["config"])

        # Effektiven Modell-Namen bestimmen
        effective_model_name = model_name or MODEL_CONFIGS[model].get("default_model_name") or None

        # Worker über Adapter ausführen
        result, adapter_diagnostics = adapter.run(
            prompt=sanitize_worker_prompt_secret_paths(prompt, repo_dir),
            repo_path=repo_dir,
            env=env,
            model_name=effective_model_name,
            verbosity=verbosity,
            run_report=run_report,
            **adapter_kwargs,
        )

        # OpenCode-Session-Metriken aus Adapter-Diagnostics extrahieren
        opencode_session_metrics = None
        if adapter_diagnostics.opencode_session_totals:
            opencode_session_metrics = dict(adapter_diagnostics.opencode_session_totals)
            if adapter_diagnostics.opencode_budget_exceeded:
                opencode_session_metrics["budget_exceeded"] = adapter_diagnostics.opencode_budget_exceeded
        openrouter_usage_metrics = None
        if adapter_diagnostics.openrouter_usage:
            openrouter_usage_metrics = dict(adapter_diagnostics.openrouter_usage)
            if adapter_diagnostics.openrouter_budget_exceeded:
                openrouter_usage_metrics["budget_exceeded"] = adapter_diagnostics.openrouter_budget_exceeded
            if adapter_diagnostics.openrouter_request_timed_out:
                openrouter_usage_metrics["timed_out"] = True

        # Monthly spending erfassen (solver role)
        if role_routing is not None:
            try:
                from role_routing_loader import record_spending
                cost_usd = 0.0
                if adapter_diagnostics.opencode_session_totals:
                    cost_usd = float(
                        adapter_diagnostics.opencode_session_totals.get("cost_usd", 0.0)
                    )
                record_spending("solver", cost_usd)
            except Exception as exc:
                print_warn(f"Could not record spending: {exc}")

        # Modellauswahl-Metadaten im Report speichern (falls vorhanden)
        model_selection_metadata = None
        if auto_model:
            from model_selection import select_model_for_issue
            model_selection_metadata = select_model_for_issue(
                issue=issue,
                repo_type=repo_type_from_profile(repo_profile_obj),
                max_cost_tier=max_cost,
            )

        diagnostic_outputs = list(adapter_diagnostics.all_outputs)
        rate_limit_deferred_note = adapter_diagnostics.rate_limit_note or None

        diagnostic_result = result
        if len(diagnostic_outputs) > 1:
            combined_output = "\n".join(
                f"--- Worker-Lauf {index} ---\n{output}"
                for index, output in enumerate(diagnostic_outputs, start=1)
            )
            diagnostic_result = WorkerRunResult(result.returncode, combined_output)

        if run_report:
            write_run_health(run_report, result.output if result else "",
                             result.last_activity_at if result else None,
                             status="running", phase="validating")

        git_status = git_status_porcelain(repo_dir)
        git_change_summary = format_git_change_summary(repo_dir, git_status)
        for line in git_change_summary:
            print(f"      {line}")
        assessment = assess_worker_result(
            result,
            git_status,
            repo_dir=repo_dir,
            issue_text=f"{title}\n\n{body or ''}",
        )
        print_worker_assessment(result, assessment)
        # OpenCode Runtime-Diagnostics werden bereits vom OpenCodeAdapter ausgegeben.
        # Zur Vollständigkeit: falls ein anderer Adapter diesen Code aufruft, hier nicht doppeln.

        # Vibe-Log-Snippet aus Adapter-Diagnostics verwenden (MistralVibeAdapter sammelt es bereits)
        vibe_log_snippet = adapter_diagnostics.vibe_log_snippet

        if rate_limit_deferred_note:
            status = "rate_limit_deferred"
            if run_report and should_preserve_worktree(
                status,
                repo_dir,
                base_branch,
                changes_exist=assessment.has_changes,
            ):
                preserved_worktree = preserve_worker_worktree(
                    repo_dir=repo_dir,
                    report=run_report,
                    owner=config["owner"],
                    repo=repo,
                    issue_number=number,
                    branch=branch_name,
                    status=status,
                    base_branch=base_branch,
                )
            if run_report:
                write_resource_diagnostics_to_report(
                    run_report.path, run_resources, resource_diagnostics
                )
                write_run_report(
                    run_report,
                    status,
                    worker_result=diagnostic_result,
                    note=rate_limit_deferred_note,
                    preserved_worktree_path=preserved_worktree,
                    base_branch=base_branch,
                    git_change_summary=git_change_summary,
                    vibe_log_snippet=vibe_log_snippet if model == "mistral-vibe" else None,
                    resource_diagnostics=resource_diagnostics,
                    opencode_session_metrics=opencode_session_metrics,
                    openrouter_usage_metrics=openrouter_usage_metrics,
                    repo_profile=repo_profile_dict,
                )
            return False
        if not assessment.should_continue:
            status = assessment.reason
            if run_report and should_preserve_worktree(
                status,
                repo_dir,
                base_branch,
                changes_exist=assessment.has_changes,
            ):
                preserved_worktree = preserve_worker_worktree(
                    repo_dir=repo_dir,
                    report=run_report,
                    owner=config["owner"],
                    repo=repo,
                    issue_number=number,
                    branch=branch_name,
                    status=status,
                    base_branch=base_branch,
                )
            if run_report:
                write_resource_diagnostics_to_report(
                    run_report.path, run_resources, resource_diagnostics
                )
                write_run_report(
                    run_report,
                    status,
                    worker_result=diagnostic_result,
                    preserved_worktree_path=preserved_worktree,
                    base_branch=base_branch,
                    git_change_summary=git_change_summary,
                    vibe_log_snippet=vibe_log_snippet if model == "mistral-vibe" else None,
                    resource_diagnostics=resource_diagnostics,
                    opencode_session_metrics=opencode_session_metrics,
                    openrouter_usage_metrics=openrouter_usage_metrics,
                    repo_profile=repo_profile_dict,
                )
            return False

        if adapter_diagnostics.openrouter_budget_exceeded:
            print_warn(
                "OpenRouter-Direct Budget-/Kontrolllimit überschritten; "
                "erstelle keinen Commit und keinen PR"
            )
            print(f"      {adapter_diagnostics.openrouter_budget_exceeded}")
            status = "budget_exceeded"
            if run_report and should_preserve_worktree(
                status,
                repo_dir,
                base_branch,
                changes_exist=assessment.has_changes,
            ):
                preserved_worktree = preserve_worker_worktree(
                    repo_dir=repo_dir,
                    report=run_report,
                    owner=config["owner"],
                    repo=repo,
                    issue_number=number,
                    branch=branch_name,
                    status=status,
                    base_branch=base_branch,
                )
            if run_report:
                write_resource_diagnostics_to_report(
                    run_report.path, run_resources, resource_diagnostics
                )
                write_run_report(
                    run_report,
                    status,
                    worker_result=diagnostic_result,
                    note=adapter_diagnostics.openrouter_budget_exceeded,
                    preserved_worktree_path=preserved_worktree,
                    base_branch=base_branch,
                    git_change_summary=git_change_summary,
                    vibe_log_snippet=vibe_log_snippet if model == "mistral-vibe" else None,
                    resource_diagnostics=resource_diagnostics,
                    opencode_session_metrics=opencode_session_metrics,
                    openrouter_usage_metrics=openrouter_usage_metrics,
                    repo_profile=repo_profile_dict,
                )
            return False

        # Ab hier beginnt die Post-Worker-Phase (Issue #350).
        post_worker_started_at = datetime.now()
        post_worker_deadline_seconds = compute_post_worker_deadline(
            run_started_at,
            max_run_runtime_seconds,
            max_post_worker_runtime_seconds,
        )
        branch_pushed_remote = False

        def _write_post_push_recovery_report(
            status_value: str,
            note_text: str,
            *,
            worker_result_for_report=diagnostic_result,
        ) -> None:
            """Schreibt einen Run-Report fuer ``pushed_without_pr``/``pr_creation_timeout``.

            Enthaelt Branch-Namen, PR-Recovery-Befehl und (falls vorhanden)
            das Worktree-Preset, damit das Watchdog die Lage bewerten und
            ein Folgerun aufsetzen kann.
            """
            if not run_report:
                return
            note = note_text
            if branch_name and branch_pushed_remote:
                note = (
                    f"{note_text}\n"
                    + format_post_push_recovery_note(
                        config["owner"],
                        repo,
                        branch_name,
                        number,
                        base_branch,
                    )
                )
            write_resource_diagnostics_to_report(
                run_report.path, run_resources, resource_diagnostics
            )
            write_run_report(
                run_report,
                status_value,
                worker_result=worker_result_for_report,
                note=note,
                preserved_worktree_path=preserved_worktree,
                base_branch=base_branch,
                git_change_summary=git_change_summary,
                vibe_log_snippet=vibe_log_snippet if model == "mistral-vibe" else None,
                resource_diagnostics=resource_diagnostics,
                opencode_session_metrics=opencode_session_metrics,
                openrouter_usage_metrics=openrouter_usage_metrics,
                repo_profile=repo_profile_dict,
            )

        # Post-Worker-Watchdog fuer die Validierungs-Phase. Die Phase
        # selbst ist billig, aber sie ist der erste Schritt nach dem
        # Worker-Heartbeat; ein expliziter Heartbeat + Deadline-Check
        # schliesst die Luecke, die Issue #339/Issue #340 aufgedeckt haben.
        try:
            _check_post_worker_deadline(
                post_worker_started_at,
                post_worker_deadline_seconds,
                "validating",
            )
        except PostWorkerTimeoutError as exc:
            print_warn(f"Post-Worker-Timeout in 'validating': {exc}")
            if run_report:
                write_run_health(
                    run_report,
                    status="unhealthy",
                    phase="validating",
                )
            return False
        if run_report:
            write_run_health(
                run_report,
                status="running",
                phase="validating",
            )
        validation = validate_worker_changes(repo_dir, git_status)
        if not validation.ok:
            print_warn("Worker-Validierung fehlgeschlagen; erstelle keinen Commit und keinen PR")
            for error in validation.errors[:5]:
                print(f"      {error}")
            status = "validation_failed"
            if run_report and should_preserve_worktree(
                status,
                repo_dir,
                base_branch,
                changes_exist=assessment.has_changes,
            ):
                preserved_worktree = preserve_worker_worktree(
                    repo_dir=repo_dir,
                    report=run_report,
                    owner=config["owner"],
                    repo=repo,
                    issue_number=number,
                    branch=branch_name,
                    status=status,
                    base_branch=base_branch,
                )
            if run_report:
                write_resource_diagnostics_to_report(
                    run_report.path, run_resources, resource_diagnostics
                )
                write_run_report(
                    run_report,
                    status,
                    worker_result=diagnostic_result,
                    note="; ".join(validation.errors),
                    preserved_worktree_path=preserved_worktree,
                    base_branch=base_branch,
                    git_change_summary=git_change_summary,
                    vibe_log_snippet=vibe_log_snippet if model == "mistral-vibe" else None,
                    resource_diagnostics=resource_diagnostics,
                    opencode_session_metrics=opencode_session_metrics,
                    openrouter_usage_metrics=openrouter_usage_metrics,
                    repo_profile=repo_profile_dict,
                )
            return False

        # Committen & pushen
        if run_report:
            write_run_health(run_report, status="running", phase="committing")
        print(f"      📤 Commit & Push ...", end=" ", flush=True)
        commit_msg = f"fix: Löse Issue #{number} — {title}\n\nAutomatisch gelöst mit AI Issue Solver (Modell: {model})\nIssue: https://github.com/{config['owner']}/{repo}/issues/{number}"

        # Post-Worker-Watchdog (Issue #350): Commit + Push unter expliziter
        # Deadline fuehren. Wenn das Budget ueberschritten wird, schreiben
        # wir einen ``pushed_without_pr``-Report, weil der Branch moeglicherweise
        # bereits remote ist (commit_and_push fuehrt git add/commit/push in
        # einem Schritt aus).
        try:
            _check_post_worker_deadline(
                post_worker_started_at,
                post_worker_deadline_seconds,
                "committing",
            )
        except PostWorkerTimeoutError as exc:
            print_warn(f"Post-Worker-Timeout in 'committing': {exc}")
            if run_report:
                write_run_health(
                    run_report,
                    status="unhealthy",
                    phase="committing",
                )
            _write_post_push_recovery_report(
                "pushed_without_pr",
                f"Timeout vor Commit/Push: {exc}",
            )
            return False

        pushed = commit_and_push(
            repo_dir,
            branch_name,
            commit_msg,
            token,
            config["owner"],
            repo,
            timeout_seconds=post_worker_deadline_seconds or DEFAULT_POST_WORKER_RUNTIME_SECONDS,
        )

        # Nach erfolgreichem Push die "pushing"-Phase markieren. Falls
        # commit_and_push teilweise erfolgreich war (Commit ok, Push fehlt),
        # behandeln wir das wie vorher als "push_failed" und erhalten den
        # Branch-Wert ueber das Worktree-Preset.
        if pushed:
            branch_pushed_remote = True
            if run_report:
                write_run_health(
                    run_report,
                    status="running",
                    phase="pushing",
                )
                # Heartbeat direkt nach erfolgreichem Push schreiben.
                write_run_health(
                    run_report,
                    last_activity_at=datetime.now(),
                    status="running",
                    phase="creating_pr",
                )

        if not pushed:
            print_warn("Push fehlgeschlagen oder keine Änderungen")
            status = "push_failed"
            if run_report and should_preserve_worktree(
                status,
                repo_dir,
                base_branch,
                changes_exist=assessment.has_changes,
            ):
                preserved_worktree = preserve_worker_worktree(
                    repo_dir=repo_dir,
                    report=run_report,
                    owner=config["owner"],
                    repo=repo,
                    issue_number=number,
                    branch=branch_name,
                    status=status,
                    base_branch=base_branch,
                )
            if run_report:
                write_resource_diagnostics_to_report(
                    run_report.path, run_resources, resource_diagnostics
                )
                write_run_report(
                    run_report,
                    status,
                    worker_result=diagnostic_result,
                    preserved_worktree_path=preserved_worktree,
                    base_branch=base_branch,
                    git_change_summary=git_change_summary,
                    vibe_log_snippet=vibe_log_snippet if model == "mistral-vibe" else None,
                    resource_diagnostics=resource_diagnostics,
                    opencode_session_metrics=opencode_session_metrics,
                    openrouter_usage_metrics=openrouter_usage_metrics,
                    repo_profile=repo_profile_dict,
                )
            return False
        print("✅")

        # Post-Solve-Test (Issue #281): fuehre den Standard-Testbefehl aus und
        # protokolliere Status, Befehl und Zusammenfassung fuer PR-Body und
        # Run-Report. Bei Fehlschlag wird der PR trotzdem erstellt (kein Draft),
        # aber der Status ist im Body sichtbar.
        if run_report:
            write_run_health(run_report, status="running", phase="post_solve_tests")
        test_command = format_post_solve_test_command()
        post_solve_test = run_post_solve_tests(repo_dir)
        if post_solve_test.status == "passed":
            print("      ✅ Post-Solve-Tests: passed")
        elif post_solve_test.status == "failed":
            print_warn(f"      ⚠️  Post-Solve-Tests: failed (exit {post_solve_test.returncode})")
        else:
            print_warn(
                f"      ⚠️  Post-Solve-Tests: not_run"
                + (f" ({post_solve_test.note})" if post_solve_test.note else "")
            )
        test_result_summary = post_solve_test.summary

        if run_report:
            write_run_health(run_report, status="running", phase="creating_pr")
        if skip_pr:
            print("      [SKIP_PR] Überspringe PR-Erstellung (Benchmark-Modus)")
            pr = None
            status = "pr_skipped" if assessment.has_changes else "no_changes"
        else:
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
                model_name=effective_model_name,
                fallback_from=model_selection_metadata.get('fallback_from') if model_selection_metadata else None,
                dry_run=dry_run,
                test_result_summary=test_result_summary,
            )
            # Pruefe ob Mistral Vibe mit Turn-Limit beendet hat
            is_vibe_turn_limit = (
                model == "mistral-vibe"
                and pr
            and VIBE_TURN_LIMIT_RE.search(diagnostic_result.output)
        )
            status = "pr_created_with_warning" if is_vibe_turn_limit else ("pr_created" if pr else "pr_failed")
        if not pr and run_report and should_preserve_worktree(
            status,
            repo_dir,
            base_branch,
            changes_exist=assessment.has_changes,
        ):
            preserved_worktree = preserve_worker_worktree(
                repo_dir=repo_dir,
                report=run_report,
                owner=config["owner"],
                repo=repo,
                issue_number=number,
                branch=branch_name,
                status=status,
                base_branch=base_branch,
            )
            if run_report:
                write_resource_diagnostics_to_report(
                    run_report.path, run_resources, resource_diagnostics
                )
                write_run_report(
                    run_report,
                    status,
                    worker_result=diagnostic_result,
                    pr_url=pr.get("html_url") if pr else None,
                    preserved_worktree_path=preserved_worktree,
                    base_branch=base_branch,
                    git_change_summary=git_change_summary,
                    vibe_log_snippet=vibe_log_snippet if model == "mistral-vibe" else None,
                    resource_diagnostics=resource_diagnostics,
                    model_selection_metadata=model_selection_metadata,
                    opencode_session_metrics=opencode_session_metrics,
                    openrouter_usage_metrics=openrouter_usage_metrics,
                    repo_profile=repo_profile_dict,
                    test_command=test_command,
                    test_result=post_solve_test.status,
                )
        elif run_report:
            # Erfolgreicher PR oder uebersprungener PR ohne Worktree-Erhaltung
            write_resource_diagnostics_to_report(
                run_report.path, run_resources, resource_diagnostics
            )
            write_run_report(
                run_report,
                status,
                worker_result=diagnostic_result,
                pr_url=pr.get("html_url") if pr else None,
                preserved_worktree_path=preserved_worktree,
                base_branch=base_branch,
                git_change_summary=git_change_summary,
                vibe_log_snippet=vibe_log_snippet if model == "mistral-vibe" else None,
                resource_diagnostics=resource_diagnostics,
                model_selection_metadata=model_selection_metadata,
                opencode_session_metrics=opencode_session_metrics,
                openrouter_usage_metrics=openrouter_usage_metrics,
                repo_profile=repo_profile_dict,
                test_command=test_command,
                test_result=post_solve_test.status,
            )
        return bool(pr)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

    return True


def check_and_warn_on_congestion(
    client: GitHubClient,
    repo: str,
    issue_number: int | None = None,
    *,
    pr_threshold: int = 3,
    skip_congestion_check: bool = False,
) -> bool:
    """Prueft Workflow-Congestion und warnt, wenn die Schwelle ueberschritten ist.

    Returns:
        True wenn weitergemacht werden kann, False wenn abgebrochen werden sollte.
    """
    if skip_congestion_check:
        return True

    try:
        raw_prs = client.get_open_pull_requests(repo)
        detailed_prs = []
        for pr in raw_prs:
            if isinstance(pr, dict) and not pr.get("mergeable_state") and pr.get("number"):
                detailed = client.get_pull_request(repo, pr["number"])
                if detailed:
                    pr = {**pr, **detailed}
            detailed_prs.append(pr)

        open_prs = [
            pull_request_from_github(pr)
            for pr in detailed_prs
        ]
        open_issues_list = [
            issue_from_github(issue)
            for issue in client.get_open_issues(repo)
        ]
        summary = analyze_workflow_congestion(
            open_prs,
            open_issues_list,
            pr_threshold=pr_threshold,
        )

        if summary.needs_attention:
            print_warn(f"Workflow-Congestion erkannt in {repo}:")
            for finding in summary.findings:
                print(f"   [{finding.severity}] {finding.message} → {finding.action}")

            # Pruefe ob das angefragte Issue bereits einen offenen PR hat
            if issue_number is not None and issue_has_open_pr(issue_number, open_prs):
                print_warn(
                    f"Issue #{issue_number} hat bereits einen offenen PR. "
                    "Verwende --retry um trotzdem zu starten, "
                    "oder --compare-models fuer einen Modellvergleich."
                )
                return False

            if summary.recommended_action != "continue":
                print_warn(
                    f"Empfohlene Aktion: {summary.recommended_action}. "
                    "Setze --skip-congestion-check um dies zu uebergehen."
                )
                return False

        return True
    except Exception as exc:
        print_warn(f"Workflow-Congestion-Check fehlgeschlagen: {exc}")
        return True


def print_solver_directories() -> None:
    """
    Dokumentiert die solver-lokalen Verzeichnisstrukturen und Umgebungsvariablen.
    """
    _state_dir, cache_dir = ensure_solver_directories()

    print("\n📁 Solver-lokale Verzeichnisstruktur:")
    print(f"   XDG_CACHE_HOME/opencode: {cache_dir}")
    print("\n🔧 Wichtige Umgebungsvariablen:")
    print(f"   OPENCODE_CACHE_DIR: {cache_dir}")
    print("\n📝 Verwendung:")
    print("   - OpenCode State/Auth: Standardpfad der OpenCode-Installation")
    print("   - OpenCode Cache: $OPENCODE_CACHE_DIR")
    print("   - Isolierte Run-Checkouts: $OPENCODE_CACHE_DIR/tmp/ai-solver-*/<repo>")
    print("   - Temporäre Dateien: $OPENCODE_CACHE_DIR/tmp/")


# ─────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────

def main():
    print_banner("SCHRITT 3: ISSUES MIT KI LÖSEN")

    parser = argparse.ArgumentParser(description="GitHub Issues automatisch mit KI lösen")
    parser.add_argument(
        "--skip-slug-verification",
        action="store_true",
        help="OpenRouter-Slug-Verifikation beim Start überspringen",
    )
    parser.add_argument(
        "--skip-budget-check",
        action="store_true",
        help="Monatliches Budget-Limit pro Rolle ignorieren",
    )
    parser.add_argument(
        "--model", choices=list(MODEL_CONFIGS.keys()),
        help="KI-Modell: codex, mistral-vibe, opencode, openrouter, claude, openai, mistral oder ollama"
    )
    parser.add_argument(
        "--model-name",
        help=(
            "Spezifisches Modell (z.B. 'opencode/deepseek-v4-flash-free', 'opencode/mimo-v2.5-free', "
            "'mistral/mistral-small-2603', "
            "'claude-sonnet-4-20250514', 'gpt-4o', 'deepseek-coder:6.7b', "
            "'openrouter/openai/gpt-4o-mini')"
        )
    )
    parser.add_argument(
        "--auto-model",
        action="store_true",
        help="Modell automatisch basierend auf Issue-Typ, Risiko und Kosten auswählen"
    )
    parser.add_argument(
        "--max-cost",
        choices=["cheap", "medium", "expensive"],
        default="expensive",
        help="Maximales Kosten-Tier für die automatische Modellauswahl (Standard: expensive)"
    )
    parser.add_argument(
        "--diagnostic",
        action="store_true",
        help="OpenCode-Diagnose: Version, Auth-Status und Modellbeispiele anzeigen",
    )
    parser.add_argument(
        "--allow-opencode-state-conflict",
        action="store_true",
        help=(
            "OpenCode trotz laufendem Versions-/State-Mix starten. "
            "Nur bewusst verwenden; Standard ist blockieren."
        ),
    )
    parser.add_argument("--repo", help="Nur dieses Repo bearbeiten")
    parser.add_argument("--issue", type=int, help="Nur diese Issue-Nummer lösen")
    parser.add_argument("--dry-run", action="store_true", help="Nur anzeigen, nichts ändern")
    parser.add_argument(
        "--skip-pr",
        action="store_true",
        help="Benchmark-Modus: Commit & Push ausführen aber keinen PR erstellen",
    )
    parser.add_argument(
        "--branch-suffix",
        help="Optionaler Suffix für den Branch-Namen (z.B. Modell-Name für Ensemble-Läufe)",
    )
    parser.add_argument(
        "--ensemble",
        type=int,
        default=0,
        help="Führe N Modelle parallel aus und wähle die beste Lösung. Beispiel: --ensemble 3",
    )

    parser.add_argument(
        "--continue-run",
        action="store_true",
        dest="continue_",
        help="Vorhandenen Branch mit Änderungen weiterbearbeiten statt PR zu erstellen",
    )
    parser.add_argument(
        "--rework",
        action="store_true",
        help=(
            "Vorhandenen offenen Issue-PR-Branch bewusst weiterbearbeiten. "
            "Standard bleibt: offene PRs überspringen."
        ),
    )
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
    parser.add_argument(
        "--run-report-dir",
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--verbosity",
        choices=("quiet", "normal", "verbose"),
        default="normal",
        help="Worker-Ausgabe: quiet=keine Live-Ausgabe, normal=gefiltert (Standard), verbose=alles",
    )
    parser.add_argument(
        "--cleanup-preserved-worktrees",
        action="store_true",
        help="Alte gesicherte Recovery-Worktrees unter reports/preserved-worktrees aufraeumen",
    )
    parser.add_argument(
        "--retention-days",
        type=int,
        default=PRESERVED_WORKTREE_RETENTION_DAYS,
        help=f"Aufbewahrung fuer gesicherte Worktrees in Tagen (Default: {PRESERVED_WORKTREE_RETENTION_DAYS})",
    )
    parser.add_argument(
        "--cleanup-stale-locks",
        action="store_true",
        help="Veraltete Lock-Dateien unter reports/locks bereinigen",
    )
    # Workflow-Congestion-Steuerung
    parser.add_argument(
        "--skip-congestion-check",
        action="store_true",
        help="Workflow-Congestion-Check vor dem Start ueberspringen",
    )
    parser.add_argument(
        "--skip-hygiene-check",
        action="store_true",
        help="Lokalen Pre-Solver-Hygiene-Check bewusst ueberspringen",
    )
    parser.add_argument(
        "--pr-threshold",
        type=int,
        default=3,
        help="Maximale Anzahl offener PRs bevor eine Warnung ausgegeben wird (Standard: 3)",
    )
    parser.add_argument(
        "--retry",
        action="store_true",
        help="Erzwingt die erneute Bearbeitung eines Issues, auch wenn bereits ein offener PR existiert",
    )
    parser.add_argument(
        "--compare-models",
        action="store_true",
        help="Mehrere Modelle auf demselben Issue ausfuehren (erfordert --retry)",
    )
    # OpenCode Budget-Limits (nur fuer --model opencode)
    parser.add_argument(
        "--max-run-cost-usd",
        type=float,
        default=None,
        help="Maximale Kosten in USD fuer einen OpenCode-Run",
    )
    parser.add_argument(
        "--max-run-input-tokens",
        type=int,
        default=None,
        help="Maximale Input-Tokens fuer einen OpenCode-Run",
    )
    parser.add_argument(
        "--max-run-output-tokens",
        type=int,
        default=None,
        help="Maximale Output-Tokens fuer einen OpenCode-Run",
    )
    parser.add_argument(
        "--max-run-cache-read-tokens",
        type=int,
        default=None,
        help="Maximale Cache-Read-Tokens fuer einen OpenCode-Run",
    )
    parser.add_argument(
        "--max-run-runtime-seconds",
        type=float,
        default=None,
        help="Maximale Laufzeit in Sekunden fuer direkte API-Worker wie OpenRouter Direct",
    )
    parser.add_argument(
        "--max-post-worker-runtime-seconds",
        type=float,
        default=None,
        help="Maximale Laufzeit in Sekunden fuer Validierung, Tests, Commit, Push und PR-Erstellung",
    )
    args = parser.parse_args()

    if args.cleanup_preserved_worktrees:
        stale_paths = cleanup_preserved_worktrees(
            retention_days=args.retention_days,
            dry_run=args.dry_run,
        )
        action = "Wuerde loeschen" if args.dry_run else "Geloescht"
        if not stale_paths:
            print("   Keine alten gesicherten Worktrees gefunden.")
        for path in stale_paths:
            print(f"   {action}: {path}")
        if args.dry_run and stale_paths:
            print("   Ohne --dry-run ausfuehren, um diese Worktrees zu loeschen.")
        return

    if args.cleanup_stale_locks:
        stale_locks = cleanup_stale_locks(dry_run=args.dry_run)
        action = "Wuerde loeschen" if args.dry_run else "Geloescht"
        if not stale_locks:
            print("   Keine veralteten Lock-Dateien gefunden.")
        for lock_path in stale_locks:
            print(f"   {action}: {lock_path}")
        if args.dry_run and stale_locks:
            print("   Ohne --dry-run ausfuehren, um diese Lock-Dateien zu loeschen.")
        return

    if args.diagnostic:
        if args.model and args.model != "opencode":
            print_warn("--diagnostic ist nur für --model opencode vorgesehen")
        exit_code = run_opencode_diagnostic()
        sys.exit(exit_code)

    if not args.model:
        parser.error("--model ist erforderlich, ausser bei --cleanup-preserved-worktrees")

    if requests is None:
        print_err("Python-Abhängigkeit fehlt: requests")
        print("   → Installieren mit: pip install -r requirements.txt")
        sys.exit(1)

    # Config laden
    cfg = load_env()

    # Role routing config laden (überlebt Fehler — nur Warnung)
    global _ROLE_ROUTING, _BUDGET_TRACKING_ACTIVE
    _ROLE_ROUTING = _ensure_role_routing()

    # OpenRouter-Slugs verifizieren (überspringbar mit --skip-slug-verification)
    if _ROLE_ROUTING and not args.skip_slug_verification and not args.dry_run:
        if not _ensure_slug_verification():
            sys.exit(1)
        print("   ✅ OpenRouter model slugs verified")

    _BUDGET_TRACKING_ACTIVE = bool(_ROLE_ROUTING and not args.skip_budget_check)

    if not args.skip_hygiene_check:
        if not run_pre_solver_hygiene_check(dry_run=args.dry_run):
            sys.exit(1)

    # Preflight-Checks durchfuehren
    if args.repo:
        token, user = preflight_checks(cfg, args.repo, args.issue)
    else:
        token, user = require_github_config(cfg, require_user=True)

    # KI-Worker prüfen
    if args.model == "codex" and not find_codex_executable() and not args.dry_run:
        print_err("Codex CLI wurde nicht gefunden!")
        print("   → Codex Desktop App installieren oder `codex` in PATH verfügbar machen")
        sys.exit(1)

    if args.model == "mistral-vibe" and not find_vibe_executable() and not args.dry_run:
        print_err("Mistral Vibe CLI wurde nicht gefunden!")
        print("   → Installieren in der aktiven Umgebung mit: pip install mistral-vibe")
        sys.exit(1)

    if args.model == "opencode" and not args.dry_run:
        opencode_exe = find_opencode_executable()
        if not opencode_exe:
            print_err("OpenCode CLI wurde nicht gefunden!")
            print("   → Installieren: https://opencode.ai/docs/installation")
            print("   → Danach `opencode` im PATH verfügbar machen")
            sys.exit(1)
        if not check_opencode_state_guard(
            opencode_exe,
            allow_conflict=args.allow_opencode_state_conflict,
        ):
            sys.exit(1)
        check_opencode_auth(opencode_exe)
        print_solver_directories()

    if args.model == "openrouter" and not check_aider_installed() and not args.dry_run:
        print_err("aider ist nicht installiert, wird aber für OpenRouter benötigt!")
        print("   → Installieren mit: pip install aider-chat")
        print("   → Mehr Infos: docs/SETUP_AIDER.md")
        sys.exit(1)

    if args.model not in ("codex", "mistral-vibe", "opencode", "openrouter") and not check_aider_installed() and not args.dry_run:
        print_err("aider ist nicht installiert!")
        print("   → Installieren mit: pip install aider-chat")
        print("   → Mehr Infos: docs/SETUP_AIDER.md")
        sys.exit(1)

     # Modellauswahl
    if args.auto_model:
        from model_selection import select_model_for_issue
        # Hole das Issue für die Analyse
        issue = client.get_single_issue(args.repo, args.issue) if args.issue and args.repo else None
        if not issue:
            print_err("--auto-model erfordert --repo und --issue")
            sys.exit(1)
        # Wähle Modell automatisch aus
        cli_repo_profile_obj, cli_repo_profile_dict = build_repo_profile_for_run(
            args.repo, cfg, branch=None,
        )
        if cli_repo_profile_dict:
            print(
                f"      🛰️ Repo-Profil-Quelle: {cli_repo_profile_dict.get('source', 'unknown')}, "
                f"Typ: {cli_repo_profile_dict.get('repo_kind', 'unknown')}, "
                f"Sprache: {cli_repo_profile_dict.get('dominant_language') or 'unbekannt'}"
            )
        model_selection = select_model_for_issue(
            issue=issue,
            repo_type=repo_type_from_profile(cli_repo_profile_obj),
            max_cost_tier=args.max_cost,
        )
        print(f"   🔍 Automatische Modellauswahl: {model_selection['model']}")
        print(f"      Grund: {model_selection['reason']}")
        print(f"      Kategorie: {model_selection['category']} (Risiko: {model_selection['risk']})")
        print(f"      Kosten-Tier: {model_selection['cost_tier']}")

        # Mappe das ausgewählte Modell auf die bestehende MODEL_CONFIGS-Struktur
        # TODO: Erweitere MODEL_CONFIGS für alle unterstützten Modelle
        selected = model_selection["model"]
        if selected in MODEL_CONFIGS["opencode"].get("free_models", []):
            args.model = "opencode"
            args.model_name = selected
        elif "mistral" in selected:
            args.model = "mistral"
            args.model_name = selected
        elif "claude" in selected:
            args.model = "claude"
            args.model_name = selected
        elif "gpt" in selected:
            args.model = "openai"
            args.model_name = selected
        else:
            print_err(f"Automatisch ausgewähltes Modell wird nicht unterstützt: {selected}")
            sys.exit(1)

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

    if args.ensemble > 0:
        print_step(1, f"Ensemble-Modus: {args.ensemble} Modelle parallel")
        models = [
            "opencode/deepseek-v4-flash-free",
            "opencode/mimo-v2.5-free",
            "claude-sonnet-4-20250514",
            "gpt-4o",
            "mistral/mistral-small-2603"
        ]
        print(f"   Modelle: {', '.join(models[:args.ensemble])}")
    elif args.auto_model:
        print_step(1, f"Modell (automatisch): {MODEL_CONFIGS[args.model]['display_name']}")
        print(f"   Modell-Name: {args.model_name}")
        print(f"   Kosten-Tier: {args.max_cost}")
    else:
        print_step(1, f"Modell: {model_config['display_name']}")
        if model_name:
            print(f"   Modell-Name: {model_name}")

    # Repos ermitteln
    if args.repo:
        repos = [args.repo]
    else:
        all_repos = client.get_repos()
        repos = [r["name"] for r in all_repos if not r.get("archived")]

    # Modellauswahl-Logik für Batch-Modus (TODO: Erweitern)
    if args.auto_model and not args.issue:
        print_warn("--auto-model erfordert --issue; nutze --model für Batch-Modus")
        sys.exit(1)

    # Workflow-Congestion-Check vor dem Start
    if not args.skip_congestion_check and not args.dry_run:
        print_step(2, "Workflow-Congestion-Check")
        for repo_name in repos:
            can_proceed = check_and_warn_on_congestion(
                client,
                repo_name,
                issue_number=args.issue,
                pr_threshold=args.pr_threshold,
                skip_congestion_check=args.skip_congestion_check,
            )
            if not can_proceed and args.issue:
                print_err(f"Workflow-Congestion blockiert Issue #{args.issue} in {repo_name}")
                sys.exit(1)
        print()

    print_step(3, f"Suche offene Issues in {len(repos)} Repo(s)")

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
            issue_number = issue.get("number", 0)

            # Workflow-Congestion-Check: Issues mit offenen PRs ueberspringen
            # (ausser --retry, --compare-models oder --rework ist gesetzt)
            if not args.retry and not args.compare_models and not args.rework and issue_number:
                try:
                    open_prs_for_issue = client.get_pull_requests_for_branch(
                        repo_name,
                        f"ai/fix-issue-{issue_number}",
                        state="open",
                    )
                    if open_prs_for_issue:
                        print_warn(
                            f"   Issue #{issue_number} hat bereits offene PRs; "
                            "ueberspringe (--retry zum Erzwingen)"
                        )
                        for pr in open_prs_for_issue:
                            print(f"      - PR #{pr.number}: {pr.html_url}")
                        continue
                except Exception:
                    pass

            # Monthly budget check (solver role)
            if _BUDGET_TRACKING_ACTIVE and _ROLE_ROUTING:
                solver_role = _ROLE_ROUTING.get("roles", {}).get("solver", {})
                from role_routing_loader import check_budget
                allowed, budget_msg = check_budget("solver", solver_role)
                if not allowed:
                    print_err(budget_msg)
                    print_err("Use --skip-budget-check to bypass.")
                    failed += 1
                    continue
                if budget_msg:
                    print_warn(budget_msg)

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
                run_report_dir=args.run_report_dir,
                verbosity=args.verbosity,
                auto_model=args.auto_model,
                max_cost=args.max_cost,
                skip_pr=args.skip_pr,
                branch_suffix=args.branch_suffix,
                continue_=args.continue_,
                max_run_cost_usd=args.max_run_cost_usd,
                max_run_input_tokens=args.max_run_input_tokens,
                max_run_output_tokens=args.max_run_output_tokens,
                max_run_cache_read_tokens=args.max_run_cache_read_tokens,
                max_run_runtime_seconds=args.max_run_runtime_seconds,
                max_post_worker_runtime_seconds=args.max_post_worker_runtime_seconds,
                ensemble=args.ensemble,
                role_routing=_ROLE_ROUTING if _BUDGET_TRACKING_ACTIVE else None,
                rework=args.rework,
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
