"""ais_core.repo_resolve — resolve a repo hint to a fully-qualified
GitHub repository reference plus optional local checkout path.

This module is intentionally side-effect-free: it does not import any
GitHub client or perform I/O at import time. The functions below are
placeholders for the v0.10.0 implementation (Issue #1b); they will
be filled in by subsequent work.

Public API:
    resolve_repo_hint(hint)            — accept 'owner/repo', 'repo',
                                          'repo_hint', or '/local/path'
    resolve_from_owner_repo(owner, repo)
    resolve_from_git_remote(path)
    ResolvedRepo                       — typed result
"""

from __future__ import annotations

from typing import NamedTuple


class ResolvedRepo(NamedTuple):
    """A fully-qualified repository reference.

    Attributes:
        owner: GitHub owner (user or org).
        repo: GitHub repository name.
        remote: Canonical remote URL (e.g. 'https://github.com/owner/repo').
        local_path: Optional local checkout path (None if not on disk).
    """

    owner: str
    repo: str
    remote: str
    local_path: str | None


__all__ = [
    "ResolvedRepo",
    "resolve_repo_hint",
    "resolve_from_owner_repo",
    "resolve_from_git_remote",
]


def resolve_repo_hint(hint: str) -> ResolvedRepo:
    """Resolve an arbitrary repo hint to a ResolvedRepo.

    Accepts any of:
        - explicit 'owner/repo'
        - bare 'repo' (assumes configured default owner)
        - 'repo_hint' (looked up against a hint registry)
        - '/local/path' to a git checkout
    """
    raise NotImplementedError("ais_core.repo_resolve.resolve_repo_hint (Issue #1b)")


def resolve_from_owner_repo(owner: str, repo: str) -> ResolvedRepo:
    """Resolve from explicit (owner, repo) GitHub coordinates."""
    raise NotImplementedError("ais_core.repo_resolve.resolve_from_owner_repo (Issue #1b)")


def resolve_from_git_remote(path: str) -> ResolvedRepo:
    """Resolve by inspecting the `origin` remote of a local git checkout."""
    raise NotImplementedError("ais_core.repo_resolve.resolve_from_git_remote (Issue #1b)")