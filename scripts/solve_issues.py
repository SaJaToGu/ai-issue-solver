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
import json
import os
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
    print_ok,
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
                             head: str, base: str = "main",
                             dry_run: bool = False) -> dict | None:
        if dry_run:
            print(f"      [DRY-RUN] Würde PR erstellen: '{title}'")
            return {"html_url": "https://github.com/dry-run-pr"}

        # Prüfe ob 'main' oder 'master' existiert
        resp = self.session.get(f"{self.BASE}/repos/{self.owner}/{repo}/branches/{base}")
        if resp.status_code == 404:
            base = "master"

        resp = self.session.post(
            f"{self.BASE}/repos/{self.owner}/{repo}/pulls",
            json={"title": title, "body": body, "head": head, "base": base}
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


def build_aider_command(model: str, model_name: str, prompt: str, repo_path: str) -> list:
    config = MODEL_CONFIGS[model]
    flags = []

    for flag in config["aider_flags"]:
        if "{model_name}" in flag:
            flags.append(flag.format(model_name=model_name))
        else:
            flags.append(flag)

    cmd = [
        "aider",
        *flags,
        "--yes",                   # Automatisch ja sagen
        "--no-auto-commits",       # Wir committen selbst
        "--message", prompt,       # Direkt-Prompt (kein interaktiver Modus)
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
    subprocess.run(
        ["git", "commit", "-m", message],
        cwd=repo_dir, capture_output=True, text=True,
        env={**os.environ,
             "GIT_AUTHOR_NAME": "AI Issue Solver",
             "GIT_AUTHOR_EMAIL": "ai@github.com",
             "GIT_COMMITTER_NAME": "AI Issue Solver",
             "GIT_COMMITTER_EMAIL": "ai@github.com"}
    )

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
        create_branch(repo_dir, branch_name)

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

        result = subprocess.run(
            cmd, cwd=repo_dir, env=env,
            capture_output=False,  # Output direkt anzeigen
            text=True,
        )

        if result.returncode != 0:
            changed = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=repo_dir, capture_output=True, text=True,
            )
            if not changed.stdout.strip():
                print_warn(f"KI-Worker exit code: {result.returncode}; keine Änderungen erzeugt")
                return False
            print_warn(f"KI-Worker exit code: {result.returncode}; Änderungen werden geprüft")

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
    parser.add_argument("--base-branch", default="develop", help="Zielbranch für Klon und PR")
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
                base_branch=args.base_branch,
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
