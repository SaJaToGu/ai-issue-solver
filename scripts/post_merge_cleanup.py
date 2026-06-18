#!/usr/bin/env python3
"""
post_merge_cleanup.py — Aufräumen nach gemergten AI Pull Requests

Fasst gemergte AI-PRs zusammen, schließt sicher referenzierte Issues, löscht
gemergte AI-Branches und meldet alles, was manuell geprüft werden sollte.

Verwendung:
    python scripts/post_merge_cleanup.py
    python scripts/post_merge_cleanup.py --repo ai-issue-solver
    python scripts/post_merge_cleanup.py --repo ai-issue-solver --apply
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import re
import subprocess
import sys
from pathlib import Path
from typing import Callable
from urllib.parse import quote

try:
    import requests
except ModuleNotFoundError:
    requests = None

sys.path.insert(0, str(Path(__file__).parent))
from utils import (  # noqa: E402
    handle_github_request_error,
    load_env,
    print_banner,
    print_err,
    print_ok,
    print_step,
    print_warn,
    raise_for_github_response,
    require_github_config,
)
from cleanup_backlog import (  # noqa: E402
    find_completed_issues as find_completed_backlog_issues,
    parse_backlog as parse_cleanup_backlog,
    remove_sections_from_backlog,
)


ISSUE_KEYWORD_RE = re.compile(
    r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s+#(\d+)\b",
    re.IGNORECASE,
)
LOOSE_ISSUE_RE = re.compile(r"(?<![\w/])#(\d+)\b")
BRANCH_ISSUE_RE = re.compile(r"(?:^|/)fix-issue-(\d+)(?:\D|$)", re.IGNORECASE)
MANUAL_LABELS = {"needs-review", "blocked", "wontfix", "invalid", "duplicate"}


@dataclass(frozen=True)
class ReferencedIssue:
    number: int
    source: str


@dataclass
class CleanupItem:
    repo: str
    pr_number: int
    pr_title: str
    pr_url: str
    branch: str
    merged_at: str | None
    referenced_issues: list[ReferencedIssue] = field(default_factory=list)
    closed_issues: list[int] = field(default_factory=list)
    branch_deleted: bool = False
    review_notes: list[str] = field(default_factory=list)


@dataclass
class CleanupResult:
    items: list[CleanupItem]
    stale_deleted_branches: list[str]
    stale_branch_notes: list[str]

    @property
    def closed_issue_count(self) -> int:
        return sum(len(item.closed_issues) for item in self.items)

    @property
    def deleted_branch_count(self) -> int:
        return sum(1 for item in self.items if item.branch_deleted) + len(self.stale_deleted_branches)

    @property
    def review_count(self) -> int:
        return sum(len(item.review_notes) for item in self.items) + len(self.stale_branch_notes)


@dataclass
class BacklogCleanupResult:
    backlog_path: Path
    completed_titles: list[str] = field(default_factory=list)
    removed_count: int = 0
    skipped_reason: str = ""


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

    def request(self, method: str, path: str, **kwargs):
        try:
            resp = self.session.request(method, f"{self.BASE}{path}", **kwargs)
        except requests.RequestException as exc:
            handle_github_request_error(exc, f"{method} {path}")
        return resp

    def get_page(self, path: str, **params) -> dict | list | None:
        resp = self.request("GET", path, params=params)
        if resp.status_code == 404:
            return None
        raise_for_github_response(resp, f"GET {path}")
        return resp.json()

    def get_all_pages(self, path: str, stop_after=None, **params) -> list:
        results = []
        params["per_page"] = min(int(params.get("per_page", 100)), 100)
        page = 1
        while True:
            params["page"] = page
            data = self.get_page(path, **params)
            if data is None:
                return []
            items = data.get("workflow_runs", []) if isinstance(data, dict) else data
            if not items:
                break
            results.extend(items)
            if stop_after and any(stop_after(item) for item in items):
                break
            if len(items) < params["per_page"]:
                break
            page += 1
        return results

    def get_repos(self) -> list[dict]:
        repos = self.get_all_pages(
            f"/users/{self.owner}/repos",
            type="owner",
            sort="updated",
            direction="desc",
        )
        return [repo for repo in repos if not repo.get("archived")]

    def get_repo(self, repo: str) -> dict | None:
        return self.get_page(f"/repos/{self.owner}/{repo}")

    def get_merged_pulls(self, repo: str, since: datetime) -> list[dict]:
        def is_older_than_window(pull: dict) -> bool:
            updated_at = parse_github_datetime(pull.get("updated_at"))
            return bool(updated_at and updated_at < since)

        pulls = self.get_all_pages(
            f"/repos/{self.owner}/{repo}/pulls",
            stop_after=is_older_than_window,
            state="closed",
            sort="updated",
            direction="desc",
        )
        return [
            pull for pull in pulls
            if pull.get("merged_at")
            and (parse_github_datetime(pull.get("merged_at")) or datetime.min.replace(tzinfo=timezone.utc)) >= since
        ]

    def get_issue(self, repo: str, number: int) -> dict | None:
        item = self.get_page(f"/repos/{self.owner}/{repo}/issues/{number}")
        if item and "pull_request" in item:
            return None
        return item

    def get_issues_by_title(self, repo: str, titles: list[str]) -> dict[str, dict]:
        wanted = set(titles)
        found: dict[str, dict] = {}
        for issue in self.get_all_pages(
            f"/repos/{self.owner}/{repo}/issues",
            state="all",
        ):
            if "pull_request" in issue:
                continue
            title = issue.get("title") or ""
            if title in wanted:
                found[title] = issue
        return found

    def get_open_prs_for_branch(self, repo: str, branch: str) -> list[dict]:
        return self.get_all_pages(
            f"/repos/{self.owner}/{repo}/pulls",
            state="open",
            head=f"{self.owner}:{branch}",
        )

    def get_pulls_for_branch(self, repo: str, branch: str) -> list[dict]:
        return self.get_all_pages(
            f"/repos/{self.owner}/{repo}/pulls",
            state="all",
            head=f"{self.owner}:{branch}",
        )

    def get_branches(self, repo: str) -> list[dict]:
        return self.get_all_pages(f"/repos/{self.owner}/{repo}/branches")

    def branch_exists(self, repo: str, branch: str) -> bool:
        encoded = quote(branch, safe="")
        resp = self.request("GET", f"/repos/{self.owner}/{repo}/branches/{encoded}")
        if resp.status_code == 404:
            return False
        raise_for_github_response(resp, f"Branch prüfen: {repo}/{branch}")
        return True

    def get_commit(self, repo: str, sha: str) -> dict | None:
        return self.get_page(f"/repos/{self.owner}/{repo}/commits/{sha}")

    def close_issue(self, repo: str, number: int, comment: str) -> None:
        comment_resp = self.request(
            "POST",
            f"/repos/{self.owner}/{repo}/issues/{number}/comments",
            json={"body": comment},
        )
        raise_for_github_response(comment_resp, f"Issue kommentieren: {repo}#{number}")
        close_resp = self.request(
            "PATCH",
            f"/repos/{self.owner}/{repo}/issues/{number}",
            json={"state": "closed"},
        )
        raise_for_github_response(close_resp, f"Issue schließen: {repo}#{number}")

    def delete_branch(self, repo: str, branch: str) -> None:
        encoded = quote(branch, safe="/")
        resp = self.request("DELETE", f"/repos/{self.owner}/{repo}/git/refs/heads/{encoded}")
        if resp.status_code == 404:
            return
        raise_for_github_response(resp, f"Branch löschen: {repo}/{branch}")


def parse_github_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def is_ai_pull_request(pull: dict, branch_prefix: str) -> bool:
    head = pull.get("head") or {}
    labels = [label.get("name", "") for label in pull.get("labels", [])]
    return (
        (head.get("ref") or "").startswith(branch_prefix)
        or any(label == "ai-generated" for label in labels)
    )


def referenced_issues_from_pr(pull: dict) -> list[ReferencedIssue]:
    text = "\n".join([
        pull.get("title") or "",
        pull.get("body") or "",
        pull.get("head", {}).get("ref") or "",
    ])
    found: dict[int, str] = {}

    for match in ISSUE_KEYWORD_RE.finditer(text):
        found[int(match.group(1))] = "closing-keyword"

    branch = pull.get("head", {}).get("ref") or ""
    branch_match = BRANCH_ISSUE_RE.search(branch)
    if branch_match:
        found.setdefault(int(branch_match.group(1)), "branch-name")

    for match in LOOSE_ISSUE_RE.finditer(text):
        found.setdefault(int(match.group(1)), "reference")

    return [ReferencedIssue(number, source) for number, source in sorted(found.items())]


def issue_has_manual_label(issue: dict) -> bool:
    labels = issue.get("labels") or []
    names = {label.get("name", "").lower() for label in labels}
    return bool(names & MANUAL_LABELS)


def can_close_issue(issue: dict | None, refs: list[ReferencedIssue]) -> tuple[bool, str]:
    if issue is None:
        return False, "referenziertes Issue nicht gefunden oder ist ein Pull Request"
    if issue.get("state") == "closed":
        return False, f"Issue #{issue.get('number')} ist bereits geschlossen"
    if issue_has_manual_label(issue):
        return False, f"Issue #{issue.get('number')} hat ein manuelles Review-Label"
    if not any(ref.source in {"closing-keyword", "branch-name"} for ref in refs):
        return False, f"Issue #{issue.get('number')} ist nur lose referenziert"
    return True, "ok"


def branch_commit_date(branch: dict, commit: dict | None = None) -> datetime | None:
    embedded = ((branch.get("commit") or {}).get("commit") or {}).get("committer") or {}
    timestamp = parse_github_datetime(embedded.get("date"))
    if timestamp:
        return timestamp
    if commit:
        detail = ((commit.get("commit") or {}).get("committer") or {}).get("date")
        return parse_github_datetime(detail)
    return None


def cleanup_repo(
    client: GitHubClient,
    repo: str,
    since: datetime,
    stale_before: datetime,
    branch_prefix: str,
    dry_run: bool,
) -> CleanupResult:
    pulls = [pull for pull in client.get_merged_pulls(repo, since) if is_ai_pull_request(pull, branch_prefix)]
    items = []
    deleted_branches = set()

    for pull in pulls:
        head = pull.get("head") or {}
        branch = head.get("ref") or ""
        item = CleanupItem(
            repo=repo,
            pr_number=int(pull.get("number") or 0),
            pr_title=pull.get("title") or "",
            pr_url=pull.get("html_url") or "",
            branch=branch,
            merged_at=pull.get("merged_at"),
            referenced_issues=referenced_issues_from_pr(pull),
        )

        if not item.referenced_issues:
            item.review_notes.append("keine Issue-Referenz im PR gefunden")

        for ref in item.referenced_issues:
            issue = client.get_issue(repo, ref.number)
            can_close, reason = can_close_issue(issue, [ref])
            if not can_close:
                item.review_notes.append(reason)
                continue
            if not dry_run:
                client.close_issue(repo, ref.number, close_comment(pull))
            item.closed_issues.append(ref.number)

        if branch:
            if head.get("repo", {}).get("owner", {}).get("login") != client.owner:
                item.review_notes.append(f"Branch {branch} liegt nicht im Owner-Repo")
            elif not branch.startswith(branch_prefix):
                item.review_notes.append(f"Branch {branch} passt nicht zum AI-Präfix {branch_prefix}")
            elif client.get_open_prs_for_branch(repo, branch):
                item.review_notes.append(f"Branch {branch} hat noch einen offenen PR")
            elif client.branch_exists(repo, branch):
                if not dry_run:
                    client.delete_branch(repo, branch)
                item.branch_deleted = True
                deleted_branches.add(branch)
        else:
            item.review_notes.append("PR hat keinen Head-Branch")

        items.append(item)

    stale_deleted_branches, stale_branch_notes = cleanup_stale_branches(
        client,
        repo,
        branch_prefix,
        stale_before,
        deleted_branches,
        dry_run,
    )
    return CleanupResult(
        items=items,
        stale_deleted_branches=stale_deleted_branches,
        stale_branch_notes=stale_branch_notes,
    )


def cleanup_stale_branches(
    client: GitHubClient,
    repo: str,
    branch_prefix: str,
    stale_before: datetime,
    ignored_branches: set[str],
    dry_run: bool,
) -> tuple[list[str], list[str]]:
    deleted = []
    notes = []
    for branch in client.get_branches(repo):
        name = branch.get("name") or ""
        if not name.startswith(branch_prefix) or name in ignored_branches:
            continue
        open_prs = client.get_open_prs_for_branch(repo, name)
        if open_prs:
            continue
        sha = (branch.get("commit") or {}).get("sha")
        commit = client.get_commit(repo, sha) if sha and not branch_commit_date(branch) else None
        commit_date = branch_commit_date(branch, commit)
        if not commit_date or commit_date >= stale_before:
            continue
        pull_states = client.get_pulls_for_branch(repo, name)
        if any(pull.get("merged_at") for pull in pull_states):
            if not dry_run:
                client.delete_branch(repo, name)
            deleted.append(name)
            continue
        if pull_states:
            notes.append(f"{repo}: Branch {name} ist stale, aber der zugehörige PR wurde nicht gemergt")
        else:
            notes.append(f"{repo}: Branch {name} ist stale und hat keinen PR")
    return deleted, notes


def cleanup_backlog_entries(
    client: GitHubClient,
    repo: str,
    backlog_path: Path,
    dry_run: bool,
) -> BacklogCleanupResult:
    if not backlog_path.exists():
        return BacklogCleanupResult(
            backlog_path=backlog_path,
            skipped_reason=f"Backlog-Datei nicht gefunden: {backlog_path}",
        )

    issues = parse_cleanup_backlog(backlog_path)
    if not issues:
        return BacklogCleanupResult(
            backlog_path=backlog_path,
            skipped_reason="Keine Backlog-Einträge gefunden",
        )

    github_issues = client.get_issues_by_title(repo, [issue["title"] for issue in issues])
    completed = find_completed_backlog_issues(issues, github_issues)
    result = BacklogCleanupResult(
        backlog_path=backlog_path,
        completed_titles=[issue["title"] for issue in completed],
    )
    if not completed:
        return result

    if dry_run:
        return result

    new_content, removed_count = remove_sections_from_backlog(backlog_path, completed)
    backlog_path.write_text(new_content, encoding="utf-8")
    result.removed_count = removed_count
    return result


def close_comment(pull: dict) -> str:
    return (
        "Automatisch geschlossen durch post_merge_cleanup.py, weil der "
        f"referenzierte AI-PR #{pull.get('number')} gemergt wurde: {pull.get('html_url')}"
    )


def print_cleanup_result(result: CleanupResult, dry_run: bool) -> None:
    if not result.items and not result.stale_deleted_branches and not result.stale_branch_notes:
        print("   Keine gemergten AI-PRs oder stale AI-Branches gefunden.")
        return

    action = "Würde" if dry_run else "Hat"
    for item in result.items:
        print(f"\n   PR #{item.pr_number}: {item.pr_title}")
        print(f"      Branch: {item.branch or '?'}")
        if item.closed_issues:
            print(f"      {action} Issues schließen: {', '.join(f'#{n}' for n in item.closed_issues)}")
        elif item.referenced_issues:
            refs = ", ".join(f"#{ref.number} ({ref.source})" for ref in item.referenced_issues)
            print(f"      Referenzierte Issues: {refs}")
        if item.branch_deleted:
            print(f"      {action} Branch löschen: {item.branch}")
        for note in item.review_notes:
            print_warn(note)

    if result.stale_branch_notes:
        print("\n   Manuelle Branch-Prüfung:")
        for note in result.stale_branch_notes:
            print_warn(note)

    if result.stale_deleted_branches:
        action = "Würde" if dry_run else "Hat"
        print("\n   Stale gemergte AI-Branches:")
        for branch in result.stale_deleted_branches:
            print(f"      {action} Branch löschen: {branch}")


def print_backlog_cleanup_result(result: BacklogCleanupResult, dry_run: bool) -> None:
    if result.skipped_reason:
        print_warn(result.skipped_reason)
        return
    if not result.completed_titles:
        print("   Keine abgeschlossenen Backlog-Einträge gefunden.")
        return

    action = "Würde entfernen" if dry_run else "Entfernt"
    print(f"   {action}: {len(result.completed_titles)} Eintrag/Einträge aus {result.backlog_path}")
    for title in result.completed_titles:
        print(f"      - {title}")


def collect_repos(client: GitHubClient, repo: str | None) -> list[str]:
    if repo:
        if client.get_repo(repo) is None:
            print_err(f"Repository nicht gefunden: {client.owner}/{repo}")
            raise SystemExit(1)
        return [repo]
    return [item["name"] for item in client.get_repos()]


# ── Lokale Branch-Bereinigung ──────────────────────────────
#
# Sicherheitsregel (siehe Issue #331):
#   - Protected Branches (main, develop, current) werden NIE gelöscht.
#   - Gelöscht werden darf NUR, was "merged into base" ist UND nicht protected.
#   - "gone-upstream" allein ist KEIN Löschgrund — es ist nur ein Hinweis,
#     dass der Remote-Ast bereits weg ist. Ein gone-upstream Branch, der
#     nicht gemergt ist, wird in der Manual-Review-Liste aufgeführt
#     (besonders sichtbar mit --show-unmerged), aber NIE automatisch
#     gelöscht.
#
# Diese Funktion erweitert post_merge_cleanup.py um eine `--local-branches`
# Option. Die Remote-Branch-Logik oben bleibt byte-identisch.


# Branches, die als "deleted" an git übergeben werden — `git branch -d`
# weigert sich, einen Branch zu löschen, der nicht gemergt ist. Wir
# filtern vorher, also ist -d sicher.
GIT_DELETE_FLAG = "-d"


def run_git(
    args: list[str],
    cwd: str | Path | None = None,
) -> subprocess.CompletedProcess:
    """Run a git command. Returns CompletedProcess; never raises on non-zero exit.

    Default cwd is the project root (parent of scripts/). Injected in
    tests via the `git_runner` parameter on cleanup_local_branches.
    """
    return subprocess.run(
        ["git", *args],
        cwd=str(cwd) if cwd is not None else str(Path(__file__).resolve().parent.parent),
        capture_output=True,
        text=True,
        check=False,
    )


@dataclass(frozen=True)
class LocalBranchEntry:
    """Single local branch and its classification."""
    name: str
    category: str  # "protected" | "merged" | "unmerged-gone" | "unmerged-alive"
    reason: str


@dataclass
class LocalBranchReport:
    """Result of cleanup_local_branches."""
    fetch_ok: bool
    fetch_error: str
    current_branch: str
    base: str
    protected: list[LocalBranchEntry] = field(default_factory=list)
    to_delete: list[LocalBranchEntry] = field(default_factory=list)
    manual_review: list[LocalBranchEntry] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def would_delete(self) -> list[LocalBranchEntry]:
        return list(self.to_delete)

    @property
    def has_deletable(self) -> bool:
        return bool(self.to_delete)


def _parse_branch_listing(text: str) -> list[str]:
    """Parse the output of `git for-each-ref --format=%(refname:short) refs/heads/`.

    Each non-empty line is a branch name. We strip whitespace defensively.
    """
    out: list[str] = []
    for line in text.splitlines():
        name = line.strip()
        if name:
            out.append(name)
    return out


def _parse_merged_listing(text: str) -> set[str]:
    """Parse the output of `git branch --list --merged <base>`.

    Each line may be prefixed with `* ` (current) or `  ` (other) and
    may end with `+` for worktree-pinned branches. We extract just the
    branch name.
    """
    out: set[str] = set()
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        # Strip the leading markers `* `, `  `, `+ `
        # The format is e.g. "* main", "  feature/foo", "+  worktree"
        while line and line[0] in {"*", "+", " "}:
            line = line[1:]
        if line:
            out.add(line.strip())
    return out


def cleanup_local_branches(
    base: str = "develop",
    show_unmerged: bool = False,
    dry_run: bool = True,
    protected_names: tuple[str, ...] = ("main", "develop"),
    git_runner: Callable[..., subprocess.CompletedProcess] = run_git,
) -> LocalBranchReport:
    """
    Classify local branches and return a report.

    Safety rule (see Issue #331): only branches that are merged into
    `base` AND not protected become deletion candidates. Branches
    whose upstream is gone are listed as manual-review items if
    they are unmerged; merged-and-gone branches ARE deletable (their
    upstream was deleted because the PR was merged, the commits live
    on `base`).

    Never deletes anything; deletion is the caller's job, gated on
    `dry_run` and a separate --apply flag at the CLI layer.
    """
    # 1. Prune stale remote-tracking refs so upstream-gone detection is fresh.
    fetch_proc = git_runner(["fetch", "--prune", "origin"])
    fetch_ok = fetch_proc.returncode == 0
    fetch_error = "" if fetch_ok else (fetch_proc.stderr.strip() or "git fetch fehlgeschlagen")

    # 2. Find the current branch — never delete it.
    current_proc = git_runner(["rev-parse", "--abbrev-ref", "HEAD"])
    current = ""
    if current_proc.returncode == 0:
        current = current_proc.stdout.strip()

    # 3. Enumerate local branches.
    list_proc = git_runner(["for-each-ref", "--format=%(refname:short)", "refs/heads/"])
    if list_proc.returncode != 0:
        return LocalBranchReport(
            fetch_ok=fetch_ok,
            fetch_error=fetch_error,
            current_branch=current,
            base=base,
            errors=[
                "kann lokale Branches nicht auflisten: "
                + (list_proc.stderr.strip() or "git for-each-ref fehlgeschlagen")
            ],
        )
    local_branches = _parse_branch_listing(list_proc.stdout)

    # 4. Determine which branches are merged into `base`.
    merged_proc = git_runner(["branch", "--list", "--merged", base])
    merged_into_base: set[str] = set()
    if merged_proc.returncode == 0:
        merged_into_base = _parse_merged_listing(merged_proc.stdout)
    # Also consider base itself as "merged into itself" (it always is).
    if base:
        merged_into_base.add(base)

    # 5. Classify each local branch.
    protected_set: set[str] = set(protected_names) | ({current} if current else set())

    protected_entries: list[LocalBranchEntry] = []
    to_delete: list[LocalBranchEntry] = []
    manual_review: list[LocalBranchEntry] = []

    for branch in local_branches:
        if branch in protected_set:
            protected_entries.append(LocalBranchEntry(
                name=branch,
                category="protected",
                reason=_protected_reason(branch, protected_names, current),
            ))
            continue

        upstream_proc = git_runner(
            ["rev-parse", "--verify", f"refs/remotes/origin/{branch}"]
        )
        upstream_exists = upstream_proc.returncode == 0

        is_merged = branch in merged_into_base

        if is_merged:
            upstream_note = "" if upstream_exists else " (Upstream bereits weg, unbedenklich)"
            to_delete.append(LocalBranchEntry(
                name=branch,
                category="merged",
                reason=f"in {base} gemergt{upstream_note}",
            ))
            continue

        # Unmerged. Always a manual-review item, never auto-deleted.
        if not upstream_exists:
            reason = f"nicht in {base} gemergt; Upstream bereits weg (manuell prüfen — möglicherweise unbeabsichtigte Lokalarbeit)"
            category = "unmerged-gone"
        else:
            reason = f"nicht in {base} gemergt; Upstream existiert (manuell prüfen — könnte offener PR oder unbeabsichtigte Lokalarbeit sein)"
            category = "unmerged-alive"
        manual_review.append(LocalBranchEntry(
            name=branch,
            category=category,
            reason=reason,
        ))

    # Without --show-unmerged, hide unmerged manual-review entries from
    # the "would show" output. We still keep them in the report so a
    # caller that wants the full picture can access them.
    if not show_unmerged:
        manual_review = []

    return LocalBranchReport(
        fetch_ok=fetch_ok,
        fetch_error=fetch_error,
        current_branch=current,
        base=base,
        protected=protected_entries,
        to_delete=to_delete,
        manual_review=manual_review,
    )


def _protected_reason(branch: str, protected_names: tuple[str, ...], current: str) -> str:
    """Build a human-readable reason string for a protected branch."""
    parts: list[str] = []
    if branch in protected_names:
        parts.append("geschützt per Default-Liste")
    if current and branch == current:
        parts.append("aktuell ausgecheckter Branch")
    return "; ".join(parts) if parts else "geschützt"


def print_local_branch_report(report: LocalBranchReport, dry_run: bool) -> None:
    """Print a LocalBranchReport in the existing script's German style."""
    if not report.fetch_ok:
        print_warn(f"`git fetch --prune origin` fehlgeschlagen: {report.fetch_error}")

    if report.protected:
        print("\n   Geschützte Branches (nie löschen):")
        for entry in report.protected:
            print(f"      - {entry.name}  ({entry.reason})")

    if report.to_delete:
        action = "Würde löschen" if dry_run else "Löscht"
        print(f"\n   {action} (in {report.base} gemergt, nicht geschützt):")
        for entry in report.to_delete:
            print(f"      - {entry.name}  ({entry.reason})")

    if report.manual_review:
        print("\n   Manuelle Prüfung (nicht gemergt — wird NIE automatisch gelöscht):")
        for entry in report.manual_review:
            print(f"      - {entry.name}  [{entry.category}]  ({entry.reason})")

    if not report.to_delete and not report.manual_review and not report.protected:
        print("   Keine lokalen Branches gefunden.")


def apply_local_branch_cleanup(
    report: LocalBranchReport,
    dry_run: bool,
    git_runner: Callable[..., subprocess.CompletedProcess] = run_git,
) -> list[str]:
    """Delete the branches in report.to_delete. Returns a list of action descriptions.

    Called only when --apply is set. Never deletes anything protected or
    unmerged (those are not in report.to_delete by construction).
    """
    if dry_run:
        return []

    actions: list[str] = []
    for entry in report.to_delete:
        proc = git_runner(["branch", GIT_DELETE_FLAG, entry.name])
        if proc.returncode == 0:
            actions.append(f"gelöscht: {entry.name}")
        else:
            err = proc.stderr.strip() or f"git branch {GIT_DELETE_FLAG} {entry.name} fehlgeschlagen"
            actions.append(f"FEHLGESCHLAGEN beim Löschen von {entry.name}: {err}")
    return actions


def main() -> int:
    print_banner("POST-MERGE CLEANUP")

    parser = argparse.ArgumentParser(
        description="Schließt sichere AI-Issues und räumt gemergte AI-Branches auf"
    )
    parser.add_argument("--repo", help="Nur dieses Repository bereinigen")
    parser.add_argument("--merged-days", type=int, default=30, help="Zeitraum für gemergte PRs")
    parser.add_argument("--stale-days", type=int, default=30, help="Alter für stale AI-Branches")
    parser.add_argument("--branch-prefix", default="ai/", help="Präfix für AI-Branches")
    parser.add_argument("--apply", action="store_true", help="Änderungen wirklich auf GitHub ausführen")
    parser.add_argument("--dry-run", action="store_true", help="Nur anzeigen; Standard ohne --apply")
    parser.add_argument(
        "--cleanup-backlog",
        action="store_true",
        help="Entfernt abgeschlossene Einträge aus der Backlog-Datei nach dem Issue-Cleanup",
    )
    parser.add_argument(
        "--backlog",
        default="docs/BACKLOG/open.md",
        help="Backlog-Datei für --cleanup-backlog",
    )
    parser.add_argument(
        "--local-branches",
        action="store_true",
        help=(
            "Auch lokale Branches prüfen: `git fetch --prune origin` ausführen "
            "und in --base gemergte, nicht geschützte Branches zum Löschen "
            "vorschlagen. Niemals nicht-gemergte Branches löschen."
        ),
    )
    parser.add_argument(
        "--base",
        default="develop",
        help="Base-Branch für den Merge-Check bei --local-branches (Standard: develop)",
    )
    parser.add_argument(
        "--show-unmerged",
        action="store_true",
        help=(
            "Mit --local-branches: auch nicht-gemergte Branches als "
            "Manual-Review-Hinweis anzeigen. Ohne dieses Flag werden "
            "nur die zum Löschen vorgeschlagenen (gemergten) Branches "
            "ausgegeben."
        ),
    )
    args = parser.parse_args()

    if args.merged_days < 1:
        parser.error("--merged-days muss mindestens 1 sein")
    if args.stale_days < 1:
        parser.error("--stale-days muss mindestens 1 sein")
    if not args.branch_prefix:
        parser.error("--branch-prefix darf nicht leer sein")
    if args.cleanup_backlog and not args.repo:
        parser.error("--cleanup-backlog braucht --repo, damit Backlog-Titel einem Repository zugeordnet werden")

    if requests is None:
        print_err("Python-Abhängigkeit fehlt: requests")
        print("   → Installieren mit: pip install -r requirements.txt")
        return 1

    dry_run = not args.apply or args.dry_run
    config = load_env()
    token, user = require_github_config(config)
    client = GitHubClient(token, user)
    now = datetime.now(timezone.utc)
    since = now - timedelta(days=args.merged_days)
    stale_before = now - timedelta(days=args.stale_days)
    repos = collect_repos(client, args.repo)

    print_step(1, f"Prüfe {len(repos)} Repo(s) für @{user}")
    print(f"   Modus: {'Dry-Run' if dry_run else 'Apply'}")
    print(f"   Gemergte AI-PRs seit: {since.strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"   Stale AI-Branches vor: {stale_before.strftime('%Y-%m-%d %H:%M UTC')}")

    totals = CleanupResult(items=[], stale_deleted_branches=[], stale_branch_notes=[])
    for repo in repos:
        print(f"\n📁 {repo}")
        result = cleanup_repo(client, repo, since, stale_before, args.branch_prefix, dry_run)
        print_cleanup_result(result, dry_run)
        totals.items.extend(result.items)
        totals.stale_deleted_branches.extend(result.stale_deleted_branches)
        totals.stale_branch_notes.extend(result.stale_branch_notes)

    backlog_result = None
    if args.cleanup_backlog:
        print_step(2, "Bereinige abgeschlossene Backlog-Einträge")
        backlog_result = cleanup_backlog_entries(
            client,
            args.repo,
            Path(args.backlog),
            dry_run,
        )
        print_backlog_cleanup_result(backlog_result, dry_run)

    local_actions: list[str] = []
    if args.local_branches:
        print_step(3 if args.cleanup_backlog else 2, "Prüfe lokale Branches")
        local_report = cleanup_local_branches(
            base=args.base,
            show_unmerged=args.show_unmerged,
            dry_run=dry_run,
        )
        print_local_branch_report(local_report, dry_run)
        local_actions = apply_local_branch_cleanup(local_report, dry_run)

    print("\n" + "─" * 50)
    print(
        "  Cleanup: "
        f"{len(totals.items)} gemergte AI-PRs | "
        f"{totals.closed_issue_count} Issues {'würden geschlossen' if dry_run else 'geschlossen'} | "
        f"{totals.deleted_branch_count} Branches {'würden gelöscht' if dry_run else 'gelöscht'} | "
        f"{totals.review_count} Review-Hinweise"
    )
    if backlog_result:
        changed = backlog_result.removed_count if not dry_run else len(backlog_result.completed_titles)
        print(f"  Backlog: {changed} Einträge {'würden entfernt' if dry_run else 'entfernt'}")
    if args.local_branches:
        deleted = sum(1 for a in local_actions if a.startswith("gelöscht:"))
        failed = sum(1 for a in local_actions if a.startswith("FEHLGESCHLAGEN"))
        verb = "würden gelöscht" if dry_run else "gelöscht"
        print(
            f"  Lokale Branches: {len(local_actions)} {verb if not failed else 'versucht'} | "
            f"{deleted} {verb} | {failed} fehlgeschlagen"
        )
        for action in local_actions:
            if action.startswith("FEHLGESCHLAGEN"):
                print_warn(action)
    print("─" * 50 + "\n")
    if dry_run:
        print_ok("Dry-Run abgeschlossen. Für echte Änderungen erneut mit --apply starten.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
