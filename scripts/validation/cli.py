from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from scripts.validation.github_client import ValidationGitHubClient
from scripts.validation.metrics import (
    compute_metrics,
    format_cost,
    format_duration,
    is_oversized,
    load_thresholds,
    persist_validation_run,
    write_validation_report,
)
from scripts.validation.models import ValidationConfig, ValidationMetrics
from scripts.validation.parsers import collect_run_reports
from scripts.validation.pr_checks import check_pr_statuses
from scripts.validation.runner import run_solver_for_issue
from scripts.validation.selection import select_issues_by_label
from scripts.validation.split import close_parent_with_cross_ref, decompose_pr_to_sub_issues


def _load_config() -> dict[str, Any]:
    """Load configuration from environment / .env files."""
    try:
        from scripts.utils import load_env
        config = load_env()
    except ImportError:
        config = {}
    for key in ("GITHUB_TOKEN", "GITHUB_OWNER", "GITHUB_REPO"):
        import os
        val = os.environ.get(key)
        if val:
            config[key] = val
    return config


def _require_config(config: dict[str, Any], key: str, subcommand: str) -> str | None:
    """Return a required config value, or print error and return None."""
    val = config.get(key)
    if not val:
        print(
            f"Error: {key} not set. Add it to config/.env or set it as an "
            f"environment variable before running 'validation_run {subcommand}'.",
            file=sys.stderr,
        )
        return None
    return val


def _get_client(config: dict[str, Any]) -> tuple[ValidationGitHubClient | None, str | None]:
    """Build client + return (client, owner) or (None, None) on missing config."""
    token = config.get("GITHUB_TOKEN", "")
    owner = _require_config(config, "GITHUB_OWNER", "run/check-prs/list")
    if owner is None:
        return None, None
    if not token:
        print("Warning: GITHUB_TOKEN not set. API calls will fail.", file=sys.stderr)
    return ValidationGitHubClient(token, owner), owner


def cmd_run(args: argparse.Namespace, config: dict[str, Any]) -> int:
    """Run the solver on N issues and produce a validation report."""
    client, owner = _get_client(config)
    if client is None or owner is None:
        return 1
    repo = args.repo

    try:
        issues = select_issues_by_label(
            client=client,
            repo=repo,
            label=args.label,
            max_issues=args.issues,
            state="open",
        )
    except RuntimeError as exc:
        print(f"Error fetching issues: {exc}", file=sys.stderr)
        if args.dry_run:
            print("Dry-run: proceeding with synthetic issues for smoke test.")
            from scripts.validation.models import ValidationIssue
            issues = [
                ValidationIssue(number=n, title=f"Synthetic issue #{n}", body="")
                for n in range(1, args.issues + 1)
            ]
        else:
            return 1

    if not issues:
        print(f"No open issues found with label '{args.label}' in {owner}/{repo}")
        return 1

    print(f"Selected {len(issues)} issues for validation run:")
    for iss in issues:
        print(f"  #{iss.number}: {iss.title}")

    reports: list = []

    for idx, issue in enumerate(issues):
        print(f"\n[{idx+1}/{len(issues)}] Running solver for issue #{issue.number}...")
        # Resolve model: CLI flag > env var (OPENCODE_MODEL / OPENCODE_MODEL_NAME)
        # > config/.env. No silent defaults — fail fast if missing.
        model = args.model or os.environ.get("OPENCODE_MODEL")
        if not model:
            print(
                "Error: --model (or OPENCODE_MODEL env) required.",
                file=sys.stderr,
            )
            return 1
        model_name = args.model_name or os.environ.get("OPENCODE_MODEL_NAME")
        if not model_name:
            print(
                "Error: --model-name (or OPENCODE_MODEL_NAME env) required.",
                file=sys.stderr,
            )
            return 1
        report = run_solver_for_issue(
            repo=repo,
            issue_number=issue.number,
            model=model,
            model_name=model_name,
            max_run_cost_usd=args.max_run_cost_usd or 5.0,
            dry_run=args.dry_run,
            base_branch=args.base_branch,
        )
        if not args.dry_run:
            if report.pr_number is not None:
                print(f"  PR created: #{report.pr_number}")
                report = check_pr_statuses(client, repo, report)
                merged = "yes" if report.pr_merged else "no"
                ci = "yes" if report.ci_green else ("no" if report.ci_green is False else "unknown")
                print(f"  Merged: {merged}, CI green: {ci}")
            else:
                print(f"  Status: {report.status}")
        reports.append(report)

    metrics = compute_metrics(reports)
    run_id = datetime.utcnow().strftime("validation-%Y%m%d-%H%M%S")

    output_path = Path(args.output) if args.output else Path("reports/validation") / f"{run_id}.md"
    write_validation_report(metrics, output_path, title=args.title)
    print(f"\nReport written to: {output_path}")

    persist_validation_run(metrics, Path("reports/validation"), run_id=run_id)
    print(f"Metrics persisted to: reports/validation/")

    print(f"\n=== Validation Summary ===")
    print(f"  Processed: {metrics.total_processed}")
    print(f"  Merged:    {metrics.total_merged}")
    print(f"  Success:   {metrics.success_rate:.1%}")
    print(f"  Total cost: {format_cost(metrics.total_cost_usd)}")
    print(f"  Total time: {format_duration(metrics.total_duration_seconds)}")
    if metrics.top_errors:
        print(f"  Top errors:")
        for ec, count in metrics.top_errors:
            print(f"    - {ec}: {count}")

    return 0


def cmd_report(args: argparse.Namespace, config: dict[str, Any]) -> int:
    """Generate a report from existing run reports."""
    client = None
    owner: str | None = None
    if not args.no_github:
        client, owner = _get_client(config)
        if client is None or owner is None:
            return 1
    repo = args.repo

    runs_dir = Path(args.runs_dir)
    reports = collect_run_reports(runs_dir)

    if not reports:
        print(f"No run reports found in {runs_dir}")
        return 1

    if client and not args.no_github:
        enriched: list = []
        for report in reports:
            enriched.append(check_pr_statuses(client, repo, report))
        reports = enriched

    metrics = compute_metrics(reports)
    run_id = datetime.utcnow().strftime("validation-%Y%m%d-%H%M%S")

    output_path = Path(args.output) if args.output else Path("reports/validation") / f"{run_id}.md"
    write_validation_report(metrics, output_path, title=args.title)
    print(f"Report written to: {output_path}")

    thresholds = load_thresholds()
    oversized_flag = metrics.oversized_count > 0

    print(f"\n=== Report Summary ===")
    print(f"  Run reports found: {len(reports)}")
    print(f"  Merged:            {metrics.total_merged}")
    print(f"  Success rate:      {metrics.success_rate:.1%}")
    print(f"  Oversized PRs:     {metrics.oversized_count}")
    if oversized_flag:
        for r in reports:
            if r.pr_loc is not None and is_oversized(r.pr_loc, r.pr_files or 0, 0.0, thresholds):
                print(f"    - PR #{r.pr_number}: {r.pr_loc} LOC, {r.pr_files} files")

    return 0


def _resolve_pr_for_number(client, repo: str, owner: str, num: int):
    """Resolve a PR-or-issue number to a single PullRequestInfo.

    Tries PR-by-number first (works for merged PRs whose branches were
    deleted by `--delete-branch` on merge). Falls back to the legacy
    `ai/fix-issue-{N}` branch lookup for issues whose PRs still have
    the conventional branch name (open PRs).

    Returns None when no PR is associated with the number.
    """
    pr = client.get_pull_request(repo, num)
    if pr is not None:
        return pr
    prs = client.get_pull_requests(repo, head=f"{owner}:ai/fix-issue-{num}")
    return prs[0] if prs else None


def cmd_check_prs(args: argparse.Namespace, config: dict[str, Any]) -> int:
    """Check PR statuses (merge state + CI) for a set of PR or issue numbers.

    Each input number is resolved as a PR first (works for merged PRs
    with deleted branches). Falls back to the legacy
    `ai/fix-issue-{N}` branch lookup for issues whose PRs still have
    the conventional branch name.
    """
    client, owner = _get_client(config)
    if client is None or owner is None:
        return 1
    repo = args.repo

    if args.numbers or args.issues:
        # Accept both `--numbers` (new) and `--issues` (deprecated
        # alias). Concatenate and dedupe, preserving order.
        raw = list(args.numbers or []) + list(args.issues or [])
        seen: set[int] = set()
        numbers: list[int] = []
        for x in raw:
            n = int(x)
            if n not in seen:
                seen.add(n)
                numbers.append(n)
    else:
        issues = client.get_repo_issues(repo, state="all")
        numbers = [i.number for i in issues][:args.max]

    print(f"Checking PRs for up to {len(numbers)} numbers...")
    checked = 0
    for num in numbers:
        pr = _resolve_pr_for_number(client, repo, owner, num)
        if pr is None:
            print(f"  #{num} [no PR]  (issue may not have a PR yet, or branch was renamed)")
            continue
        checked += 1
        merged = "MERGED" if pr.merged else "open"
        ci = "-"
        # CI runs on the PR head SHA, not the merge commit. The merge
        # commit is a brand-new commit that may have no checks or
        # pending re-runs. The head SHA is what the PR's CI actually
        # ran against and stays queryable even after --delete-branch.
        ci_sha = pr.head_sha or pr.merge_commit_sha
        if ci_sha:
            ci_status = client.get_combined_ci_status(repo, ci_sha)
            ci = "GREEN" if ci_status.state == "success" else "RED"
        print(f"  #{pr.number} [{merged}] CI:{ci}  {pr.title[:60]}")

    if checked == 0:
        print("  No PRs found.")
    return 0


def cmd_list(args: argparse.Namespace, config: dict[str, Any]) -> int:
    """List issues matching a label."""
    client, _owner = _get_client(config)
    if client is None:
        return 1
    repo = args.repo

    issues = select_issues_by_label(
        client=client,
        repo=repo,
        label=args.label,
        max_issues=args.max,
        state="open",
    )

    if not issues:
        print(f"No issues found with label '{args.label}' in {repo}")
        return 0

    print(f"Issues with label '{args.label}' (showing up to {args.max}):")
    for iss in issues:
        labels_str = ", ".join(iss.labels) if iss.labels else "-"
        print(f"  #{iss.number} [{iss.state}] {iss.title}")
        print(f"       labels: {labels_str}")
    return 0


def cmd_split(args: argparse.Namespace, config: dict[str, Any]) -> int:
    client, owner = _get_client(config)
    if client is None or owner is None:
        return 1
    repo = args.repo

    # Wrap the core client in a SplitGitHubClient so split.py can call
    # the file-listing / sub-issue-creation / close-issue helpers without
    # bloating ValidationGitHubClient beyond its line cap.
    from scripts.validation.split_client import SplitGitHubClient
    split_client = SplitGitHubClient(client)

    thresholds = load_thresholds(
        {"max_loc": args.max_loc, "max_files": args.max_files}
    )

    print(f"Decomposing PR #{args.pr}...")
    try:
        result = decompose_pr_to_sub_issues(
            client=split_client,
            repo=repo,
            pr_number=args.pr,
            close_parent=args.close_parent,
            report_path=args.report_path,
            thresholds=thresholds,
        )
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except RuntimeError as exc:
        print(f"GitHub API error: {exc}", file=sys.stderr)
        return 1

    if not result["is_oversized"]:
        print(f"PR #{args.pr} is not oversized ({result['total_loc']} LOC, {result['total_files']} files).")
        return 0

    print(f"\nPR #{args.pr} is oversized:")
    print(f"  Total LOC: {result['total_loc']}")
    print(f"  Total files: {result['total_files']}")
    print(f"  Sub-issues created: {len(result['sub_issues'])}")
    for s in result["sub_issues"]:
        print(f"    #{s['number']}: {s['title']}")
    if result.get("manual_review_files"):
        print(f"  Manual review needed for: {result['manual_review_files']}")

    if args.close_parent and result["sub_issues"]:
        sub_numbers = [s["number"] for s in result["sub_issues"]]
        close_parent_with_cross_ref(split_client, repo, args.pr, sub_numbers)
        print(f"  Parent PR #{args.pr} closed.")

    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="validation_run",
        description="AI Issue Solver — Validation Metrics & Run",
    )
    parser.add_argument("--repo", default="ai-issue-solver", help="Target repository (default: from --repo or config GITHUB_REPO)")
    parser.add_argument("--title", default="Validation Report", help="Report title (default: 'Validation Report')")

    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="Run solver on N issues and generate validation report")
    run_parser.add_argument("--issues", type=int, default=3, help="Number of issues to process")
    run_parser.add_argument("--label", default="ai-generated", help="Issue label filter")
    run_parser.add_argument("--model", default=None, help="Solver model type (e.g. opencode, mistral, claude). Reads OPENCODE_MODEL env if not set.")
    run_parser.add_argument("--model-name", default=None, help="Solver model name (e.g. opencode/deepseek-v4-flash-free). Reads OPENCODE_MODEL_NAME env if not set.")
    run_parser.add_argument("--max-run-cost-usd", type=float, default=None, help="Max cost per run in USD")
    run_parser.add_argument("--base-branch", default=None, help="Base branch for PRs")
    run_parser.add_argument("--dry-run", action="store_true", help="Simulate without actual solver invocation")
    run_parser.add_argument("--output", default=None, help="Output report path (default: reports/validation/<run-id>.md)")

    report_parser = subparsers.add_parser("report", help="Generate report from existing run reports")
    report_parser.add_argument("--runs-dir", default="reports/runs", help="Directory with run reports")
    report_parser.add_argument("--output", default=None, help="Output report path (default: reports/validation/<run-id>.md)")
    report_parser.add_argument("--no-github", action="store_true", help="Skip GitHub API enrichment")

    check_parser = subparsers.add_parser("check-prs", help="Check PR merge state and CI status")
    check_parser.add_argument(
        "--numbers", nargs="*", default=None,
        help="PR or issue numbers to check (accepts both — merged PRs with deleted branches are found by number)",
    )
    check_parser.add_argument(
        "--issues", nargs="*", default=None,
        help=argparse.SUPPRESS,  # deprecated alias for --numbers
    )
    check_parser.add_argument("--max", type=int, default=20, help="Max issues to check when no explicit list")

    list_parser = subparsers.add_parser("list", help="List issues matching a label")
    list_parser.add_argument("--label", default="ai-generated", help="Issue label filter")
    list_parser.add_argument("--max", type=int, default=20, help="Max issues to show")

    split_parser = subparsers.add_parser("split", help="Decompose an oversized PR into sub-issues")
    split_parser.add_argument("--pr", type=int, required=True, help="PR number to decompose")
    split_parser.add_argument("--close-parent", action="store_true", help="Close parent PR with cross-reference after decomposition")
    split_parser.add_argument("--report-path", default=None, help="Path to validation report for context")
    split_parser.add_argument("--max-loc", type=int, default=None, help="Override max LOC threshold (default: 500)")
    split_parser.add_argument("--max-files", type=int, default=None, help="Override max file threshold (default: 10)")

    return parser


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = build_parser()
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    config = _load_config()

    command_map = {
        "run": cmd_run,
        "report": cmd_report,
        "check-prs": cmd_check_prs,
        "list": cmd_list,
        "split": cmd_split,
    }

    handler = command_map.get(args.command)
    if handler is None:
        print(f"Unknown command: {args.command}", file=sys.stderr)
        return 1

    return handler(args, config)


if __name__ == "__main__":
    sys.exit(main())
