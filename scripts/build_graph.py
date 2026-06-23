#!/usr/bin/env python3
"""
build_graph.py — Build an issue/PR/commit relationship graph for the
ai-issue-solver repo.

Reads:
- ``docs/BACKLOG/open.md`` — active backlog items, parsed for § number,
  title, and (when present) parent-issue reference
- ``docs/BACKLOG/done.md`` — completed items, parsed for § number, GitHub
  issue number, PR number, commit SHA, and the +/- LOC + files lines
  already in the entries
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
    python scripts/build_graph.py --output /tmp/graph.json # custom path
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BACKLOG_OPEN = REPO_ROOT / "docs" / "BACKLOG" / "open.md"
DEFAULT_BACKLOG_DONE = REPO_ROOT / "docs" / "BACKLOG" / "done.md"
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
# Backlog parsing                                                             #
# --------------------------------------------------------------------------- #


# `## 37. Free OpenCode models full integration and evaluation *(parked)*`
_OPEN_RE = re.compile(r"^##\s+(\d+)\.\s+(.+?)\s*$", re.MULTILINE)
# `Parent: #357` inside an open.md section
_PARENT_RE = re.compile(r"^\s*Parent:\s*#(\d+)\s*$", re.MULTILINE)

# `## Done — §42 0.9.0 Validation Metrics & Run (GitHub #326)`
# or `## Done — check-prs handles merged PRs (GitHub #420)` (no §N,
# for ad-hoc fixes not tracked in the backlog)
_DONE_RE = re.compile(
    r"^##\s+Done\s+—\s+(?:§\d+\s+)?(.+?)\s+\(GitHub\s+#(\d+)\)\s*$",
    re.MULTILINE,
)
# `Closed via #357 (PR #417, squash-merged into develop at commit 64d28a8ed5).`
# or `Closed via #418 (PR #419, squash-merged into develop at commit `0a2864b`).`
# (backticks are optional in done.md)
_CLOSED_VIA_RE = re.compile(
    r"Closed\s+via\s+#(\d+)\s+\(PR\s+#(\d+)[^)]*?commit\s+`?([0-9a-f]{7,40})`?",
    re.IGNORECASE,
)
# `+86/-6 across 5 files` or `+186/-6 in 5 files`
_LOC_RE = re.compile(
    r"([+-]?\d+)\s*/\s*([+-]?\d+)\s+(?:across|in)\s+(\d+)\s+files?",
    re.IGNORECASE,
)


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


def parse_done_backlog(path: Path) -> tuple[list[Node], list[Edge]]:
    """Parse ``docs/BACKLOG/done.md`` for closed items, with PR + commit
    cross-references. Returns (issue_nodes, edges)."""
    if not path.exists():
        return [], []
    text = path.read_text(encoding="utf-8")
    issue_nodes: list[Node] = []
    edges: list[Edge] = []

    for m in _DONE_RE.finditer(text):
        title = m.group(1).strip()
        issue_num = int(m.group(2))
        issue_node = Node(
            id=f"issue-{issue_num}",
            type="issue",
            title=title,
            attrs={"state": "done"},
        )
        issue_nodes.append(issue_node)

        # Look for `Closed via #N (PR #M, ...commit SHA...)` within the
        # section body (between this match and the next `## ` heading).
        body_start = m.end()
        body_end = text.find("\n## ", body_start)
        if body_end == -1:
            body_end = len(text)
        body = text[body_start:body_end]

        cv = _CLOSED_VIA_RE.search(body)
        if cv:
            pr_num = int(cv.group(2))
            commit_sha = cv.group(3)
            pr_node = Node(
                id=f"pr-{pr_num}",
                type="pr",
                title=f"PR #{pr_num}",
                attrs={"head_sha": commit_sha},
            )
            issue_nodes.append(pr_node)
            edges.append(Edge(
                from_id=f"issue-{issue_num}",
                to_id=f"pr-{pr_num}",
                type="closes",
            ))
            edges.append(Edge(
                from_id=f"pr-{pr_num}",
                to_id=f"commit-{commit_sha}",
                type="merged_into",
            ))
            # Add a commit node so the merged_into edge has a target
            issue_nodes.append(Node(
                id=f"commit-{commit_sha}",
                type="commit",
                title=commit_sha[:10],
            ))

        # LOC + files: look for `+X/-Y across N files` or `+X/-Y in N files`
        loc = _LOC_RE.search(body)
        if loc:
            issue_node.attrs["loc_add"] = int(loc.group(1))
            issue_node.attrs["loc_del"] = int(loc.group(2))
            issue_node.attrs["files"] = int(loc.group(3))

    return issue_nodes, edges


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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build an issue/PR/commit relationship graph from "
        "backlog files and run-reports.",
    )
    parser.add_argument(
        "--backlog-open", type=Path, default=DEFAULT_BACKLOG_OPEN,
        help="Path to open.md backlog file",
    )
    parser.add_argument(
        "--backlog-done", type=Path, default=DEFAULT_BACKLOG_DONE,
        help="Path to done.md backlog file",
    )
    parser.add_argument(
        "--runs-dir", type=Path, default=DEFAULT_RUNS_DIR,
        help="Path to reports/runs/ directory",
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

    nodes: list[Node] = []
    nodes.extend(parse_open_backlog(args.backlog_open))
    done_nodes, done_edges = parse_done_backlog(args.backlog_done)
    nodes.extend(done_nodes)
    edges: list[Edge] = list(done_edges)

    # Parent-of edges for open issues
    for n in nodes:
        parent = n.attrs.get("parent")
        if n.type == "issue" and parent:
            edges.append(Edge(
                from_id=f"issue-{parent}",
                to_id=n.id,
                type="parent_of",
            ))

    # Dedupe nodes by id (same issue can appear in both open and done)
    by_id: dict[str, Node] = {}
    for n in nodes:
        if n.id not in by_id:
            by_id[n.id] = n
        else:
            # Merge attrs (done overrides open)
            for k, v in n.attrs.items():
                by_id[n.id].attrs.setdefault(k, v)
            if n.title and not by_id[n.id].title:
                by_id[n.id].title = n.title
    nodes = list(by_id.values())

    # Enrich with cost data
    enrich_from_runs(args.runs_dir, nodes)

    # Apply color-by
    apply_color_by(nodes, args.color_by)

    # Output
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
