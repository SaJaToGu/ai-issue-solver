from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

NOTES_REF = "refs/notes/ais"


def _git(*args: str, repo_root: str | Path | None = None) -> str:
    cmd = ["git"]
    if repo_root:
        cmd.extend(["-C", str(repo_root)])
    cmd.extend(args)
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        print(f"git error: {result.stderr.strip()}", file=sys.stderr)
        raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout.strip()


def ensure_notes_ref(repo_root: str | Path | None = None) -> None:
    _git("notes", "--ref", NOTES_REF, "add", "-m", "{}", "HEAD", repo_root=repo_root)


def read_note(ref: str = NOTES_REF, repo_root: str | Path | None = None) -> dict[str, Any]:
    try:
        output = _git("notes", "--ref", ref, "show", "HEAD", repo_root=repo_root)
        return json.loads(output) if output.strip() else {}
    except RuntimeError:
        return {}


def write_note(
    data: dict[str, Any],
    ref: str = NOTES_REF,
    repo_root: str | Path | None = None,
) -> None:
    payload = json.dumps(data, indent=2)
    _git("notes", "--ref", ref, "add", "-f", "-m", payload, "HEAD", repo_root=repo_root)


def add_sub_issues_to_note(
    parent_pr: int,
    sub_issues: list[dict[str, Any]],
    repo_root: str | Path | None = None,
) -> dict[str, Any]:
    note = read_note(repo_root=repo_root)
    key = str(parent_pr)
    existing = note.get(key, [])
    existing.extend(sub_issues)
    note[key] = existing
    write_note(note, repo_root=repo_root)
    return note


def get_sub_issues_for_pr(
    parent_pr: int,
    repo_root: str | Path | None = None,
) -> list[dict[str, Any]]:
    note = read_note(repo_root=repo_root)
    return note.get(str(parent_pr), [])
