#!/usr/bin/env python3
"""Provider-neutral repository profile helpers.

This module intentionally keeps the first slice small: GitHub is the only
implemented remote provider, local/offline repositories are supported as a
fallback, and other forge providers are represented as provider targets so the
solver contract does not become GitHub-shaped.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

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
        }


class RepoProfileProvider(ABC):
    """Abstract provider contract for GitHub, GitLab, Forgejo/Gitea, Bitbucket, and local repos."""

    provider_name: str

    @abstractmethod
    def get_profile(self, repo: str, branch: str | None = None) -> RepoProfile:
        """Build a provider-neutral profile for a repository."""


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
        paths = self._tree_paths(owner, name, default_branch)

        language = dominant_language(languages) or normalize_language(metadata.get("language")) or infer_marker_language(paths)
        percentages = language_percentages(languages)
        kind = infer_repo_kind(language, paths, topics)

        return RepoProfile(
            provider=self.provider_name,
            repo=f"{owner}/{name}",
            dominant_language=language,
            language_percentages=percentages,
            repo_kind=kind,
            framework_hints=collect_framework_hints(paths, topics),
            test_hints=collect_test_hints(paths),
            recommended_worker=recommended_worker_for(kind),
            python_required=python_required_for(language, paths),
            default_branch=default_branch,
            is_archived=bool(metadata.get("archived", False)),
            is_private=bool(metadata.get("private", False)),
            repo_size_kb=metadata.get("size"),
            description=metadata.get("description"),
            topics=topics,
            marker_files=tuple(paths),
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


class LocalRepoProfileProvider(RepoProfileProvider):
    """Local/offline provider using checked-out files and lightweight marker heuristics."""

    provider_name = "local"

    def __init__(self, root: Path | str):
        self.root = Path(root)

    def get_profile(self, repo: str | None = None, branch: str | None = None) -> RepoProfile:
        paths = self._paths()
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
        )

    def _paths(self) -> list[str]:
        if not self.root.exists():
            return []
        ignored_dirs = {".git", ".venv", "__pycache__", "node_modules", "reports"}
        paths: list[str] = []
        for path in self.root.rglob("*"):
            if any(part in ignored_dirs for part in path.parts):
                continue
            if path.is_file():
                paths.append(path.relative_to(self.root).as_posix())
        return sorted(paths)


def provider_targets() -> dict[str, str]:
    """Return known provider targets for future implementations."""
    return dict(PROVIDER_TARGETS)
