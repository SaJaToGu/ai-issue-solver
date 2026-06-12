#!/usr/bin/env python3
"""solver_repository.py — Repository-Checkout und Branch-Lifecycle.

Dieses Modul bündelt den Git-Teil des Solver-Runs: das isolierte Klonen des
Repositories pro Run (#193), das Anlegen bzw. Wiederherstellen von Branches,
die Diff-Prüfung gegen den Base-Branch sowie Commit und Push.

Die Funktionen werden von ``solve_issues.py`` importiert und dort weiter unter
den bisherigen Namen bereitgestellt, damit sich das CLI-Verhalten nicht ändert.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import shutil
import subprocess

from scripts.utils import print_warn


@dataclass(frozen=True)
class CloneResult:
    ok: bool
    stderr: str = ""
    stdout: str = ""
    target_dir: str = ""

    def __bool__(self) -> bool:
        return self.ok


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


def sanitize_clone_output(output: str, token: str) -> str:
    if not output:
        return ""
    cleaned = output
    if token:
        cleaned = cleaned.replace(token, "***")
    return cleaned


def clone_repo(owner: str, repo: str, token: str, target_dir: str,
               base_branch: str) -> CloneResult:
    """Klont das Repository als isolierten Checkout in das Zielverzeichnis."""
    target_path = Path(target_dir)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    if target_path.exists() or target_path.is_symlink():
        if target_path.is_symlink() or target_path.is_file():
            target_path.unlink()
        else:
            shutil.rmtree(target_path)

    url = f"https://{token}@github.com/{owner}/{repo}.git"
    result = subprocess.run(
        ["git", "clone", "--branch", base_branch, "--single-branch", url, str(target_path)],
        capture_output=True, text=True
    )

    return CloneResult(
        ok=result.returncode == 0,
        stdout=sanitize_clone_output(result.stdout, token),
        stderr=sanitize_clone_output(result.stderr, token),
        target_dir=str(target_path),
    )


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
