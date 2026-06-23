"""validation — 0.9.0 Validation Metrics & Run package.

Split from monolithic scripts/validation_run.py (1570 LOC) into modules:

  models         — data classes
  parsers        — summary.txt + run-report reading
  pr_checks      — check_pr_statuses + GitHub merge/CI helpers
  selection      — issue selection by label
  github_client  — ValidationGitHubClient wrapping the GitHub API
  runner         — subprocess orchestration for solver + reviewer
  metrics        — compute_metrics, format_duration, generate_report,
                   validation-run persistence, is_oversized
  git_notes      — read/write refs/notes/ais for parent_pr → sub_issues
  split          — decompose oversized PRs into sub-issues
  split_client   — SplitGitHubClient for the backward-split flow
  cli            — argparse subcommands + main entry point

Entry point: ``validation.cli.main``. ``validation_run.py`` (the
sibling shim in scripts/) imports it directly to avoid the
circular import that would happen if this __init__ itself pulled
``from validation.cli import main`` (cli.py imports from sibling
modules like ``validation.github_client`` which on first load
re-enters this __init__).
"""

__all__ = [
    "models",
    "parsers",
    "pr_checks",
    "selection",
    "github_client",
    "runner",
    "metrics",
    "git_notes",
    "split",
    "split_client",
    "cli",
]

