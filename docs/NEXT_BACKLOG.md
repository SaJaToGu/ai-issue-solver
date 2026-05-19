# Next Backlog

This backlog captures the next phase after the initial issue-solver workflow:
parallel execution, run visibility, and smoother review loops.

Create them as GitHub issues with:

```bash
python scripts/create_backlog_issues.py --backlog docs/NEXT_BACKLOG.md
python scripts/create_backlog_issues.py --backlog docs/NEXT_BACKLOG.md --apply --confirm-create
```

## 1. Add a bounded parallel issue runner

Labels: `automation`, `workflow`

Allow `solve_issues.py` or a dedicated batch script to process multiple issues in
parallel with a configurable worker limit. The runner should avoid duplicate
branches, keep output readable, and continue processing other issues when one
worker fails.

## 2. Persist run status and worker diagnostics

Labels: `automation`, `quality`

Write every solve run to a timestamped directory under `reports/runs/`. Store the
selected repo, issue number, branch, model, worker exit code, PR URL if created,
and a short output tail for debugging failed or partial runs.

## 3. Build a local status dashboard

Labels: `documentation`, `workflow`

Generate a simple local HTML dashboard from `reports/runs/` that shows running,
successful, failed, and no-op jobs. The dashboard should link to GitHub issues,
branches, and pull requests where available.

## 4. Add a PR and issue summary command

Labels: `github`, `workflow`

Add a command that prints a compact overview of open issues, open PRs, merged
PRs, and recently failed runs. It should work without requiring the GitHub CLI,
using the existing GitHub API configuration.

## 5. Improve interrupted-run recovery

Labels: `safety`, `automation`

Make it easy to resume after a stopped terminal, crashed worker, failed push, or
closed unmerged PR. The script should detect existing branches and PRs, explain
what it found, and either reuse them safely or ask the user to choose a new run.
