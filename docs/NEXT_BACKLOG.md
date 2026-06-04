# Next Backlog

> **📌 Sprachhinweis / Language Note:**
> Diese Datei bleibt bewusst auf Englisch, da sie als Vorlage für GitHub Issues dient
> und von KI-Workern verarbeitet wird. Siehe [Sprachrichtlinie](LANGUAGE_POLICY.md)
> This file remains in English as it serves as a template for GitHub Issues and is
> processed by AI workers. See [Language Policy](LANGUAGE_POLICY.md)

This backlog captures the next technical ai-issue-solver provider phase.
Private personal ideas belong in the separate private `guido-project-lab`
repository and must not be added here.

Priority uses numeric ordering: `1` is highest urgency; larger numbers are
lower priority. Section numbers are stable backlog identifiers, not priority.

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

Priority: `1`

We need a small, repeatable benchmark for non-Codex solver paths before using
them for larger unattended work. OpenCode with Mistral Large is promising, and
OpenCode with Claude Sonnet should be tested as the next strong alternative.

Suggested scope:
- add a benchmark or smoke workflow that can run tiny safe issues against
  selected non-Codex providers
- include at least OpenCode + `mistral/mistral-large-latest` and OpenCode +
  `anthropic/claude-sonnet-4-6`
- keep benchmark issues narrow, low-risk, and explicitly targeted at this repo
- support running multiple providers against the same issue or benchmark fixture
  in isolated branches/worktrees so results are directly comparable
- include free or low-cost coding candidates where available, especially
  DeepSeek, Qwen Coder, and MiniMax/MiniMax-M1, alongside Mistral Large and
  Claude Sonnet
- record same-issue comparison groups with a stable benchmark ID, issue number,
  provider, model, branch, commit, PR, and test outcome
- record whether each provider created a PR, changed files, passed tests, or
  produced no changes
- avoid Aider for this benchmark
- do not read or expose secret files such as `config/.env` or provider auth
  files

Checks:
- `git diff --check`
- `python -m unittest discover -s tests`

## 8. Automate model selection by issue type, expected performance, and cost

Labels: `automation`, `quality`, `provider`, `workflow`

Priority: `1`

The solver should not require manual model selection for every issue. It should
use measured provider performance, rough cost, repository type, issue risk, and
task category to recommend or select the cheapest model that is likely to solve
the problem safely.

Suggested scope:
- collect comparable provider performance data from run reports and provider
  scorecards
- classify issues by task type, for example docs-only, tests, Python, R,
  dashboard/UI, provider integration, refactor, CI failure, or low-code repo
- estimate risk and required model strength from touched files, labels, issue
  text, repo type, and historical failure modes
- add a model selection policy that can choose or recommend providers such as
  OpenCode + Mistral Large, OpenCode + Claude Sonnet, OpenRouter Direct,
  DeepSeek, Qwen Coder, MiniMax/MiniMax-M1, local Ollama, or Codex as last
  resort
- include cost ceilings and escalation rules, for example try cheaper models
  first for low-risk docs/tasks and escalate only after no-change or failed runs
- prefer free or low-cost model candidates for benchmark and low-risk issues
  when prior same-issue results are good enough
- make the decision transparent in run reports and dashboard: selected model,
  reason, expected cost tier, and fallback plan
- use dashboard comparison metrics as one input for future model selection,
  while keeping explicit safeguards for low sample sizes and stale benchmark
  data
- prefer same-issue benchmark groups over cross-issue averages when ranking
  models for a task type
- keep manual override flags for model, model name, max cost tier, and
  no-Codex mode
- add tests for model selection across issue categories, missing cost data,
  failed-history fallback, and manual overrides
- do not expose API keys, provider auth files, or full prompts in selection
  metadata

Checks:
- `git diff --check`
- `python -m unittest discover -s tests`

## 2. Make OpenRouter Direct file-edit capable

Labels: `automation`, `quality`, `provider`

Priority: `1`

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

## 6. Support low-code and non-code repositories without Python assumptions

Labels: `automation`, `quality`, `workflow`, `analysis`

Priority: `2`

The solver should handle repositories that contain little or no application
code, such as documentation, research notes, prompt collections, data-only
repositories, planning repos, or mixed-language projects. Python must not be
treated as mandatory unless the target repo actually uses Python.

Suggested scope:
- detect repository type and dominant stack before selecting checks or worker
  instructions
- support low-code/no-code repo classes such as docs-only, research, data,
  templates, configuration, and project-management repositories
- choose validation commands based on detected files, for example markdown
  checks for docs, R checks for R repos, npm checks for JS repos, and no forced
  Python tests when no Python project exists
- make no-op or documentation-only changes first-class successful outcomes when
  they satisfy the issue
- show the detected repo type and selected validation plan in run reports
- add tests for Python, R, docs-only, and empty/minimal repository fixtures
- do not read or expose secret files such as `.env`, provider auth files, or API
  keys

Checks:
- `git diff --check`
- `python -m unittest discover -s tests`

## 7. Build dashboard UI for cost, runtime, and backlog prioritization

Labels: `automation`, `quality`, `workflow`, `dashboard`

Priority: `1`

The status dashboard should help decide what to run next and what it costs.
Provider choice, runtime, rough cost, success rate, and backlog priority should
be visible in one UI so Codex usage can be conserved and cheaper alternatives
can be tested deliberately.

Suggested scope:
- organize the dashboard into tabs such as Overview, Model Comparison,
  Backlog/Prioritization, Run List, and Diagnostics
- add dashboard sections for provider/model, runtime, worker status, PR URL,
  issue status, and rough cost estimate when token or provider data is available
- add a model comparison view that aggregates runs by provider and model
- support same-issue comparison groups so several model attempts on one issue
  can be reviewed side by side
- show comparable metrics such as success rate, PR-created rate, no-change rate,
  failure rate, median runtime, estimated cost per successful PR, and manual
  review notes
- keep an aggregated overview tab for current state, open issues, open PRs,
  spend/runtime summary, and next recommended actions
- keep an analysis tab for provider/model comparisons, trend charts, scorecards,
  and cost/performance tradeoffs
- in the analysis tab, show side-by-side diffs and outcomes for models that ran
  against the same issue or benchmark fixture
- keep a run list tab for raw run reports with filters, sorting, lifecycle
  status, PR links, issue links, and failure diagnostics
- show backlog priority numbers and sort/filter issues by priority, risk, repo
  type, and suggested provider
- make cost fields explicit about confidence level, for example exact from
  provider metadata, estimated from tokens, or unavailable
- surface no-change, warning, failed, delayed, and successful runs separately
- include controls or generated commands for safe next actions, such as
  run with Mistral Large, run with Claude Sonnet, retry failed, or cleanup
  completed backlog
- keep secrets out of dashboard data and logs
- add tests for dashboard rendering, sorting, missing cost data, and mixed
  provider runs
- add tests for model comparison tables with missing, partial, and conflicting
  scorecard data

Checks:
- `git diff --check`
- `python -m unittest discover -s tests`

## 3. Add provider scorecard to run reports

Labels: `automation`, `quality`, `workflow`

Priority: `2`

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

## 4. Evaluate best non-Codex model for R-based reproducible Bullwhip Game work

Labels: `automation`, `quality`, `provider`, `research`

Priority: `4`

We need to identify which non-Codex model is strongest for R-heavy work such as
a reproducible Bullwhip Game implementation. The target workflow should cover
R scripts, package-style project structure, deterministic simulations, tests,
and possibly Shiny or Quarto documentation.

Suggested scope:
- define a small reproducible Bullwhip Game benchmark repository or fixture in R
- compare Claude Code, OpenCode + Claude Sonnet, OpenCode + Mistral Large,
  OpenRouter Direct + Mistral Large, DeepSeek, Qwen Coder, MiniMax/MiniMax-M1,
  and Cursor Web/Mobile if practical
- evaluate R-specific quality: idiomatic tidyverse/base R usage, reproducible
  random seeds, `testthat` tests, simulation correctness, plotting, and
  documentation
- include dependency handling with `renv`, `DESCRIPTION`, or clearly documented
  install steps where appropriate
- measure whether the model can diagnose failing R tests and repair the code
  without touching unrelated files
- record results in the provider scorecard once available
- do not read or expose secret files, API keys, or local provider auth files

Checks:
- `git diff --check`
- `python -m unittest discover -s tests`

## 5. Evaluate mobile-first Claude Code alternative to Codex

Labels: `automation`, `quality`, `provider`, `workflow`

Priority: `1`

Codex usage should be conserved when possible. We need a practical alternative
that can be used from a phone in a similar supervision style, with comparable
quality for GitHub issue solving and pull request creation.

Suggested scope:
- evaluate Claude Code on the web/mobile app with GitHub repositories as the
  primary Codex alternative
- compare Cursor Web/Mobile Agent as a secondary candidate
- define a phone-first workflow for starting tasks, reviewing progress,
  responding to clarifying questions, and reviewing generated PRs
- test against tiny safe issues in this repo before using it for larger work
- compare quality against Codex using concrete outcomes: PR created, tests
  passed, review effort, runtime, cost, and failure mode
- document setup requirements, GitHub permissions, mobile limitations, and
  rollback/recovery steps
- do not read or expose secret files such as `config/.env`, provider auth
  files, or API keys

Checks:
- `git diff --check`
- `python -m unittest discover -s tests`
