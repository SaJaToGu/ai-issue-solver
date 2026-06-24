"""Unit tests for build_graph.py.

The script fetches data from the GitHub API (via ``gh api``) when
available, falling back gracefully when ``gh`` is not installed or
the API is unreachable. Tests use ``unittest.mock.patch`` to replace
``_gh_api`` and ``_gh_api_paginate`` with canned responses.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# Add scripts/ to path so we can import build_graph as a module
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from build_graph import (  # noqa: E402
    Node,
    Edge,
    parse_open_backlog,
    fetch_github_graph_data,
    enrich_from_runs,
    apply_color_by,
    to_json,
    to_dot,
    _color_for_cost,
    _color_for_loc,
    _color_for_difficulty,
    _MODEL_COLORS,
    _CLOSES_RE,
    _gh_api,
    _gh_api_paginate,
    _detect_github_owner_repo,
)


# --------------------------------------------------------------------------- #
# Fixtures — canned GitHub API responses                                      #
# --------------------------------------------------------------------------- #

_SEARCH_RESULT = {
    "total_count": 2,
    "incomplete_results": False,
    "items": [
        {
            "number": 416,
            "title": "Consolidate solver orchestration",
            "body": "Closes #357",
            "state": "closed",
            "pull_request": {
                "merged_at": "2026-06-23T10:00:00Z",
                "url": "https://api.github.com/repos/test-owner/test-repo/pulls/416",
            },
            "labels": [{"name": "ai-generated"}],
            "user": {"login": "ai-solver"},
        },
        {
            "number": 419,
            "title": "Forward --max-run-cost-usd",
            "body": "Closes #418\nParent: #357",
            "state": "closed",
            "pull_request": {
                "merged_at": "2026-06-24T12:00:00Z",
                "url": "https://api.github.com/repos/test-owner/test-repo/pulls/419",
            },
            "labels": [{"name": "ai-generated"}],
            "user": {"login": "ai-solver"},
        },
    ],
}

_PR_416 = {
    "number": 416,
    "title": "Consolidate solver orchestration",
    "body": "Closes #357",
    "state": "closed",
    "merged_at": "2026-06-23T10:00:00Z",
    "additions": 384,
    "deletions": 205,
    "changed_files": 9,
    "head": {"ref": "ai/fix-issue-357", "sha": "f17783f3abc"},
    "merge_commit_sha": "f17783f3abc",
    "labels": [{"name": "ai-generated"}],
    "user": {"login": "ai-solver"},
}

_PR_419 = {
    "number": 419,
    "title": "Forward --max-run-cost-usd",
    "body": "Closes #418\nParent: #357",
    "state": "closed",
    "merged_at": "2026-06-24T12:00:00Z",
    "additions": 186,
    "deletions": 6,
    "changed_files": 5,
    "head": {"ref": "ai/fix-issue-418", "sha": "0a2864b"},
    "merge_commit_sha": "0a2864b",
    "labels": [{"name": "ai-generated"}],
    "user": {"login": "ai-solver"},
}

_ISSUE_357 = {
    "number": 357,
    "title": "Consolidate solver orchestration across workflows",
    "state": "closed",
    "body": "Consolidate the shared orchestration layer.",
}

_ISSUE_418 = {
    "number": 418,
    "title": "Forward --max-run-cost-usd",
    "state": "closed",
    "body": "Forward budget flags through run_overnight.",
}


class TestClosesRegex(unittest.TestCase):
    """Verify the regex we use to parse PR bodies."""

    def test_closes_via(self):
        m = _CLOSES_RE.search("Closed via #357 (PR #416)")
        self.assertIsNotNone(m)
        self.assertEqual(m.group(1), "357")

    def test_closes_keyword(self):
        m = _CLOSES_RE.search("Closes #357")
        self.assertIsNotNone(m)
        self.assertEqual(m.group(1), "357")

    def test_fixes_keyword(self):
        m = _CLOSES_RE.search("Fixes #418")
        self.assertIsNotNone(m)
        self.assertEqual(m.group(1), "418")

    def test_resolves_keyword(self):
        m = _CLOSES_RE.search("Resolves #123")
        self.assertIsNotNone(m)
        self.assertEqual(m.group(1), "123")

    def test_no_match(self):
        self.assertIsNone(_CLOSES_RE.search("No reference here"))


class TestParseOpenBacklog(unittest.TestCase):
    def test_parses_active_sections(self):
        nodes = parse_open_backlog(ROOT / "docs" / "BACKLOG" / "open.md")
        ids = {n.id for n in nodes}
        self.assertIn("issue-37", ids)
        self.assertIn("issue-39", ids)
        for n in nodes:
            self.assertEqual(n.type, "issue")
            self.assertEqual(n.attrs.get("state"), "open")

    def test_parses_parent_reference(self):
        nodes = parse_open_backlog(ROOT / "docs" / "BACKLOG" / "open.md")
        for n in nodes:
            self.assertIn("parent", n.attrs)

    def test_missing_file_returns_empty(self):
        result = parse_open_backlog(
            ROOT / "docs" / "BACKLOG" / "does_not_exist.md",
        )
        self.assertEqual(result, [])


class TestFetchGitHubGraphData(unittest.TestCase):
    """Tests for the GitHub-native data path (replaces done.md parsing)."""

    maxDiff = None

    @staticmethod
    def _decode(endpoint: str) -> str:
        import urllib.parse
        return urllib.parse.unquote(endpoint)

    def _mock_paginate(self, endpoint: str) -> list:
        """Return canned search results for the search endpoint."""
        if "search/issues" in endpoint:
            return _SEARCH_RESULT["items"]
        return []

    def _mock_api(self, endpoint: str) -> dict | list | None:
        """Return canned PR / issue details."""
        if "pulls/416" in endpoint:
            return _PR_416
        if "pulls/419" in endpoint:
            return _PR_419
        if "issues/357" in endpoint:
            return _ISSUE_357
        if "issues/418" in endpoint:
            return _ISSUE_418
        return None

    def test_fetch_returns_nodes_and_edges(self):
        with patch("build_graph._gh_api_paginate", self._mock_paginate), \
             patch("build_graph._gh_api", self._mock_api):
            nodes, edges = fetch_github_graph_data(
                "test-owner", "test-repo",
            )

        # Should have 2 PR nodes, 2 issue nodes, 2 commit nodes
        pr_ids = {n.id for n in nodes if n.type == "pr"}
        issue_ids = {n.id for n in nodes if n.type == "issue"}
        commit_ids = {n.id for n in nodes if n.type == "commit"}
        self.assertIn("pr-416", pr_ids)
        self.assertIn("pr-419", pr_ids)
        self.assertIn("issue-357", issue_ids)
        self.assertIn("issue-418", issue_ids)
        self.assertIn("commit-f17783f3ab", commit_ids)
        self.assertIn("commit-0a2864b", commit_ids)

    def test_fetch_without_since_omits_filter(self):
        with patch("build_graph._gh_api_paginate", self._mock_paginate), \
             patch("build_graph._gh_api", self._mock_api):
            nodes, edges = fetch_github_graph_data(
                "test-owner", "test-repo", since=None,
            )
        self.assertGreater(len(nodes), 0)

    def test_loc_attrs_from_pr_api(self):
        with patch("build_graph._gh_api_paginate", self._mock_paginate), \
             patch("build_graph._gh_api", self._mock_api):
            nodes, edges = fetch_github_graph_data(
                "test-owner", "test-repo",
            )

        issue_357 = next((n for n in nodes if n.id == "issue-357"), None)
        self.assertIsNotNone(issue_357)
        self.assertEqual(issue_357.attrs.get("loc_add"), 384)
        self.assertEqual(issue_357.attrs.get("loc_del"), -205)
        self.assertEqual(issue_357.attrs.get("files"), 9)

    def test_pr_node_has_head_sha_and_ref(self):
        with patch("build_graph._gh_api_paginate", self._mock_paginate), \
             patch("build_graph._gh_api", self._mock_api):
            nodes, edges = fetch_github_graph_data(
                "test-owner", "test-repo",
            )

        pr_416 = next((n for n in nodes if n.id == "pr-416"), None)
        self.assertIsNotNone(pr_416)
        self.assertEqual(pr_416.attrs.get("head_sha"), "f17783f3ab")
        self.assertEqual(pr_416.attrs.get("head_ref"), "ai/fix-issue-357")

    def test_ai_generated_flag(self):
        with patch("build_graph._gh_api_paginate", self._mock_paginate), \
             patch("build_graph._gh_api", self._mock_api):
            nodes, edges = fetch_github_graph_data(
                "test-owner", "test-repo",
            )

        pr_416 = next((n for n in nodes if n.id == "pr-416"), None)
        self.assertTrue(pr_416.attrs.get("ai_generated"))
        self.assertEqual(pr_416.attrs.get("author"), "ai-solver")

    def test_edges_closes_and_merged_into(self):
        with patch("build_graph._gh_api_paginate", self._mock_paginate), \
             patch("build_graph._gh_api", self._mock_api):
            nodes, edges = fetch_github_graph_data(
                "test-owner", "test-repo",
            )

        edge_types = {e.type for e in edges}
        self.assertIn("closes", edge_types)
        self.assertIn("merged_into", edge_types)

        # Verify specific edges
        closes_357 = [
            e for e in edges
            if e.from_id == "issue-357" and e.type == "closes"
        ]
        self.assertEqual(len(closes_357), 1)
        self.assertEqual(closes_357[0].to_id, "pr-416")

    def test_since_filter_passed_to_query(self):
        """Verify that the since parameter is included in the search query."""
        mock_paginate = MagicMock(return_value=[])
        mock_api = MagicMock(return_value=None)

        with patch("build_graph._gh_api_paginate", mock_paginate), \
             patch("build_graph._gh_api", mock_api):
            fetch_github_graph_data(
                "test-owner", "test-repo", since="2026-06-01",
            )

        mock_paginate.assert_called_once()
        call_endpoint = self._decode(mock_paginate.call_args[0][0])
        self.assertIn(
            "merged:>=2026-06-01",
            call_endpoint,
            msg=f"since filter should be in endpoint, got: {call_endpoint}",
        )

    def test_without_since_no_date_filter(self):
        """Verify that without --since, no date filter is added."""
        mock_paginate = MagicMock(return_value=[])
        mock_api = MagicMock(return_value=None)

        with patch("build_graph._gh_api_paginate", mock_paginate), \
             patch("build_graph._gh_api", mock_api):
            fetch_github_graph_data(
                "test-owner", "test-repo", since=None,
            )

        mock_paginate.assert_called_once()
        call_endpoint = self._decode(mock_paginate.call_args[0][0])
        self.assertNotIn("merged:>=", call_endpoint)

    def test_empty_api_returns_empty(self):
        """When gh is not installed or API is unavailable, return empty."""
        nodes, edges = fetch_github_graph_data(
            "test-owner", "test-repo", since=None,
        )
        # Without mocking, _gh_api_paginate will try to call real gh and
        # either fail gracefully (FileNotFoundError) or return empty.
        # This test just verifies no crash.
        self.assertIsInstance(nodes, list)
        self.assertIsInstance(edges, list)


class TestDetectGithubOwnerRepo(unittest.TestCase):
    @patch("build_graph.subprocess.run")
    def test_from_git_remote(self, mock_run):
        mock_run.return_value.stdout = (
            "git@github.com:my-org/my-repo.git\n"
        )
        mock_run.return_value.returncode = 0
        owner, repo = _detect_github_owner_repo()
        self.assertEqual(owner, "my-org")
        self.assertEqual(repo, "my-repo")

    @patch("build_graph.subprocess.run")
    def test_from_git_remote_https(self, mock_run):
        mock_run.return_value.stdout = (
            "https://github.com/foo/bar.git\n"
        )
        mock_run.return_value.returncode = 0
        owner, repo = _detect_github_owner_repo()
        self.assertEqual(owner, "foo")
        self.assertEqual(repo, "bar")

    @patch("build_graph.subprocess.run")
    def test_git_not_found_falls_back(self, mock_run):
        mock_run.side_effect = FileNotFoundError("git not found")
        owner, repo = _detect_github_owner_repo()
        self.assertEqual(owner, "ai-issue-solver")
        self.assertEqual(repo, "ai-issue-solver")


class TestEnrichFromRuns(unittest.TestCase):
    def test_no_runs_dir_no_change(self):
        nodes = [Node(id="pr-1", type="pr", attrs={})]
        before = [n.attrs.copy() for n in nodes]
        enrich_from_runs(ROOT / "does_not_exist", nodes)
        after = [n.attrs.copy() for n in nodes]
        self.assertEqual(before, after)

    def test_real_runs_dir_adds_model(self):
        runs_dir = ROOT / "reports" / "runs"
        if not runs_dir.exists():
            self.skipTest("no reports/runs/ directory")
        nodes = [
            Node(id="pr-416", type="pr", attrs={}),
            Node(id="pr-419", type="pr", attrs={}),
        ]
        enrich_from_runs(runs_dir, nodes)
        models = [
            n.attrs.get("model") for n in nodes if n.attrs.get("model")
        ]
        self.assertTrue(
            len(models) > 0,
            f"expected at least one model; got {models}",
        )


class TestApplyColorBy(unittest.TestCase):
    def test_color_by_model_assigns_known_color(self):
        nodes = [Node(id="pr-1", type="pr", attrs={"model": "opencode"})]
        apply_color_by(nodes, "model")
        self.assertEqual(
            nodes[0].attrs.get("color"), _MODEL_COLORS["opencode"],
        )

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
        n1 = Node(id="issue-1", type="issue", attrs={"state": "open"})
        n2 = Node(
            id="issue-2", type="issue",
            attrs={"state": "done", "cost": 1.0, "loc_add": 50},
        )
        n3 = Node(
            id="issue-3", type="issue",
            attrs={"state": "done", "cost": 1.0, "loc_add": 800},
        )
        nodes = [n1, n2, n3]
        apply_color_by(nodes, "difficulty")
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
        self.assertEqual(_color_for_cost(10, 10), "#ef4444")

    def test_color_for_cost_no_max(self):
        self.assertEqual(_color_for_cost(5, 0), "#22c55e")

    def test_color_for_loc_no_max(self):
        self.assertEqual(_color_for_loc(100, 0), "#22c55e")

    def test_color_for_difficulty_unsolved(self):
        self.assertEqual(
            _color_for_difficulty(
                Node(id="x", type="issue", attrs={"state": "open"}),
            ),
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
            Node(
                id="issue-1", type="issue", title="Test",
                attrs={"color": "#22c55e"},
            ),
            Node(id="pr-1", type="pr", title="PR"),
        ]
        edges = [Edge(from_id="issue-1", to_id="pr-1", type="closes")]
        out = to_dot(nodes, edges)
        self.assertIn("digraph issue_network", out)
        self.assertIn('"issue-1"', out)
        self.assertIn('"pr-1"', out)
        self.assertIn('fillcolor="#22c55e"', out)
        self.assertIn("closes", out)


class TestEndToEndWithMockedApi(unittest.TestCase):
    """Run the full pipeline with mocked GitHub API and assert the
    resulting graph has the expected shape."""

    def _mock_paginate(self, endpoint: str) -> list:
        if "search/issues" in endpoint:
            return _SEARCH_RESULT["items"]
        return []

    def _mock_api(self, endpoint: str) -> dict | list | None:
        if "pulls/416" in endpoint:
            return _PR_416
        if "pulls/419" in endpoint:
            return _PR_419
        if "issues/357" in endpoint:
            return _ISSUE_357
        if "issues/418" in endpoint:
            return _ISSUE_418
        return None

    def test_full_pipeline_json(self):
        with patch("build_graph._gh_api_paginate", self._mock_paginate), \
             patch("build_graph._gh_api", self._mock_api):
            nodes: list[Node] = []
            nodes.extend(
                parse_open_backlog(ROOT / "docs" / "BACKLOG" / "open.md"),
            )
            gh_nodes, gh_edges = fetch_github_graph_data(
                "test-owner", "test-repo",
            )
            nodes.extend(gh_nodes)
            enrich_from_runs(ROOT / "reports" / "runs", nodes)

        out = to_json(nodes, gh_edges)
        parsed = json.loads(out)

        issue_count = sum(1 for n in parsed["nodes"] if n["type"] == "issue")
        pr_count = sum(1 for n in parsed["nodes"] if n["type"] == "pr")
        self.assertGreaterEqual(issue_count, 2)
        self.assertGreaterEqual(pr_count, 2)
        self.assertGreaterEqual(len(parsed["edges"]), 2)
        known = {"closes", "merged_into", "parent_of"}
        for e in parsed["edges"]:
            self.assertIn(e["type"], known)

    def test_full_pipeline_dot(self):
        with patch("build_graph._gh_api_paginate", self._mock_paginate), \
             patch("build_graph._gh_api", self._mock_api):
            nodes: list[Node] = [
                Node(id="issue-1", type="issue", title="Test"),
            ]
            gh_nodes, gh_edges = fetch_github_graph_data(
                "test-owner", "test-repo",
            )
            nodes.extend(gh_nodes)
            apply_color_by(nodes, "model")
            out = to_dot(nodes, gh_edges)
        self.assertIn("digraph", out)
        self.assertIn("->", out)


if __name__ == "__main__":
    unittest.main()
