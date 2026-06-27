#!/usr/bin/env python3
"""
review_pr.py — Reviewer Runtime.

Loads a reviewer prompt (code / architecture / documentation), fetches a
pull-request diff from GitHub, and emits a structured verdict via the
model declared in `config/role_routing.yaml` for the selected role.

This is the runtime for the three reviewer prompt profiles introduced
in #313 (`.agents/reviewers/reviewer-{code,architecture,documentation}.md`).
Before this script existed, the prompts were loadable artifacts but
nothing invoked them.

Architectural invariant: the reviewer is a SEPARATE script or subcommand,
NOT a flag on `solve_issues.py`. The solver stays dumb.

Usage:
    python scripts/review_pr.py --pr 321 --role code
    python scripts/review_pr.py --pr 321 --role architecture --owner myorg --repo myrepo
    python scripts/review_pr.py --pr 321 --role documentation --dry-run
    python scripts/review_pr.py --pr 321 --role code --config path/to/role_routing.yaml

Exit codes:
    0  verdict emitted and `**Verdict**:` line parsed
    1  configuration / I/O / API error
    2  verdict emitted but no `**Verdict**:` line found (LLM did not follow schema)

This is an infrastructure PR. It does not, by itself, validate that
ai-issue-solver works end-to-end — that is the role of #326 (first
real Solver run with a real `reports/runs/.../summary.txt`).
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import requests


SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(SCRIPT_DIR))

from role_routing_loader import (  # noqa: E402
    get_role_config,
    load_role_config,
)


# ── Constants ────────────────────────────────────────────────────────

# Map the user-facing --role arg to the role_routing.yaml key.
ROLE_ALIASES: dict[str, str] = {
    "code": "reviewer_code",
    "architecture": "reviewer_architecture",
    "documentation": "reviewer_documentation",
}

# Verdicts the reviewer prompts declare (see `.agents/reviewers/reviewer-*.md`).
# Both legacy values (approve/request changes/comment) and the new
# code-reviewer values (ready to merge/needs work/discuss) are accepted
# by the parser so old PR comments and the new schema coexist.
VALID_VERDICTS: tuple[str, ...] = (
    "approve", "request changes", "comment",
    "ready to merge", "needs work", "discuss",
)

# The 3 reviewer prompt files this runtime supports. Kept here so we can
# raise a clear error if a future prompt is added without updating ROLE_ALIASES.
REVIEWER_PROMPT_FILES: dict[str, str] = {
    "reviewer_code": ".agents/reviewers/reviewer-code.md",
    "reviewer_architecture": ".agents/reviewers/reviewer-architecture.md",
    "reviewer_documentation": ".agents/reviewers/reviewer-documentation.md",
}

# Cap on diff size we will send to the LLM. Beyond this we truncate with
# a clear marker. The 0.9.0 validation run can produce large diffs; we
# fail loudly rather than silently dropping content.
MAX_DIFF_CHARS = 200_000

# Compile a regex once at import time. Matches the `**Verdict**: <value>`
# line that all three reviewer prompts declare in their "## Output" sections.
# Accepts both legacy values and the new code-reviewer values.
_VERDICT_RE = re.compile(
    r"\*\*Verdict\*\*\s*:\s*"
    r"(approve|request\s+changes|comment|ready\s+to\s+merge|needs\s+work|discuss)",
    re.IGNORECASE,
)


# ── Errors ───────────────────────────────────────────────────────────

class ReviewerRoleError(ValueError):
    """Raised when the requested role is unknown or not configured."""


class PullRequestNotFoundError(LookupError):
    """Raised when the PR does not exist or is not accessible."""


# ── Data classes ────────────────────────────────────────────────────

@dataclass(frozen=True)
class ReviewerVerdict:
    """Structured output of a reviewer run."""
    raw_text: str
    verdict: str | None  # one of VALID_VERDICTS, or None if not parseable
    role_name: str
    model: str
    pr_number: int
    pr_repo: str


@dataclass(frozen=True)
class ReviewResult:
    """Full result of `run_review`: the parsed verdict plus the
    parsed findings (with whitelist-filter applied).

    `dropped_findings` are the entries whose cited symbol was not
    in the diff — they were stripped before surfacing to the human.
    `available_symbols` is the whitelist itself, useful for the
    CLI to print "dropped N findings (symbols not in diff: ...)".
    """
    verdict: ReviewerVerdict
    findings: list[Finding]
    dropped_findings: list[Finding]
    available_symbols: set[str] = field(default_factory=set)


# ── Role resolution ────────────────────────────────────────────────

def resolve_role(role_arg: str, config: dict[str, Any] | None = None) -> dict[str, Any]:
    """
    Map the user-facing --role arg to the role_routing.yaml key and
    return its resolved config.

    Raises ReviewerRoleError if the role is not a known reviewer alias
    or is not present in the loaded config.
    """
    if role_arg not in ROLE_ALIASES:
        raise ReviewerRoleError(
            f"unknown role '{role_arg}'. "
            f"Valid roles: {', '.join(sorted(ROLE_ALIASES))}"
        )
    role_name = ROLE_ALIASES[role_arg]
    if config is None:
        config = load_role_config()
    try:
        return get_role_config(role_name, config)
    except KeyError as exc:
        raise ReviewerRoleError(
            f"role '{role_name}' is not configured in role_routing.yaml"
        ) from exc


# ── Prompt loading ─────────────────────────────────────────────────

def load_prompt(role: dict[str, Any], project_root: Path = PROJECT_ROOT) -> str:
    """
    Load the reviewer prompt text from the path declared in the role config.

    The role config must contain a 'prompt_file' field (relative to
    project_root). Raises ReviewerRoleError if the field is missing or
    the file cannot be read.
    """
    prompt_file = role.get("prompt_file")
    if not prompt_file:
        raise ReviewerRoleError(
            f"role '{role.get('_name', '<unknown>')}' has no 'prompt_file' "
            f"field in role_routing.yaml"
        )
    prompt_path = Path(prompt_file)
    if not prompt_path.is_absolute():
        prompt_path = project_root / prompt_path
    try:
        return prompt_path.read_text(encoding="utf-8")
    except (FileNotFoundError, OSError) as exc:
        raise ReviewerRoleError(
            f"cannot read prompt file '{prompt_path}': {exc}"
        ) from exc


# ── GitHub PR diff fetch ───────────────────────────────────────────

def fetch_pull_request_diff(
    owner: str,
    repo: str,
    pr_number: int,
    token: str | None = None,
    *,
    _session: requests.Session | None = None,
) -> str:
    """
    Fetch the unified diff of a pull request via the GitHub API.

    Uses the `application/vnd.github.v3.diff` media type to get the full
    patch directly. Returns the diff text. Truncates to MAX_DIFF_CHARS
    with a clear marker if the diff is larger.

    Raises PullRequestNotFoundError if the PR is 404. Other HTTP errors
    are re-raised.
    """
    url = f"https://api.github.com/repos/{owner}/{repo}/pulls/{pr_number}"
    headers = {
        "Accept": "application/vnd.github.v3.diff",
        "User-Agent": "ai-issue-solver-reviewer-runtime",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"

    session = _session or requests
    response = session.get(url, headers=headers, timeout=30)
    if response.status_code == 404:
        raise PullRequestNotFoundError(
            f"PR #{pr_number} not found in {owner}/{repo} (404)"
        )
    response.raise_for_status()
    diff = response.text
    if len(diff) > MAX_DIFF_CHARS:
        diff = (
            diff[:MAX_DIFF_CHARS]
            + f"\n\n... [truncated, original diff was {len(response.text)} chars] ...\n"
        )
    return diff


# ── OpenRouter call ────────────────────────────────────────────────

def call_openrouter(
    system_prompt: str,
    user_prompt: str,
    model: str,
    token: str | None,
    *,
    base_url: str = "https://openrouter.ai/api/v1",
    referer: str | None = None,
    x_title: str = "ai-issue-solver-reviewer",
    temperature: float = 0.0,
    timeout: float = 120.0,
    _session: requests.Session | None = None,
) -> str:
    """
    Call OpenRouter's chat/completions endpoint with a system + user prompt.

    Returns the assistant message text. Raises ValueError if no token is
    provided, requests.HTTPError on non-2xx responses, and ValueError if
    the response is missing the expected `choices[0].message.content` field.
    """
    if not token:
        raise ValueError("OPENROUTER_API_KEY is not set")
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "X-Title": x_title,
    }
    if referer:
        headers["HTTP-Referer"] = referer
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": temperature,
    }
    session = _session or requests
    response = session.post(
        f"{base_url}/chat/completions",
        headers=headers,
        json=payload,
        timeout=timeout,
    )
    response.raise_for_status()
    data = response.json()
    choices = data.get("choices") or []
    if not choices:
        raise ValueError("OpenRouter response has no choices")
    message = choices[0].get("message") or {}
    content = message.get("content")
    if not content:
        raise ValueError("OpenRouter response is missing message content")
    return content


# ── Diff symbol extraction + finding parsing ──────────────────────


# Patterns for symbols that appear in an added line of a unified diff.
# The leading `+` (single, not `+++`) is intentional — `+++ b/path` is
# the file-header line in a unified diff, not an added line.
_ADDED_IMPORT_RE = re.compile(
    r"^\+(?:from\s+([\w.]+)\s+)?import\s+([\w.]+(?:\s+as\s+\w+)?)"
)
_ADDED_DEF_RE = re.compile(r"^\+\s*def\s+(\w+)\s*\(")
_ADDED_CLASS_RE = re.compile(r"^\+\s*class\s+(\w+)")
_ADDED_ASSIGN_RE = re.compile(r"^\+\s*(\w+)\s*=\s*[^=]")


@dataclass(frozen=True)
class Finding:
    """A single review finding (Improvement / Concern / Strength / Open Q).

    `file_ref` is the `file:line` portion as it appeared in the
    reviewer's output, or the literal `general` for entries that
    don't reference a specific location. `symbol` is the function,
    class, import, or variable name extracted from the reference —
    it is `None` for `general` entries and for entries where no
    Python symbol could be parsed out.
    """

    section: str  # 'Improvements' | 'Concerns' | 'Strengths' | 'Open questions'
    file_ref: str
    symbol: str | None
    text: str


def _extract_symbols_from_diff(diff: str) -> set[str]:
    """Return the set of Python symbols added in a unified diff.

    Only collects symbols from `+` lines (additions), not from `-`
    or context lines. Covers:
    - imports: `import X` / `from Y import Z` (keeps module and name)
    - top-level `def name(` and `class name(` declarations
    - top-level variable assignments (`NAME = ...`)

    Symbols that appear in comments, strings, or docstrings are not
    extracted — the patterns only fire on the first non-whitespace
    token being a Python keyword.
    """
    symbols: set[str] = set()
    for line in diff.splitlines():
        if not line.startswith("+"):
            continue
        # Skip the file header lines (+++ b/path)
        if line.startswith("+++"):
            continue
        m = _ADDED_IMPORT_RE.match(line)
        if m:
            # group(1) is the from-module, group(2) is the imported name
            from_module = m.group(1)
            imported = m.group(2).split(" as ")[0].split(".")[0]
            symbols.add(imported)
            if from_module:
                symbols.add(from_module.rstrip("."))
            continue
        m = _ADDED_DEF_RE.match(line)
        if m:
            symbols.add(m.group(1))
            continue
        m = _ADDED_CLASS_RE.match(line)
        if m:
            symbols.add(m.group(1))
            continue
        m = _ADDED_ASSIGN_RE.match(line)
        if m:
            name = m.group(1)
            # Only collect ALL_CAPS module-level constants — they are
            # the module-level symbols that other modules import.
            if name.isupper():
                symbols.add(name)
    return symbols


# Pattern for a single finding bullet: ``- `file:line` — text`` or
# ``- `general` — text`` or ``- text — text`` (no file_ref).
_FINDING_BULLET_RE = re.compile(
    r"^-\s+"
    r"(?P<ref>`?(?P<file>[^`:]+?):?(?P<line>\d+)?`?|\"?(?P<file2>general)\"?)"  # noqa: E501
    r"\s*[—\-]\s*"
    r"(?P<text>.+?)$"
)


def _parse_findings(text: str) -> list[Finding]:
    """Parse the four findings sections from a reviewer's output.

    Returns findings in the order they appear in the text. Sections
    with `(none observed)` produce no findings. Unknown section
    names are tolerated (logged-as-empty).
    """
    section_re = re.compile(
        r"^###\s+(Improvements|Concerns|Strengths|Open questions)\s*$",
        re.MULTILINE,
    )
    findings: list[Finding] = []
    sections = list(section_re.finditer(text))
    for i, m in enumerate(sections):
        section_name = m.group(1)
        start = m.end()
        end = sections[i + 1].start() if i + 1 < len(sections) else len(text)
        body = text[start:end]
        for line in body.splitlines():
            line = line.strip()
            if not line.startswith("- "):
                continue
            bm = _FINDING_BULLET_RE.match(line)
            if not bm:
                # Bullet without recognised file_ref — treat the
                # whole thing as text and keep it (no symbol to
                # filter on). This is the "general" path for
                # observations that don't cite a location.
                text_only = line[2:].strip()
                if text_only.lower() == "(none observed)":
                    continue
                findings.append(Finding(
                    section=section_name,
                    file_ref="general",
                    symbol=None,
                    text=text_only,
                ))
                continue
            file_ref = bm.group("ref").strip("`")
            text_part = bm.group("text").strip()
            # Extract the symbol name from `file:line` — the symbol
            # is the basename without `.py`. For "general" or
            # file references without a clean symbol, set symbol=None.
            symbol = None
            if ":" in file_ref and file_ref != "general":
                path_part = file_ref.split(":")[0]
                base = path_part.rsplit("/", 1)[-1]
                if base.endswith(".py"):
                    symbol = base[:-3]
                else:
                    symbol = base
            findings.append(Finding(
                section=section_name,
                file_ref=file_ref,
                symbol=symbol,
                text=text_part,
            ))
    return findings


def _filter_findings_by_symbols(
    findings: list[Finding],
    symbols: set[str],
) -> tuple[list[Finding], list[Finding]]:
    """Drop findings that cite symbols absent from the diff.

    A finding is kept if:
    - its `symbol` is `None` (general observation), or
    - its `symbol` is in `symbols`.

    Findings whose symbol is not in the set are dropped. Returns
    `(kept, dropped)` lists — neither is mutated.
    """
    kept: list[Finding] = []
    dropped: list[Finding] = []
    for f in findings:
        if f.symbol is None or f.symbol in symbols:
            kept.append(f)
        else:
            dropped.append(f)
    return kept, dropped


# ── Verdict parsing ───────────────────────────────────────────────

def parse_verdict(text: str) -> str | None:
    """
    Extract the verdict from the LLM's Markdown output.

    All three reviewer prompts declare a `**Verdict**: <value>` line in
    their "## Output" section (see `.agents/reviewers/reviewer-*.md`).
    Returns the lowercased verdict string, or None if the line is missing.

    ## Examples

    Well-formed `**Verdict**: approve` line (single-token value):

    >>> parse_verdict("Some preamble\\n\\n**Verdict**: approve\\n\\nMore text")
    'approve'

    Well-formed `**Verdict**: request changes` line (note the embedded
    space inside the value — the regex collapses it to a single space):

    >>> parse_verdict("**Verdict**: request changes\\n")
    'request changes'

    Malformed input without a verdict line returns ``None``:

    >>> parse_verdict("Some text without any verdict") is None
    True

    ## Notes

    - The regex is case-insensitive (e.g. ``**Verdict**: APPROVE`` parses
      as ``'approve'``) and tolerates extra whitespace around the colon
      and the value (e.g. ``**Verdict**:   approve  ``).
    - Only the FIRST matching ``**Verdict**:`` line in the text is
      considered. Any later verdict lines in the same output are ignored.
    - Unrecognized verdict values (anything that is not ``approve``,
      ``request changes`` or ``comment`` — e.g. ``**Verdict**: maybe``)
      return ``None`` rather than the raw value as a string.
    """
    if not text:
        return None
    match = _VERDICT_RE.search(text)
    if not match:
        return None
    return match.group(1).lower().strip()


# ── End-to-end runner ─────────────────────────────────────────────

def run_review(
    pr_number: int,
    role_arg: str,
    *,
    owner: str = "SaJaToGu",
    repo: str = "ai-issue-solver",
    github_token: str | None = None,
    openrouter_token: str | None = None,
    config: dict[str, Any] | None = None,
    model_override: str | None = None,
    openrouter_call: Callable[..., str] = call_openrouter,
    diff_fetcher: Callable[..., str] = fetch_pull_request_diff,
    project_root: Path = PROJECT_ROOT,
) -> ReviewResult:
    """
    End-to-end: resolve role, load prompt, fetch diff, extract the
    symbol whitelist, augment the prompt with it, call the model,
    parse the verdict, parse findings, and apply the post-filter
    that drops findings whose cited symbol is not in the diff.

    The symbol whitelist is sent to the model as part of the
    system prompt context so the model can cite real symbols
    directly. The post-filter is a safety net for the case where
    the model still emits a name that is not in the diff.

    `openrouter_call` and `diff_fetcher` are injectable for tests.
    """
    role = resolve_role(role_arg, config)
    base_system_prompt = load_prompt(role, project_root)
    pr_diff = diff_fetcher(owner, repo, pr_number, token=github_token)
    available_symbols = _extract_symbols_from_diff(pr_diff)

    symbol_block = (
        "\n\n## Available symbols in this diff\n\n"
        "Cite only these symbols in your findings. Each was added "
        "by the diff; any other name is either pre-existing code or "
        "hallucinated.\n\n"
        f"```\n{', '.join(sorted(available_symbols))}\n```"
    ) if available_symbols else ""
    system_prompt = base_system_prompt + symbol_block

    model = model_override or role["model"]
    user_prompt = (
        f"PR #{pr_number} in {owner}/{repo}\n\n"
        f"{pr_diff}\n"
    )
    response_text = openrouter_call(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        model=model,
        token=openrouter_token,
    )
    verdict = ReviewerVerdict(
        raw_text=response_text,
        verdict=parse_verdict(response_text),
        role_name=role["_name"],
        model=model,
        pr_number=pr_number,
        pr_repo=f"{owner}/{repo}",
    )
    all_findings = _parse_findings(response_text)
    findings, dropped = _filter_findings_by_symbols(
        all_findings, available_symbols,
    )
    return ReviewResult(
        verdict=verdict,
        findings=findings,
        dropped_findings=dropped,
        available_symbols=available_symbols,
    )


# ── CLI ────────────────────────────────────────────────────────────

def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run a reviewer role on a PR and emit a structured verdict. "
            "Infrastructure for the 0.9.0 validation run; not a Solver "
            "run itself."
        ),
    )
    parser.add_argument(
        "--pr", type=int, required=True,
        help="PR number to review",
    )
    parser.add_argument(
        "--role", required=True, choices=sorted(ROLE_ALIASES),
        help="Reviewer sub-role to invoke",
    )
    parser.add_argument(
        "--owner", default="SaJaToGu",
        help="GitHub owner (default: SaJaToGu)",
    )
    parser.add_argument(
        "--repo", default="ai-issue-solver",
        help="GitHub repo name (default: ai-issue-solver)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help=(
            "Resolve role and prompt, fetch the diff, but do not call the "
            "LLM. Useful for verifying the wiring without spending tokens."
        ),
    )
    parser.add_argument(
        "--config", default=None,
        help="Path to role_routing.yaml (default: config/role_routing.yaml)",
    )
    parser.add_argument(
        "--model-override",
        default=None,
        help=(
            "Temporarily use this OpenRouter model for the review instead "
            "of the role_routing.yaml model. Useful for cheaper standard reviews."
        ),
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    # 1. Load config
    try:
        config = (
            load_role_config(args.config) if args.config else load_role_config()
        )
    except (FileNotFoundError, ValueError) as exc:
        print(f"error: cannot load role_routing.yaml: {exc}", file=sys.stderr)
        return 1

    # 2. Resolve role (for the dry-run branch's metadata print)
    try:
        role = resolve_role(args.role, config)
    except ReviewerRoleError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    # 3. Load prompt (dry-run needs it for prompt_chars)
    try:
        system_prompt = load_prompt(role)
    except ReviewerRoleError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    # 4. Fetch PR diff (dry-run needs it for diff_chars)
    github_token = os.getenv("GITHUB_TOKEN")
    try:
        pr_diff = fetch_pull_request_diff(
            args.owner, args.repo, args.pr, token=github_token
        )
    except PullRequestNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except requests.HTTPError as exc:
        print(f"error: failed to fetch PR diff: {exc}", file=sys.stderr)
        return 1

    # 5. Either dry-run report or actual LLM call
    if args.dry_run:
        model = args.model_override or role["model"]
        symbols = _extract_symbols_from_diff(pr_diff)
        print("=== DRY RUN ===")
        print(f"role:         {role['_name']}")
        print(f"model:        {model}")
        if args.model_override:
            print(f"model_source: override (configured: {role['model']})")
        else:
            print("model_source: role_routing.yaml")
        print(f"prompt_file:  {role['prompt_file']}")
        print(f"prompt_chars: {len(system_prompt)}")
        print(f"pr:           {args.owner}/{args.repo}#{args.pr}")
        print(f"diff_chars:   {len(pr_diff)}")
        print(f"available_symbols: {len(symbols)}")
        return 0

    openrouter_token = os.getenv("OPENROUTER_API_KEY")
    if not openrouter_token:
        print("error: OPENROUTER_API_KEY is not set", file=sys.stderr)
        return 1

    # 6. Run end-to-end via run_review (handles diff fetch, prompt
    #    augmentation, LLM call, verdict + findings parse, post-filter).
    try:
        result = run_review(
            pr_number=args.pr,
            role_arg=args.role,
            owner=args.owner,
            repo=args.repo,
            github_token=github_token,
            openrouter_token=openrouter_token,
            config=config,
            model_override=args.model_override,
        )
    except requests.HTTPError as exc:
        print(f"error: OpenRouter call failed: {exc}", file=sys.stderr)
        return 1
    except ValueError as exc:
        print(f"error: OpenRouter call failed: {exc}", file=sys.stderr)
        return 1

    # 7. Emit verdict + findings summary
    print(result.verdict.raw_text)
    if result.dropped_findings:
        dropped_symbols = sorted({
            f.symbol for f in result.dropped_findings if f.symbol
        })
        print(
            f"\n[whitelist-filter] dropped {len(result.dropped_findings)} "
            f"findings citing symbols not in diff: {dropped_symbols}",
            file=sys.stderr,
        )
    if result.verdict.verdict is None:
        print(
            "\nwarning: no '**Verdict**: <value>' line found in output",
            file=sys.stderr,
        )
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
