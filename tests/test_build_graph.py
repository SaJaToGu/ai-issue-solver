"""Unit tests for build_graph.py.

The script is offline-only: it reads from the repo's own docs/
BACKLOG/*.md and reports/runs/*/metadata.json files. No network
calls. Tests use the real on-disk files (open.md and done.md) plus
small synthetic inputs where needed.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

# Add scripts/ to path so we can import build_graph as a module
ROOT = Path(__file__).resolve().parents[1]  # tests/ → repo root
sys.path.insert(0, str(ROOT / "scripts"))

from build_graph import (  # noqa: E402
    Node,
    Edge,
    parse_open_backlog,
    parse_done_backlog,
    enrich_from_runs,
    apply_color_by,
    to_json,
    to_dot,
    _color_for_cost,
    _color_for_loc,
    _color_for_difficulty,
    _MODEL_COLORS,
)


class TestParseOpenBacklog(unittest.TestCase):
    def test_parses_active_sections(self):
        nodes = parse_open_backlog(ROOT / "docs" / "BACKLOG" / "open.md")
        # At minimum, §37 and §39 are always present (parked)
        ids = {n.id for n in nodes}
        self.assertIn("issue-37", ids)
        self.assertIn("issue-39", ids)
        # All parsed nodes are issues with state=open
        for n in nodes:
            self.assertEqual(n.type, "issue")
            self.assertEqual(n.attrs.get("state"), "open")

    def test_parses_parent_reference(self):
        """An open issue with `Parent: #N` in the body gets parent_of
        metadata. Most current open issues don't have parents, but
        the parser should not crash on the field if absent."""
        nodes = parse_open_backlog(ROOT / "docs" / "BACKLOG" / "open.md")
        for n in nodes:
            self.assertIn("parent", n.attrs)  # always set (None or int)

    def test_missing_file_returns_empty(self):
        result = parse_open_backlog(ROOT / "docs" / "BACKLOG" / "does_not_exist.md")
        self.assertEqual(result, [])


class TestParseDoneBacklog(unittest.TestCase):
    def test_parses_done_sections_with_pr_and_commit(self):
        nodes, edges = parse_done_backlog(ROOT / "docs" / "BACKLOG" / "done.md")
        # At least the recent merged PRs should be in the graph
        ids = {n.id for n in nodes}
        self.assertIn("issue-410", ids)
        self.assertIn("issue-411", ids)
        self.assertIn("issue-412", ids)
        self.assertIn("issue-357", ids)
        self.assertIn("issue-383", ids)
        self.assertIn("issue-418", ids)
        self.assertIn("issue-420", ids)
        # Corresponding PR nodes exist (e.g. PR #416 for issue #357)
        self.assertIn("pr-416", ids)
        self.assertIn("pr-417", ids)
        self.assertIn("pr-419", ids)
        self.assertIn("pr-420", ids)

    def test_backticked_commit_sha_handled(self):
        """The current done.md format uses `commit `0a2864b`` (with
        backticks for code formatting). The parser must accept that."""
        nodes, edges = parse_done_backlog(ROOT / "docs" / "BACKLOG" / "done.md")
        # Find issue-418 (which was closed with backticked commit `0a2864b`)
        issue_418 = next((n for n in nodes if n.id == "issue-418"), None)
        self.assertIsNotNone(issue_418)
        # Should have a `closes` edge to pr-419
        closes = [e for e in edges if e.from_id == "issue-418" and e.type == "closes"]
        self.assertEqual(len(closes), 1)
        self.assertEqual(closes[0].to_id, "pr-419")
        # The PR node should carry the head_sha
        pr_419 = next((n for n in nodes if n.id == "pr-419"), None)
        self.assertIsNotNone(pr_419)
        self.assertEqual(pr_419.attrs.get("head_sha"), "0a2864b")

    def test_loc_parsing(self):
        """Issues that closed a PR with +X/-Y across N files should
        have those attributes populated."""
        nodes, _ = parse_done_backlog(ROOT / "docs" / "BACKLOG" / "done.md")
        issue_357 = next((n for n in nodes if n.id == "issue-357"), None)
        self.assertIsNotNone(issue_357)
        self.assertEqual(issue_357.attrs.get("loc_add"), 384)
        self.assertEqual(issue_357.attrs.get("loc_del"), -205)
        self.assertEqual(issue_357.attrs.get("files"), 9)

    def test_edges_have_closes_and_merged_into(self):
        _, edges = parse_done_backlog(ROOT / "docs" / "BACKLOG" / "done.md")
        edge_types = {e.type for e in edges}
        self.assertIn("closes", edge_types)
        self.assertIn("merged_into", edge_types)


class TestEnrichFromRuns(unittest.TestCase):
    def test_no_runs_dir_no_change(self):
        nodes = [Node(id="pr-1", type="pr", attrs={})]
        before = [n.attrs.copy() for n in nodes]
        enrich_from_runs(ROOT / "does_not_exist", nodes)
        after = [n.attrs.copy() for n in nodes]
        self.assertEqual(before, after)

    def test_real_runs_dir_adds_model(self):
        """The real reports/runs/ directory contains metadata for
        runs that closed today's PRs. The model field should be
        populated for those PRs."""
        runs_dir = ROOT / "reports" / "runs"
        if not runs_dir.exists():
            self.skipTest("no reports/runs/ directory")
        nodes = [Node(id="pr-416", type="pr", attrs={}), Node(id="pr-419", type="pr", attrs={})]
        enrich_from_runs(runs_dir, nodes)
        # At least one of the PRs should have a model attribute
        models = [n.attrs.get("model") for n in nodes if n.attrs.get("model")]
        self.assertTrue(len(models) > 0, f"expected at least one model; got {models}")


class TestApplyColorBy(unittest.TestCase):
    def test_color_by_model_assigns_known_color(self):
        nodes = [Node(id="pr-1", type="pr", attrs={"model": "opencode"})]
        apply_color_by(nodes, "model")
        self.assertEqual(nodes[0].attrs.get("color"), _MODEL_COLORS["opencode"])

    def test_color_by_model_unknown_falls_back_to_default(self):
        nodes = [Node(id="pr-1", type="pr", attrs={"model": "unknown-thing"})]
        apply_color_by(nodes, "model")
        self.assertEqual(nodes[0].attrs.get("color"), "#94a3b8")

    def test_color_by_cost_gradient(self):
        nodes = [
            Node(id="pr-1", type="pr", attrs={"cost": 0.0}),
            Node(id="pr-2", type="pr", attrs={"cost": 10.0}),
        ]
        apply_color_by(nodes, "cost")
        # Low cost → green, high cost → red
        self.assertTrue(nodes[0].attrs.get("color").startswith("#"))
        self.assertNotEqual(
            nodes[0].attrs.get("color"),
            nodes[1].attrs.get("color"),
        )

    def test_color_by_loc_gradient(self):
        nodes = [
            Node(id="pr-1", type="pr", attrs={"loc_add": 0}),
            Node(id="pr-2", type="pr", attrs={"loc_add": 1000}),
        ]
        apply_color_by(nodes, "loc")
        self.assertNotEqual(
            nodes[0].attrs.get("color"),
            nodes[1].attrs.get("color"),
        )

    def test_color_by_difficulty_for_issue(self):
        # unsolved (no PR, open state)
        n1 = Node(id="issue-1", type="issue", attrs={"state": "open"})
        # narrow (low cost + small LOC, done)
        n2 = Node(id="issue-2", type="issue", attrs={"state": "done", "cost": 1.0, "loc_add": 50})
        # broad (large LOC)
        n3 = Node(id="issue-3", type="issue", attrs={"state": "done", "cost": 1.0, "loc_add": 800})
        nodes = [n1, n2, n3]
        apply_color_by(nodes, "difficulty")
        # All three should have distinct colors
        colors = {n.attrs.get("color") for n in nodes}
        self.assertEqual(len(colors), 3)

    def test_no_op_when_dimension_empty(self):
        nodes = [Node(id="issue-1", type="issue", attrs={"state": "done"})]
        apply_color_by(nodes, "")
        self.assertNotIn("color", nodes[0].attrs)


class TestColorFunctions(unittest.TestCase):
    def test_color_for_cost_zero(self):
        self.assertEqual(_color_for_cost(0, 10), "#22c55e")

    def test_color_for_cost_max(self):
        # At max cost, should be fully red
        self.assertEqual(_color_for_cost(10, 10), "#ef4444")

    def test_color_for_cost_no_max(self):
        # Avoid division by zero
        self.assertEqual(_color_for_cost(5, 0), "#22c55e")

    def test_color_for_loc_no_max(self):
        self.assertEqual(_color_for_loc(100, 0), "#22c55e")

    def test_color_for_difficulty_unsolved(self):
        self.assertEqual(
            _color_for_difficulty(Node(id="x", type="issue", attrs={"state": "open"})),
            "#ef4444",
        )


class TestOutputFormats(unittest.TestCase):
    def test_to_json_structure(self):
        nodes = [Node(id="issue-1", type="issue", title="Test")]
        edges = [Edge(from_id="issue-1", to_id="pr-1", type="closes")]
        out = to_json(nodes, edges)
        parsed = json.loads(out)
        self.assertIn("nodes", parsed)
        self.assertIn("edges", parsed)
        self.assertEqual(len(parsed["nodes"]), 1)
        self.assertEqual(len(parsed["edges"]), 1)
        self.assertEqual(parsed["nodes"][0]["id"], "issue-1")
        self.assertEqual(parsed["edges"][0]["from"], "issue-1")
        self.assertEqual(parsed["edges"][0]["to"], "pr-1")
        self.assertEqual(parsed["edges"][0]["type"], "closes")

    def test_to_dot_basic(self):
        nodes = [
            Node(id="issue-1", type="issue", title="Test", attrs={"color": "#22c55e"}),
            Node(id="pr-1", type="pr", title="PR"),
        ]
        edges = [Edge(from_id="issue-1", to_id="pr-1", type="closes")]
        out = to_dot(nodes, edges)
        self.assertIn("digraph issue_network", out)
        self.assertIn('"issue-1"', out)
        self.assertIn('"pr-1"', out)
        self.assertIn('fillcolor="#22c55e"', out)
        self.assertIn("closes", out)


class TestEndToEnd(unittest.TestCase):
    """Run the full pipeline on the real on-disk files and assert
    the resulting graph has the expected shape (counts, types)."""

    def test_full_pipeline_json(self):
        import build_graph

        nodes = []
        nodes.extend(parse_open_backlog(ROOT / "docs" / "BACKLOG" / "open.md"))
        done_nodes, done_edges = parse_done_backlog(ROOT / "docs" / "BACKLOG" / "done.md")
        nodes.extend(done_nodes)
        enrich_from_runs(ROOT / "reports" / "runs", nodes)
        out = to_json(nodes, done_edges)
        parsed = json.loads(out)
        # At least 10 issue nodes, 5+ PR nodes, 5+ commit nodes
        issue_count = sum(1 for n in parsed["nodes"] if n["type"] == "issue")
        pr_count = sum(1 for n in parsed["nodes"] if n["type"] == "pr")
        commit_count = sum(1 for n in parsed["nodes"] if n["type"] == "commit")
        self.assertGreaterEqual(issue_count, 10)
        self.assertGreaterEqual(pr_count, 5)
        self.assertGreaterEqual(commit_count, 5)
        # Edges
        self.assertGreaterEqual(len(parsed["edges"]), 5)
        # All edges are one of the known types
        known = {"closes", "merged_into", "parent_of"}
        for e in parsed["edges"]:
            self.assertIn(e["type"], known)

    def test_full_pipeline_dot(self):
        import build_graph

        nodes = []
        nodes.extend(parse_open_backlog(ROOT / "docs" / "BACKLOG" / "open.md"))
        done_nodes, done_edges = parse_done_backlog(ROOT / "docs" / "BACKLOG" / "done.md")
        nodes.extend(done_nodes)
        apply_color_by(nodes, "model")
        out = to_dot(nodes, done_edges)
        self.assertIn("digraph", out)
        self.assertIn("->", out)
        # At least one PR has a color
        self.assertIn('fillcolor=', out)


if __name__ == "__main__":
    unittest.main()
