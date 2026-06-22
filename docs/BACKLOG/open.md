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

## 44. Add backward-split loop: detect oversized PRs and route to sub-issues (GitHub #402)

Labels: `kind/refactor`, `theme/workflow`, `area/runs`, `priority/2`

Priority: `2`

The split-planning step (#387, PR #400) covers the FORWARD direction
only — split broad issues BEFORE solver. There is no symmetric
backward path: when a worker delivers an oversized PR anyway, the
loop is manual (reviewer flags → user decides merge/rework/split).

This issue was raised by user after 3+ occurrences in one session:
- PR #393: 1570-LOC monolithic validation_run.py
- PR #394: same file, re-attempt
- PR #400 (+877 LOC) and PR #401 (+734 LOC): borderline, both merged

Scope:
- detection in validation report: per-PR / per-issue
  - LOC > 500 → flag "oversized"
  - files changed > 10 → flag
  - module split violation (file > hard cap) → flag
  - test ratio < 0.3 → flag
- action: new `scripts/validation_run.py split --pr N` decomposes the
  PR into sub-issues (file-based, deterministic), optionally auto-closes
  the parent with cross-reference comment.
- tracking: parent_pr → sub_issues relationship in git notes + per-issue
  metadata. Validation report's per-issue section reflects the split.

Acceptance:
- PR > 500 LOC OR > 10 new files → validation report flags `oversized`
- `validation_run.py split --pr N` decomposes + closes parent + opens
  sub-issues, deterministic by file/module
- Backward loop integrates with the existing #326 validation infra

Out of scope (this issue):
- Auto-merge of sub-issues (humans still approve each).
- LLM-based decomposition (deterministic for now).
- Cross-repo decomposition.

Refs: #387 (forward), #393/#394 (failure mode), #399-#401 (borderline
cases), 1.0 architecture (plan_issue_batches.py as starting point for
decomposition heuristic).

Touches: scripts/validation/{metrics,cli,runner,__init__}.py, new
scripts/validation/split.py, tests/test_validation/test_split.py,
docs/PLANNING_1.0.md (split-loop section).

Checks:
- `python -m unittest discover -s tests` (regression check)
- `python scripts/validation_run.py --help` shows new `split` subcommand
- `python scripts/validation_run.py split --pr <N> --dry-run` shows
  proposed decomposition without actually creating sub-issues

---
