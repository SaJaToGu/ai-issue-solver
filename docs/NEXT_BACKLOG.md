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

## 11. Extract repository checkout and branch lifecycle from solve_issues.py

Labels: `automation`, `quality`, `workflow`, `refactor`

Priority: `1`

`scripts/solve_issues.py` has grown too large and mixes repository checkout,
branch recovery, commit/push, PR creation, worker execution, reporting, and
cleanup. The first safe refactoring step should extract repository checkout and
branch lifecycle behavior into a focused module without changing user-facing
solver behavior.

Suggested scope:
- create a focused module for repository checkout, branch creation/reuse,
  remote branch checkout, branch diff checks, commit, push, and PR lifecycle
  helpers
- keep isolated per-run checkout behavior from issue #193 intact
- make checkout paths, branch names, and run directories explicit data passed
  between functions instead of implicit local variables
- preserve recovery behavior for existing branches and preserved worktrees
- keep GitHub tokens out of logs, reports, exceptions, and test snapshots
- add tests around clone failure stderr, existing remote branch reuse, branch
  diff detection, commit/push failure, and PR lifecycle handoff
- keep the public CLI behavior and existing report formats compatible

Checks:
- `git diff --check`
- `python -m unittest discover -s tests`

## 12. Extract worker execution adapters from solve_issues.py

Labels: `automation`, `quality`, `workflow`, `provider`, `refactor`

Priority: `1`

Worker-specific command construction and execution for Codex, OpenCode, Aider
style providers, Mistral Vibe, and OpenRouter Direct should move behind a small
adapter interface. This will make provider behavior easier to test and reduce
the risk that changes for one worker break another.

Suggested scope:
- define a small worker adapter protocol or dataclass for build, run, output
  filtering, diagnostics, and result classification
- move Codex, OpenCode, OpenRouter Direct, Mistral Vibe, and Aider-style
  behavior out of the main solver flow into focused modules
- preserve existing CLI flags and model names
- keep provider-specific secret handling and environment pruning covered by
  tests
- keep full raw worker output available in diagnostics while using the shared
  live-output filter in normal mode
- make no-change, nonzero-with-changes, rate-limit, and failed-worker outcomes
  consistent across adapters
- add adapter-level tests that do not call real provider APIs or CLIs

Checks:
- `git diff --check`
- `python -m unittest discover -s tests`

## 13. Extract run reporting, diagnostics, and health state from solve_issues.py

Labels: `automation`, `quality`, `workflow`, `dashboard`, `refactor`

Priority: `1`

Run reports, worker diagnostics, health files, preserved worktree notes, and
dashboard-facing status metadata should be managed outside the main solver
script. This extraction should prepare the codebase for issue #194 job
heartbeats without forcing that feature into the same change.

Suggested scope:
- move run report creation, metadata writing, summaries, diagnostics, health
  updates, and preserved worktree notes into focused modules
- keep existing report file names and fields compatible unless a migration is
  explicitly documented
- expose a small API for status transitions such as started, cloned, running
  worker, validating, committing, creating PR, failed, warning, and completed
- make health updates safe for concurrent jobs writing to distinct run
  directories
- keep dashboard parsing compatible with existing historical reports
- add tests for report compatibility, health writes, preserved worktree notes,
  and stale/missing report data
- do not write secrets, full provider auth contents, or raw tokens to reports

Checks:
- `git diff --check`
- `python -m unittest discover -s tests`

## 14. Add per-run resource ownership and locking for parallel solver jobs

Labels: `automation`, `quality`, `workflow`, `parallelism`, `refactor`

Priority: `1`

Parallel solver jobs should have explicit ownership of their checkout,
temporary directory, report directory, health file, branch, and PR lifecycle.
Shared resources should be minimized and guarded so same-repo and same-issue
runs do not collide during benchmarks or unattended batches.

Suggested scope:
- define a per-run resource model with checkout path, temp path, report path,
  branch name, issue key, provider/model, and cleanup policy
- ensure same-repo parallel jobs never share mutable checkout directories
- add issue/branch-level locking or conflict detection for resources that must
  remain unique, especially branch names and PR creation
- keep provider auth and cache directories shared only when safe and documented
- make lock acquisition, stale lock cleanup, and lock failure diagnostics visible
  in run reports and batch summaries
- support same-issue benchmark groups by requiring distinct branch names or
  explicit comparison IDs
- add tests for two parallel same-repo runs, two same-issue provider attempts,
  stale locks, branch-name conflicts, and cleanup after failed runs
- avoid storing secrets in lock files, paths, or report metadata

Checks:
- `git diff --check`
- `python -m unittest discover -s tests`

## 10. Add configurable worker verbosity and job heartbeats

Labels: `automation`, `quality`, `workflow`, `dashboard`

Priority: `1`

Worker output is currently filtered to avoid noisy patch/code floods, but long
runs are still hard to supervise from Codex or a phone. The solver should expose
clear job heartbeats and configurable verbosity so a run can be followed without
starting separate parallel monitoring commands.

Suggested scope:
- add a worker output mode such as `quiet`, `normal`, and `verbose` for
  `solve_issues.py`, `solve_issues_batch.py`, and overnight runs
- keep `normal` compact by surfacing status lines such as plan, read, write,
  edit, tests, warnings, errors, and final result
- make `verbose` show more live worker output for debugging while still keeping
  secrets and known auth paths hidden
- make Codex output more compact in `normal` mode while preserving full raw
  output in diagnostics
- write regular per-job heartbeat updates to run metadata or `health.json`,
  including phase, runtime, last worker activity time, last surfaced signal,
  current worker/model, issue, branch, and run report directory
- update heartbeats during clone, worker execution, validation, commit, PR
  creation, and cleanup phases
- teach batch and overnight runners to read these heartbeats instead of needing
  external `ps`/parallel polling for basic liveness
- surface heartbeat status in summaries and the dashboard so running jobs show
  alive, stalled, waiting, failed, or completed states
- include clear stale-heartbeat behavior and health-timeout diagnostics
- keep full raw output in run reports but never write secrets, API keys, or
  provider auth file contents
- add tests for verbosity modes, heartbeat updates across phases, stale
  heartbeat detection, and dashboard rendering of running jobs

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

## 15. Add vertical process quality analysis and periodic workflow retrospective

Labels: `automation`, `quality`, `workflow`, `dashboard`

Priority: `2`

The solver should not only move forward through the backlog but periodically
step back and assess quality at every stage of its own workflow. After a
configurable number of solved issues per repository, or on demand, it should
analyse each workflow step — analysis, issue creation, worker execution,
validation, commit, PR creation, and review — and surface patterns, regressions,
and improvement opportunities before the next batch starts.

A periodic comparison with structurally similar open-source solver projects
should also be included so the project does not optimise in isolation.

Suggested scope:
- define the workflow steps to be assessed: repo analysis, issue creation,
  worker execution (per provider), validation, commit/push, PR creation,
  and post-merge cleanup
- collect per-step quality signals from existing run reports: success rate,
  no-change rate, failure mode distribution, median runtime, retry count,
  and open vs closed PR ratio per step and per provider
- trigger a retrospective automatically after a configurable number of solved
  issues per repository (for example every 10 issues), and expose it as an
  explicit `--retrospective` mode or standalone script
- produce a structured retrospective report per repository with findings per
  workflow step, trend direction (improving, stable, degrading), and suggested
  next actions such as retry threshold adjustment, provider swap, or backlog
  reprioritisation
- include a periodic comparison with structurally comparable open-source
  AI-assisted issue solver projects to avoid local optimisation traps; record
  comparable metrics, approach differences, and transferable ideas
- surface retrospective findings in the dashboard and overnight summaries so
  they are visible without running a separate command
- keep retrospective reports free of secrets, API keys, provider auth contents,
  and raw prompts
- add tests for retrospective triggering logic, per-step signal collection,
  trend detection, and report formatting with missing or partial run data

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
