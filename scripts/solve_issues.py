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

import argparse
from dataclasses import dataclass
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

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


@dataclass(frozen=True)
class WorkerRunResult:
    returncode: int
    output: str


@dataclass(frozen=True)
class WorkerAssessment:
    should_continue: bool
    has_changes: bool
    reason: str


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
        try:
            resp = self.session.get(f"{self.BASE}/repos/{self.owner}/{repo}/branches/{branch}")
        except requests.RequestException as exc:
            handle_github_request_error(exc, f"Branch prüfen: {repo}/{branch}")
        if resp.status_code == 404:
            return False
        raise_for_github_response(resp, f"Branch prüfen: {repo}/{branch}")
        return True

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
    """Fuehrt den KI-Worker aus, zeigt Output live und haelt ihn fuer Diagnosen fest."""
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
    if process.stdout:
        for line in process.stdout:
            print(line, end="")
            output_parts.append(line)
        process.stdout.close()

    return WorkerRunResult(
        returncode=process.wait(),
        output="".join(output_parts),
    )


def git_status_porcelain(repo_dir: str) -> str:
    result = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=repo_dir, capture_output=True, text=True,
    )
    if result.returncode != 0:
        print_warn("Git-Status konnte nicht gelesen werden")
        return ""
    return result.stdout


def assess_worker_result(result: WorkerRunResult, git_status: str) -> WorkerAssessment:
    has_changes = bool(git_status.strip())
    if result.returncode == 0 and has_changes:
        return WorkerAssessment(True, True, "changed")
    if result.returncode == 0:
        return WorkerAssessment(False, False, "no_changes")
    if has_changes:
        return WorkerAssessment(True, True, "nonzero_with_changes")
    return WorkerAssessment(False, False, "nonzero_without_changes")


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


# ─────────────────────────────────────────────────────────────
# Issue lösen
# ─────────────────────────────────────────────────────────────

def solve_issue(client: GitHubClient, issue: dict, repo: str,
                model: str, model_name: str, config: dict,
                token: str, dry_run: bool, base_branch: str,
                close_issues: bool) -> bool:
    number = issue["number"]
    title = issue["title"]
    body = issue.get("body", "")

    print(f"\n   🔧 Issue #{number}: {title}")
    print(f"      Modell: {MODEL_CONFIGS[model]['display_name']}")

    if dry_run:
        print(f"      [DRY-RUN] Würde bearbeiten mit {model}")
        print(f"      [DRY-RUN] Zielbranch: {base_branch}")
        return True

    # Repo klonen
    with tempfile.TemporaryDirectory(prefix="ai-solver-") as tmpdir:
        repo_dir = os.path.join(tmpdir, repo)
        print(f"      📥 Klone {repo} ...", end=" ", flush=True)

        if not clone_repo(config["owner"], repo, token, repo_dir, base_branch):
            print_err("Klonen fehlgeschlagen")
            print(f"      Prüfe, ob der Branch '{base_branch}' in {repo} existiert.")
            return False
        print("✅")

        # Branch anlegen
        branch_name = f"ai/fix-issue-{number}"
        if not create_branch(repo_dir, branch_name):
            print_err(f"Branch konnte nicht erstellt werden: {branch_name}")
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

        result = run_worker_command(cmd, repo_dir, env)
        assessment = assess_worker_result(result, git_status_porcelain(repo_dir))
        print_worker_assessment(result, assessment)
        if not assessment.should_continue:
            return False

        # Committen & pushen
        print(f"      📤 Commit & Push ...", end=" ", flush=True)
        commit_msg = f"fix: Löse Issue #{number} — {title}\n\nAutomatisch gelöst mit AI Issue Solver (Modell: {model})\nIssue: https://github.com/{config['owner']}/{repo}/issues/{number}"

        pushed = commit_and_push(repo_dir, branch_name, commit_msg, token, config["owner"], repo)

        if not pushed:
            print_warn("Push fehlgeschlagen oder keine Änderungen")
            return False
        print("✅")

        # PR erstellen
        pr_body = f"""## 🤖 AI-generierter Fix für Issue #{number}

Dieses PR wurde automatisch durch [ai-issue-solver](https://github.com/{config['owner']}/ai-issue-solver) erstellt.

### Gelöstes Issue
{"Closes" if close_issues else "Refs"} #{number}: {title}

### Verwendetes Modell
`{MODEL_CONFIGS[model]['display_name']}`

### Änderungen
*(bitte vor dem Merge reviewen)*

---
*Erstellt mit dem AI Issue Solver (Morpheus-Methode)*
"""
        pr = client.create_pull_request(
            repo=repo,
            title=f"[AI] Fix: {title}",
            body=pr_body,
            head=branch_name,
            base=base_branch,
            dry_run=dry_run,
        )
        if pr:
            print(f"      🔀 PR erstellt: {pr.get('html_url', '?')}")

        if close_issues:
            close_comment = f"✅ Dieses Issue wurde automatisch durch den AI Issue Solver bearbeitet.\n\nPR: {pr.get('html_url', '?') if pr else '(kein PR)'}\nModell: {MODEL_CONFIGS[model]['display_name']}"
            client.close_issue_with_comment(repo, number, close_comment)

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
