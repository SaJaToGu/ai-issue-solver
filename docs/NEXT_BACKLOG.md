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

Labels: `kind/automation`, `theme/quality`, `area/opencode`, `theme/provider`

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

Labels: `kind/automation`, `theme/quality`, `theme/provider`, `theme/workflow`

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

## 16. Use GitHub repository intelligence before local repo type detection

Labels: `kind/automation`, `kind/analysis`, `theme/quality`, `theme/workflow`, `theme/github`

Priority: `1`

The solver should use GitHub's existing repository intelligence before falling
back to local repo type detection. GitHub already exposes language shares,
repository metadata, topics, file trees, workflows, issues, PRs, and checks. We
should avoid rebuilding a large Linguist-like detector locally.

Context:
- PR #211 attempted to solve #188 by adding a large local
  `repo_type_detection.py` implementation.
- That approach passed CI after a small fix, but it duplicated GitHub data and
  increased maintenance surface.
- We are GitHub-first in practice; generic/non-GitHub support can remain a
  fallback abstraction.

Suggested scope:
- add a `RepoProfileProvider` abstraction
- implement `GitHubRepoProfileProvider` as the primary provider
- keep a thin `LocalRepoProfileProvider` fallback for offline, non-GitHub, or
  already-checked-out repositories
- use GitHub REST data first:
  - `/repos/{owner}/{repo}/languages` for language byte shares and dominant
    language
  - repo metadata for default branch, archived/private state, size, and
    description
  - topics for explicit project signals
  - recursive git tree or contents API for marker files
  - workflows/actions metadata for validation hints
  - existing PR/check/issue state to avoid duplicate work
- use local marker heuristics only for details GitHub does not provide, for
  example `DESCRIPTION`, `renv.lock`, `app.R`, `inst/shiny/app.R`,
  `pyproject.toml`, and `package.json`
- expose a structured `RepoProfile` in run reports:
  - `dominant_language`
  - `language_percentages`
  - `repo_kind`
  - `framework_hints`
  - `test_hints`
  - `recommended_worker`
  - `python_required`
- make #188 solvable without assuming Python is mandatory
- do not read or expose secret files such as `.env`, provider auth files, or
  API keys

Checks:
- `git diff --check`
- `python -m unittest discover -s tests`

## 17. Add workflow control for backlog and PR queue congestion

Labels: `kind/automation`, `theme/workflow`, `theme/dashboard`, `theme/quality`

Priority: `1`

The solver should detect and surface workflow congestion before starting more
automated work. Congestion includes too many open PRs, open issues that already
have PRs, stale generated branches, unresolved red checks, superseded
approaches, and backlog items that were converted into issues but not cleaned
up.

Suggested scope:
- detect open PR count, red PR count, green-but-unreviewed PR count, and stale
  PR age
- map open PRs back to issues and backlog entries
- warn before starting new solver runs when unresolved PRs exceed a
  configurable threshold
- recommend the next workflow action: review, merge, close, rebase, rerun,
  create follow-up, or clean backlog
- add a process status section to the dashboard and overnight summary
- show backlog entries that already have matching issues or merged/closed issues
- make generated solver runs avoid issues that already have open PRs unless the
  user explicitly asks for a retry or alternative model comparison
- add tests for clean workflow, PR congestion, stale generated branches, and
  duplicate issue/PR situations
- do not read or expose secret files such as `.env`, provider auth files, or
  API keys

Checks:
- `git diff --check`
- `python -m unittest discover -s tests`

## 18. Harden Codex sandbox and escalated-command workflow handling

Labels: `kind/automation`, `theme/workflow`, `theme/codex`, `theme/quality`

Priority: `1`

Codex runs can behave differently inside the app sandbox than the same commands
run directly in the user's terminal. We have seen GitHub API DNS failures from
Python inside the sandbox while the terminal worked, `.git` write operations
blocked by sandbox permissions, and commands such as `git pull`, `git switch`,
or GitHub checks needing escalated execution. The solver workflow should make
these differences explicit, diagnosable, and recoverable.

Suggested scope:
- add a Codex environment preflight that checks GitHub API access through both
  `gh` and Python `requests`
- detect sandbox-related DNS/network failures and recommend or request
  escalated execution instead of retrying blindly
- detect `.git` write permission failures such as blocked `FETCH_HEAD` or
  `index.lock` creation and surface a clear recovery hint
- record whether commands ran sandboxed or escalated in run reports and
  overnight summaries
- add a safe command classification for common workflow operations such as
  `git switch`, `git pull --ff-only`, `gh pr checks`, `gh run view`, and
  `gh issue create`
- avoid broad approvals; keep suggested escalation prefix rules narrow and
  task-specific
- make Codex-specific limitations visible in the dashboard process status
  section once workflow congestion reporting exists
- add tests for sandbox DNS failure classification, `.git` permission failure
  handling, and escalated-command recommendation text
- do not read or expose secrets such as `.env`, provider auth files, API keys,
  or GitHub tokens

Checks:
- `git diff --check`
- `python -m unittest discover -s tests`

## 19. Add structured rework workflow with sub-issues and separate PRs

Labels: `kind/automation`, `theme/workflow`, `theme/quality`, `theme/github`

Priority: `1`

When a generated PR needs rework, the solver should avoid turning one branch
into a mixed correction pile. Rework should be tracked explicitly, split into
clear sub-tasks, and implemented through separate PRs when the changes are
independent enough to review and merge safely.

Suggested scope:
- detect rework situations such as user review feedback, failed checks,
  behavior that looks unchanged, partial implementation, superseded approach, or
  a PR that should be closed in favor of a better path
- create or update a GitHub issue with a checklist of concrete rework
  sub-tasks instead of hiding the plan only in chat or run logs
- link each sub-task to the related original issue, PR, run report, failing
  check, and user observation
- support one PR per sub-task when the work is separable, for example:
  - validation/test repair
  - implementation correction
  - documentation or backlog cleanup
  - dashboard/reporting follow-up
  - closing or replacing a superseded PR
- keep a single PR only when the rework is tiny, tightly coupled, and easier to
  review as one change
- make solver scripts avoid reusing a messy failed branch unless explicitly
  requested; prefer a fresh branch from the base branch with preserved context
- add run-report and dashboard fields for `rework_of`, `rework_reason`,
  `subtask_id`, `supersedes_pr`, and `follow_up_issue`
- add commands or script modes to generate the rework issue/checklist from a PR,
  failed run, or user review note
- add tests for rework issue creation, checklist parsing, separate PR
  recommendation, superseded PR handling, and tiny-rework single-PR fallback
- do not read or expose secret files such as `.env`, provider auth files, API
  keys, or GitHub tokens

Checks:
- `git diff --check`
- `python -m unittest discover -s tests`

## 20. Include exact provider model name in generated PR summaries

Labels: `kind/automation`, `theme/quality`, `theme/workflow`, `theme/provider`

Priority: `1`

Generated pull request bodies should identify both the worker adapter and the
exact provider model used for the run. Showing only `OpenCode CLI` is not
enough when OpenCode can run Mistral, MiniMax, Claude, DeepSeek, Qwen, or other
providers.

Suggested scope:
- update generated PR bodies so the "Used model" section includes the adapter
  and the effective model name, for example `OpenCode CLI` plus
  `mistral/mistral-medium-latest`
- include fallback model information when a fallback worker/model was used
- keep existing adapter display names for readability, but never hide the
  concrete model identifier when it is known
- include the same exact model information in run reports and summaries if any
  field still only stores the adapter display name
- add tests for PR body rendering with:
  - adapter only
  - adapter plus model name
  - OpenCode plus provider model name
  - fallback worker/model
- avoid exposing API keys, provider auth files, prompts, or other secrets

Checks:
- `git diff --check`
- `python -m unittest discover -s tests`

## 21. Add solver process supervisor for monitoring and targeted cancellation

Labels: `kind/automation`, `theme/workflow`, `theme/dashboard`, `theme/quality`

Priority: `1`

Running solver jobs should not require Codex to manually inspect process lists,
tail health files, infer stuck states, and kill individual processes. The
project should provide a small supervisor command or daemon that tracks active
solver runs, reports their health, and can stop exactly the intended job by
run id, issue number, repo, branch, or worker pid.

Suggested scope:
- add a solver process registry that records run id, repo, issue, branch,
  worker adapter, model name, pid tree, start time, latest health timestamp,
  run report path, and current phase
- provide a command such as `scripts/solver_supervisor.py status` to list
  active jobs with stale/healthy/unhealthy classification
- provide targeted stop commands such as `stop --run-id`, `stop --issue`,
  `stop --repo`, or `stop --pid`, with a dry-run mode that shows the exact
  process tree before sending signals
- use graceful termination first, then configurable escalation only for the
  selected process tree; never kill unrelated solver, dashboard, terminal, or
  user processes
- detect repeated test loops, repeated edit failures, no-health-update windows,
  WAL/database failures, network stalls, and worker output inactivity
- preserve or copy the active worktree before terminating an unhealthy job when
  there are local changes
- write a structured cancellation reason to the run report and overnight
  summary
- surface active job status and stop recommendations in the dashboard, ideally
  with copyable commands rather than requiring Codex to run process monitoring
  manually
- integrate with `solve_issues.py`, `solve_issues_batch.py`, and
  `run_overnight.py` without requiring a separate terminal watcher for normal
  runs
- add tests for registry writes, stale detection, process tree selection,
  dry-run stop output, preservation-before-stop, and unrelated-process safety
- do not read or expose secret files such as `.env`, provider auth files, API
  keys, or GitHub tokens

Checks:
- `git diff --check`
- `python -m unittest discover -s tests`

## 6. Support low-code and non-code repositories without Python assumptions

Labels: `kind/automation`, `theme/quality`, `theme/workflow`, `kind/analysis`

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

Labels: `kind/automation`, `theme/quality`, `theme/workflow`, `theme/dashboard`

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

Labels: `kind/automation`, `theme/quality`, `theme/workflow`

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

Labels: `kind/automation`, `theme/quality`, `theme/provider`, `theme/research`

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

Labels: `kind/automation`, `theme/quality`, `theme/workflow`, `theme/dashboard`

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

Labels: `kind/automation`, `theme/quality`, `theme/provider`, `theme/workflow`

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

## 22. Research backlog shaping frameworks before turning ideas into issues

Labels: `theme/research`, `theme/workflow`, `theme/backlog`, `theme/quality`

Priority: `1`

The project needs a deliberate shaping layer between raw ideas and generated
GitHub issues. We are moving bottom-up from concrete observations and
experiments, but we need structure so interesting ideas do not immediately
become oversized implementation issues. Before changing the backlog generator
or dashboard workflow, research established approaches and recommend a small
set of candidate structures that fit `ai-issue-solver`.

Context:
- raw ideas, initiatives, discovery work, ready implementation issues, and
  generated GitHub issues are currently too close together
- `NEXT_BACKLOG.md` should remain useful, but not every idea should become a
  GitHub issue automatically
- the dashboard/PWA will likely need to show ideas, shaped candidates, ready
  issues, generated issues, and run history as different workflow states
- strategic ideas such as reusing old laptops as coding worker nodes should be
  researched against existing distributed-computing, home-lab, CI-runner, and
  agent-runner solutions before we design our own implementation

Suggested scope:
- research and compare established product/workflow structures for the path
  from idea to executable issue, including at least:
  - Dual-Track Agile / Discovery and Delivery
  - Opportunity Solution Tree
  - GIST planning: Goals, Ideas, Steps, Tasks
  - Backlog Refinement and Definition of Ready
  - RICE or similar lightweight prioritisation/scoring methods
  - Shape Up pitches, appetite, bets, and cycles if applicable
- research structurally similar open-source or platform projects that are close
  to this project's domain, including at least OpenCode, Codex, OpenRouter, and
  other AI coding, model-routing, agent-orchestration, or provider-integration
  projects
- create a standardised comparison report for each researched approach:
  - purpose and core workflow
  - where raw ideas live
  - how ideas become candidates
  - how candidates become ready implementation work
  - prioritisation model
  - evidence or confidence signals
  - fit for solo/mobile use
  - fit for AI-assisted issue generation
  - fit for dashboard/PWA representation
  - risks, overhead, and failure modes
- create an evidence log for project assumptions and lessons learned, for
  example Aider currently being a weak fit for this workflow, MiniMax looking
  promising for some R work, or Mistral Medium being a good cost/performance
  default
- define how often subjective provider/model assessments should be challenged
  again using fresh benchmark runs, new public information, and recent local
  solver outcomes
- propose a lightweight model/provider knowledge base that records strengths,
  weaknesses, cost tier, interface stability, task fit, last-reviewed date, and
  evidence source for each model or provider interface
- include internet research as one input for model preselection, but keep local
  benchmark results and project-specific failures visible so recommendations do
  not rely only on public claims
- research comparable systems for reusing old hardware or distributed worker
  capacity, including:
  - self-hosted GitHub Actions runners
  - Buildkite/GitLab/Jenkins style worker agents
  - home-lab orchestration patterns
  - distributed CI queues
  - agent runner or coding-worker orchestration projects
  - lightweight SSH-based job dispatch patterns
- produce a recommended backlog state model for this project, for example:
  `idea -> opportunity -> solution candidate -> discovery spike -> ready issue
  -> generated GitHub issue -> solver run -> PR/rework/done`
- define which states are allowed to generate GitHub issues automatically and
  which states must remain research/shaping only
- propose a small schema for `NEXT_BACKLOG.md` entries, including fields such as
  `type`, `state`, `priority`, `confidence`, `evidence`, `dependencies`,
  `generate_issue`, and `source`
- propose dashboard views for the shaped backlog, including mobile-first
  handling of idea inbox, candidates, ready issues, and generated GitHub issues
- keep this issue as research and recommendation only; do not implement the
  backlog generator or dashboard changes in the same PR

Deliverables:
- one markdown report under `docs/` comparing the researched frameworks
- one recommended state model for `ai-issue-solver`
- one proposed `NEXT_BACKLOG.md` item template
- a list of follow-up implementation issues that can be generated separately

Checks:
- `git diff --check`
- `python -m unittest discover -s tests`

## 23. Define label taxonomy and agent-role mapping for issues and files

Labels: `theme/workflow`, `theme/quality`, `theme/github`, `kind/automation`

Priority: `1`

The project needs a consistent label taxonomy so issues can be grouped,
filtered, assigned to process roles, and selected for separate solver or
research workflows. Existing issues should be classified without losing their
overlapping nature. The taxonomy should also map labels to existing files and
modules so future changes can be routed to the right agent role and workflow
phase.

Context:
- labels are already useful for grouping, but they are not yet structured as a
  deliberate multi-dimensional taxonomy
- issues often overlap, for example dashboard + workflow + cost or research +
  backlog + provider
- role-based agents are emerging as a target architecture:
  - `agent/triage` for GitHub/API classification and issue routing
  - `agent/supervisor` for running process monitoring and targeted cancellation
  - `agent/cost` for budget and cost aggregation from reports
  - `agent/research` for structured research reports and evidence logs
  - `agent/planner` for shaping ideas into ready issues
  - `agent/solver` for implementation work through coding CLIs/models
  - `agent/reviewer` for PR review, rework detection, and follow-up tasks
- labels should help split future development by agent responsibility, not just
  by feature area

Suggested scope:
- define the label dimensions:
  - `theme/*` for business or workflow themes, for example dashboard, model,
    cost, provider, workflow, backlog, supervisor, distributed-workers, github,
    quality, research, codex
  - `area/*` for technical modules or locations, for example pwa, reports,
    runs, prs, issues, labels, model-selection, provider-interface, budget,
    worker-node, opencode, openrouter, mistral, minimax, anthropic
  - `kind/*` for type of work, for example research, spike, feature, refactor,
    bug, process, docs
  - `state/*` for workflow state, for example needs-shaping, ready,
    in-progress, rework, blocked, superseded
  - `priority/*` for explicit priority labels, matching the numeric backlog
    priority where practical
  - `agent/*` for responsible process role, for example triage, supervisor,
    cost, research, planner, solver, reviewer
- map existing GitHub issues into the new taxonomy, preserving multiple labels
  where an issue spans several themes or agents
- propose label mappings for existing files and modules, for example:
  - dashboard/status files -> `theme/dashboard`, `area/pwa`,
    `agent/solver`, possibly `agent/cost` or `agent/supervisor`
  - run reports and summaries -> `theme/workflow`, `area/reports`,
    `agent/supervisor`, `agent/cost`
  - provider adapters and model selection -> `theme/provider`, `theme/model`,
    `area/provider-interface`, `area/model-selection`, `agent/solver`,
    `agent/cost`
  - backlog generator and cleanup -> `theme/backlog`, `area/issues`,
    `agent/planner`, `agent/triage`
  - PR/rework handling -> `theme/workflow`, `area/prs`, `agent/reviewer`
- identify existing large or cross-cutting issues that should be split by agent
  responsibility, for example separating research, planning, solving, review,
  cost, and supervision work into distinct follow-up issues
- define how `create_backlog_issues.py` should preserve or create the new labels
  from `NEXT_BACKLOG.md`
- define how the dashboard should group and filter by label dimensions without
  forcing every issue into a single hierarchy
- propose a migration plan for adding missing labels in GitHub without creating
  noise or rewriting unrelated issue history
- keep this issue focused on taxonomy, mapping, and migration planning; do not
  implement dashboard UI or solver behaviour changes in the same PR

Deliverables:
- a markdown label taxonomy document under `docs/`
- a proposed mapping table from existing labels to new label dimensions
- a proposed file/module-to-label mapping table
- a list of existing issues that should be relabelled
- a list of large issues that should be split by agent responsibility
- follow-up implementation issues for generator, dashboard, and process
  integration

Checks:
- `git diff --check`
- `python -m unittest discover -s tests`

## 24. Trigger the solver automatically via GitHub Actions when an issue is labeled

Labels: `kind/automation`, `theme/workflow`, `theme/github`

Priority: `1`

Inspired by OpenHands, which demonstrated that an AI coding agent can be
triggered directly from GitHub events without requiring a local machine to be
running. OpenHands uses a similar label-based dispatch model to start solver
runs on GitHub-hosted infrastructure.

Currently the solver must be started manually on the local machine. This is a
break in the workflow: the issue exists on GitHub, but the fix has to be
triggered locally. A GitHub Actions workflow that automatically triggers the
solver when a defined label is applied closes this gap and brings the project
closer to how git-bob and OpenHands work.

Suggested scope:
- add `.github/workflows/solve-on-label.yml` that triggers on
  `issues: [labeled]`
- when the label is `ai-solve`, check out the repo, install dependencies, and
  run `solve_issues.py` with the labeled issue number
- remove the `ai-solve` label after the solver run completes, regardless of
  outcome
- store API keys as GitHub Secrets, never hardcoded in the workflow
- give the runner write access only to its own fork branch, not to the base
  branch
- do not forward secrets to the AI worker beyond what `solve_issues.py`
  already handles
- support optional label variants as a follow-up: `ai-solve-claude` for an
  explicit Claude run, `ai-analyze` to run `analyze_repos.py` only,
  `ai-cleanup` to run `post_merge_cleanup.py`
- optionally restrict the workflow to label setters defined in CODEOWNERS
- do not expose API keys, provider auth files, or GitHub tokens in logs or
  run reports

Checks:
- `git diff --check`
- `python -m unittest discover -s tests`

## 25. Decompose oversized issues into sub-issues automatically

Labels: `kind/automation`, `theme/workflow`, `theme/github`, `theme/quality`

Priority: `2`

When an issue is too large or vague, the solver often fails or produces a
large, hard-to-review PR. The better strategy: the solver recognises when an
issue should be split and creates concrete sub-issues instead of attempting a
monolithic fix.

Suggested scope:
- add complexity heuristics to `solve_issues.py` that flag an issue as too
  large: body longer than ~1500 characters, more than three distinct file areas
  mentioned, labels such as `epic`, `large`, or `refactor`, the AI worker
  explicitly stating that multiple steps are needed, or no clear `Touches:`
  hint in the body
- add a `--decompose` flag that sends the issue to the AI with a prompt asking
  for 3–5 concrete, independently solvable sub-issues returned as JSON
- add an `--auto-decompose` flag that applies the same logic automatically when
  complexity heuristics are triggered
- create sub-issues via the GitHub Issues API with title
  `[Sub] <parent-title> — Part N`, a body describing the sub-task with
  `Parent: #<number>` reference, and labels `ai-sub-issue` and `ai-solve`
- add a comment to the parent issue linking all generated sub-issues
- add tests for complexity heuristic thresholds, sub-issue JSON parsing, and
  parent-issue comment creation
- do not expose API keys, provider auth files, or GitHub tokens in sub-issue
  bodies or comments

Checks:
- `git diff --check`
- `python -m unittest discover -s tests`

## 26. Run tests after each solver fix and include the result in the PR body

Labels: `kind/automation`, `theme/quality`, `theme/workflow`

Priority: `2`

Inspired by OpenHands and SWE-agent, both of which validate fixes internally
before creating a PR. This entry applies the same principle using the existing
test setup instead of requiring external infrastructure.

Tests already run as a preflight check before the solver. But after the fix is
committed, there is currently no check whether the new code still passes the
test suite. A solver that fixes a bug but breaks another test lands in the PR
undetected. The AI branch should be tested after the commit and the result
should flow into the run report and PR body.

Suggested scope:
- add a `--post-solve-tests` flag to `solve_issues.py` that runs the test
  suite on the AI branch after a successful commit
- accept a `--test-command` override, defaulting to the existing preflight test
  command
- measure a baseline from the preflight run and compare outcomes: all green,
  unchanged, or new failures
- create the PR as a normal PR when all tests pass, with a warning note when
  results are unchanged, and as a draft PR with an explicit failure block when
  new failures appear
- include a compact test-delta table in `summary.txt` and the PR body, for
  example: passed before / passed after / delta
- feed the test delta into the provider scorecard so cross-model comparisons
  can show which model breaks the fewest tests
- add tests for each outcome: all green, unchanged, new failures, and draft PR
  creation
- do not expose API keys, provider auth files, or full test output in the PR
  body

Checks:
- `git diff --check`
- `python -m unittest discover -s tests`

## 27. Document RepoLens: what it is and why Docker isolation is used

Labels: `kind/docs`, `theme/quality`

Priority: `3`

The README describes a complex Docker wrapper for RepoLens with `--network
none`, a separate report mount, and explicit exclusion of GitHub write
credentials. For any new contributor — and for the project maintainer returning
after a few months — it is unclear: what is RepoLens, why does it need
isolation, and is it an external tool, an internal script, or a commercial
service?

Suggested scope:
- add `docs/REPOLENS.md` explaining what RepoLens does, why network isolation
  is useful, and how to embed it safely in the workflow without needing to
  understand the Docker wrapper code
- cover: what RepoLens analyses (security, performance, code quality, finding
  types and severities), why `--network none` is used, how the report mount
  separates the analysis agent from the deployment agent, and the principle of
  least privilege
- include a minimal quick-start example: scan a repo, read the report, import
  findings as issues
- add a security model section clarifying what RepoLens is and is not allowed
  to see, and why
- optionally add inline `--help` output to `run_repolens_docker.sh` that
  surfaces the security rationale directly when the script is run, not only in
  the documentation
- do not expose API keys, provider auth files, or GitHub tokens in the
  documentation

Checks:
- `git diff --check`
- `python -m unittest discover -s tests`

## 28. Track solver success rate with a benchmark script

Labels: `kind/automation`, `theme/quality`, `theme/workflow`, `theme/provider`

Priority: `2`

Inspired by SWE-Bench, which made it possible to compare AI coding agents on
a standardised benchmark. The goal here is a lightweight internal equivalent:
a `benchmark_solver.py` script that aggregates run reports into a comparable
success-rate view per model, provider, and issue type — without requiring an
external evaluation harness.

The test-delta data from entry #26 (post-solve test validation) is the primary
input for cross-model comparisons.

Suggested scope:
- add `scripts/benchmark_solver.py` that reads run reports from `reports/runs/`
  and aggregates outcomes by provider, model, repo, issue label, and task type
- track per-run fields: PR created, tests passed, no-change, validation failed,
  runtime, and estimated cost
- group runs by same-issue comparison groups so several model attempts on the
  same issue can be compared directly
- compute per-model metrics: PR-created rate, test-pass rate, no-change rate,
  failure rate, median runtime, and estimated cost per successful PR
- consume the test-delta table from `summary.txt` (added in #26) as a
  structured quality signal — which model broke the fewest tests
- output a compact scorecard to stdout and optionally write a JSON report for
  dashboard integration
- integrate scorecard output into the status dashboard as a model comparison
  tab (coordinate with dashboard work in #7)
- support filtering by repo, model, date range, and issue label
- add tests for scorecard aggregation, missing fields, single-run groups, and
  same-issue comparison output
- do not expose API keys, provider auth files, or raw prompts in benchmark
  output

Checks:
- `git diff --check`
- `python -m unittest discover -s tests`

## 29. Skip existing GitHub issues in the backlog issue generator

Labels: `kind/automation`, `theme/workflow`, `theme/github`, `theme/quality`

Priority: `1`

The backlog issue generator (`create_backlog_issues.py`) currently proposes to
create all backlog entries as new issues, including entries that already have a
corresponding open or closed GitHub issue. This makes the dry-run output
misleading and the `--apply` flag unsafe to use without manual filtering. The
generator must detect duplicates before creating anything.

Context:
- in practice, new issues have been created manually with `gh issue create`
  to avoid accidental duplicates, which defeats the purpose of the generator
- the dry-run for 21 backlog entries showed all 21 as "would create", even
  though most already existed as GitHub issues
- the generator needs to match backlog titles against existing issues and only
  propose entries that have no matching issue yet

Suggested scope:
- before proposing or creating an issue, fetch the list of open and closed
  GitHub issues for the target repo and match each backlog entry title against
  existing issue titles using exact match and a normalised fuzzy match
  (lowercase, punctuation-stripped)
- skip backlog entries where a matching open issue already exists; log a clear
  "already exists as #NNN" line for each skipped entry
- optionally warn (but still skip) when a matching closed or merged issue is
  found, in case the backlog entry needs to be cleaned up
- add a `--only-new` flag (or make this the default) so the generator never
  proposes entries that already have a GitHub issue
- add a `--force` flag to override duplicate detection for explicit re-creation
  (e.g. after a closed issue was invalidated and the work is starting fresh)
- update the dry-run summary to clearly distinguish: new (would create),
  skipped (already exists), and unknown (no match found but title is ambiguous)
- add tests for exact-match detection, normalised fuzzy match, open vs closed
  issue handling, and the `--force` override
- do not expose API keys, provider auth files, or GitHub tokens in generator
  output

Checks:
- `git diff --check`
- `python -m unittest discover -s tests`

## 31. Implement agent/triage — automated issue classification and routing

Labels: `kind/automation`, `theme/workflow`, `theme/github`, `agent/triage`

Priority: `2`

The triage agent classifies incoming issues and routes them to the correct
agent role. Currently `create_backlog_issues.py` creates issues with labels
from a static list, and `label_migration.py` updates existing issues manually.
Neither applies the full label taxonomy automatically nor routes issues to an
agent based on their content and labels. The triage agent closes this gap.

Suggested scope:
- add a `triage_issue.py` script (or extend `create_backlog_issues.py`) that
  reads an issue body and title and applies the full multi-dimensional taxonomy:
  `theme/*`, `area/*`, `kind/*`, `state/*`, `priority/*`, and `agent/*`
- use keyword matching, file-path hints in the issue body (`Touches:`), and
  label presence to assign one or more `agent/*` labels automatically
- produce a dry-run output that shows proposed labels before applying them, and
  require `--apply` to write labels to GitHub
- integrate with the backlog generator so new backlog entries get labels at
  creation time, not as a separate migration step
- support batch re-triage of existing unlabeled or partially labeled issues via
  a `--retriage` flag
- add tests for taxonomy assignment, file-hint routing, `agent/*` label
  selection, dry-run output, and batch re-triage with already-labeled issues
- do not read or expose secret files such as `.env`, provider auth files, or
  API keys

Checks:
- `git diff --check`
- `python -m unittest discover -s tests`

## 32. Implement agent/cost — dedicated cost tracking and budget alert agent

Labels: `kind/automation`, `theme/workflow`, `theme/dashboard`, `agent/cost`

Priority: `2`

Cost information exists in run reports and the dashboard but is scattered and
passive. There is no agent that aggregates costs across runs, enforces budget
ceilings, or proactively recommends cheaper providers when a budget threshold is
approached. The cost agent makes budget constraints explicit and actionable.

Suggested scope:
- add a `cost_agent.py` script (or extend `solver_reporting.py`) that reads all
  run reports in a configurable time window and aggregates cost by provider,
  model, repo, and issue type
- support configurable daily and per-run budget ceilings; emit a structured
  warning when a ceiling would be exceeded before starting a new run
- surface an escalation recommendation when the cheapest model that historically
  solves an issue type is not the model currently configured
- write a structured cost summary to `reports/cost/` after each batch or
  overnight run, including: total cost, per-model breakdown, budget consumed,
  remaining budget, and cheapest-model recommendation for the next run
- add a cost section to the status dashboard that shows the current period
  spend, per-model breakdown, and budget status at a glance
- integrate with `solve_issues_batch.py` and `run_overnight.py` so budget
  warnings appear before new solver jobs are queued
- add tests for cost aggregation, budget ceiling logic, empty reports,
  partial cost data, and dashboard rendering with missing or zero-cost runs
- do not read or expose API keys, provider auth files, or secret files

Checks:
- `git diff --check`
- `python -m unittest discover -s tests`

## 33. Implement agent/research — structured research report framework

Labels: `kind/automation`, `theme/research`, `theme/workflow`, `agent/research`

Priority: `2`

Research work is currently ad-hoc: `analyze_repos.py` exists for repository
analysis but there is no structured framework for processing `agent/research`
labeled issues, collecting evidence, or producing comparable research reports.
Research findings are not logged in a reusable format, so the same questions
get re-investigated from scratch.

Suggested scope:
- define a research issue template with fields: research question, scope,
  deliverables, evidence sources, and success criteria
- add a `research_agent.py` script that processes issues labeled `agent/research`
  and produces a structured markdown report under `docs/research/`
- support at minimum: web search via `gh` and repository inspection via
  `analyze_repos.py` as evidence sources
- define an evidence log schema with fields: source, claim, confidence, date,
  and link; write evidence logs to `docs/research/evidence/`
- add a `--dry-run` mode that shows which issues would be processed and what
  evidence sources would be queried without making changes
- surface research reports and evidence logs in the status dashboard under a
  Research tab
- add tests for report template rendering, evidence log schema validation, issue
  selection by label, and dry-run output
- do not expose API keys, provider auth files, or secret files in research
  output or evidence logs

Checks:
- `git diff --check`
- `python -m unittest discover -s tests`

## 34. Implement agent/planner — idea-to-issue shaping pipeline

Labels: `kind/automation`, `theme/backlog`, `theme/workflow`, `agent/planner`

Priority: `2`

The planner agent bridges raw ideas and ready implementation issues. Currently
`NEXT_BACKLOG.md` entries go directly to `create_backlog_issues.py` with no
intermediate shaping, scoring, or readiness gate. Ideas and ready issues live
in the same file with no automated prioritization beyond manually set priority
numbers. The planner agent introduces a deliberate shaping layer.

Suggested scope:
- define backlog entry states: `idea`, `candidate`, `shaped`, `ready`,
  `generated`; add a `state:` field to `NEXT_BACKLOG.md` entries (coordinate
  with the schema proposed in #22)
- add a `planner_agent.py` script that reads `NEXT_BACKLOG.md`, scores each
  entry using configurable criteria (priority, estimated complexity, dependency
  on open issues, label coverage), and outputs a ranked candidate list
- only entries in `ready` state should be eligible for `create_backlog_issues.py`
  to generate GitHub issues; block `idea` and `candidate` entries from automatic
  issue creation
- support a `--shape` mode that takes a `candidate` entry and prompts the solver
  worker to refine its scope, add acceptance criteria, and assign labels before
  advancing it to `ready`
- write a daily planning summary to `reports/planning/` with: entry counts per
  state, top-5 ready candidates, blocked entries, and suggested next action
- add tests for state transitions, scoring logic, readiness gate enforcement,
  and planning summary output with missing or malformed entries
- do not read or expose secret files such as `.env`, provider auth files, or API
  keys

Checks:
- `git diff --check`
- `python -m unittest discover -s tests`

## 35. Implement agent/reviewer — automated PR review and rework detection

Labels: `kind/automation`, `theme/quality`, `theme/workflow`, `agent/reviewer`

Priority: `2`

Generated PRs are currently merged after a manual review with no structured
quality gate from the solver side. The reviewer agent provides an automated
first-pass review of AI-generated PRs: it checks for correctness signals,
detects rework indicators, and creates a follow-up issue when the PR should not
be merged as-is. This is distinct from #19 (rework workflow) and #26
(post-solve tests), which cover specific sub-tasks the reviewer coordinates.

Suggested scope:
- add a `reviewer_agent.py` script that, given a PR number, fetches the diff,
  test results, and run report, and produces a structured review summary
- define review checks: post-solve test delta (from #26), diff size against
  issue scope, touched files vs `Touches:` hint, no-change detection, and
  obvious regression signals such as removed tests or weakened assertions
- output a verdict: `approve`, `request-changes`, or `needs-rework` with a
  brief rationale and a checklist of specific concerns
- when verdict is `needs-rework`, create a GitHub issue using the rework
  workflow from #19 with the reviewer's checklist as the issue body
- post the review summary as a PR comment when `--comment` is passed, or print
  to stdout for manual inspection by default
- integrate with `solve_issues.py` via a `--auto-review` flag that runs the
  reviewer after a successful PR is created
- add tests for each verdict, the rework issue creation flow, PR comment
  formatting, and edge cases such as empty diff or missing run report
- do not expose API keys, provider auth files, or secret files in PR comments
  or review output

Checks:
- `git diff --check`
- `python -m unittest discover -s tests`

## 36. Persist dashboard repo, tab and agent selection in URL parameters

Labels: `kind/feature`, `theme/dashboard`, `theme/quality`, `agent/solver`

Priority: `1`

The dashboard resets to its default view on every auto-refresh or manual reload,
discarding the user's current repo, tab, and agent selection. Users cannot share
or bookmark a specific dashboard view. All three selection dimensions must be
persisted in the URL and restored on load.

Suggested scope:
- store `repo`, `tab`, and `agent` as `URLSearchParams` query parameters; update
  them via `history.replaceState` whenever the user changes a selection so the
  page does not reload
- on page load, read all three parameters from `location.search` and apply them
  before rendering; fall back to sensible defaults when a parameter is absent
- default `tab`: `run-list`; default `agent`: `all`; default `repo`: the repo
  with currently running jobs (most recently started if multiple repos are active)
- agent filter: add a selector that filters the visible run rows by worker/model
  adapter; use `agent=all` to show all rows; implement as a sub-filter within
  the active tab (Variant C from the requirements doc)
- ensure the auto-refresh meta tag does not fight the URL state; the restored
  view after refresh must exactly match what was in the URL — same repo, tab,
  and agent — with no automatic jump back to run-list
- update `switchTab`, the repo dropdown, and the new agent selector to all call
  a shared `updateUrlParams({tab, repo, agent})` helper that keeps the URL in
  sync
- add tests for URL parameter read/write, default fallback logic, multi-repo
  active-job selection, and single-repo auto-selection
- do not expose API keys, provider auth files, or secret files in dashboard
  output

Touches: `scripts/status_dashboard.py`, `scripts/serve_dashboard.py`

Checks:
- `git diff --check`
- `python -m unittest discover -s tests`

## 37. Free OpenCode models full integration and evaluation

Labels: `kind/feature`, `theme/workflow`, `agent/solver`, `priority/1`

Priority: `1`

Integrate all free OpenCode models into the project's model framework and
evaluate them against the current open issue backlog.

Currently only `opencode/mistral-small-2603`, `claude-sonnet-4-20250514`, and
`gpt-4o` are mentioned in help text; the available free tier models
(`opencode/deepseek-v4-flash-free`, `opencode/mimo-v2.5-free`,
`opencode/minimax-m3-free`, `opencode/nemotron-3-ultra-free`) are not
registered anywhere and users cannot discover or select them easily.

Suggested scope:
- add default model names to `MODEL_CONFIGS["opencode"]` so that
  `--model opencode` without `--model-name` picks a sensible default
- add entries in `STRENGTH_MAP` and `COST_TIERS` in `model_selection.py` for
  the free OpenCode models so auto-selection can choose them
- update `benchmark_issues.py` to include the free model list (or make it
  discover them dynamically via `opencode models`)
- run a full benchmark sweep against all open issues (ideally the small,
  low-risk ones first: regression tests, config changes, simple features)
- report per-model: can it solve the issue, does it create a valid PR, do
  tests pass, wall-clock time, and estimated token cost
- if a model consistently fails for a certain class of issues, document the
  pattern and add a model-selection guard in `model_selection.py`
- update `model_selection.py` to support the `opencode` provider family,
  including setting `model` via `--model-name` instead of guessing from
  substring matches
- add a `--list-free-models` (or similar) flag to discover available models
  dynamically via `opencode models` instead of hardcoding them

Touches: `scripts/solve_issues.py`, `scripts/model_selection.py`,
         `scripts/benchmark_issues.py`, `scripts/solver_run_resources.py`

Checks:
- `git diff --check`
- `python -m unittest discover -s tests`

## 38. Parallel Solver Ensemble – mehrere Modelle auf ein Issue, beste Lösung gewinnt

Labels: `kind/feature`, `theme/workflow`, `agent/solver`, `priority/1`

Priority: `1`

Replace the current single-model-per-issue approach with an ensemble that runs
multiple models on the same issue concurrently, then selects the best result
and creates a single PR. This serves both production (best possible solution)
and benchmarking (fair comparison without branch collision).

Key design decisions:
- each model gets its own branch: `ai/fix-issue-{number}/{sanitized-model-name}`
- all branches are pushed to the remote; no PR is created per model
- after all models finish, a "reviewer" step evaluates each result by:
  - did tests pass? (primary gate)
  - diff size vs issue scope
  - touched files vs `Touches:` hint
  - number of edit/fix iterations the model needed
  - worker exit code and output signals (WAL failures, edit loops)
- the best result is promoted: its branch becomes the PR branch, or a new
  combined branch is created cherry-picking the best parts
- in benchmark mode (`--benchmark` / `--skip-pr`): evaluation results are
  logged, no PR is created, no branch is promoted
- in production mode (`--ensemble`): the best result gets a single PR

Suggested scope:
- add `--ensemble N` flag to `solve_issues.py` that spawns N model workers for
  each issue; workers share the same clone but get isolated solver dirs
- extend branch naming in `solve_issue()` to accept an optional suffix
  (`model_slug`) so branches don't collide
- implement the reviewer/evaluation step as a standalone function that takes a
  list of `DiagnosticResult` and returns a ranked list
- update `benchmark_issues.py` to be a thin wrapper around `--ensemble --skip-pr`
- show benchmark results (per-model diffs, test delta, wall-clock time) in the
  dashboard's model-comparison tab so results are可视 without digging through
  JSON files
- add tests for: branch name generation with model suffix, reviewer ranking
  logic, ensemble dispatch with N workers, skip-pr mode in ensemble context

Touches: `scripts/solve_issues.py`, `scripts/benchmark_issues.py`,
         `scripts/status_dashboard.py`, `tests/`

Checks:
- `git diff --check`
- `python -m unittest discover -s tests`
