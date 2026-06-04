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

## 1. Benchmark non-Codex solver providers on tiny safe issues

Labels: `automation`, `quality`, `opencode`, `provider`

Priority: `high`

We need a small, repeatable benchmark for non-Codex solver paths before using
them for larger unattended work. OpenCode with Mistral Large is promising, and
OpenCode with Claude Sonnet should be tested as the next strong alternative.

Suggested scope:
- add a benchmark or smoke workflow that can run tiny safe issues against
  selected non-Codex providers
- include at least OpenCode + `mistral/mistral-large-latest` and OpenCode +
  `claude-sonnet-4-20250514`
- keep benchmark issues narrow, low-risk, and explicitly targeted at this repo
- record whether each provider created a PR, changed files, passed tests, or
  produced no changes
- avoid Aider for this benchmark
- do not read or expose secret files such as `config/.env` or provider auth
  files

Checks:
- `git diff --check`
- `python -m unittest discover -s tests`

## 2. Make OpenRouter Direct file-edit capable

Labels: `automation`, `quality`, `provider`

Priority: `high`

The direct OpenRouter worker path should be verified and hardened so it can
actually modify files in the worker checkout, not just return API text. This is
the key requirement before OpenRouter can be a practical non-Aider fallback.

Suggested scope:
- inspect the current `openrouter_direct` worker integration end to end
- ensure model output is converted into file edits or patches that are applied
  safely in the worker repo
- make failures explicit when the model returns prose without actionable edits
- support `mistralai/mistral-large` as the default test model
- add tests for successful patch application, no-op output, malformed patches,
  and missing `OPENROUTER_API_KEY`
- do not read or expose secret files such as `config/.env`

Checks:
- `git diff --check`
- `python -m unittest discover -s tests`

## 3. Add provider scorecard to run reports

Labels: `automation`, `quality`, `workflow`

Priority: `medium`

Provider comparisons are currently manual and scattered across console output,
run reports, and PR outcomes. Each solver run should write a compact scorecard
that makes provider quality and stability comparable across Codex alternatives.

Suggested scope:
- add provider scorecard fields to run metadata and summaries
- include requested model, actual model, fallback source, duration, worker exit
  code, run status, PR URL, test command/result if available, and no-change
  classification
- surface provider scorecards in overnight summaries or the status dashboard
- keep the scorecard compact enough for quick review
- add tests for successful PR runs, no-change warnings, failed workers, and
  fallback runs
- avoid storing secrets or full prompts in scorecard data

Checks:
- `git diff --check`
- `python -m unittest discover -s tests`
