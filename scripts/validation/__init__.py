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
  cli            — argparse subcommands + main entry point
"""
from validation.cli import main

__all__ = ["main"]
