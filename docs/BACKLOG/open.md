# Open Backlog

> **📌 Sprachhinweis / Language Note:**
> Diese Datei bleibt bewusst auf Englisch, da sie als Vorlage für GitHub Issues dient
> und von KI-Workern verarbeitet wird. Siehe [Sprachrichtlinie](../LANGUAGE_POLICY.md)
> This file remains in English as it serves as a template for GitHub Issues and is
> processed by AI workers. See [Language Policy](../LANGUAGE_POLICY.md)

This backlog captures the **active, not-yet-closed** technical work for the
`ai-issue-solver` project. Private personal ideas belong in the separate
private `guido-project-lab` repository and must not be added here.

**Naming & location** (Release 0.7.0 split): this file replaces the old
`docs/NEXT_BACKLOG.md`. Completed items are archived in
[`done.md`](done.md). Long-term direction is in
[`../ROADMAP.md`](../ROADMAP.md).

**Priority** uses numeric ordering: `1` is highest urgency; larger numbers
are lower priority.

**Section numbers** are stable backlog identifiers, not priority. They are
preserved across renames and splits so that GitHub issues, PRs, and external
references keep working. Gaps in the numbering reflect historical insertion
order, not deleted sections.

Create selected items as GitHub issues with:

```bash
python scripts/create_backlog_issues.py --backlog docs/BACKLOG/open.md
python scripts/create_backlog_issues.py --backlog docs/BACKLOG/open.md --apply --confirm-create
```

Clean up completed items after their GitHub issues are closed by moving the
section to [`done.md`](done.md) and running:

```bash
python scripts/cleanup_backlog.py --backlog docs/BACKLOG/open.md
python scripts/cleanup_backlog.py --backlog docs/BACKLOG/open.md --apply --confirm-remove
```

---

## Priority 1

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

---
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

---
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

---
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

---
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

---
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

---
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

---
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

---
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

---
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

---
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

---
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

---
## 39. Periodic documentation benchmark with free OpenCode models


Labels: `kind/automation`, `kind/docs`, `theme/workflow`, `theme/provider`, `priority/2`

Priority: `2`

Every tenth documentation-only solver run should be executed as a controlled
benchmark across all currently available free OpenCode models. This should keep
model comparison data fresh without spending tokens and provider quota on every
routine documentation issue.

Policy:
- only apply to documentation-only issues with low risk and narrow `Touches:`
  scope
- count successful documentation solver attempts and trigger the benchmark on
  every tenth eligible run
- run all free OpenCode candidates:
  - `opencode/deepseek-v4-flash-free`
  - `opencode/mimo-v2.5-free`
  - `opencode/minimax-m3-free`
  - `opencode/nemotron-3-ultra-free`
- use isolated branch suffixes and `--skip-pr` while benchmarking candidates
- do not automatically close the issue until the selected candidate is promoted
  and reviewed

Missing functionality to implement:
- persist a documentation-run counter or cadence marker so the scheduler can
  decide when the tenth eligible documentation issue is reached
- add a benchmark trigger mode that runs the free OpenCode models for the same
  documentation issue without requiring manual commands
- rank candidate branches by run outcome, diff relevance, test signal, touched
  files, and worker/runtime health
- promote the best candidate to one draft PR, or record that no candidate was
  good enough
- write durable benchmark comparison data grouped by model, repo type, issue
  type, and failure class
- surface the benchmark comparison in the dashboard, including no-op,
  model-failure, pipeline-failure, preserved-worktree, and promoted-candidate
  states
- record the result so future model selection can learn which free OpenCode
  models work best for documentation, Python, R, dashboard, and mixed repos

Suggested implementation:
- extend `benchmark_issues.py` or add a thin scheduler wrapper around
  `solve_issues.py --skip-pr --branch-suffix`
- reuse `run_outcome` fields from solver reports once available
- add a small persistent state file such as `reports/benchmark-cadence.json`
  or a project status file
- keep the first implementation documentation-only; expand to Python/R only
  after dashboard comparison and recovery semantics are reliable

Touches: `scripts/benchmark_issues.py`, `scripts/solve_issues.py`,
         `scripts/status_dashboard.py`, `scripts/model_selection.py`,
         `reports/`, `tests/`

Checks:
- `git diff --check`
- `python -m unittest discover -s tests`

---
