---
name: git-cleanup
description: Use before repository cleanup, branch deletion, stale branch review, merge hygiene, or any potentially destructive Git/GitHub maintenance in ai-issue-solver. Checks local state, branch tracking, PR/issue context, and refuses unsafe cleanup unless the user explicitly confirms it.
---

# Git Cleanup

Use this skill before deleting branches, pruning refs, merging cleanup PRs, or
changing repository state after automated agent work.

## Safety Rules

- Never delete or overwrite uncommitted user changes.
- Never use `git reset --hard`, `git checkout --`, or forced deletion unless the
  user explicitly confirmed the exact target.
- Prefer `git branch -d`; use `git branch -D` only after proving the branch is
  merged, superseded, or intentionally abandoned.
- Treat closed-unmerged PR branches and open issues as "review first".
- Keep local cleanup separate from remote branch deletion.

## Required Checks

Run these first:

```bash
git status --short --branch
git branch -vv --sort=-committerdate
git branch -r --sort=-committerdate
gh pr list --state open --limit 50 --json number,title,headRefName,baseRefName,isDraft,mergeStateStatus,url
```

If network or GitHub auth fails, continue with local-only analysis and clearly
mark the missing evidence.

## Branch Classification

Classify each candidate branch as one of:

- `safe-delete`: merged into target branch, cherry-pick equivalent, or superseded
  by a merged PR.
- `review-first`: has unique commits, open issue, closed-unmerged PR, or unclear
  purpose.
- `keep`: active branch, open PR branch, current branch, or user-owned work.
- `remote-review`: remote-only branch that needs separate confirmation before
  deletion.

Use targeted evidence:

```bash
git branch --merged origin/develop
git branch --no-merged origin/develop
git log --left-right --cherry-pick --oneline origin/develop...BRANCH
git diff --stat origin/develop...BRANCH
gh pr list --state all --search "head:BRANCH" --limit 20 --json number,title,state,mergedAt,closedAt,url
```

## Output Format

Report:

- current branch and working tree status
- open PR count
- `safe-delete` branches with evidence
- `review-first` branches with reason
- remote-only branches that need separate review
- exact commands to run, or execute them only after user confirmation

After deleting branches, run:

```bash
git fetch origin --prune
git status --short --branch
git branch -vv --sort=-committerdate
git branch -r --sort=-committerdate
```
