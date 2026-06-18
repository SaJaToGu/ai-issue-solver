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
- `open.md` should remain useful, but not every idea should become a
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
- propose a small schema for `open.md` entries, including fields such as
  `type`, `state`, `priority`, `confidence`, `evidence`, `dependencies`,
  `generate_issue`, and `source`
- propose dashboard views for the shaped backlog, including mobile-first
  handling of idea inbox, candidates, ready issues, and generated GitHub issues
- keep this issue as research and recommendation only; do not implement the
  backlog generator or dashboard changes in the same PR

Deliverables:
- one markdown report under `docs/` comparing the researched frameworks
- one recommended state model for `ai-issue-solver`
- one proposed `open.md` item template
- a list of follow-up implementation issues that can be generated separately

Checks:
- `git diff --check`
- `python -m unittest discover -s tests`

---

---

## Parked / Future

Items below are NOT active priority-1 work. They are kept here so
the file is a complete backlog, but they will not be picked up by
`scripts/create_backlog_issues.py` until they are explicitly
moved back into a priority section. Each entry explains why it
is parked.
## 37. Free OpenCode models full integration and evaluation *(parked)*


Labels: `kind/feature`, `theme/workflow`, `agent/solver`, `priority/1`

Parked because: Free OpenCode models full integration and evaluation — not 0.9.0-critical; the hard-coded free-models list is known stale (see agent memory 2026-06-14) and must be re-verified before any real run, not parked as a priority-1 item.

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

---

## 39. Periodic documentation benchmark with free OpenCode models *(parked)*


Labels: `kind/automation`, `kind/docs`, `theme/workflow`, `theme/provider`, `priority/2`

Parked because: Periodic documentation benchmark with free OpenCode models — depends on later validation/model-comparison data from 0.9.0; defer until 0.9.0 validation report and free-model registry are stable.

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

Touches: `scripts/benchmark_issues.py`, `scripts/solve_issues.py`,
         `scripts/status_dashboard.py`, `scripts/model_selection.py`,
         `reports/`, `tests/`

Checks:
- `git diff --check`
- `python -m unittest discover -s tests`

---
