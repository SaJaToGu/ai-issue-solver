"""Unit tests for build_graph.py.

The script reads from:
- the local open.md backlog (no network)
- the GitHub API via ``gh api`` subprocess calls
- local reports/runs/*/metadata.json files

Tests mock ``subprocess.run`` at the boundary so the GitHub
subprocess path is exercised without actually shelling out.
File-fixture tests are used only for the parse_open_backlog
path (which has no GitHub equivalent).
"""

from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

# Add scripts/ to path so we can import build_graph as a module
ROOT = Path(__file__).resolve().parents[1]  # tests/ → repo root
sys.path.insert(0, str(ROOT / "scripts"))

from build_graph import (  # noqa: E402
    Node,
    Edge,
    parse_open_backlog,
    fetch_github_graph_data,
    _gh_api,
    _detect_github_owner_repo,
    _extract_issue_refs,
    _is_solver_produced,
    _validate_since,
    enrich_from_runs,
    apply_color_by,
    to_json,
    to_dot,
    _color_for_cost,
    _color_for_loc,
    _color_for_difficulty,
    _MODEL_COLORS,
)


# --------------------------------------------------------------------------- #
# subprocess.run fake — lets each test register a queue of (cmd-matcher,       #
# stdout, returncode, stderr) responses.                                       #
# --------------------------------------------------------------------------- #


class _FakeProc:
    def __init__(self, returncode: int, stdout: str = "", stderr: str = ""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class _FakeRunner:
    """Drop-in replacement for subprocess.run that serves
    pre-registered responses in order. Each entry is a tuple
    ``(predicate, response)`` where ``predicate(cmd)`` returns
    True for the matching command. The longest-substring match
    wins (most specific predicate first); if no entry matches,
    raises AssertionError to surface the gap in test fixtures.
    """

    def __init__(self):
        self.responses: list[tuple[callable, _FakeProc]] = []
        self._substrings: list[str] = []
        self.calls: list[list[str]] = []

    def push(self, cmd_substring: str, *, returncode: int = 0, stdout: str = "", stderr: str = ""):
        """Register a response that matches any command containing
        ``cmd_substring``."""
        proc = _FakeProc(returncode=returncode, stdout=stdout, stderr=stderr)
        self.responses.append(
            (lambda cmd, sub=cmd_substring: sub in " ".join(cmd), proc)
        )
        self._substrings.append(cmd_substring)
        return self

    def push_json(self, cmd_substring: str, payload):
        return self.push(cmd_substring, stdout=json.dumps(payload))

    def push_many(self, cmd_substring: str, payloads: list):
        """Register one response per payload, each matching the
        same substring. They are consumed in order."""
        for p in payloads:
            self.push_json(cmd_substring, p)
        return self

    def __call__(self, cmd, *args, **kwargs):
        self.calls.append(list(cmd))
        # Longest-substring match wins: more specific predicates
        # (e.g. "issues/400/comments") match before generic ones
        # (e.g. "issues"). This avoids ambiguity when both
        # predicates match the same call.
        matches: list[tuple[int, int, _FakeProc]] = []
        for idx, (predicate, proc) in enumerate(self.responses):
            if predicate(cmd):
                matches.append((-len(self._substrings[idx]), idx, proc))
        if not matches:
            raise AssertionError(
                f"_FakeRunner: no response registered for command: {cmd}"
            )
        matches.sort()
        _, idx, proc = matches[0]
        self.responses.pop(idx)
        self._substrings.pop(idx)
        return proc


# --------------------------------------------------------------------------- #
# Open backlog parsing (still file-based)                                      #
# --------------------------------------------------------------------------- #


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


# --------------------------------------------------------------------------- #
# _gh_api (subprocess wrapper)                                                #
# --------------------------------------------------------------------------- #


class TestGhApi(unittest.TestCase):
    def test_returns_parsed_json_list(self):
        runner = _FakeRunner().push_json("gh api", [{"id": 1}, {"id": 2}])
        with patch("build_graph.subprocess.run", runner):
            result = _gh_api("/repos/owner/repo/issues")
        self.assertEqual(result, [{"id": 1}, {"id": 2}])

    def test_returns_parsed_json_dict(self):
        runner = _FakeRunner().push_json("gh api", {"name": "test", "value": 42})
        with patch("build_graph.subprocess.run", runner):
            result = _gh_api("/repos/owner/repo")
        self.assertEqual(result, {"name": "test", "value": 42})

    def test_empty_stdout_returns_empty_list(self):
        runner = _FakeRunner().push("gh api", stdout="")
        with patch("build_graph.subprocess.run", runner):
            result = _gh_api("/repos/owner/repo/issues?per_page=0")
        self.assertEqual(result, [])

    def test_raises_on_nonzero_exit(self):
        runner = _FakeRunner().push("gh api", returncode=1, stderr="401 Unauthorized")
        with patch("build_graph.subprocess.run", runner):
            with self.assertRaises(RuntimeError) as cm:
                _gh_api("/repos/owner/repo/issues")
        self.assertIn("401 Unauthorized", str(cm.exception))

    def test_raises_on_non_json_output(self):
        runner = _FakeRunner().push("gh api", stdout="<html>not json</html>")
        with patch("build_graph.subprocess.run", runner):
            with self.assertRaises(RuntimeError) as cm:
                _gh_api("/repos/owner/repo/issues")
        self.assertIn("non-JSON", str(cm.exception))

    def test_passes_params_as_query_string(self):
        runner = _FakeRunner().push_json("gh api", [])
        with patch("build_graph.subprocess.run", runner):
            _gh_api("/repos/owner/repo/issues", state="closed", per_page="50")
        # Last call should be ['gh', 'api', '/repos/owner/repo/issues?state=closed&per_page=50']
        cmd = runner.calls[-1]
        self.assertEqual(cmd[0], "gh")
        self.assertEqual(cmd[1], "api")
        url = cmd[2]
        self.assertIn("state=closed", url)
        self.assertIn("per_page=50", url)
        # URL-encoded query string, not -f
        self.assertNotIn("-f", cmd)
        self.assertTrue(url.startswith("/repos/owner/repo/issues?"))


# --------------------------------------------------------------------------- #
# _detect_github_owner_repo                                                    #
# --------------------------------------------------------------------------- #


class TestDetectGithubOwnerRepo(unittest.TestCase):
    def test_from_git_remote_https(self):
        runner = _FakeRunner().push(
            "git remote get-url origin",
            stdout="https://github.com/SaJaToGu/ai-issue-solver.git",
        )
        with patch("build_graph.subprocess.run", runner):
            result = _detect_github_owner_repo()
        self.assertEqual(result, ("SaJaToGu", "ai-issue-solver"))

    def test_from_git_remote_ssh(self):
        runner = _FakeRunner().push(
            "git remote get-url origin",
            stdout="git@github.com:SaJaToGu/ai-issue-solver.git",
        )
        with patch("build_graph.subprocess.run", runner):
            result = _detect_github_owner_repo()
        self.assertEqual(result, ("SaJaToGu", "ai-issue-solver"))

    def test_from_git_remote_no_dot_git(self):
        runner = _FakeRunner().push(
            "git remote get-url origin",
            stdout="https://github.com/Owner/Repo",
        )
        with patch("build_graph.subprocess.run", runner):
            result = _detect_github_owner_repo()
        self.assertEqual(result, ("Owner", "Repo"))

    def test_git_not_found_returns_none(self):
        def fake_run(*args, **kwargs):
            raise FileNotFoundError("git not found")
        with patch("build_graph.subprocess.run", side_effect=fake_run):
            result = _detect_github_owner_repo()
        self.assertIsNone(result)

    def test_git_failure_returns_none(self):
        runner = _FakeRunner().push("git remote get-url origin", returncode=1, stdout="")
        with patch("build_graph.subprocess.run", runner):
            result = _detect_github_owner_repo()
        self.assertIsNone(result)


# --------------------------------------------------------------------------- #
# _extract_issue_refs (PR body / comment parser)                              #
# --------------------------------------------------------------------------- #


class TestExtractIssueRefs(unittest.TestCase):
    def test_closes_keyword(self):
        self.assertEqual(_extract_issue_refs("This PR closes #123."), [123])

    def test_fixes_keyword(self):
        self.assertEqual(_extract_issue_refs("Fixes #42"), [42])

    def test_resolves_keyword(self):
        self.assertEqual(_extract_issue_refs("resolves #7"), [7])

    def test_refs_keyword(self):
        # "Refs #N" is the ai-issue-solver solver-PR pattern. Without
        # this, ~55% of closes-edges in this repo are dropped.
        self.assertEqual(_extract_issue_refs("Refs #425: build_graph.py"), [425])

    def test_issue_keyword(self):
        # "Issue #N" appears in older PR bodies (label / URL form).
        self.assertEqual(_extract_issue_refs("Issue: #318 — see also issue #320"), [318, 320])

    def test_see_keyword(self):
        self.assertEqual(_extract_issue_refs("See #55 for context"), [55])

    def test_implements_keyword(self):
        self.assertEqual(_extract_issue_refs("Implements #100"), [100])

    def test_no_match(self):
        self.assertEqual(_extract_issue_refs("Just a regular PR body."), [])

    def test_multiple_refs(self):
        self.assertEqual(
            _extract_issue_refs("Closes #1, fixes #2, part of #3"),
            [1, 2, 3],
        )

    def test_refs_with_other_refs(self):
        # Mixed patterns in one body — the common ai-issue-solver case
        # where a PR refs an issue and closes another. The output is
        # sorted numerically, so order in the input does not matter.
        self.assertEqual(
            sorted(_extract_issue_refs("Refs #425: build_graph. Closes #1.")),
            [1, 425],
        )

    def test_parent_line(self):
        self.assertEqual(
            _extract_issue_refs("Some intro\n\nParent: #99\nMore text"),
            [99],
        )

    def test_dedup(self):
        self.assertEqual(
            _extract_issue_refs("Closes #5. Also closes #5."),
            [5],
        )

    def test_none_input(self):
        self.assertEqual(_extract_issue_refs(None), [])


# --------------------------------------------------------------------------- #
# _is_solver_produced (PR author / label heuristic)                           #
# --------------------------------------------------------------------------- #


class TestIsSolverProduced(unittest.TestCase):
    def test_ai_issue_solver_user(self):
        pr = {"user": {"login": "ai-issue-solver[bot]"}, "labels": []}
        self.assertTrue(_is_solver_produced(pr))

    def test_ai_issue_solver_login_plain(self):
        pr = {"user": {"login": "ai-issue-solver"}, "labels": []}
        self.assertTrue(_is_solver_produced(pr))

    def test_ai_generated_label(self):
        pr = {"user": {"login": "guido"}, "labels": [{"name": "ai-generated"}]}
        self.assertTrue(_is_solver_produced(pr))

    def test_human_user_no_label(self):
        pr = {"user": {"login": "guido"}, "labels": []}
        self.assertFalse(_is_solver_produced(pr))

    def test_no_user_field(self):
        pr = {"labels": []}
        self.assertFalse(_is_solver_produced(pr))


# --------------------------------------------------------------------------- #
# _validate_since (argparse type=)                                            #
# --------------------------------------------------------------------------- #


class TestValidateSince(unittest.TestCase):
    def test_valid_date(self):
        # YYYY-MM-DD is accepted and expanded to the ISO 8601 form
        # that the GitHub API requires.
        self.assertEqual(_validate_since("2026-06-24"), "2026-06-24T00:00:00Z")

    def test_valid_iso_passthrough(self):
        # Full ISO 8601 with time + Z is accepted as-is.
        self.assertEqual(
            _validate_since("2026-06-24T12:30:00Z"),
            "2026-06-24T12:30:00Z",
        )

    def test_invalid_format_raises(self):
        import argparse
        with self.assertRaises(argparse.ArgumentTypeError):
            _validate_since("06/24/2026")

    def test_short_string_raises(self):
        import argparse
        with self.assertRaises(argparse.ArgumentTypeError):
            _validate_since("2026-6-24")


# --------------------------------------------------------------------------- #
# fetch_github_graph_data (the main GitHub-native path)                       #
# --------------------------------------------------------------------------- #


def _make_pr_listing(pr_numbers: list[int], since: str | None = None) -> list[dict]:
    """Build a /issues?state=closed listing response. Each item
    carries a ``pull_request`` key so the parser picks it up as a
    PR (not a plain issue)."""
    items = []
    for n in pr_numbers:
        items.append({
            "number": n,
            "title": f"PR #{n}",
            "state": "closed",
            "pull_request": {"url": f"https://api.github.com/repos/o/r/pulls/{n}"},
        })
    return items


def _make_pr_full(
    pr_num: int,
    *,
    body: str = "Closes #1",
    head_ref: str = "feature/branch",
    head_sha: str = "abc123def456789",
    merged_at: str | None = "2026-06-20T10:00:00Z",
    additions: int = 50,
    deletions: int = 10,
    changed_files: int = 3,
    author_login: str = "ai-issue-solver[bot]",
    labels: list[dict] | None = None,
) -> dict:
    return {
        "number": pr_num,
        "title": f"PR #{pr_num}",
        "body": body,
        "head": {"ref": head_ref, "sha": head_sha},
        "merged_at": merged_at,
        "additions": additions,
        "deletions": deletions,
        "changed_files": changed_files,
        "user": {"login": author_login},
        "labels": labels if labels is not None else [{"name": "ai-generated"}],
    }


class TestFetchGitHubGraphData(unittest.TestCase):
    def test_returns_nodes_and_edges(self):
        runner = _FakeRunner()
        # 1) /issues listing
        runner.push_json(
            "issues",
            _make_pr_listing([100, 101, 102]),
        )
        # 2) three /pulls/N responses
        runner.push_json("pulls/100", _make_pr_full(100, body="Closes #1", head_sha="aaa111"))
        runner.push_json("pulls/101", _make_pr_full(101, body="Fixes #2", head_sha="bbb222"))
        runner.push_json("pulls/102", _make_pr_full(102, body="Resolves #3", head_sha="ccc333"))
        # 3) comments for each PR
        runner.push_json("issues/100/comments", [])
        runner.push_json("issues/101/comments", [])
        runner.push_json("issues/102/comments", [])

        with patch("build_graph.subprocess.run", runner):
            nodes, edges = fetch_github_graph_data("owner", "repo")

        ids = {n.id for n in nodes}
        # PRs and commits
        self.assertIn("pr-100", ids)
        self.assertIn("pr-101", ids)
        self.assertIn("pr-102", ids)
        self.assertIn("commit-aaa111", ids)
        self.assertIn("commit-bbb222", ids)
        self.assertIn("commit-ccc333", ids)

        # Closes edges from issue → PR
        closes = {e.to_id: e.from_id for e in edges if e.type == "closes"}
        self.assertEqual(closes.get("pr-100"), "issue-1")
        self.assertEqual(closes.get("pr-101"), "issue-2")
        self.assertEqual(closes.get("pr-102"), "issue-3")

        # merged_into edges
        merged = {e.from_id: e.to_id for e in edges if e.type == "merged_into"}
        self.assertEqual(merged.get("pr-100"), "commit-aaa111")
        self.assertEqual(merged.get("pr-101"), "commit-bbb222")
        self.assertEqual(merged.get("pr-102"), "commit-ccc333")

        # PR attributes: loc_add, loc_del, files, ai_generated
        pr100 = next(n for n in nodes if n.id == "pr-100")
        self.assertEqual(pr100.attrs.get("loc_add"), 50)
        self.assertEqual(pr100.attrs.get("loc_del"), 10)
        self.assertEqual(pr100.attrs.get("files"), 3)
        self.assertTrue(pr100.attrs.get("ai_generated"))
        self.assertEqual(pr100.attrs.get("state"), "merged")

    def test_pr_body_comment_refs_combined(self):
        """Issue refs from BOTH the PR body AND the PR comments
        should be picked up."""
        runner = _FakeRunner()
        runner.push_json("issues", _make_pr_listing([200]))
        runner.push_json("pulls/200", _make_pr_full(200, body="", head_sha="def456"))
        runner.push_json(
            "issues/200/comments",
            [{"body": "Retrospective: also closes #55"}],
        )

        with patch("build_graph.subprocess.run", runner):
            nodes, edges = fetch_github_graph_data("o", "r")

        closes = {e.to_id: e.from_id for e in edges if e.type == "closes"}
        self.assertEqual(closes.get("pr-200"), "issue-55")

    def test_unmerged_pr_has_no_commit_edge(self):
        runner = _FakeRunner()
        runner.push_json("issues", _make_pr_listing([300]))
        runner.push_json("pulls/300", _make_pr_full(300, head_sha="eee789", merged_at=None))
        runner.push_json("issues/300/comments", [])

        with patch("build_graph.subprocess.run", runner):
            nodes, edges = fetch_github_graph_data("o", "r")

        # No merged_into edge (since not merged), no commit node
        merged = [e for e in edges if e.type == "merged_into"]
        self.assertEqual(len(merged), 0)
        pr300 = next(n for n in nodes if n.id == "pr-300")
        self.assertEqual(pr300.attrs.get("state"), "closed")
        self.assertIsNone(pr300.attrs.get("merged_at"))

    def test_human_pr_not_marked_ai_generated(self):
        runner = _FakeRunner()
        runner.push_json("issues", _make_pr_listing([400]))
        runner.push_json(
            "pulls/400",
            _make_pr_full(400, head_sha="fff000", author_login="guido", labels=[]),
        )
        runner.push_json("issues/400/comments", [])

        with patch("build_graph.subprocess.run", runner):
            nodes, _ = fetch_github_graph_data("o", "r")

        pr400 = next(n for n in nodes if n.id == "pr-400")
        self.assertFalse(pr400.attrs.get("ai_generated"))

    def test_since_filter_passed_to_query(self):
        runner = _FakeRunner()
        # Empty listing — we only need to verify the call shape.
        runner.push_json("issues", [])
        with patch("build_graph.subprocess.run", runner):
            fetch_github_graph_data("o", "r", since="2026-06-01T00:00:00Z")
        # First /issues call should include the since filter in the URL query string.
        # urlencode percent-encodes the colons in the timestamp.
        from urllib.parse import quote
        encoded = quote("2026-06-01T00:00:00Z", safe="")
        issues_call = next(c for c in runner.calls if "/issues" in c[2] and "/repos" in c[2])
        self.assertIn(f"since={encoded}", issues_call[2])

    def test_without_since_no_date_filter(self):
        runner = _FakeRunner()
        runner.push_json("issues", [])
        with patch("build_graph.subprocess.run", runner):
            fetch_github_graph_data("o", "r")
        issues_call = next(c for c in runner.calls if "/issues" in " ".join(c) and "/repos" in " ".join(c))
        self.assertNotIn("since", " ".join(issues_call))

    def test_gh_api_unavailable_returns_empty(self):
        """When gh is not installed / not authenticated, the
        function returns ([], []) so the rest of the pipeline
        degrades to 'open issues only' rather than crashing."""
        def fake_run(*args, **kwargs):
            raise FileNotFoundError("gh not found")
        with patch("build_graph.subprocess.run", side_effect=fake_run):
            nodes, edges = fetch_github_graph_data("o", "r")
        self.assertEqual(nodes, [])
        self.assertEqual(edges, [])

    def test_empty_api_returns_empty(self):
        runner = _FakeRunner().push_json("issues", [])
        with patch("build_graph.subprocess.run", runner):
            nodes, edges = fetch_github_graph_data("o", "r")
        self.assertEqual(nodes, [])
        self.assertEqual(edges, [])


# --------------------------------------------------------------------------- #
# Cost enrichment from run-reports                                            #
# --------------------------------------------------------------------------- #


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


# --------------------------------------------------------------------------- #
# Color-by                                                                    #
# --------------------------------------------------------------------------- #


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


# --------------------------------------------------------------------------- #
# Output formats                                                              #
# --------------------------------------------------------------------------- #


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


# --------------------------------------------------------------------------- #
# End-to-end with mocked GitHub API                                           #
# --------------------------------------------------------------------------- #


class TestEndToEndWithMockedApi(unittest.TestCase):
    """Run the full pipeline with a fake GitHub API and assert
    the resulting graph has the expected shape."""

    def test_full_pipeline_json(self):
        runner = _FakeRunner()
        # Open backlog (no subprocess) + 3 closed PRs.
        runner.push_json(
            "issues",
            _make_pr_listing([500, 501, 502]),
        )
        runner.push_json("pulls/500", _make_pr_full(500, body="Closes #1", head_sha="sha500"))
        runner.push_json("pulls/501", _make_pr_full(501, body="Fixes #2", head_sha="sha501"))
        runner.push_json("pulls/502", _make_pr_full(502, body="Resolves #3", head_sha="sha502"))
        runner.push_json("issues/500/comments", [])
        runner.push_json("issues/501/comments", [])
        runner.push_json("issues/502/comments", [])

        with patch("build_graph.subprocess.run", runner):
            nodes = []
            nodes.extend(parse_open_backlog(ROOT / "docs" / "BACKLOG" / "open.md"))
            gh_nodes, gh_edges = fetch_github_graph_data("owner", "repo")
            nodes.extend(gh_nodes)
            edges: list[Edge] = list(gh_edges)
            enrich_from_runs(ROOT / "reports" / "runs", nodes)
            out = to_json(nodes, edges)
        parsed = json.loads(out)
        # At least 3 PR nodes, 3 commit nodes from the mock
        pr_count = sum(1 for n in parsed["nodes"] if n["type"] == "pr")
        commit_count = sum(1 for n in parsed["nodes"] if n["type"] == "commit")
        self.assertGreaterEqual(pr_count, 3)
        self.assertGreaterEqual(commit_count, 3)
        # Closes edges present
        closes = [e for e in parsed["edges"] if e["type"] == "closes"]
        self.assertGreaterEqual(len(closes), 3)
        # merged_into edges present
        merged = [e for e in parsed["edges"] if e["type"] == "merged_into"]
        self.assertEqual(len(merged), 3)
        # All edges are one of the known types
        known = {"closes", "merged_into", "parent_of"}
        for e in parsed["edges"]:
            self.assertIn(e["type"], known)

    def test_full_pipeline_dot(self):
        runner = _FakeRunner()
        runner.push_json("issues", _make_pr_listing([600]))
        runner.push_json("pulls/600", _make_pr_full(600, head_sha="sha600", labels=[{"name": "ai-generated"}]))
        runner.push_json("issues/600/comments", [])

        with patch("build_graph.subprocess.run", runner):
            nodes = []
            nodes.extend(parse_open_backlog(ROOT / "docs" / "BACKLOG" / "open.md"))
            gh_nodes, gh_edges = fetch_github_graph_data("owner", "repo")
            nodes.extend(gh_nodes)
            apply_color_by(nodes, "model")
            out = to_dot(nodes, gh_edges)
        self.assertIn("digraph", out)
        self.assertIn("->", out)
        # At least one PR has a color
        self.assertIn('fillcolor=', out)


if __name__ == "__main__":
    unittest.main()
