---
name: rework
description: Use when a generated PR or solver run needs targeted follow-up before merge, including red CI, green-but-risky PRs, oversized diffs, interrupted model output, superseded approaches, or user review feedback. Creates or updates explicit rework context before rerunning a model on the same branch or a fresh scoped branch.
---

# Rework

Use this skill when an AI-generated PR should not be merged as-is, even if it
has produced useful work. The goal is to make the next step explicit, narrow,
and reviewable instead of letting a branch become a mixed correction pile.

## Required Checks

Start with current repository and GitHub state:

```bash
git status --short --branch
gh pr view PR_NUMBER --json number,title,state,mergeable,headRefName,baseRefName,changedFiles,additions,deletions,commits,url
gh pr checks PR_NUMBER
gh pr diff PR_NUMBER --name-only
```

If CI failed, inspect the failing logs before rerunning a model:

```bash
gh run view RUN_ID --log-failed
```

## Rework Classification

Classify the PR or run before starting another solver:

- `tests_failed`: CI or local tests are red.
- `risky_pr_rework`: CI is green, but the PR is too large, too broad, or risky
  to merge without scope reduction.
- `partial_implementation`: useful work exists, but required behavior is
  incomplete.
- `superseded_approach`: the branch should be closed or replaced by a cleaner
  approach.
- `user_review_feedback`: user or reviewer gave concrete correction notes.

## Standard Flow

1. Add or update explicit context on the original issue or a rework issue.
2. State the exact next slice, for example "PR4 safe stop only".
3. Mark already completed sub-steps in the issue body when the original issue is
   split across several PRs.
4. If continuing the same PR branch, use the PR branch directly and keep the
   prompt focused on the failing or risky part only.
5. If replacing a broad or interrupted PR, close the old PR as superseded before
   starting a fresh scoped branch.

## Script Support

Preview a rework issue from a note:

```bash
python scripts/rework_workflow.py --from-note "PR #288 is CI green but too large for #223" --dry-run
```

Create a structured rework issue when needed:

```bash
python scripts/rework_workflow.py --from-pr 288 --rework-reason risky_pr_rework --apply --confirm-create
```

For same-branch rework with OpenCode, prefer a short prompt file that includes:

- current PR number and branch
- exact failure or review concern
- files allowed to change
- commands that must pass
- explicit out-of-scope items

## Merge Guard

Do not merge solely because checks are green. A generated PR still needs rework
when it is broad, interrupted, touches unexpected files, introduces stop/kill or
other high-risk behavior, or does not clearly match the issue slice.
