#!/usr/bin/env python3
"""
Tests for the Reviewer Runtime (scripts/review_pr.py).

This is the infrastructure for the 0.9.0 Solver Validation run (issue #325).
It is intentionally NOT a test of the Solver itself — that is the role of
#326's real `solve_issues.py` run with a real `reports/runs/.../summary.txt`.
"""

from __future__ import annotations

import contextlib
import io
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import review_pr  # noqa: E402
from review_pr import (  # noqa: E402
    ROLE_ALIASES,
    REVIEWER_PROMPT_FILES,
    VALID_VERDICTS,
    PullRequestNotFoundError,
    ReviewerRoleError,
    ReviewerVerdict,
    call_openrouter,
    fetch_pull_request_diff,
    load_prompt,
    parse_args,
    parse_verdict,
    resolve_role,
    run_review,
)


# ── Helpers ─────────────────────────────────────────────────────────

def _real_config() -> dict:
    """Load the real config/role_routing.yaml for tests."""
    from role_routing_loader import load_role_config
    return load_role_config()


def _role_for(role_arg: str) -> dict:
    """Resolve a role using the real config."""
    return resolve_role(role_arg, _real_config())


# ── Constants ──────────────────────────────────────────────────────

class ConstantsTests(unittest.TestCase):
    """The 3 reviewer aliases and prompt files must stay in sync."""

    def test_role_aliases_cover_the_three_reviewer_paths(self):
        self.assertEqual(
            set(ROLE_ALIASES.keys()),
            {"code", "architecture", "documentation"},
        )

    def test_role_aliases_point_to_role_routing_yaml_keys(self):
        self.assertEqual(ROLE_ALIASES["code"], "reviewer_code")
        self.assertEqual(ROLE_ALIASES["architecture"], "reviewer_architecture")
        self.assertEqual(ROLE_ALIASES["documentation"], "reviewer_documentation")

    def test_reviewer_prompt_files_match_the_three_known_prompts(self):
        self.assertEqual(
            set(REVIEWER_PROMPT_FILES.keys()),
            {"reviewer_code", "reviewer_architecture", "reviewer_documentation"},
        )

    def test_review_prompt_files_exist_on_disk(self):
        # The runtime depends on these files being there. If a path drifts
        # (rename, move) we want a clear test failure, not a runtime crash.
        for role_name, rel_path in REVIEWER_PROMPT_FILES.items():
            with self.subTest(role=role_name):
                self.assertTrue(
                    (ROOT / rel_path).is_file(),
                    f"prompt file for {role_name} missing at {rel_path}",
                )


# ── Role resolution ───────────────────────────────────────────────

class ResolveRoleTests(unittest.TestCase):
    """Mapping from --role arg to role_routing.yaml entry."""

    def test_code_resolves_to_reviewer_code(self):
        role = _role_for("code")
        self.assertEqual(role["_name"], "reviewer_code")
        self.assertIn("model", role)
        self.assertIn("provider", role)

    def test_architecture_resolves_to_reviewer_architecture(self):
        role = _role_for("architecture")
        self.assertEqual(role["_name"], "reviewer_architecture")

    def test_documentation_resolves_to_reviewer_documentation(self):
        role = _role_for("documentation")
        self.assertEqual(role["_name"], "reviewer_documentation")

    def test_unknown_role_raises(self):
        with self.assertRaisesRegex(ReviewerRoleError, "unknown role 'banana'"):
            resolve_role("banana", _real_config())

    def test_role_missing_from_config_raises(self):
        # Build a config that does not contain reviewer_code
        from role_routing_loader import load_role_config
        minimal = load_role_config()
        minimal["roles"].pop("reviewer_code", None)
        with self.assertRaisesRegex(ReviewerRoleError, "reviewer_code"):
            resolve_role("code", minimal)


# ── Prompt loading ─────────────────────────────────────────────────

class LoadPromptTests(unittest.TestCase):
    """The role's prompt_file field is honored, the prompt text is loaded."""

    def test_loads_real_reviewer_code_prompt(self):
        prompt = load_prompt(_role_for("code"))
        self.assertIn("Code Review", prompt)
        self.assertIn("**Verdict**", prompt)

    def test_loads_real_reviewer_architecture_prompt(self):
        prompt = load_prompt(_role_for("architecture"))
        self.assertIn("Architecture Review", prompt)
        self.assertIn("**Verdict**", prompt)

    def test_loads_real_reviewer_documentation_prompt(self):
        prompt = load_prompt(_role_for("documentation"))
        self.assertIn("Documentation Review", prompt)
        self.assertIn("**Verdict**", prompt)

    def test_role_without_prompt_file_raises(self):
        role = _role_for("code")
        role.pop("prompt_file", None)
        with self.assertRaisesRegex(ReviewerRoleError, "no 'prompt_file' field"):
            load_prompt(role)

    def test_missing_prompt_file_raises(self):
        role = _role_for("code")
        role["prompt_file"] = "does/not/exist.md"
        with self.assertRaisesRegex(ReviewerRoleError, "cannot read prompt file"):
            load_prompt(role)


# ── Verdict parsing ───────────────────────────────────────────────

class ParseVerdictTests(unittest.TestCase):
    """The **Verdict**: <value> line is required by the prompt schema."""

    def test_parses_approve(self):
        self.assertEqual(
            parse_verdict("Some text\n\n**Verdict**: approve\n\nMore text"),
            "approve",
        )

    def test_parses_request_changes(self):
        self.assertEqual(
            parse_verdict("**Verdict**: request changes\n"),
            "request changes",
        )

    def test_parses_comment(self):
        self.assertEqual(
            parse_verdict("**Verdict**: comment"),
            "comment",
        )

    def test_handles_extra_whitespace(self):
        self.assertEqual(
            parse_verdict("**Verdict**:   approve  "),
            "approve",
        )

    def test_is_case_insensitive(self):
        self.assertEqual(parse_verdict("**Verdict**: APPROVE"), "approve")
        self.assertEqual(parse_verdict("**Verdict**: Request Changes"), "request changes")

    def test_returns_none_when_no_verdict_line(self):
        self.assertIsNone(parse_verdict("Some text without any verdict"))
        self.assertIsNone(parse_verdict(""))
        self.assertIsNone(parse_verdict(None))

    def test_returns_none_for_unrecognized_verdict_value(self):
        # LLM hallucinated a value not in the schema; treat as missing.
        self.assertIsNone(parse_verdict("**Verdict**: maybe"))

    def test_all_valid_verdicts_are_in_the_documented_set(self):
        # Legacy verdicts (approve/request changes/comment) coexist
        # with the new code-reviewer verdicts (ready to merge/
        # needs work/discuss) introduced by the prompt-reframe PR.
        self.assertEqual(
            set(VALID_VERDICTS),
            {
                "approve", "request changes", "comment",
                "ready to merge", "needs work", "discuss",
            },
        )


# ── GitHub PR diff fetch ──────────────────────────────────────────

class FetchPullRequestDiffTests(unittest.TestCase):
    """Diff is fetched via the GitHub API; 404 is treated as PR-not-found."""

    def _mock_response(self, status_code: int, text: str = "") -> MagicMock:
        resp = MagicMock()
        resp.status_code = status_code
        resp.text = text
        resp.raise_for_status = MagicMock()
        if status_code >= 400:
            import requests
            resp.raise_for_status.side_effect = requests.HTTPError(f"{status_code}")
        return resp

    def test_returns_diff_on_200(self):
        diff_body = "diff --git a/foo b/foo\n+hello\n"
        session = MagicMock()
        session.get.return_value = self._mock_response(200, diff_body)
        result = fetch_pull_request_diff(
            "SaJaToGu", "ai-issue-solver", 321, token="t", _session=session
        )
        self.assertEqual(result, diff_body)

    def test_404_raises_pull_request_not_found(self):
        session = MagicMock()
        session.get.return_value = self._mock_response(404)
        with self.assertRaisesRegex(
            PullRequestNotFoundError, "PR #321 not found"
        ):
            fetch_pull_request_diff(
                "SaJaToGu", "ai-issue-solver", 321, token="t", _session=session
            )

    def test_500_propagates_http_error(self):
        session = MagicMock()
        session.get.return_value = self._mock_response(500)
        import requests
        with self.assertRaises(requests.HTTPError):
            fetch_pull_request_diff(
                "SaJaToGu", "ai-issue-solver", 321, token="t", _session=session
            )

    def test_uses_diff_accept_header(self):
        session = MagicMock()
        session.get.return_value = self._mock_response(200, "diff --git x")
        fetch_pull_request_diff(
            "SaJaToGu", "ai-issue-solver", 321, token="gh_tok", _session=session
        )
        kwargs = session.get.call_args.kwargs
        self.assertEqual(
            kwargs["headers"]["Accept"], "application/vnd.github.v3.diff"
        )
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer gh_tok")

    def test_no_token_skips_authorization_header(self):
        session = MagicMock()
        session.get.return_value = self._mock_response(200, "diff")
        fetch_pull_request_diff(
            "SaJaToGu", "ai-issue-solver", 321, token=None, _session=session
        )
        self.assertNotIn("Authorization", session.get.call_args.kwargs["headers"])

    def test_huge_diff_is_truncated_with_marker(self):
        # Build a diff larger than MAX_DIFF_CHARS
        big = "diff --git a/foo b/foo\n" + ("+line\n" * 50_000)
        self.assertGreater(len(big), review_pr.MAX_DIFF_CHARS)
        session = MagicMock()
        session.get.return_value = self._mock_response(200, big)
        result = fetch_pull_request_diff(
            "SaJaToGu", "ai-issue-solver", 321, token=None, _session=session
        )
        self.assertIn("[truncated", result)
        # Truncated output must still be <= MAX_DIFF_CHARS + a small marker
        self.assertLess(len(result), review_pr.MAX_DIFF_CHARS + 200)


# ── OpenRouter call ───────────────────────────────────────────────

class CallOpenRouterTests(unittest.TestCase):
    """chat/completions is called with system + user messages; response
    is parsed back to assistant text."""

    def _mock_completions_response(self, content: str) -> MagicMock:
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json.return_value = {
            "choices": [{"message": {"content": content}}]
        }
        return resp

    def test_returns_assistant_content_on_success(self):
        session = MagicMock()
        session.post.return_value = self._mock_completions_response(
            "## Code Review\n\n**Verdict**: approve\n"
        )
        out = call_openrouter(
            system_prompt="sys",
            user_prompt="usr",
            model="anthropic/claude-sonnet-4",
            token="or_key",
            _session=session,
        )
        self.assertIn("**Verdict**: approve", out)

    def test_uses_model_from_role_config_not_hardcoded(self):
        # The call must put the role's model in the request payload, not
        # the test's hardcoded string. Pass two different models and
        # verify the request payload uses the role's value.
        session = MagicMock()
        session.post.return_value = self._mock_completions_response("ok")
        call_openrouter(
            system_prompt="s", user_prompt="u",
            model="openai/gpt-5",  # this is what gets sent
            token="t", _session=session,
        )
        payload = session.post.call_args.kwargs["json"]
        self.assertEqual(payload["model"], "openai/gpt-5")

    def test_missing_token_raises(self):
        with self.assertRaisesRegex(ValueError, "OPENROUTER_API_KEY is not set"):
            call_openrouter("s", "u", "m", token=None)

    def test_http_error_propagates(self):
        session = MagicMock()
        session.post.return_value = MagicMock(
            raise_for_status=MagicMock(side_effect=Exception("boom"))
        )
        with self.assertRaises(Exception):
            call_openrouter("s", "u", "m", token="t", _session=session)

    def test_missing_choices_raises_value_error(self):
        session = MagicMock()
        session.post.return_value = MagicMock(
            raise_for_status=MagicMock(),
            json=MagicMock(return_value={"choices": []}),
        )
        with self.assertRaisesRegex(ValueError, "no choices"):
            call_openrouter("s", "u", "m", token="t", _session=session)

    def test_missing_message_content_raises_value_error(self):
        session = MagicMock()
        session.post.return_value = MagicMock(
            raise_for_status=MagicMock(),
            json=MagicMock(return_value={"choices": [{"message": {}}]}),
        )
        with self.assertRaisesRegex(ValueError, "missing message content"):
            call_openrouter("s", "u", "m", token="t", _session=session)


# ── End-to-end runner ─────────────────────────────────────────────

class RunReviewTests(unittest.TestCase):
    """run_review stitches resolve_role + load_prompt + diff + LLM + parse."""

    SAMPLE_VERDICT_TEXT = (
        "## Code Review\n\n"
        "**Verdict**: request changes\n\n"
        "### Findings\n"
        "- [blocker] src/x.py:42 -- this is broken\n"
    )

    def _stub_diff_fetcher(self, diff: str = "diff --git a/x b/x\n+hi\n"):
        return lambda owner, repo, pr, token=None, **kw: diff

    def _stub_openrouter_call(self, text: str = None):
        if text is None:
            text = self.SAMPLE_VERDICT_TEXT
        return lambda **kw: text

    def test_happy_path_code_role(self):
        v = run_review(
            pr_number=321,
            role_arg="code",
            openrouter_token="or_key",
            config=_real_config(),
            openrouter_call=self._stub_openrouter_call(),
            diff_fetcher=self._stub_diff_fetcher(),
        )
        # run_review now returns a ReviewResult; verdict is nested.
        self.assertEqual(v.verdict.role_name, "reviewer_code")
        self.assertEqual(v.verdict.pr_number, 321)
        self.assertEqual(v.verdict.verdict, "request changes")
        self.assertIn("blocker", v.verdict.raw_text)

    def test_happy_path_architecture_role(self):
        v = run_review(
            pr_number=42,
            role_arg="architecture",
            openrouter_token="or_key",
            config=_real_config(),
            openrouter_call=self._stub_openrouter_call(
                "## Architecture Review\n\n**Verdict**: comment\n"
            ),
            diff_fetcher=self._stub_diff_fetcher(),
        )
        self.assertEqual(v.verdict.role_name, "reviewer_architecture")
        self.assertEqual(v.verdict.verdict, "comment")

    def test_happy_path_documentation_role(self):
        v = run_review(
            pr_number=99,
            role_arg="documentation",
            openrouter_token="or_key",
            config=_real_config(),
            openrouter_call=self._stub_openrouter_call(
                "## Documentation Review\n\n**Verdict**: approve\n"
            ),
            diff_fetcher=self._stub_diff_fetcher(),
        )
        self.assertEqual(v.verdict.role_name, "reviewer_documentation")
        self.assertEqual(v.verdict.verdict, "approve")

    def test_propagates_role_error(self):
        with self.assertRaises(ReviewerRoleError):
            run_review(
                pr_number=1,
                role_arg="banana",
                openrouter_token="or_key",
                config=_real_config(),
                openrouter_call=self._stub_openrouter_call(),
                diff_fetcher=self._stub_diff_fetcher(),
            )

    def test_propagates_pull_request_not_found(self):
        def fetcher_404(*args, **kwargs):
            raise PullRequestNotFoundError("PR not found")

        with self.assertRaises(PullRequestNotFoundError):
            run_review(
                pr_number=999999,
                role_arg="code",
                openrouter_token="or_key",
                config=_real_config(),
                openrouter_call=self._stub_openrouter_call(),
                diff_fetcher=fetcher_404,
            )

    def test_model_is_taken_from_role_config(self):
        # Capture the model passed to the LLM call. The role for "code" is
        # configured with anthropic/claude-sonnet-4 in role_routing.yaml;
        # verify the call passes that exact slug, not a hardcoded one.
        captured = {}

        def capturing_call(**kwargs):
            captured["model"] = kwargs["model"]
            return "## Code Review\n\n**Verdict**: approve\n"

        run_review(
            pr_number=1,
            role_arg="code",
            openrouter_token="or_key",
            config=_real_config(),
            openrouter_call=capturing_call,
            diff_fetcher=self._stub_diff_fetcher(),
        )
        expected_model = _role_for("code")["model"]
        self.assertEqual(captured["model"], expected_model)
        self.assertNotEqual(captured["model"], "hardcoded-model")

    def test_model_override_replaces_role_model_for_call_and_verdict(self):
        captured = {}

        def capturing_call(**kwargs):
            captured["model"] = kwargs["model"]
            return "## Code Review\n\n**Verdict**: approve\n"

        verdict = run_review(
            pr_number=1,
            role_arg="code",
            openrouter_token="or_key",
            config=_real_config(),
            model_override="openai/gpt-4.1-mini",
            openrouter_call=capturing_call,
            diff_fetcher=self._stub_diff_fetcher(),
        )

        self.assertEqual(captured["model"], "openai/gpt-4.1-mini")
        self.assertEqual(verdict.verdict.model, "openai/gpt-4.1-mini")


# ── CLI surface ───────────────────────────────────────────────────

class ParseArgsTests(unittest.TestCase):
    """The CLI exposes the documented flags; --role is constrained."""

    def test_minimal_args(self):
        args = parse_args(["--pr", "321", "--role", "code"])
        self.assertEqual(args.pr, 321)
        self.assertEqual(args.role, "code")
        self.assertEqual(args.owner, "SaJaToGu")
        self.assertEqual(args.repo, "ai-issue-solver")
        self.assertFalse(args.dry_run)
        self.assertIsNone(args.config)
        self.assertIsNone(args.model_override)

    def test_dry_run_flag(self):
        args = parse_args(["--pr", "1", "--role", "code", "--dry-run"])
        self.assertTrue(args.dry_run)

    def test_model_override_flag(self):
        args = parse_args([
            "--pr", "1",
            "--role", "code",
            "--model-override", "openai/gpt-4.1-mini",
        ])

        self.assertEqual(args.model_override, "openai/gpt-4.1-mini")

    def test_invalid_role_rejected(self):
        with self.assertRaises(SystemExit):
            parse_args(["--pr", "1", "--role", "banana"])

    def test_missing_pr_rejected(self):
        with self.assertRaises(SystemExit):
            parse_args(["--role", "code"])


# ── CLI runner ────────────────────────────────────────────────────

class MainCliTests(unittest.TestCase):
    def test_dry_run_reports_model_override_without_llm_call(self):
        with patch(
            "review_pr.fetch_pull_request_diff",
            return_value="diff --git a/x b/x\n+hi\n",
        ), patch("review_pr.call_openrouter") as call_mock:
            printed = io.StringIO()
            with contextlib.redirect_stdout(printed):
                exit_code = review_pr.main([
                    "--pr", "358",
                    "--role", "code",
                    "--dry-run",
                    "--model-override", "openai/gpt-4.1-mini",
                ])

        self.assertEqual(exit_code, 0)
        self.assertIn("model:        openai/gpt-4.1-mini", printed.getvalue())
        self.assertIn("model_source: override", printed.getvalue())
        call_mock.assert_not_called()


# ── Output data class ─────────────────────────────────────────────

class ExtractSymbolsFromDiffTests(unittest.TestCase):
    """Unit tests for the symbol-whitelist pre-filter."""

    SAMPLE_DIFF = (
        "diff --git a/scripts/build_graph.py b/scripts/build_graph.py\n"
        "@@ -1,5 +1,8 @@\n"
        "+import os\n"
        "+import sys\n"
        "+from collections import defaultdict\n"
        "+\n"
        "+DEFAULT_BACKLOG_OPEN = Path('x')\n"
        "+\n"
        "+def _extract_symbols_from_diff(diff: str) -> set[str]:\n"
        "+    return set()\n"
        "+\n"
        "+class GraphBuilder:\n"
        "+    pass\n"
    )

    def test_extracts_imports(self):
        from review_pr import _extract_symbols_from_diff
        symbols = _extract_symbols_from_diff(self.SAMPLE_DIFF)
        # 'os', 'sys', 'defaultdict', plus the from-module 'collections'
        self.assertIn("os", symbols)
        self.assertIn("sys", symbols)
        self.assertIn("defaultdict", symbols)
        self.assertIn("collections", symbols)

    def test_extracts_top_level_defs(self):
        from review_pr import _extract_symbols_from_diff
        symbols = _extract_symbols_from_diff(self.SAMPLE_DIFF)
        self.assertIn("_extract_symbols_from_diff", symbols)

    def test_extracts_class(self):
        from review_pr import _extract_symbols_from_diff
        symbols = _extract_symbols_from_diff(self.SAMPLE_DIFF)
        self.assertIn("GraphBuilder", symbols)

    def test_extracts_uppercase_module_constants(self):
        from review_pr import _extract_symbols_from_diff
        symbols = _extract_symbols_from_diff(self.SAMPLE_DIFF)
        self.assertIn("DEFAULT_BACKLOG_OPEN", symbols)

    def test_skips_context_minus_and_blank_lines(self):
        from review_pr import _extract_symbols_from_diff
        # No '+' lines → empty set
        diff = (
            "diff --git a/scripts/foo.py b/scripts/foo.py\n"
            "@@ -1,3 +1,3 @@\n"
            "-import os\n"
            "-def foo():\n"
            "-    pass\n"
        )
        symbols = _extract_symbols_from_diff(diff)
        self.assertEqual(symbols, set())

    def test_skips_diff_file_header_lines(self):
        """'+++ b/path/to/file' is the unified-diff file header,
        not an added line. The double-plus must not be parsed."""
        from review_pr import _extract_symbols_from_diff
        diff = (
            "diff --git a/scripts/foo.py b/scripts/foo.py\n"
            "+++ b/scripts/foo.py\n"
            "+import os\n"
        )
        symbols = _extract_symbols_from_diff(diff)
        self.assertIn("os", symbols)
        # The '+++ b/scripts/foo.py' line should NOT add 'b' or
        # 'scripts' or 'foo' to the symbol set.
        self.assertNotIn("b", symbols)
        self.assertNotIn("scripts", symbols)

    def test_empty_diff(self):
        from review_pr import _extract_symbols_from_diff
        self.assertEqual(_extract_symbols_from_diff(""), set())


class ParseFindingsTests(unittest.TestCase):
    """Unit tests for the structured finding parser."""

    SAMPLE_REVIEW = """\
## Code Review

**Verdict**: ready to merge

### Improvements
- `scripts/build_graph.py:100` — consider extracting helper
- `scripts/review_pr.py:42` — return type annotation would help
- just a comment about nothing in particular
- (none observed)
- `general` — covers many files at once

### Concerns
- `scripts/build_graph.py:200` — infinite loop risk

### Strengths
- `tests/test_build_graph.py:55` — good test coverage

### Open questions
- should we also check for X?
"""

    def test_parses_four_sections(self):
        from review_pr import _parse_findings
        findings = _parse_findings(self.SAMPLE_REVIEW)
        sections = [f.section for f in findings]
        self.assertIn("Improvements", sections)
        self.assertIn("Concerns", sections)
        self.assertIn("Strengths", sections)
        self.assertIn("Open questions", sections)

    def test_extracts_symbol_from_file_ref(self):
        from review_pr import _parse_findings
        findings = _parse_findings(self.SAMPLE_REVIEW)
        # `scripts/build_graph.py:100` → symbol = "build_graph"
        with_file = [f for f in findings if f.section == "Improvements"
                     and f.file_ref == "scripts/build_graph.py:100"]
        self.assertEqual(len(with_file), 1)
        self.assertEqual(with_file[0].symbol, "build_graph")

    def test_general_finding_has_no_symbol(self):
        from review_pr import _parse_findings
        findings = _parse_findings(self.SAMPLE_REVIEW)
        # Two general Improvements (`just a comment...` and the
        # `general`-tagged one) plus one general Open question
        # ("should we also check for X?") = 3 generals total.
        generals = [f for f in findings if f.file_ref == "general"]
        self.assertEqual(len(generals), 3)
        for g in generals:
            self.assertIsNone(g.symbol)

    def test_none_observed_section_produces_no_findings(self):
        from review_pr import _parse_findings
        findings = _parse_findings(self.SAMPLE_REVIEW)
        # The Improvements section has `(none observed)` as one of
        # its bullets; that bullet must be filtered out.
        none_findings = [f for f in findings if "(none observed)" in f.text]
        self.assertEqual(len(none_findings), 0)

    def test_unquoted_bullet_with_no_file_ref(self):
        """A bullet like `- just a comment about nothing` (no
        `file:line`, no `general`) should still parse as a
        general observation, not be dropped."""
        from review_pr import _parse_findings
        findings = _parse_findings(self.SAMPLE_REVIEW)
        # The 'just a comment about nothing in particular' bullet
        # must end up as a general finding.
        comment_findings = [
            f for f in findings if "just a comment" in f.text
        ]
        self.assertEqual(len(comment_findings), 1)
        self.assertEqual(comment_findings[0].file_ref, "general")
        self.assertIsNone(comment_findings[0].symbol)


class FilterFindingsBySymbolsTests(unittest.TestCase):
    """Unit tests for the post-filter that drops findings citing
    symbols not in the diff."""

    def test_keeps_findings_with_symbol_in_whitelist(self):
        from review_pr import Finding, _filter_findings_by_symbols
        f = Finding(
            section="Improvements",
            file_ref="scripts/build_graph.py:100",
            symbol="build_graph",
            text="text",
        )
        kept, dropped = _filter_findings_by_symbols([f], {"build_graph"})
        self.assertEqual(len(kept), 1)
        self.assertEqual(len(dropped), 0)

    def test_drops_findings_with_symbol_not_in_whitelist(self):
        from review_pr import Finding, _filter_findings_by_symbols
        f = Finding(
            section="Concerns",
            file_ref="scripts/foo.py:1",
            symbol="foo",
            text="text",
        )
        kept, dropped = _filter_findings_by_symbols([f], {"bar"})
        self.assertEqual(len(kept), 0)
        self.assertEqual(len(dropped), 1)
        self.assertEqual(dropped[0].symbol, "foo")

    def test_keeps_general_findings_without_symbol(self):
        from review_pr import Finding, _filter_findings_by_symbols
        f = Finding(
            section="Improvements",
            file_ref="general",
            symbol=None,
            text="text",
        )
        kept, dropped = _filter_findings_by_symbols([f], set())
        self.assertEqual(len(kept), 1)
        self.assertEqual(len(dropped), 0)

    def test_does_not_mutate_input(self):
        from review_pr import Finding, _filter_findings_by_symbols
        f1 = Finding("Improvements", "a.py:1", "a", "x")
        f2 = Finding("Concerns", "b.py:2", "b", "y")
        findings = [f1, f2]
        _filter_findings_by_symbols(findings, {"a"})
        self.assertEqual(len(findings), 2)


class ReviewResultDataclassTests(unittest.TestCase):
    """Smoke tests for the ReviewResult wrapper."""

    def test_default_symbols_set_is_empty(self):
        from review_pr import ReviewResult, ReviewerVerdict
        v = ReviewerVerdict(
            raw_text="", verdict=None, role_name="r", model="m",
            pr_number=1, pr_repo="o/r",
        )
        r = ReviewResult(verdict=v, findings=[], dropped_findings=[])
        self.assertEqual(r.available_symbols, set())


class ReviewerVerdictDataclassTests(unittest.TestCase):
    def test_construction_and_attribute_access(self):
        v = ReviewerVerdict(
            raw_text="**Verdict**: approve",
            verdict="approve",
            role_name="reviewer_code",
            model="anthropic/claude-sonnet-4",
            pr_number=321,
            pr_repo="SaJaToGu/ai-issue-solver",
        )
        self.assertEqual(v.verdict, "approve")
        self.assertEqual(v.pr_number, 321)
        self.assertEqual(v.pr_repo, "SaJaToGu/ai-issue-solver")


if __name__ == "__main__":
    unittest.main()
