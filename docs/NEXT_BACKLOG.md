# Next Backlog

This backlog captures the next phase after the parallel workflow is available:
running longer unattended sessions, keeping the dashboard truthful, and reducing
manual review cleanup after generated PRs.

Create them as GitHub issues with:

```bash
python scripts/create_backlog_issues.py --backlog docs/NEXT_BACKLOG.md
python scripts/create_backlog_issues.py --backlog docs/NEXT_BACKLOG.md --apply --confirm-create
```

## 1. Add a dashboard cleanup command for stale and legacy runs

Labels: `workflow`, `quality`

Add a small command or status-dashboard option that can mark old legacy run
reports as successful, failed, no-op, or archived. It should avoid editing recent
active runs by default, show a dry-run preview first, and make the dashboard stop
counting incomplete historical reports as active work.

## 2. Add an unattended overnight runner

Labels: `automation`, `workflow`

Create a wrapper command for longer unattended sessions. It should pull the base
branch, run tests before starting, invoke the bounded batch solver with a worker
limit, regenerate the dashboard, write a final summary, and keep enough logs to
review the run the next morning.

## 3. Reschedule batch jobs after Codex rate limits

Labels: `codex`, `automation`, `safety`

When a worker hits the Codex message limit, the batch runner should not burn the
same issue repeatedly. It should recognize the reset time from the worker output,
record the issue as delayed, sleep or requeue it for after the reset when
configured, and continue processing other available jobs.

## 4. Add a post-merge cleanup helper

Labels: `github`, `workflow`

Add a command that summarizes merged AI PRs, closes their referenced issues when
safe, deletes stale AI branches, and reports anything that still needs manual
review. It should use the existing GitHub API configuration and support a dry-run
mode before changing GitHub state.
