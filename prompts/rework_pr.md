# PR Rework: Apply Review Feedback

This is a **rework pass** on an existing pull request. Review feedback has been
provided that must be addressed by making additional changes on the same branch.

## Context

- **PR #{pr_number}** in `{owner}/{repo}`
- **Base branch:** `{base_branch}`
- **Head branch:** `{head_branch}` (the branch you will modify)
- **Current head commit:** `{head_sha}`
- **Reviewers:** {reviewer_usernames}

## Current Branch State

The PR branch already contains the following commits, newest first:

{existing_commits_list}

Your patch MUST be a minimal incremental diff that applies cleanly on top of
commit `{head_sha}`. Do not rewrite files from scratch against older PR or base
branch content. Reference files by their current post-`{head_sha}` content.

## PR Diff (current state vs base)

```
{diff}
```

## Review Feedback

The following review comments must be addressed:

{review_threads}

## Instructions

1. Apply the changes requested in the review feedback above.
2. Do NOT change files unrelated to the feedback.
3. Preserve the existing branch name — push follow-up commits to `{head_branch}`.
4. If a reviewer comment is unclear, use your best judgment to resolve it.
5. After applying changes, verify the code is syntactically correct.
6. Return only an incremental patch for the current branch tip `{head_sha}`.

## Constraints

- Only modify files that are relevant to the review feedback.
- Do not add new features beyond the scope of the feedback.
- Do not change existing test logic unless the feedback explicitly requests it.
- Do not reformat or restructure code unless the feedback asks for it.
