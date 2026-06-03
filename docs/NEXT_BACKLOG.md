# Next Backlog

> **📌 Sprachhinweis / Language Note:**
> Diese Datei bleibt bewusst auf Englisch, da sie als Vorlage für GitHub Issues dient
> und von KI-Workern verarbeitet wird. Siehe [Sprachrichtlinie](LANGUAGE_POLICY.md)
> This file remains in English as it serves as a template for GitHub Issues and is
> processed by AI workers. See [Language Policy](LANGUAGE_POLICY.md)

This backlog captures the next technical ai-issue-solver provider phase.
Private personal ideas belong in the separate private `guido-project-lab`
repository and must not be added here.

Create selected items as GitHub issues with:

```bash
python scripts/create_backlog_issues.py --backlog docs/NEXT_BACKLOG.md
python scripts/create_backlog_issues.py --backlog docs/NEXT_BACKLOG.md --apply --confirm-create
```

Clean up completed items after their GitHub issues are closed with:

```bash
python scripts/cleanup_backlog.py --backlog docs/NEXT_BACKLOG.md
python scripts/cleanup_backlog.py --backlog docs/NEXT_BACKLOG.md --apply --confirm-remove
```

## 1. Treat no-change worker runs as warnings in batch and overnight summaries

Labels: `automation`, `quality`, `workflow`

Priority: `high`

The batch and overnight runners can currently report a job as `OK` when the
inner solver process exits with code 0 even though the run report says no
changes were produced and no PR was created.

Suggested scope:
- classify `no_changes` and `nonzero_without_changes` run reports as warnings
  or failures in batch summaries
- surface the inner run status, PR URL, and issue number in overnight summaries
- keep successful PR-creating runs clearly separate from no-op worker runs
- add tests for mixed batches with PR-created and no-change runs

Checks:
- `git diff --check`
- `python -m unittest discover -s tests`

## 2. Constrain OpenCode worker reads to repo-relative paths

Labels: `automation`, `quality`, `opencode`

Priority: `high`

OpenCode can still request file reads through absolute temporary worktree paths,
which the Codex app permission model treats as external directory access. The
worker should stay within repo-relative paths while running in the cloned
worktree.

Suggested scope:
- start OpenCode in a way that avoids model-visible absolute temp paths
- ensure OpenCode prompts prefer repo-relative paths such as `docs/WORKFLOW.md`
- add tests that catch absolute temp-path leakage in OpenCode prompts/commands
- preserve existing Codex, OpenRouter, Mistral Vibe, and Aider behavior

Checks:
- `git diff --check`
- `python -m unittest discover -s tests`

## 3. Add secret-file guardrails for AI worker prompts

Labels: `safety`, `automation`, `quality`

Priority: `high`

Worker runs should avoid reading or copying real secret files such as
`config/.env`. Credential and preflight issues should inspect code and example
configuration only, never local secret values.

Suggested scope:
- add a small denylist for worker-visible prompt targets such as `config/.env`
  and other local secret files
- allow safe example files such as `config/config.example.env` only when needed
- document the rule in the worker setup docs
- add tests showing secret files are not copied, targeted, or encouraged in
  worker prompts

Checks:
- `git diff --check`
- `python -m unittest discover -s tests`

## 4. Document night-mode issue selection and OpenCode/Mistral calibration

Labels: `documentation`, `workflow`, `opencode`

Priority: `medium`

Night-mode runs should start with safe, narrow issues while OpenCode/Mistral is
being calibrated. The workflow should explain which issues are suitable and which
ones should wait for manual supervision.

Suggested scope:
- document the OpenCode -> Mistral command for overnight runs
- recommend `--workers 1` and explicit `--issue` flags during calibration
- avoid unattended issues touching credentials, `config/.env`, provider auth, or
  multi-repo access
- include the direct OpenCode smoke-test command

Checks:
- `git diff --check`
- `python -m unittest discover -s tests`

## 5. Improve OpenCode runtime health diagnostics for WAL and edit-loop failures

Labels: `automation`, `quality`, `opencode`

Priority: `medium`

OpenCode runs can fail before worker execution with SQLite/WAL checkpoint
errors, and some runs can get stuck in repeated edit failures. The solver should
make those known OpenCode failure modes visible in console output and run
reports instead of treating them as generic worker failures.

Suggested scope:
- detect OpenCode SQLite/WAL checkpoint failures such as
  `PRAGMA wal_checkpoint(PASSIVE)` in worker output
- surface a concise German warning with the documented recovery hint: stop
  OpenCode processes, then remove only `opencode.db-wal` and `opencode.db-shm`
- detect repeated OpenCode edit failures such as `Edit README.md failed` and
  classify or report them as an edit-loop risk when possible
- keep the implementation small and avoid broad refactors
- do not read or copy real secret files such as `config/.env`
- safe example files such as `config/config.example.env` and `.env.example`
  remain allowed

Checks:
- `git diff --check`
- `python -m unittest tests.test_solve_issues`
- `python -m unittest discover -s tests`

## 6. Slim README into quickstart and move operational details to docs

Labels: `documentation`, `quality`, `workflow`

Priority: `medium`

The README has grown into a full operational handbook. It should become a
shorter quickstart again, while detailed script behavior, provider setup,
night-mode guidance, dashboard usage, and recovery notes live in dedicated docs.

Suggested scope:
- keep README focused on project purpose, quickstart, core commands, and links
  to detailed documentation
- move or link detailed provider setup to `docs/SETUP_AIDER.md`
- move or link workflow, batch, dashboard, and night-mode details to
  `docs/WORKFLOW.md`
- avoid deleting useful documentation; preserve it in the appropriate docs file
- keep the README change reviewable and avoid broad unrelated rewrites
- add a short README maintenance rule so future small workflow issues do not
  expand README by dozens of lines

Checks:
- `git diff --check`
- `python -m unittest discover -s tests`
