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

## 46. Sync VERSION file and CHANGELOG to current 0.9.0 milestone


Labels: `kind/refactor`, `priority/3`, `theme/workflow`

Priority: `3`

`VERSION` is still `0.3.1` and `CHANGELOG.md` tops out at `0.3.1 - 2026-06-01`.
Since then §42–§45 of `docs/BACKLOG/open.md` have all shipped via merged PRs
(#399/#400/#401, #402/#403, #404/#405, #406). Effectively we are post-0.9.0.

Problem:
- `VERSION` lies about the current release.
- No CHANGELOG entry exists for §42–§45 work, so external readers can't see
  what landed in 0.9.0.
- Release tooling (CI tags, badges, anything reading `VERSION`) is silently
  wrong.

Suggested scope:
- bump `VERSION` to `0.9.0` (or `0.9.1` if a patch fix lands first)
- add a top section `## 0.9.0 - <today>` to `CHANGELOG.md` summarising the
  §42–§45 shipped work in 4–8 bullets (split-loop, solver consolidation,
  PR rework loop, RepoLens archive)
- keep the existing `0.3.0` / `0.3.1` entries intact below
- create tag `v0.9.0` on the merge commit (or a follow-up release commit)
- ensure no code/CLI defaults reference the old version string

Out of scope:
- cutting the actual release (just the version bump + changelog)
- removing the `0.3.x` history entries

Touches: `VERSION`, `CHANGELOG.md`

Checks:
- `git diff --check`
- `python -m unittest discover -s tests`

---

## 47. Deprecate Aider worker adapter (opencode + openrouter + codex suffice)


Labels: `kind/refactor`, `priority/3`, `theme/workflow`, `theme/provider`

Priority: `3`

Three worker paths exist: `workers/aider_adapter.py`, plus opencode,
openrouter, and codex. Aider requires `requirements-aider.txt` extra install
and `docs/SETUP_AIDER.md` setup; in practice the proven free path
`opencode/deepseek-v4-flash-free` plus `openrouter_direct` and `codex`
covers every overnight/batch run from the last month.

Problem:
- `requirements-aider.txt` pulls in a heavy dep tree nobody runs by default.
- `docs/SETUP_AIDER.md` still presents Aider as a primary path — misleading.
- Worker-adapter surface in `workers/` is wider than needed, slows onboarding.

Suggested scope:
- make `workers/aider_adapter.py` emit a `DeprecationWarning` on import,
  printed once per process, naming opencode / openrouter / codex as the
  three supported paths
- add the same deprecation note to the top of `requirements-aider.txt` and
  mark it optional
- add a banner at the top of `docs/SETUP_AIDER.md`: "Aider is deprecated.
  Use `opencode/deepseek-v4-flash-free` for default runs. This file will be
  removed in the next minor release."
- keep the adapter working so existing workflows don't break
- file a follow-up issue for actual removal after 1–2 releases confirm
  zero usage in run-reports

Out of scope:
- removing the adapter outright (deferred to next release after telemetry)
- changing default `--model` values anywhere

Touches: `workers/aider_adapter.py`, `requirements-aider.txt`, `docs/SETUP_AIDER.md`

Checks:
- `git diff --check`
- `python -m unittest discover -s tests`
- `python -c "import workers.aider_adapter"` shows the warning once

---

## 48. Consolidate rework/retry flag surface across solve_issues.py


Labels: `kind/refactor`, `priority/3`, `theme/workflow`, `area/runs`

Priority: `3`

`solve_issues.py` currently exposes three rework entry points:
- `--rework <issue>` — Issue-keyed, solver run on existing issue-branch
- `--retry` — force a run despite an open PR
- `--rework-pr <N>` — PR-keyed, applies review feedback via direct model
  call (added in PR #405 / Issue #404)

Plus the standalone `scripts/rework_workflow.py` for sub-issue decomposition,
with its own CLI surface (`--rework-of`, `--from-pr`, `--from-run`,
`--from-note`).

After PR #405, `--rework-pr` is the orthogonal PR-feedback path; the older
`--rework` / `--retry` / `rework_workflow.py` trio may overlap or be unused.

Problem:
- new users see four rework-adjacent flags and don't know which to pick
- `rework_workflow.py` partly overlaps with `solve_issues.py --rework`
- we don't have usage data yet to know which flags are actually exercised
  in nightly/batch runs

Suggested scope:
- add light instrumentation: each `--rework*` / `--retry` flag use appends
  one line to `reports/usage/rework-flags.jsonl`
  (timestamp + flag + model + run-id)
- update `docs/WORKFLOW.md` rework section (around lines 208, 334, 340)
  with an explicit decision matrix: when to use `--rework` vs `--retry` vs
  `--rework-pr` vs `rework_workflow.py`
- no flag removal yet — gather usage for one release cycle first

Follow-up (separate issue, NOT in scope here):
- after one release of telemetry: pick the canonical path, deprecate the
  others with a clear migration note

Out of scope:
- removing `rework_workflow.py`
- merging rework logic into a single function
- changing CLI defaults

Touches: `scripts/solve_issues.py`, `scripts/rework_workflow.py`,
         `docs/WORKFLOW.md`, `reports/usage/`

Checks:
- `git diff --check`
- `python -m unittest discover -s tests`

---
