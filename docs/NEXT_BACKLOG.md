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

## 16. Use GitHub repository intelligence before local repo type detection

Labels: `automation`, `analysis`, `quality`, `workflow`, `github`

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

Labels: `automation`, `workflow`, `dashboard`, `quality`

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

Labels: `automation`, `workflow`, `codex`, `sandbox`, `quality`

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

Labels: `automation`, `workflow`, `quality`, `github`

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

Labels: `automation`, `quality`, `workflow`, `provider`

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

Labels: `automation`, `workflow`, `dashboard`, `quality`

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

## 22. Research backlog shaping frameworks before turning ideas into issues

Labels: `research`, `workflow`, `backlog`, `quality`

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

Labels: `workflow`, `quality`, `github`, `automation`

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

Labels: `automation`, `workflow`, `github`

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

Labels: `automation`, `workflow`, `github`, `quality`

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

Labels: `automation`, `quality`, `workflow`

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

Labels: `docs`, `quality`

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

Labels: `automation`, `quality`, `workflow`, `provider`

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
