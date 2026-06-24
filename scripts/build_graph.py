#!/usr/bin/env python3
"""
build_graph.py — Build an issue/PR/commit relationship graph for the
ai-issue-solver repo.

Data sources:
- ``docs/BACKLOG/open.md`` — active backlog items, parsed for § number,
  title, and (when present) parent-issue reference
- GitHub API (via ``gh api``) — closed/merged PRs with their linked
  issues, LOC stats (additions/deletions/changed_files), merge commit
  SHA, branch, labels, and author
- ``reports/runs/<run-id>/metadata.json`` — solver cost data per run
- ``reports/runs/<run-id>/summary.txt`` — pr_url, merge commit, cost

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
    python scripts/build_graph.py --since 2026-06-01       # scope to recent
    python scripts/build_graph.py --output /tmp/graph.json # custom path
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.parse
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BACKLOG_OPEN = REPO_ROOT / "docs" / "BACKLOG" / "open.md"
DEFAULT_RUNS_DIR = REPO_ROOT / "reports" / "runs"

# Regex patterns for PR body → issue references
_CLOSES_RE = re.compile(
    r"(?:Closes|Fixes|Resolves|Closed\s+via)\s+#(\d+)",
    re.IGNORECASE,
)
_PARENT_OF_RE = re.compile(
    r"(?:Parent|Part\s+of):\s*#(\d+)",
    re.IGNORECASE,
)

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
# Backlog parsing (open.md — stays local)                                     #
# --------------------------------------------------------------------------- #


# `## 37. Free OpenCode models full integration and evaluation *(parked)*`
_OPEN_RE = re.compile(r"^##\s+(\d+)\.\s+(.+?)\s*$", re.MULTILINE)
# `Parent: #357` inside an open.md section
_PARENT_REF_RE = re.compile(r"^\s*Parent:\s*#(\d+)\s*$", re.MULTILINE)


def parse_open_backlog(path: Path) -> list[Node]:
    """Parse ``docs/BACKLOG/open.md`` for active § items."""
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8")
    nodes: list[Node] = []
    for m in _OPEN_RE.finditer(text):
        number = int(m.group(1))
        title = m.group(2).strip()
        body = text[m.end(): text.find(f"\n## ", m.end()) if text.find(f"\n## ", m.end()) != -1 else len(text)]
        parent_match = _PARENT_REF_RE.search(body)
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
# GitHub API helpers                                                          #
# --------------------------------------------------------------------------- #


def _gh_api(endpoint: str) -> Any:
    """Single ``gh api`` call, returns parsed JSON.

    Returns ``None`` on network/auth errors so callers can degrade
    gracefully (e.g. fall back to local data or produce an empty
    graph).
    """
    try:
        result = subprocess.run(
            ["gh", "api", endpoint],
            capture_output=True, text=True, check=True, timeout=30,
        )
        return json.loads(result.stdout)
    except FileNotFoundError:
        print("Warning: `gh` CLI not found. Install it from https://cli.github.com/ "
              "and run `gh auth login`.", file=sys.stderr)
        return None
    except subprocess.CalledProcessError as exc:
        print(f"Warning: `gh api {endpoint}` failed: {exc.stderr.strip()[:200]}",
              file=sys.stderr)
        return None
    except (json.JSONDecodeError, subprocess.TimeoutExpired) as exc:
        print(f"Warning: `gh api {endpoint}` error: {exc}", file=sys.stderr)
        return None


def _gh_api_paginate(endpoint: str) -> list[dict[str, Any]]:
    """Call ``gh api`` with manual pagination.

    Returns a combined list of all pages. Stops on the first empty
    page or error.
    """
    items: list[dict[str, Any]] = []
    page = 1
    while True:
        sep = "&" if "?" in endpoint else "?"
        url = f"{endpoint}{sep}per_page=100&page={page}"
        data = _gh_api(url)
        if data is None or isinstance(data, dict) or (isinstance(data, list) and len(data) == 0):
            break
        items.extend(data)
        if len(data) < 100:
            break
        page += 1
    return items


def _detect_github_owner_repo() -> tuple[str, str]:
    """Detect owner/repo from the local git remote, then env, then defaults."""
    env_owner = os.environ.get("GITHUB_OWNER", "")
    env_repo = os.environ.get("GITHUB_REPO", "")
    if env_owner and env_repo:
        return env_owner, env_repo

    try:
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            capture_output=True, text=True, check=True, timeout=10,
        )
        url = result.stdout.strip()
        for pattern in (r"git@github\.com:([^/]+)/(.+)\.git$",
                        r"https://github\.com/([^/]+)/(.+?)\.git$",
                        r"https://github\.com/([^/]+)/(.+?)$"):
            m = re.match(pattern, url)
            if m:
                return m.group(1), m.group(2).replace(".git", "")
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass

    if env_owner:
        return env_owner, env_repo or "ai-issue-solver"
    return "ai-issue-solver", "ai-issue-solver"


# --------------------------------------------------------------------------- #
# GitHub-native graph data (replaces the old done.md parser)                  #
# --------------------------------------------------------------------------- #


def fetch_github_graph_data(
    owner: str,
    repo: str,
    since: str | None = None,
) -> tuple[list[Node], list[Edge]]:
    """Fetch merged PRs + linked issues from the GitHub API.

    Returns ``(nodes, edges)`` with issue→pr ``closes`` edges and
    pr→commit ``merged_into`` edges.  LOC and file-count come from
    the PR's native ``additions`` / ``deletions`` / ``changed_files``
    fields so the old LOC-parsing caveat no longer applies.
    """
    # Build search query — use ``merged:>=YYYY-MM-DD`` when ``--since``
    # is given, otherwise all merged PRs.
    q = f"repo:{owner}/{repo}+type:pr+is:merged"
    if since:
        q += f"+merged:>={since}"

    encoded = urllib.parse.quote(q, safe="")
    endpoint = f"search/issues?q={encoded}&sort=updated&order=desc"

    raw_items = _gh_api_paginate(endpoint)
    if not raw_items:
        return [], []

    nodes: list[Node] = []
    edges: list[Edge] = []
    seen_issues: dict[int, dict[str, Any] | None] = {}

    for item in raw_items:
        if "pull_request" not in item:
            continue

        pr_num: int = item["number"]
        pr_title: str = item.get("title", "") or ""
        pr_body: str = item.get("body") or ""

        # Parse issue references from PR body
        closes = [int(m.group(1)) for m in _CLOSES_RE.finditer(pr_body)]

        # Fetch full PR detail for LOC stats
        pr_detail = _gh_api(f"repos/{owner}/{repo}/pulls/{pr_num}")
        if not pr_detail:
            continue

        head_sha = (pr_detail.get("head") or {}).get("sha", "") or ""
        merge_commit_sha = (pr_detail.get("merge_commit_sha") or "") or ""
        commit_sha = merge_commit_sha or head_sha
        additions = pr_detail.get("additions", 0)
        deletions = pr_detail.get("deletions", 0)
        changed_files = pr_detail.get("changed_files", 0)
        merged_at = pr_detail.get("merged_at")
        head_ref = (pr_detail.get("head") or {}).get("ref", "") or ""
        labels = [lb["name"] for lb in (pr_detail.get("labels") or [])]
        author = (pr_detail.get("user") or {}).get("login", "") or ""

        # Build PR node
        pr_node = Node(
            id=f"pr-{pr_num}",
            type="pr",
            title=f"PR #{pr_num}: {pr_title[:60]}",
            attrs={
                "head_sha": commit_sha[:10],
                "head_ref": head_ref,
                "merged_at": merged_at or "",
                "additions": additions,
                "deletions": deletions,
                "changed_files": changed_files,
                "ai_generated": "ai-generated" in labels,
                "author": author,
            },
        )
        nodes.append(pr_node)

        # Commit node + merged_into edge
        if commit_sha:
            commit_id = f"commit-{commit_sha[:10]}"
            nodes.append(Node(
                id=commit_id,
                type="commit",
                title=commit_sha[:10],
            ))
            edges.append(Edge(
                from_id=f"pr-{pr_num}",
                to_id=commit_id,
                type="merged_into",
            ))

        # Issue nodes + closes edges
        for issue_num in closes:
            if issue_num not in seen_issues:
                issue_data = _gh_api(
                    f"repos/{owner}/{repo}/issues/{issue_num}",
                )
                if issue_data and "pull_request" not in issue_data:
                    seen_issues[issue_num] = issue_data
                else:
                    seen_issues[issue_num] = None

            issue_data = seen_issues[issue_num]
            if issue_data is not None:
                issue_node = Node(
                    id=f"issue-{issue_num}",
                    type="issue",
                    title=issue_data.get("title", "") or "",
                    attrs={
                        "state": "done",
                        "loc_add": additions,
                        "loc_del": -deletions,
                        "files": changed_files,
                    },
                )
                nodes.append(issue_node)
                edges.append(Edge(
                    from_id=f"issue-{issue_num}",
                    to_id=f"pr-{pr_num}",
                    type="closes",
                ))

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


# Discrete color map for model names.
_MODEL_COLORS: dict[str, str] = {
    "opencode": "#22c55e",
    "codex": "#3b82f6",
    "claude": "#8b5cf6",
    "mistral": "#ec4899",
    "openai": "#f97316",
    "ollama": "#14b8a6",
    "mistral-vibe": "#d946ef",
    "openrouter": "#eab308",
    "openrouter_direct": "#06b6d4",
    "opencode/deepseek-v4-flash-free": "#22c55e",
    "opencode/minimax-m3-free": "#ef4444",
    "opencode/mimo-v2.5-free": "#f59e0b",
    "opencode/minimax-m2.5": "#84cc16",
    "opencode/nemotron-3-super-free": "#06b6d4",
}
_DEFAULT_MODEL_COLOR = "#94a3b8"


def _color_for_cost(cost: float, max_cost: float) -> str:
    if max_cost <= 0:
        return "#22c55e"
    pct = min(1.0, max(0.0, cost / max_cost))
    r = int(34 + (239 - 34) * pct)
    g = int(197 - (197 - 68) * pct)
    b = int(94 - (94 - 68) * pct)
    return f"#{r:02x}{g:02x}{b:02x}"


def _color_for_loc(loc: int, max_loc: int) -> str:
    if max_loc <= 0:
        return "#22c55e"
    pct = min(1.0, max(0.0, loc / max_loc))
    r = int(34 + (239 - 34) * pct)
    g = int(197 - (197 - 68) * pct)
    b = int(94 - (94 - 68) * pct)
    return f"#{r:02x}{g:02x}{b:02x}"


def _color_for_time(merged_at: str | None) -> str:
    return "#22c55e" if merged_at else "#94a3b8"


def _color_for_difficulty(node: Node) -> str:
    if node.type == "issue":
        loc = node.attrs.get("loc_add", 0) or 0
        cost = node.attrs.get("cost", 0) or 0
        if node.attrs.get("state") != "done":
            return "#ef4444"
        if loc > 500 or cost > 8:
            return "#f59e0b"
        if loc > 100 or cost > 2:
            return "#eab308"
        return "#22c55e"
    return "#94a3b8"


def apply_color_by(nodes: list[Node], color_by: str) -> None:
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
    issue_nodes = [n for n in nodes if n.type == "issue"]
    pr_nodes = [n for n in nodes if n.type == "pr"]
    commit_nodes = [n for n in nodes if n.type == "commit"]

    lines: list[str] = [
        "digraph issue_network {",
        "  rankdir=LR;",
        '  node [shape=box, style="rounded,filled", fontname="Helvetica"];',
    ]
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build an issue/PR/commit relationship graph. "
        "Data source: GitHub API (gh api) for merged PR data, "
        "backlog files for active issue parent references, "
        "and run-reports for cost/model enrichment.",
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
        "--github-owner", default="",
        help="GitHub owner (default: auto-detect from git remote or env)",
    )
    parser.add_argument(
        "--github-repo", default="",
        help="GitHub repo name (default: auto-detect from git remote or env)",
    )
    parser.add_argument(
        "--since", default=None,
        help="Only include items merged on or after YYYY-MM-DD",
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

    collect_err = False

    # Validate --since format
    if args.since:
        try:
            datetime.strptime(args.since, "%Y-%m-%d")
        except ValueError:
            print(f"Error: --since must be YYYY-MM-DD, got {args.since!r}",
                  file=sys.stderr)
            return 1

    # 1. Open backlog (local, for parent_of edges)
    nodes: list[Node] = []
    edges: list[Edge] = []
    nodes.extend(parse_open_backlog(args.backlog_open))

    # 2. GitHub API (replaces done.md parser)
    owner = args.github_owner or os.environ.get("GITHUB_OWNER", "")
    repo = args.github_repo or os.environ.get("GITHUB_REPO", "")
    if not owner or not repo:
        owner, repo = _detect_github_owner_repo()
    gh_nodes, gh_edges = fetch_github_graph_data(owner, repo, since=args.since)
    nodes.extend(gh_nodes)
    edges.extend(gh_edges)

    # 3. Parent-of edges for open issues (from open.md)
    for n in nodes:
        parent = n.attrs.get("parent")
        if n.type == "issue" and parent:
            edges.append(Edge(
                from_id=f"issue-{parent}",
                to_id=n.id,
                type="parent_of",
            ))

    # Dedupe nodes by id
    by_id: dict[str, Node] = {}
    for n in nodes:
        if n.id not in by_id:
            by_id[n.id] = n
        else:
            for k, v in n.attrs.items():
                by_id[n.id].attrs.setdefault(k, v)
            if n.title and not by_id[n.id].title:
                by_id[n.id].title = n.title
    nodes = list(by_id.values())

    # 4. Enrich with cost data from local run-reports
    enrich_from_runs(args.runs_dir, nodes)

    # 5. Apply color-by
    apply_color_by(nodes, args.color_by)

    # 6. Output
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
