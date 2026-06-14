#!/usr/bin/env python3
"""Provider-neutral repository profile helpers.

This module intentionally keeps the first slice small: GitHub is the only
implemented remote provider, local/offline repositories are supported as a
fallback, and other forge providers are represented as provider targets so the
solver contract does not become GitHub-shaped.

The provider is selected at runtime via :func:`select_profile_provider` which
prefers :class:`GitHubRepoProfileProvider` whenever a usable GitHub session is
available and falls back to :class:`LocalRepoProfileProvider` for offline,
non-GitHub, or already-checked-out repositories. Secret files such as ``.env``
or provider auth files are never read by either provider.
"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

try:
    import requests
except ImportError:  # pragma: no cover - exercised only in minimal installs
    requests = None


PROVIDER_TARGETS = {
    "github": "GitHub REST metadata, languages, topics, tree, workflows, issues, PRs, checks",
    "gitlab": "GitLab project metadata, languages, repository tree, CI pipelines, issues, merge requests",
    "forgejo": "Forgejo/Gitea/Codeberg metadata, file tree, issues, pull requests, CI hints",
    "gitea": "Forgejo/Gitea/Codeberg metadata, file tree, issues, pull requests, CI hints",
    "codeberg": "Forgejo/Gitea/Codeberg metadata, file tree, issues, pull requests, CI hints",
    "bitbucket": "Bitbucket metadata, file information, pipelines, issues, pull requests",
    "local": "Checked-out files and marker heuristics only",
}

SECRET_FILE_NAMES = {
    ".env",
    ".env.local",
    ".env.production",
    ".env.development",
    ".env.test",
    "auth.json",
    "credentials",
    "credentials.json",
    "secrets.json",
    "secrets.yaml",
    "secrets.yml",
    "config.json",
    "config.yaml",
    "config.yml",
}

SECRET_PATH_PREFIXES = (
    ".github/secrets/",
    "secrets/",
    "private/",
    "auth/",
)

VALIDATION_HINT_FROM_WORKFLOW = {
    "python": ("python -m pytest", "python -m unittest discover -s tests"),
    "javascript": ("npm test",),
    "typescript": ("npm test",),
    "r": ("Rscript -e 'testthat::test_dir(\"tests/testthat\")'",),
    "go": ("go test ./...",),
    "rust": ("cargo test",),
    "java": ("mvn test",),
}

LANGUAGE_NORMALIZATION = {
    "JavaScript": "javascript",
    "TypeScript": "typescript",
    "Python": "python",
    "R": "r",
    "HTML": "html",
    "CSS": "css",
    "Shell": "shell",
    "Dockerfile": "dockerfile",
}

MARKER_LANGUAGES = {
    "pyproject.toml": "python",
    "setup.py": "python",
    "requirements.txt": "python",
    "Pipfile": "python",
    "DESCRIPTION": "r",
    "renv.lock": "r",
    "app.R": "r",
    "package.json": "javascript",
    "tsconfig.json": "typescript",
    "go.mod": "go",
    "Cargo.toml": "rust",
    "pom.xml": "java",
    "build.gradle": "java",
}

FRAMEWORK_MARKERS = {
    "pyproject.toml": ("python",),
    "requirements.txt": ("python",),
    "DESCRIPTION": ("r",),
    "renv.lock": ("r",),
    "app.R": ("shiny",),
    "inst/shiny/app.R": ("shiny",),
    "package.json": ("node",),
    "tsconfig.json": ("typescript",),
}

TEST_MARKERS = {
    "pytest.ini": ("python -m pytest",),
    "tox.ini": ("tox",),
    "tests/": ("python -m unittest discover -s tests",),
    "tests/testthat/": ("Rscript -e 'testthat::test_dir(\"tests/testthat\")'",),
    "package.json": ("npm test",),
}


@dataclass(frozen=True)
class RepoProfile:
    """Provider-neutral repository profile consumed by solver planning."""

    provider: str
    repo: str
    dominant_language: str | None = None
    language_percentages: dict[str, float] = field(default_factory=dict)
    repo_kind: str = "unknown"
    framework_hints: tuple[str, ...] = ()
    test_hints: tuple[str, ...] = ()
    recommended_worker: str | None = None
    python_required: bool = False
    default_branch: str | None = None
    is_archived: bool = False
    is_private: bool = False
    repo_size_kb: int | None = None
    description: str | None = None
    topics: tuple[str, ...] = ()
    marker_files: tuple[str, ...] = ()
    extra: Mapping[str, Any] = field(default_factory=dict)
    source: str = "unknown"

    def as_model_selection_context(self) -> dict[str, Any]:
        """Return the small dict model-selection code can consume later."""
        return {
            "provider": self.provider,
            "repo": self.repo,
            "repo_type": self.repo_kind,
            "dominant_language": self.dominant_language,
            "language_percentages": dict(self.language_percentages),
            "framework_hints": list(self.framework_hints),
            "test_hints": list(self.test_hints),
            "recommended_worker": self.recommended_worker,
            "python_required": self.python_required,
            "source": self.source,
        }


class RepoProfileProvider(ABC):
    """Abstract provider contract for GitHub, GitLab, Forgejo/Gitea, Bitbucket, and local repos."""

    provider_name: str

    @abstractmethod
    def get_profile(self, repo: str, branch: str | None = None) -> RepoProfile:
        """Build a provider-neutral profile for a repository."""


def is_secret_path(path: str) -> bool:
    """Return True if a repository path points to a secret-bearing file.

    The local provider uses this to skip reading any file that may contain
    API keys, provider auth data, or other credentials. The GitHub provider
    also uses it to filter out secrets from any fetched tree payload so they
    are never written into the run report.
    """
    if not path:
        return False
    normalized = path.replace("\\", "/").lstrip("/")
    if not normalized:
        return False
    name = Path(normalized).name
    if name in SECRET_FILE_NAMES:
        return True
    lowered = normalized.lower()
    return any(lowered.startswith(prefix) for prefix in SECRET_PATH_PREFIXES)


def filter_secret_paths(paths: list[str]) -> tuple[str, ...]:
    """Drop any paths that point to secret files or directories."""
    if not paths:
        return ()
    return tuple(sorted(path for path in paths if not is_secret_path(path)))


def serialize_repo_profile(profile: RepoProfile) -> dict[str, Any]:
    """Convert a :class:`RepoProfile` into a JSON-safe dict for run reports."""
    safe_marker_files = list(filter_secret_paths(list(profile.marker_files)))
    safe_topics = list(profile.topics)
    safe_marker_files_clean = [path for path in safe_marker_files if not is_secret_path(path)]
    return {
        "provider": profile.provider,
        "repo": profile.repo,
        "dominant_language": profile.dominant_language,
        "language_percentages": dict(profile.language_percentages),
        "repo_kind": profile.repo_kind,
        "framework_hints": list(profile.framework_hints),
        "test_hints": list(profile.test_hints),
        "recommended_worker": profile.recommended_worker,
        "python_required": profile.python_required,
        "default_branch": profile.default_branch,
        "is_archived": profile.is_archived,
        "is_private": profile.is_private,
        "repo_size_kb": profile.repo_size_kb,
        "description": profile.description,
        "topics": safe_topics,
        "marker_files": safe_marker_files_clean,
        "source": profile.source,
        "extra": _serialize_extra(profile.extra),
    }


def _serialize_extra(extra: Mapping[str, Any]) -> dict[str, Any]:
    """Best-effort JSON conversion for the provider-specific ``extra`` payload."""
    if not extra:
        return {}
    converted: dict[str, Any] = {}
    for key, value in extra.items():
        if isinstance(value, (str, int, float, bool)) or value is None:
            converted[key] = value
        elif isinstance(value, Mapping):
            converted[key] = {str(inner_key): str(inner_value) for inner_key, inner_value in value.items()}
        elif isinstance(value, (list, tuple, set)):
            converted[key] = [_serialize_extra_value(item) for item in value]
        else:
            converted[key] = str(value)
    return converted


def _serialize_extra_value(value: Any) -> Any:
    """Recursively convert dicts/lists inside the ``extra`` payload."""
    if isinstance(value, Mapping):
        return {str(inner_key): _serialize_extra_value(inner_value) for inner_key, inner_value in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_serialize_extra_value(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def collect_test_hints_from_workflows(workflows: list[dict[str, Any]],
                                      dominant_language: str | None = None) -> tuple[str, ...]:
    """Derive validation hints from GitHub Actions workflow contents.

    The function intentionally only inspects top-level ``run`` commands or
    referenced scripts; it never reads file contents that may contain secrets.
    Secret-looking run targets (e.g. commands that point at ``auth.json`` or
    similar files) are filtered out so they never reach the run report.
    """
    hints: list[str] = []
    for workflow in workflows or ():
        if not isinstance(workflow, Mapping):
            continue
        name = str(workflow.get("name", "")).strip()
        path = str(workflow.get("path", "")).strip()
        run = workflow.get("run")
        if isinstance(run, str):
            stripped = run.strip()
            if stripped and not _run_command_targets_secrets(stripped):
                hints.append(stripped)
        scripts = workflow.get("scripts")
        if isinstance(scripts, (list, tuple)):
            for script in scripts:
                if isinstance(script, str) and script.strip() and not _run_command_targets_secrets(script.strip()):
                    hints.append(script.strip())
        if name or path:
            hints.append(f"github_actions: {name or Path(path).name}")
    lang_hints = VALIDATION_HINT_FROM_WORKFLOW.get(dominant_language or "", ())
    for hint in lang_hints:
        if hint not in hints:
            hints.append(hint)
    return tuple(dict.fromkeys(hints))


def _run_command_targets_secrets(command: str) -> bool:
    """Return True if a run-style command references a known secret file."""
    if not command:
        return False
    lowered = command.lower()
    for secret_name in SECRET_FILE_NAMES:
        if secret_name.lower() in lowered:
            return True
    for prefix in SECRET_PATH_PREFIXES:
        if prefix in lowered:
            return True
    return False


def summarize_remote_state(remote_state: Mapping[str, Any] | None) -> dict[str, Any]:
    """Normalize the optional remote-state payload (PRs, issues, checks)."""
    if not remote_state:
        return {
            "open_pull_requests": 0,
            "open_issues": 0,
            "open_issue_numbers": (),
            "open_pull_request_numbers": (),
            "existing_solver_branches": (),
        }
    return {
        "open_pull_requests": int(remote_state.get("open_pull_requests", 0) or 0),
        "open_issues": int(remote_state.get("open_issues", 0) or 0),
        "open_issue_numbers": tuple(remote_state.get("open_issue_numbers", ()) or ()),
        "open_pull_request_numbers": tuple(remote_state.get("open_pull_request_numbers", ()) or ()),
        "existing_solver_branches": tuple(remote_state.get("existing_solver_branches", ()) or ()),
    }


def select_profile_provider(repo: str,
                            *,
                            token: str | None = None,
                            owner: str | None = None,
                            local_root: Path | str | None = None,
                            session: Any | None = None,
                            offline: bool = False,
                            prefer: str = "github",
                            env: Mapping[str, str] | None = None) -> RepoProfileProvider:
    """Pick the right :class:`RepoProfileProvider` for the current run.

    Resolution rules:
    1. If ``offline`` is True or the configured ``prefer`` target is not
       implemented, return a :class:`LocalRepoProfileProvider` rooted at
       ``local_root`` (or the current working directory).
    2. If a GitHub token, owner, or session is available, return a
       :class:`GitHubRepoProfileProvider`.
    3. Otherwise fall back to the local provider.

    The function never reads or copies real secret files; tokens are only
    forwarded to the GitHub provider when explicitly supplied by the caller.
    """
    env_mapping: Mapping[str, str] = env if env is not None else os.environ
    prefer_normalized = (prefer or "github").strip().lower()
    if prefer_normalized not in {"github", "local"}:
        prefer_normalized = "github"

    has_token = bool(token) or bool(env_mapping.get("GITHUB_TOKEN") or env_mapping.get("GH_TOKEN"))
    has_owner = bool(owner) or bool(env_mapping.get("GITHUB_OWNER") or env_mapping.get("GH_OWNER"))
    has_session = session is not None or requests is not None

    if prefer_normalized == "github" and not offline and has_session and (has_token or has_owner or session is not None):
        return GitHubRepoProfileProvider(token=token, owner=owner, session=session)

    root = Path(local_root) if local_root is not None else Path.cwd()
    return LocalRepoProfileProvider(root)


def build_repo_profile(repo: str,
                      *,
                      token: str | None = None,
                      owner: str | None = None,
                      local_root: Path | str | None = None,
                      session: Any | None = None,
                      branch: str | None = None,
                      offline: bool = False,
                      prefer: str = "github",
                      env: Mapping[str, str] | None = None,
                      logger: Any = None) -> RepoProfile:
    """Build a :class:`RepoProfile` using GitHub first and the local fallback.

    This is the canonical entry point solver code should use. It first picks
    the appropriate provider via :func:`select_profile_provider`. When the
    GitHub provider is selected, transient API failures (network errors, 5xx
    responses) gracefully fall back to a local profile so solver runs can
    continue instead of crashing. Hard 404s for unknown repositories are not
    swallowed; they bubble up so misconfigurations stay visible.
    """
    provider = select_profile_provider(
        repo,
        token=token,
        owner=owner,
        local_root=local_root,
        session=session,
        offline=offline,
        prefer=prefer,
        env=env,
    )

    fallback_root = Path(local_root) if local_root is not None else Path.cwd()
    if provider.provider_name == "github":
        try:
            return provider.get_profile(repo, branch=branch)
        except (RuntimeError, ConnectionError, TimeoutError) as exc:
            if logger is not None and hasattr(logger, "warning"):
                logger.warning(
                    "GitHub profile fetch failed for %s (%s); using local fallback",
                    repo, exc,
                )
            return LocalRepoProfileProvider(fallback_root).get_profile(repo, branch=branch)

    return provider.get_profile(repo, branch=branch)


def normalize_language(language: str | None) -> str | None:
    if not language:
        return None
    return LANGUAGE_NORMALIZATION.get(language, language.lower())


def language_percentages(language_bytes: dict[str, int]) -> dict[str, float]:
    total = sum(max(value, 0) for value in language_bytes.values())
    if total <= 0:
        return {}
    return {
        normalize_language(name) or name.lower(): round((value / total) * 100, 2)
        for name, value in language_bytes.items()
        if value > 0
    }


def dominant_language(language_bytes: dict[str, int]) -> str | None:
    if not language_bytes:
        return None
    name, value = max(language_bytes.items(), key=lambda item: item[1])
    if value <= 0:
        return None
    return normalize_language(name)


def infer_marker_language(paths: list[str]) -> str | None:
    names = {Path(path).name for path in paths}
    for marker, language in MARKER_LANGUAGES.items():
        if marker in names or marker in paths:
            return language
    return None


def infer_repo_kind(language: str | None, paths: list[str], topics: tuple[str, ...] = ()) -> str:
    path_set = set(paths)
    lowered_topics = {topic.lower() for topic in topics}
    if not language and all(Path(path).suffix.lower() in {".md", ".txt", ".rst"} for path in paths):
        return "docs-only"
    if "app.R" in path_set or "inst/shiny/app.R" in path_set or "shiny" in lowered_topics:
        return "r-shiny"
    if language == "r":
        return "r"
    if language in {"javascript", "typescript"}:
        return "node"
    if language:
        return language
    return "unknown"


def collect_framework_hints(paths: list[str], topics: tuple[str, ...] = ()) -> tuple[str, ...]:
    hints: list[str] = []
    path_set = set(paths)
    for marker, marker_hints in FRAMEWORK_MARKERS.items():
        if marker in path_set or marker in {Path(path).name for path in paths}:
            hints.extend(marker_hints)
    for topic in topics:
        lowered = topic.lower()
        if lowered in {"shiny", "django", "flask", "fastapi", "react", "vue", "svelte"}:
            hints.append(lowered)
    return tuple(dict.fromkeys(hints))


def collect_test_hints(paths: list[str]) -> tuple[str, ...]:
    hints: list[str] = []
    path_set = set(paths)
    for marker, marker_hints in TEST_MARKERS.items():
        if marker.endswith("/"):
            if any(path.startswith(marker) for path in paths):
                hints.extend(marker_hints)
        elif marker in path_set or marker in {Path(path).name for path in paths}:
            hints.extend(marker_hints)
    return tuple(dict.fromkeys(hints))


def recommended_worker_for(repo_kind: str) -> str:
    if repo_kind in {"docs-only", "unknown"}:
        return "opencode"
    return "opencode"


def python_required_for(language: str | None, paths: list[str]) -> bool:
    if language == "python":
        return True
    names = {Path(path).name for path in paths}
    return any(marker in names for marker in ("pyproject.toml", "setup.py", "requirements.txt", "Pipfile"))


class GitHubRepoProfileProvider(RepoProfileProvider):
    """GitHub REST implementation of the provider-neutral profile contract."""

    provider_name = "github"
    base_url = "https://api.github.com"

    def __init__(self, token: str | None = None, owner: str | None = None, session: Any | None = None):
        if requests is None and session is None:
            raise RuntimeError("requests is required for GitHubRepoProfileProvider")
        self.owner = owner
        self.session = session or requests.Session()
        if hasattr(self.session, "headers"):
            self.session.headers.update({
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            })
            if token:
                self.session.headers["Authorization"] = f"token {token}"

    def get_profile(self, repo: str, branch: str | None = None) -> RepoProfile:
        owner, name = self._split_repo(repo)
        metadata = self._get_json(f"/repos/{owner}/{name}") or {}
        languages = self._get_json(f"/repos/{owner}/{name}/languages") or {}
        topics_payload = self._get_json(f"/repos/{owner}/{name}/topics") or {}
        topics = tuple(topics_payload.get("names", metadata.get("topics", ())) or ())
        default_branch = branch or metadata.get("default_branch")
        raw_paths = self._tree_paths(owner, name, default_branch)
        paths = list(filter_secret_paths(raw_paths))

        language = dominant_language(languages) or normalize_language(metadata.get("language")) or infer_marker_language(paths)
        percentages = language_percentages(languages)
        kind = infer_repo_kind(language, paths, topics)

        workflows = self._workflow_hints(owner, name, default_branch)
        remote_state = self._remote_state(owner, name)

        test_hints = collect_test_hints(paths)
        if workflows:
            test_hints = tuple(dict.fromkeys((*test_hints, *collect_test_hints_from_workflows(workflows, language))))

        extra = {
            "workflows": workflows,
            "remote_state": remote_state,
        }

        return RepoProfile(
            provider=self.provider_name,
            repo=f"{owner}/{name}",
            dominant_language=language,
            language_percentages=percentages,
            repo_kind=kind,
            framework_hints=collect_framework_hints(paths, topics),
            test_hints=test_hints,
            recommended_worker=recommended_worker_for(kind),
            python_required=python_required_for(language, paths),
            default_branch=default_branch,
            is_archived=bool(metadata.get("archived", False)),
            is_private=bool(metadata.get("private", False)),
            repo_size_kb=metadata.get("size"),
            description=metadata.get("description"),
            topics=topics,
            marker_files=tuple(paths),
            extra=extra,
            source="github_rest",
        )

    def _split_repo(self, repo: str) -> tuple[str, str]:
        if repo.startswith("https://github.com/"):
            repo = repo.removeprefix("https://github.com/").strip("/")
        if "/" in repo:
            owner, name = repo.split("/", 1)
            return owner, name
        if not self.owner:
            raise ValueError("owner is required when repo is not owner/name")
        return self.owner, repo

    def _get_json(self, path: str) -> Any:
        response = self.session.get(f"{self.base_url}{path}")
        if response.status_code == 404:
            return None
        if response.status_code >= 400:
            raise RuntimeError(f"GitHub API request failed for {path}: {response.status_code}")
        return response.json()

    def _tree_paths(self, owner: str, repo: str, branch: str | None) -> list[str]:
        if not branch:
            return []
        payload = self._get_json(f"/repos/{owner}/{repo}/git/trees/{branch}?recursive=1") or {}
        return [
            item["path"]
            for item in payload.get("tree", [])
            if item.get("type") == "blob" and "path" in item
        ]

    def _workflow_hints(self, owner: str, repo: str, branch: str | None) -> list[dict[str, Any]]:
        payload = self._get_json(f"/repos/{owner}/{repo}/contents/.github/workflows") or []
        workflows: list[dict[str, Any]] = []
        for entry in payload:
            if not isinstance(entry, Mapping):
                continue
            if str(entry.get("type", "")).lower() != "file":
                continue
            name = str(entry.get("name", ""))
            if is_secret_path(name):
                continue
            workflows.append({
                "name": name,
                "path": str(entry.get("path", "")),
                "download_url": str(entry.get("download_url", "")),
                "branch": branch,
            })
        return workflows

    def _remote_state(self, owner: str, repo: str) -> dict[str, Any]:
        pulls = self._get_json(f"/repos/{owner}/{repo}/pulls?state=open&per_page=50") or []
        issues = self._get_json(f"/repos/{owner}/{repo}/issues?state=open&per_page=50") or []

        pull_numbers: list[int] = []
        solver_branches: list[str] = []
        for pull in pulls:
            if not isinstance(pull, Mapping):
                continue
            number = pull.get("number")
            if isinstance(number, int):
                pull_numbers.append(number)
            head = pull.get("head") or {}
            ref = str(head.get("ref", ""))
            if ref.startswith("ai/fix-issue-"):
                solver_branches.append(ref)

        issue_numbers: list[int] = []
        for issue in issues:
            if not isinstance(issue, Mapping):
                continue
            if "pull_request" in issue:
                continue
            number = issue.get("number")
            if isinstance(number, int):
                issue_numbers.append(number)

        return {
            "open_pull_requests": len(pull_numbers),
            "open_pull_request_numbers": pull_numbers,
            "open_issues": len(issue_numbers),
            "open_issue_numbers": issue_numbers,
            "existing_solver_branches": sorted(set(solver_branches)),
        }


class LocalRepoProfileProvider(RepoProfileProvider):
    """Local/offline provider using checked-out files and lightweight marker heuristics."""

    provider_name = "local"

    def __init__(self, root: Path | str):
        self.root = Path(root)

    def get_profile(self, repo: str | None = None, branch: str | None = None) -> RepoProfile:
        paths = list(self._paths())
        language = infer_marker_language(paths)
        kind = infer_repo_kind(language, paths)
        repo_name = repo or self.root.name
        return RepoProfile(
            provider=self.provider_name,
            repo=repo_name,
            dominant_language=language,
            repo_kind=kind,
            framework_hints=collect_framework_hints(paths),
            test_hints=collect_test_hints(paths),
            recommended_worker=recommended_worker_for(kind),
            python_required=python_required_for(language, paths),
            marker_files=tuple(paths),
            source="local_marker_heuristics",
        )

    def _paths(self) -> list[str]:
        if not self.root.exists():
            return []
        ignored_dirs = {".git", ".venv", "__pycache__", "node_modules", "reports"}
        raw_paths: list[str] = []
        for path in self.root.rglob("*"):
            if any(part in ignored_dirs for part in path.parts):
                continue
            if path.is_file():
                relative = path.relative_to(self.root).as_posix()
                if is_secret_path(relative):
                    continue
                raw_paths.append(relative)
        return sorted(raw_paths)


def provider_targets() -> dict[str, str]:
    """Return known provider targets for future implementations."""
    return dict(PROVIDER_TARGETS)
