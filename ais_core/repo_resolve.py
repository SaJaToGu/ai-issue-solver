"""ais_core.repo_resolve — resolve a repo hint to a fully-qualified
GitHub repository reference plus optional local checkout path.

This module is intentionally side-effect-free for ``resolve_from_owner_repo``
(no network, no GitHub API call) and only invokes local ``git`` for
``resolve_from_git_remote`` (no network). It is the entry point for
extracting repo-resolution logic out of ``scripts/solve_issues.py``
under Issue #1b (Wave 1b).

Resolution surface (public API):

- :func:`resolve_from_owner_repo` — normalize an explicit
  ``(owner, repo)`` pair into a :class:`ResolvedRepo`. No API call.
- :func:`resolve_from_git_remote` — read ``remote.origin.url`` from a
  local git checkout and parse out the (owner, repo) pair. No
  network; uses local ``git config``.
- :func:`resolve_repo_hint` — dispatch a free-form hint string to the
  appropriate resolver based on its shape:

      * ``"/local/path"`` or any existing directory → :func:`resolve_from_git_remote`
      * ``"owner/repo"`` → :func:`resolve_from_owner_repo` with the split pair
      * bare ``"repo"`` → :func:`resolve_from_owner_repo` with the
        default owner from the ``GITHUB_USER`` environment variable

Resolution rules (encoded in :func:`_parse_repo_components`):

- ``owner`` and ``repo`` must be non-empty, must not contain ``/`` (after
  splitting for the hint case), and must match the GitHub naming
  character set (alnum, ``-``, ``_``, ``.``).
- The canonical remote URL is ``https://github.com/{owner}/{repo}``.
  (We do not honor per-host overrides yet; that's deferred to a
  follow-up issue.)

Limitations (intentional for #1b):

- No GitHub API call: existence of the repo on github.com is NOT
  verified. ``resolve_from_owner_repo`` will happily produce a
  ``ResolvedRepo`` for a non-existent repo.
- No SSH-vs-HTTPS preference: the canonical remote is always HTTPS.
- No sub-group / sub-path support: the remote is always
  ``github.com/{owner}/{repo}``, not e.g. a GitHub Enterprise URL.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path
from typing import NamedTuple


class ResolvedRepo(NamedTuple):
    """A fully-qualified repository reference.

    Attributes:
        owner: GitHub owner (user or org).
        repo: GitHub repository name.
        remote: Canonical remote URL (currently always
            ``https://github.com/{owner}/{repo}``).
        local_path: Optional local checkout path (None if not on disk).
    """

    owner: str
    repo: str
    remote: str
    local_path: str | None


__all__ = [
    "ResolvedRepo",
    "resolve_from_owner_repo",
    "resolve_from_git_remote",
    "resolve_repo_hint",
]


# --- helpers ---------------------------------------------------------------

# GitHub naming rules differ between owner and repo:
#   - owner: alnum + '-', 1-39 chars. Underscores and dots are NOT
#     allowed in GitHub owner names. Must START and END with alnum
#     (no leading/trailing dashes).
#   - repo:  alnum + '-', '_', '.', 1-100 chars. Underscores and dots
#     ARE allowed in GitHub repo names. Must START and END with alnum
#     (no leading/trailing separators).
_OWNER_NAME_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?$")
_REPO_NAME_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?$")
_OWNER_MAX = 39
_REPO_MAX = 100

# Hosts we accept for git remote URLs. GitHub supports both
# `github.com` and `www.github.com` as canonical hosts; anything else
# (GitLab, Bitbucket, Gitea, self-hosted) is rejected to keep the
# library's contract honest about its scope.
_ALLOWED_GIT_HOSTS = frozenset({"github.com", "www.github.com"})

# GitHub remote paths are EXACTLY /owner/repo[.git]. We reject
# anything with more or fewer path segments (e.g. org subgroups,
# deep paths, or empty owner/repo).
_MIN_PATH_SEGMENTS = 2
_MAX_PATH_SEGMENTS = 2


def _validate_component(value: str, *, kind: str) -> str:
    """Validate a single owner/repo name component. Returns the cleaned
    string on success, raises :class:`ValueError` otherwise.
    """
    if not isinstance(value, str):
        raise TypeError(
            f"{kind} must be a str, got {type(value).__name__}"
        )
    cleaned = value.strip()
    if not cleaned:
        raise ValueError(f"{kind} must not be empty")
    if kind == "owner":
        max_len = _OWNER_MAX
        pattern = _OWNER_NAME_RE
        allowed = "alnum and '-'"
    else:
        max_len = _REPO_MAX
        pattern = _REPO_NAME_RE
        allowed = "alnum, '.', '-', '_'"
    if len(cleaned) > max_len:
        raise ValueError(
            f"{kind} too long: {len(cleaned)} chars (max {max_len})"
        )
    if not pattern.match(cleaned):
        raise ValueError(
            f"{kind} contains invalid characters: {value!r} "
            f"(allowed: {allowed})"
        )
    return cleaned


def _canonical_remote(owner: str, repo: str) -> str:
    return f"https://github.com/{owner}/{repo}"


def _read_git_remote_url(path: Path) -> str:
    """Read ``remote.origin.url`` from a local git checkout.

    Uses ``git config --get`` (local invocation; no network).
    Raises :class:`ValueError` if the URL is missing or ``git`` is not
    available.
    """
    try:
        result = subprocess.run(
            ["git", "-C", str(path), "config", "--get", "remote.origin.url"],
            check=True,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as exc:
        raise ValueError(
            "git executable not found; cannot resolve from local checkout"
        ) from exc
    except subprocess.CalledProcessError as exc:
        raise ValueError(
            f"no remote.origin.url configured for {path}"
        ) from exc
    url = result.stdout.strip()
    if not url:
        raise ValueError(f"empty remote.origin.url for {path}")
    return url


def _parse_git_remote_url(url: str) -> tuple[str, str]:
    """Parse a git remote URL into ``(owner, repo)``.

    Supports:
        - HTTPS: ``https://github.com/owner/repo.git`` (also without ``.git``)
        - SSH: ``git@github.com:owner/repo.git``
        - ssh:// URL form
    """
    if not isinstance(url, str):
        raise TypeError(f"url must be a str, got {type(url).__name__}")
    url = url.strip()
    if not url:
        raise ValueError("empty git remote URL")

    if url.startswith("git@"):
        # git@github.com:owner/repo.git
        # Convert to ssh:// form for uniform parsing.
        host_and_path = url[4:]  # strip "git@"
        if ":" not in host_and_path:
            raise ValueError(f"cannot parse SSH git URL: {url!r}")
        host, path = host_and_path.split(":", 1)
        ssh_url = f"ssh://{host}/{path}"
        return _parse_http_or_ssh(ssh_url, original=url)

    if url.startswith(("http://", "https://", "ssh://")):
        return _parse_http_or_ssh(url, original=url)

    raise ValueError(f"unrecognized git remote URL format: {url!r}")


def _parse_http_or_ssh(url: str, *, original: str) -> tuple[str, str]:
    """Parse an http(s) or ssh:// URL into ``(owner, repo)``.

    Also enforces that the URL's host is in :data:`_ALLOWED_GIT_HOSTS`
    (currently ``github.com`` and ``www.github.com``). Other hosts
    (GitLab, Bitbucket, Gitea, self-hosted) raise ``ValueError``.
    """
    from urllib.parse import urlparse
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if host not in _ALLOWED_GIT_HOSTS:
        raise ValueError(
            f"unsupported git host: {host!r} "
            f"(allowed: {sorted(_ALLOWED_GIT_HOSTS)})"
        )
    path = parsed.path.strip("/")
    if not path:
        raise ValueError(f"cannot parse URL (no path): {original!r}")
    parts = path.split("/")
    if not (_MIN_PATH_SEGMENTS <= len(parts) <= _MAX_PATH_SEGMENTS):
        raise ValueError(
            f"unexpected path depth in {original!r}: "
            f"expected exactly {_MIN_PATH_SEGMENTS} segments "
            f"(/owner/repo[.git]), got {len(parts)}"
        )
    owner = parts[-2]
    repo = parts[-1]
    if repo.endswith(".git"):
        repo = repo[:-4]
    return owner, repo


# --- public API ------------------------------------------------------------


def resolve_from_owner_repo(owner: str, repo: str) -> ResolvedRepo:
    """Resolve an explicit ``(owner, repo)`` pair into a :class:`ResolvedRepo`.

    Does NOT call the GitHub API. Existence of the repo on github.com
    is not verified.

    Args:
        owner: GitHub owner (user or org). Validated for non-empty
            and GitHub naming rules.
        repo: GitHub repository name. Validated likewise.

    Returns:
        A :class:`ResolvedRepo` with ``remote`` set to
        ``https://github.com/{owner}/{repo}`` and ``local_path=None``.
    """
    owner_clean = _validate_component(owner, kind="owner")
    repo_clean = _validate_component(repo, kind="repo")
    return ResolvedRepo(
        owner=owner_clean,
        repo=repo_clean,
        remote=_canonical_remote(owner_clean, repo_clean),
        local_path=None,
    )


def resolve_from_git_remote(path: str) -> ResolvedRepo:
    """Resolve by reading ``remote.origin.url`` of a local git checkout.

    Args:
        path: Filesystem path to a local git checkout (must contain
            ``.git/config`` with a ``remote.origin.url``).

    Returns:
        A :class:`ResolvedRepo` with ``local_path`` set to the given
        path and ``remote`` set to the canonical HTTPS URL.

    Raises:
        ValueError: if the path is not a directory, the remote URL
            is missing, or the URL cannot be parsed.
    """
    p = Path(path)
    if not p.is_dir():
        raise ValueError(f"path is not a directory: {path!r}")
    url = _read_git_remote_url(p)
    owner, repo = _parse_git_remote_url(url)
    return ResolvedRepo(
        owner=owner,
        repo=repo,
        remote=_canonical_remote(owner, repo),
        local_path=str(p),
    )


def resolve_repo_hint(hint: str) -> ResolvedRepo:
    """Dispatch a free-form hint to the appropriate resolver.

    Recognized shapes (in order):

    1. Existing directory (absolute or relative) → :func:`resolve_from_git_remote`
    2. ``"owner/repo"`` (contains a ``/``) → :func:`resolve_from_owner_repo`
       with the split pair
    3. Bare ``"repo"`` (no ``/``) → :func:`resolve_from_owner_repo` with
       the default owner from the ``GITHUB_USER`` environment variable

    Args:
        hint: Free-form repo hint.

    Returns:
        A :class:`ResolvedRepo`.

    Raises:
        ValueError: if the hint is empty, the bare-repo form is used
            without a ``GITHUB_USER`` env var, the path doesn't
            resolve to a git checkout, or the input is otherwise
            invalid.
    """
    if not isinstance(hint, str):
        raise TypeError(f"hint must be a str, got {type(hint).__name__}")
    h = hint.strip()
    if not h:
        raise ValueError("hint must not be empty")

    # 1. Directory → resolve from local git remote
    if Path(h).is_dir():
        return resolve_from_git_remote(h)

    # 2. owner/repo → split
    if "/" in h:
        owner, repo = h.split("/", 1)
        return resolve_from_owner_repo(owner, repo)

    # 3. Bare repo → use GITHUB_USER default owner
    default_owner = os.environ.get("GITHUB_USER", "").strip()
    if not default_owner:
        raise ValueError(
            f"bare repo hint {h!r} requires GITHUB_USER env var "
            f"(or use 'owner/repo' form or an existing local path)"
        )
    return resolve_from_owner_repo(default_owner, h)
