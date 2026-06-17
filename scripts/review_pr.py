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
from dataclasses import dataclass
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
VALID_VERDICTS: tuple[str, ...] = ("approve", "request changes", "comment")

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
_VERDICT_RE = re.compile(
    r"\*\*Verdict\*\*\s*:\s*(approve|request\s+changes|comment)",
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


# ── Verdict parsing ───────────────────────────────────────────────

def parse_verdict(text: str) -> str | None:
    """
    Extract the verdict from the LLM's Markdown output.

    All three reviewer prompts declare a `**Verdict**: <value>` line in
    their "## Output" section (see `.agents/reviewers/reviewer-*.md`).
    Returns the lowercased verdict string, or None if the line is missing.
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
    openrouter_call: Callable[..., str] = call_openrouter,
    diff_fetcher: Callable[..., str] = fetch_pull_request_diff,
    project_root: Path = PROJECT_ROOT,
) -> ReviewerVerdict:
    """
    End-to-end: resolve role, load prompt, fetch diff, call model, parse verdict.

    `openrouter_call` and `diff_fetcher` are injectable for tests.
    """
    role = resolve_role(role_arg, config)
    system_prompt = load_prompt(role, project_root)
    pr_diff = diff_fetcher(owner, repo, pr_number, token=github_token)
    user_prompt = (
        f"PR #{pr_number} in {owner}/{repo}\n\n"
        f"{pr_diff}\n"
    )
    response_text = openrouter_call(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        model=role["model"],
        token=openrouter_token,
    )
    return ReviewerVerdict(
        raw_text=response_text,
        verdict=parse_verdict(response_text),
        role_name=role["_name"],
        model=role["model"],
        pr_number=pr_number,
        pr_repo=f"{owner}/{repo}",
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

    # 2. Resolve role
    try:
        role = resolve_role(args.role, config)
    except ReviewerRoleError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    # 3. Load prompt
    try:
        system_prompt = load_prompt(role)
    except ReviewerRoleError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    # 4. Fetch PR diff
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
        print("=== DRY RUN ===")
        print(f"role:         {role['_name']}")
        print(f"model:        {role['model']}")
        print(f"prompt_file:  {role['prompt_file']}")
        print(f"prompt_chars: {len(system_prompt)}")
        print(f"pr:           {args.owner}/{args.repo}#{args.pr}")
        print(f"diff_chars:   {len(pr_diff)}")
        return 0

    openrouter_token = os.getenv("OPENROUTER_API_KEY")
    if not openrouter_token:
        print("error: OPENROUTER_API_KEY is not set", file=sys.stderr)
        return 1

    try:
        response_text = call_openrouter(
            system_prompt=system_prompt,
            user_prompt=f"PR #{args.pr} in {args.owner}/{args.repo}\n\n{pr_diff}\n",
            model=role["model"],
            token=openrouter_token,
        )
    except requests.HTTPError as exc:
        print(f"error: OpenRouter call failed: {exc}", file=sys.stderr)
        return 1
    except ValueError as exc:
        print(f"error: OpenRouter call failed: {exc}", file=sys.stderr)
        return 1

    # 6. Emit verdict
    verdict = parse_verdict(response_text)
    print(response_text)
    if verdict is None:
        print(
            "\nwarning: no '**Verdict**: <value>' line found in output",
            file=sys.stderr,
        )
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
