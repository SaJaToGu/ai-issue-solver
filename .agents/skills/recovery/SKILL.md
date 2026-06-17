---
name: recovery
description: Use when an ai-issue-solver run was interrupted, failed after producing changes, preserved a worktree, left stale branches, or needs safe resume/retry guidance. Inspects run reports, preserved worktrees, GitHub PR/issue state, and recommends resume, push, delete, or retry actions.
---

# Recovery

Use this skill to recover safely after interrupted solver runs, failed pushes,
no-op workers, stale benchmark branches, or preserved worktrees.

## Goals

- Preserve useful agent work.
- Avoid duplicate PRs and branch collisions.
- Distinguish model failure from pipeline failure.
- Resume from existing artifacts when safer than rerunning.

## Required Checks

Start with repository state:

```bash
git status --short --branch
gh pr list --state open --limit 50 --json number,title,headRefName,baseRefName,url
gh issue list --state open --limit 100 --json number,title,labels,url
```

Find run artifacts:

```bash
find reports/runs -maxdepth 2 -type f \( -name summary.txt -o -name metadata.json -o -name worker-output.log \) 2>/dev/null
find reports/preserved-worktrees -maxdepth 2 -type d 2>/dev/null
```

For a specific run, inspect only the relevant files:

```bash
sed -n '1,220p' reports/runs/RUN_ID/summary.txt
sed -n '1,220p' reports/runs/RUN_ID/metadata.json
tail -120 reports/runs/RUN_ID/worker-output.log
```

## Recovery Classification

Classify each artifact as:

- `resume`: branch or preserved worktree has meaningful changes and no open PR.
- `push-pr`: changes are complete, tests pass, push or PR creation failed.
- `retry-clean`: no useful changes, runtime error, or no-op worker.
- `manual-review`: tests failed but changes may still be valuable.
- `delete`: stale artifact with superseded or merged work.

Useful signals:

- `status: push_failed` with `preserved_worktree` usually means pipeline failure,
  not model failure.
- `worker_exit_code: 0` plus git diff and passing tests is a strong recovery
  candidate.
- `status: started` without worker output is an interrupted run.
- no changes plus server error is usually `retry-clean`.
- closed-unmerged PR requires reviewing the PR comment before reusing work.

## Worktree Recovery

For preserved worktrees, check:

```bash
cd PRESERVED_WORKTREE
git status --short
git diff --stat origin/main...HEAD || git diff --stat origin/develop...HEAD
git log --oneline --decorate --max-count=10
```

If the worktree is useful:

- prefer a fresh branch name if the original branch had a closed-unmerged PR
- run targeted tests before pushing
- create a PR with clear recovery context

## Output Format

Report:

- run or artifact id
- issue and repository
- model/provider
- status and failure class
- whether changes exist
- test signal
- recommended action: `resume`, `push-pr`, `retry-clean`, `manual-review`, or
  `delete`
- exact next command, if safe

Do not delete preserved worktrees unless the user explicitly approves the
specific path.
