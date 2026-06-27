#!/usr/bin/env python3
"""
build_graph.py — Build an issue/PR/commit relationship graph for the
ai-issue-solver repo.

Data sources:
- ``docs/BACKLOG/open.md`` — active backlog items, parsed for § number,
  title, and (when present) parent-issue reference
- GitHub REST API via ``gh api`` — for closed issues, merged PRs, and
  the edges between them. Issue↔PR links come from PR body / PR
  comments ("Closes #N", "Fixes #N", "Resolves #N", "Part of #N",
  "Parent: #N"); PR↔branch and PR↔commit from
  ``pulls.{head.ref,head.sha}``; LOC + file count from
  ``pulls.{additions,deletions,changed_files}``; the solver-produced
  flag from PR author + ``ai-generated`` label.
- Actions workflow logs via ``gh run view`` (for cost/model/runtime
  per merged PR) — currently a TODO marker, enriched downstream from
  ``reports/runs/<id>/``.
- ``reports/runs/<run-id>/{summary.txt,metadata.json}`` — solver
  cost/model data per run, joined to PR nodes by URL.

Outputs a graph as either JSON (default) or DOT (``--format dot``).
Node types: ``issue``, ``pr``, ``commit``.
Edge types: ``closes`` (issue→pr), ``merged_into`` (pr→commit),
``parent_of`` (issue→issue).

Cost / LOC / model annotations are attached as node attributes when
the source data has them. ``--color-by <dimension>`` annotates the
output with a ``color`` field per node, ready for a downstream
renderer (Graphviz, dashboard, app) to apply.

Usage:
    python scripts/build_graph.py                          # default JSON
    python scripts/build_graph.py --format dot             # Graphviz
    python scripts/build_graph.py --color-by cost          # color by cost
    python scripts/build_graph.py --color-by model         # color by model
    python scripts/build_graph.py --since 2026-06-01       # only PRs since date
    python scripts/build_graph.py --output /tmp/graph.json # custom path
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BACKLOG_OPEN = REPO_ROOT / "docs" / "BACKLOG" / "open.md"
DEFAULT_RUNS_DIR = REPO_ROOT / "reports" / "runs"


# --------------------------------------------------------------------------- #
# Data model                                                                  #
# --------------------------------------------------------------------------- #


@dataclass
class Node:
    """A graph node. ``id`` is unique within the graph."""

    id: str
    type: str  # "issue" | "pr" | "commit"
    title: str = ""
    attrs: dict[str, object] = field(default_factory=dict)


@dataclass
class Edge:
    from_id: str
    to_id: str
    type: str  # "closes" | "merged_into" | "parent_of"


# --------------------------------------------------------------------------- #
# GitHub API helpers                                                          #
# --------------------------------------------------------------------------- #


def _gh_api(endpoint: str, **params: str) -> list[dict[str, Any]] | dict[str, Any]:
    """Call ``gh api <endpoint>`` and return the parsed JSON.

    ``endpoint`` is the path part of the API call (e.g.
    ``/repos/{o}/{r}/issues``). Keyword arguments are appended
    to the URL as query string (``?key=value&...``). This keeps
    the call a GET — using ``gh api -f key=value`` would
    implicitly turn the request into a POST and trip GitHub's
    "title wasn't supplied" 422 for endpoints that don't accept
    a body.

    Returns the parsed JSON (list or dict). When ``gh`` is not
    installed, not authenticated, or the call fails, the function
    raises ``RuntimeError`` with the captured stderr.
    """
    url = endpoint
    if params:
        from urllib.parse import urlencode
        qs = urlencode(params)
        sep = "&" if "?" in url else "?"
        url = f"{url}{sep}{qs}"
    try:
        proc = subprocess.run(
            ["gh", "api", url],
            check=False,
            capture_output=True,
            text=True,
            timeout=60,
        )
    except FileNotFoundError as e:
        raise RuntimeError("`gh` CLI not found in PATH") from e
    except subprocess.TimeoutExpired as e:
        raise RuntimeError(f"`gh api {endpoint}` timed out after 60s") from e

    if proc.returncode != 0:
        raise RuntimeError(
            f"`gh api {endpoint}` failed (exit={proc.returncode}): {proc.stderr.strip()}"
        )
    text = proc.stdout.strip()
    if not text:
        return []
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        raise RuntimeError(
            f"`gh api {endpoint}` returned non-JSON: {text[:200]!r}"
        ) from e


def _detect_github_owner_repo() -> tuple[str, str] | None:
    """Detect the ``(owner, repo)`` pair from ``git remote get-url
    origin``. Returns ``None`` when the command fails or the URL
    can't be parsed (e.g. local-only checkout, or git not
    available).
    """
    try:
        proc = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0 or not proc.stdout.strip():
        return None
    url = proc.stdout.strip()
    # git@github.com:owner/repo(.git)  or  https://github.com/owner/repo(.git)
    m = re.search(r"[:/]([^/:]+)/([^/]+?)(?:\.git)?$", url)
    if not m:
        return None
    return m.group(1), m.group(2)


# --------------------------------------------------------------------------- #
# Open backlog parsing (still file-based — no GitHub equivalent needed)       #
# --------------------------------------------------------------------------- #


# `## 37. Free OpenCode models full integration and evaluation *(parked)*`
_OPEN_RE = re.compile(r"^##\s+(\d+)\.\s+(.+?)\s*$", re.MULTILINE)
# `Parent: #357` inside an open.md section
_PARENT_RE = re.compile(r"^\s*Parent:\s*#(\d+)\s*$", re.MULTILINE)


def parse_open_backlog(path: Path) -> list[Node]:
    """Parse ``docs/BACKLOG/open.md`` for active § items."""
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8")
    nodes: list[Node] = []
    for m in _OPEN_RE.finditer(text):
        number = int(m.group(1))
        title = m.group(2).strip()
        # Look for a `Parent: #N` reference within the section body
        body = text[m.end(): text.find(f"\n## ", m.end()) if text.find(f"\n## ", m.end()) != -1 else len(text)]
        parent_match = _PARENT_RE.search(body)
        parent = int(parent_match.group(1)) if parent_match else None
        node = Node(
            id=f"issue-{number}",
            type="issue",
            title=title,
            attrs={"state": "open", "parent": parent},
        )
        nodes.append(node)
    return nodes


# --------------------------------------------------------------------------- #
# GitHub-native graph data                                                    #
# --------------------------------------------------------------------------- #


# Match any of: "Closes #N", "Fixes #N", "Resolves #N", "Part of #N",
# "Refs #N", "Issue #N", "See #N", "Implements #N", "Parent: #N" —
# case-insensitive, works in PR body or PR comment. The ai-issue-solver
# solver pipeline writes "Refs #N" (not "Closes #N") in its PR bodies,
# so missing "Refs" alone would drop ~55% of closes-edges in this repo.
_ISSUE_REF_RE = re.compile(
    r"\b(?:Closes|Fixes|Resolves|Part of|Refs|Issue|See|Implements):?\s+#(\d+)\b"
    r"|^\s*Parent:\s*#(\d+)\s*$",
    re.IGNORECASE | re.MULTILINE,
)


def _extract_issue_refs(text: str | None) -> list[int]:
    """Pull all ``#N`` references out of a PR body or comment that
    close / fix / relate to an issue."""
    if not text:
        return []
    seen: set[int] = set()
    for m in _ISSUE_REF_RE.finditer(text):
        for grp in m.groups():
            if grp is not None:
                seen.add(int(grp))
    return sorted(seen)


def _is_solver_produced(pr: dict[str, Any]) -> bool:
    """Heuristic: a PR is solver-produced when its author is the
    AI Issue Solver bot account OR it carries the ``ai-generated``
    label. This matches how the runtime pipeline tags its output
    and is robust to author renames."""
    user = (pr.get("user") or {}).get("login", "") or ""
    if "ai-issue-solver" in user.lower() or user.lower() in ("ai-issue-solver[bot]",):
        return True
    labels = [lbl.get("name", "") for lbl in pr.get("labels", []) or []]
    return "ai-generated" in labels


def fetch_github_graph_data(
    owner: str,
    repo: str,
    since: str | None = None,
    per_page: int = 100,
) -> tuple[list[Node], list[Edge]]:
    """Fetch the closed Issue↔PR↔Commit subgraph from the GitHub
    API.

    Returns ``(nodes, edges)`` in the same shape as
    ``parse_done_backlog`` did — so the rest of the pipeline does
    not have to know which backend produced the data.

    ``since`` is an optional ``YYYY-MM-DD`` filter applied to the
    PR's ``merged_at`` (or ``closed_at`` if unmerged). ``per_page``
    caps each request to keep the response small; if a page is
    full the caller can re-call with pagination cursors, but for
    the single-repo use case 100 per page is enough.

    When ``gh api`` is not available (no auth, no CLI), the
    function returns ``([], [])`` so the rest of the pipeline
    degrades gracefully to "open issues only" rather than
    crashing.
    """
    nodes: list[Node] = []
    edges: list[Edge] = []
    seen_pr_nums: set[int] = set()

    # 1) Iterate all merged PRs (paginated by 100).
    try:
        page = 1
        while True:
            params: dict[str, str] = {
                "state": "closed",
                "per_page": str(per_page),
                "page": str(page),
                "sort": "updated",
                "direction": "desc",
            }
            if since:
                params["since"] = since  # merged_at / closed_at lower bound
            data = _gh_api(
                f"/repos/{owner}/{repo}/issues",
                **params,
            )
            if not isinstance(data, list) or not data:
                break
            for item in data:
                # /issues endpoint returns both issues and PRs;
                # skip the pure issues (no pull_request key).
                if "pull_request" not in item:
                    continue
                pr_num = int(item["number"])
                if pr_num in seen_pr_nums:
                    continue
                seen_pr_nums.add(pr_num)

                # Fetch the full PR object to get body + head.ref + LOC.
                pr_full = _gh_api(f"/repos/{owner}/{repo}/pulls/{pr_num}")
                if not isinstance(pr_full, dict):
                    continue
                head = pr_full.get("head") or {}
                head_ref = head.get("ref", "")
                head_sha = head.get("sha", "")
                merged_at = pr_full.get("merged_at")
                additions = pr_full.get("additions", 0) or 0
                deletions = pr_full.get("deletions", 0) or 0
                changed_files = pr_full.get("changed_files", 0) or 0

                # Issue refs from PR body and PR comments.
                refs: list[int] = _extract_issue_refs(pr_full.get("body"))
                try:
                    comments = _gh_api(
                        f"/repos/{owner}/{repo}/issues/{pr_num}/comments",
                        per_page=str(per_page),
                    )
                except RuntimeError:
                    comments = []
                if isinstance(comments, list):
                    for c in comments:
                        refs.extend(_extract_issue_refs(c.get("body")))

                attrs: dict[str, object] = {
                    "head_ref": head_ref,
                    "head_sha": head_sha,
                    "merged_at": merged_at,
                    "loc_add": int(additions),
                    "loc_del": int(deletions),
                    "files": int(changed_files),
                    "ai_generated": _is_solver_produced(pr_full),
                    "state": "merged" if merged_at else "closed",
                }
                pr_node = Node(
                    id=f"pr-{pr_num}",
                    type="pr",
                    title=f"PR #{pr_num}",
                    attrs=attrs,
                )
                nodes.append(pr_node)

                # Issue→PR closes edges.
                for issue_num in refs:
                    edges.append(Edge(
                        from_id=f"issue-{issue_num}",
                        to_id=f"pr-{pr_num}",
                        type="closes",
                    ))

                # PR→commit merged_into edge + commit node (only when
                # the PR was actually merged — an unmerged closed PR
                # has a head_sha but no merged_into edge).
                if head_sha and merged_at:
                    edges.append(Edge(
                        from_id=f"pr-{pr_num}",
                        to_id=f"commit-{head_sha}",
                        type="merged_into",
                    ))
                    nodes.append(Node(
                        id=f"commit-{head_sha}",
                        type="commit",
                        title=head_sha[:10],
                    ))

            if len(data) < per_page:
                break
            page += 1
    except RuntimeError as e:
        # gh not available or auth failed — degrade to empty list.
        sys.stderr.write(f"build_graph: GitHub API unavailable, {e}\n")
        return [], []

    return nodes, edges


# --------------------------------------------------------------------------- #
# Cost enrichment from run-reports                                            #
# --------------------------------------------------------------------------- #


def enrich_from_runs(runs_dir: Path, nodes: list[Node]) -> None:
    """Walk reports/runs/*/summary.txt + metadata.json and add
    cost/model to PR nodes when the PR's URL is recorded in a run
    summary.

    Mutates the supplied ``nodes`` in-place.
    """
    if not runs_dir.exists():
        return

    pr_to_node = {n.id: n for n in nodes if n.type == "pr"}

    for run_dir in sorted(runs_dir.iterdir()):
        if not run_dir.is_dir():
            continue
        summary = run_dir / "summary.txt"
        meta = run_dir / "metadata.json"
        if not summary.exists() or not meta.exists():
            continue

        # Parse pr_url from summary.txt (key: pr_url: <url>)
        pr_url = None
        try:
            for line in summary.read_text(encoding="utf-8").splitlines():
                if line.startswith("pr_url:"):
                    val = line.split(":", 1)[1].strip()
                    if val:
                        pr_url = val
                    break
        except OSError:
            continue

        if not pr_url:
            continue
        pr_num_match = re.search(r"/pull/(\d+)", pr_url)
        if not pr_num_match:
            continue
        pr_num = int(pr_num_match.group(1))
        pr_node = pr_to_node.get(f"pr-{pr_num}")
        if pr_node is None:
            continue

        # Parse cost + model from metadata.json
        try:
            m = json.loads(meta.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        scorecard = m.get("provider_scorecard") or {}
        cost = scorecard.get("estimated_cost")
        model = scorecard.get("actual_model") or m.get("model")
        if cost is not None and "cost" not in pr_node.attrs:
            pr_node.attrs["cost"] = float(cost)
        if model and "model" not in pr_node.attrs:
            pr_node.attrs["model"] = model


# --------------------------------------------------------------------------- #
# Color-by                                                                    #
# --------------------------------------------------------------------------- #


# Discrete color map for model names. Matches both the high-level
# provider (what the run-reports record) and the full provider/model
# slug (what the CLI accepts). The provider-level key is the fallback
# for any sub-slug we haven't enumerated.
_MODEL_COLORS: dict[str, str] = {
    # Provider-level (used by metadata.json `actual_model`)
    "opencode": "#22c55e",                          # green
    "codex": "#3b82f6",                            # blue
    "claude": "#8b5cf6",                            # purple
    "mistral": "#ec4899",                          # pink
    "openai": "#f97316",                            # orange
    "ollama": "#14b8a6",                            # teal
    "mistral-vibe": "#d946ef",                      # fuchsia
    "openrouter": "#eab308",                        # yellow
    "openrouter_direct": "#06b6d4",                # cyan
    # Sub-slugs (used by --model arg in run_overnight.py)
    "opencode/deepseek-v4-flash-free": "#22c55e",   # green (same as opencode)
    "opencode/minimax-m3-free": "#ef4444",          # red (dead)
    "opencode/mimo-v2.5-free": "#f59e0b",          # amber
    "opencode/minimax-m2.5": "#84cc16",             # lime
    "opencode/nemotron-3-super-free": "#06b6d4",   # cyan
}
_DEFAULT_MODEL_COLOR = "#94a3b8"  # slate


def _color_for_cost(cost: float, max_cost: float) -> str:
    """Cost: green (low) → red (high)."""
    if max_cost <= 0:
        return "#22c55e"
    pct = min(1.0, max(0.0, cost / max_cost))
    # interpolate green (34,197,94) to red (239,68,68)
    r = int(34 + (239 - 34) * pct)
    g = int(197 - (197 - 68) * pct)
    b = int(94 - (94 - 68) * pct)
    return f"#{r:02x}{g:02x}{b:02x}"


def _color_for_loc(loc: int, max_loc: int) -> str:
    """LOC: green (small) → red (large)."""
    if max_loc <= 0:
        return "#22c55e"
    pct = min(1.0, max(0.0, loc / max_loc))
    r = int(34 + (239 - 34) * pct)
    g = int(197 - (197 - 68) * pct)
    b = int(94 - (94 - 68) * pct)
    return f"#{r:02x}{g:02x}{b:02x}"


def _color_for_time(merged_at: str | None) -> str:
    """Time: recent → green, old → amber. Currently maps to a single
    color since we don't have many runs to make a gradient useful."""
    return "#22c55e" if merged_at else "#94a3b8"


def _color_for_difficulty(node: Node) -> str:
    """Difficulty heuristic (matches the WORKFLOW decision matrix):
    - unsolved: no PR connected, or `failure_class: interrupted`
    - broad: large LOC + high cost
    - medium: small LOC + medium cost
    - narrow: small LOC + low cost
    """
    if node.type == "issue":
        loc = node.attrs.get("loc_add", 0) or 0
        cost = node.attrs.get("cost", 0) or 0
        if node.attrs.get("state") != "done":
            return "#ef4444"  # unsolved
        if loc > 500 or cost > 8:
            return "#f59e0b"  # broad
        if loc > 100 or cost > 2:
            return "#eab308"  # medium
        return "#22c55e"  # narrow
    return "#94a3b8"


def apply_color_by(nodes: list[Node], color_by: str) -> None:
    """Annotate each node with a ``color`` attribute based on the
    chosen dimension. Mutates in-place."""
    if not color_by:
        return
    if color_by == "model":
        for n in nodes:
            if n.type == "pr":
                n.attrs["color"] = _MODEL_COLORS.get(
                    n.attrs.get("model", ""), _DEFAULT_MODEL_COLOR,
                )
    elif color_by == "cost":
        max_cost = max(
            (float(n.attrs.get("cost", 0)) for n in nodes if n.attrs.get("cost")),
            default=0.0,
        )
        for n in nodes:
            cost = float(n.attrs.get("cost", 0))
            n.attrs["color"] = _color_for_cost(cost, max_cost)
    elif color_by == "loc":
        max_loc = max(
            (int(n.attrs.get("loc_add", 0)) for n in nodes if n.attrs.get("loc_add")),
            default=0,
        )
        for n in nodes:
            loc = int(n.attrs.get("loc_add", 0))
            n.attrs["color"] = _color_for_loc(loc, max_loc)
    elif color_by == "time":
        for n in nodes:
            merged = n.attrs.get("merged_at") if n.type == "pr" else None
            n.attrs["color"] = _color_for_time(merged)
    elif color_by == "difficulty":
        for n in nodes:
            n.attrs["color"] = _color_for_difficulty(n)


# --------------------------------------------------------------------------- #
# Output                                                                      #
# --------------------------------------------------------------------------- #


def to_json(nodes: list[Node], edges: list[Edge]) -> str:
    return json.dumps(
        {
            "nodes": [
                {"id": n.id, "type": n.type, "title": n.title, **n.attrs}
                for n in nodes
            ],
            "edges": [
                {"from": e.from_id, "to": e.to_id, "type": e.type}
                for e in edges
            ],
        },
        indent=2,
        sort_keys=False,
    )


def to_dot(nodes: list[Node], edges: list[Edge]) -> str:
    """Emit a Graphviz DOT graph with nodes colored by their ``color``
    attribute (if set by ``--color-by``)."""
    # Group by type
    issue_nodes = [n for n in nodes if n.type == "issue"]
    pr_nodes = [n for n in nodes if n.type == "pr"]
    commit_nodes = [n for n in nodes if n.type == "commit"]

    lines: list[str] = ["digraph issue_network {", "  rankdir=LR;", "  node [shape=box, style=\"rounded,filled\", fontname=\"Helvetica\"];"]
    for n in issue_nodes:
        attrs = [f'label="Issue #{n.id.split("-", 1)[1]}\\n{n.title[:40]}"']
        if "color" in n.attrs:
            attrs.append(f'fillcolor="{n.attrs["color"]}"')
        lines.append(f'  "{n.id}" [{", ".join(attrs)}];')
    for n in pr_nodes:
        attrs = [f'label="PR #{n.id.split("-", 1)[1]}"']
        if "color" in n.attrs:
            attrs.append(f'fillcolor="{n.attrs["color"]}"')
        lines.append(f'  "{n.id}" [{", ".join(attrs)}, shape=ellipse];')
    for n in commit_nodes:
        attrs = [f'label="{n.id.split("-", 1)[1][:8]}"']
        if "color" in n.attrs:
            attrs.append(f'fillcolor="{n.attrs["color"]}"')
        lines.append(f'  "{n.id}" [{", ".join(attrs)}, shape=point];')
    for e in edges:
        lines.append(f'  "{e.from_id}" -> "{e.to_id}" [label="{e.type}"];')
    lines.append("}")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# CLI                                                                         #
# --------------------------------------------------------------------------- #


_SINCE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_SINCE_ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


def _validate_since(value: str) -> str:
    """argparse type= for ``--since``. Accepts:
    - ``YYYY-MM-DD`` — expanded to ``YYYY-MM-DDT00:00:00Z``
      (midnight UTC of that day) before being passed to the
      GitHub API, which requires a full ISO 8601 timestamp.
    - ``YYYY-MM-DDTHH:MM:SSZ`` — used as-is.

    The returned string is always in the GitHub-API-compatible
    form so callers don't have to re-format.
    """
    if _SINCE_ISO_RE.match(value):
        return value
    if _SINCE_RE.match(value):
        return f"{value}T00:00:00Z"
    raise argparse.ArgumentTypeError(
        f"--since must be YYYY-MM-DD or YYYY-MM-DDTHH:MM:SSZ (got {value!r})"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build an issue/PR/commit relationship graph from "
        "the local open.md backlog + the GitHub API for closed issues/PRs.",
    )
    parser.add_argument(
        "--backlog-open", type=Path, default=DEFAULT_BACKLOG_OPEN,
        help="Path to open.md backlog file",
    )
    parser.add_argument(
        "--runs-dir", type=Path, default=DEFAULT_RUNS_DIR,
        help="Path to reports/runs/ directory",
    )
    parser.add_argument(
        "--github-owner", default=None,
        help="GitHub owner (default: auto-detect from `git remote`)",
    )
    parser.add_argument(
        "--github-repo", default=None,
        help="GitHub repo name (default: auto-detect from `git remote`)",
    )
    parser.add_argument(
        "--since", type=_validate_since, default=None,
        help="Only include PRs merged/closed on or after YYYY-MM-DD",
    )
    parser.add_argument(
        "--format", choices=("json", "dot"), default="json",
        help="Output format (default: json)",
    )
    parser.add_argument(
        "--color-by",
        choices=("", "model", "cost", "loc", "time", "difficulty"),
        default="",
        help="Annotate each node with a color based on the chosen dimension",
    )
    parser.add_argument(
        "--output", type=Path, default=None,
        help="Write to file instead of stdout",
    )
    args = parser.parse_args(argv)

    # Auto-detect owner/repo when not given.
    owner = args.github_owner
    repo = args.github_repo
    if not owner or not repo:
        detected = _detect_github_owner_repo()
        if detected is None:
            sys.stderr.write(
                "build_graph: --github-owner / --github-repo required "
                "(could not auto-detect from `git remote get-url origin`)\n"
            )
            return 2
        if not owner:
            owner = detected[0]
        if not repo:
            repo = detected[1]

    # Open issues from the local backlog.
    nodes: list[Node] = []
    nodes.extend(parse_open_backlog(args.backlog_open))

    # Closed Issue↔PR↔Commit subgraph from the GitHub API.
    gh_nodes, gh_edges = fetch_github_graph_data(owner, repo, since=args.since)
    nodes.extend(gh_nodes)
    edges: list[Edge] = list(gh_edges)

    # Parent-of edges for open issues (same logic as before).
    for n in nodes:
        parent = n.attrs.get("parent")
        if n.type == "issue" and parent:
            edges.append(Edge(
                from_id=f"issue-{parent}",
                to_id=n.id,
                type="parent_of",
            ))

    # Dedupe nodes by id (same issue can appear in both open and GitHub data).
    by_id: dict[str, Node] = {}
    for n in nodes:
        if n.id not in by_id:
            by_id[n.id] = n
        else:
            # Merge attrs (GitHub-closed overrides open for state + LOC).
            for k, v in n.attrs.items():
                by_id[n.id].attrs.setdefault(k, v)
            if n.title and not by_id[n.id].title:
                by_id[n.id].title = n.title
    nodes = list(by_id.values())

    # Enrich with cost data.
    enrich_from_runs(args.runs_dir, nodes)

    # Apply color-by.
    apply_color_by(nodes, args.color_by)

    # Output.
    if args.format == "dot":
        output = to_dot(nodes, edges)
    else:
        output = to_json(nodes, edges)

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output, encoding="utf-8")
    else:
        sys.stdout.write(output + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
