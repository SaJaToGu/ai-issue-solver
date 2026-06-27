# 0.9.0 Planning — Solver Validation

> **Purpose:** Validation release. Prove that ai-issue-solver actually
> solves real issues. Not a feature release, not a governance release.
> The next session's only job: make the system measurable and measure it.

## Start here

This release is **not** 0.7.0's "wire what exists" follow-up. It is
the **first release whose success criterion is empirical evidence** that
the solver resolves real GitHub issues end-to-end.

Do NOT add new architecture. Do NOT redesign components. Do NOT add
new governance. The previous 0.8.0 plan was archived precisely
because scoping that work had become the work — see
[`archive/PLANNING_0.8.0.md`](archive/PLANNING_0.8.0.md).

The success metric is simple: a number. How many issues did we solve
this release, and at what cost.

## Status carried over

- Release 0.7.0 closed. Close-out: [`RELEASE_REVIEW_0.7.0.md`](RELEASE_REVIEW_0.7.0.md).
  Release notes: [`RELEASE_NOTES_0.7.0.md`](RELEASE_NOTES_0.7.0.md).
  HEAD at close: `b8fabf5` (later `0c1a41a` after PR #322).
- 0.8.0 was scoped (Handover Audit + Reviewer Runtime + Knowledge
  Dry Run) but 30+ messages of meta-planning revealed the 0.8.0 scope
  had no independent identity. Pivoted. Old plan archived at
  `docs/archive/PLANNING_0.8.0.md`.
- `docs/BACKLOG/open.md` is 1043 lines and stale. The cleanup
  identified in the archived 0.8.0 plan is still required as
  Pre-Work for this release.

## Pre-Work (no GitHub issue)

### Backlog cleanup

The 10 sections of `docs/BACKLOG/open.md` listed below are duplicates
of closed GitHub issues that already delivered the work. Move them to
`docs/BACKLOG/done.md` and run the cleanup script. A clean backlog is
the substrate for a clean validation run.

| Section | Title | Closed by |
|---|---|---|
| §26 | Run tests after each solver fix | #281 |
| §28 | Track solver success rate with a benchmark script | #247 |
| §31 | Implement agent/triage | #256 |
| §32 | Implement agent/cost | #257 |
| §33 | Implement agent/research | #258 |
| §34 | Implement agent/planner | #259 |
| §35 | Implement agent/reviewer | #260 |
| §36 | Persist dashboard repo, tab and agent selection in URL params | #261 |
| §38 | Parallel Solver Ensemble | #263 |
| §40 | Add compact growing progress heartbeat | #286 |

```bash
git checkout -b chore/backlog-cleanup-0.9.0-prep
# Manually move the 10 sections to BACKLOG/done.md with provenance notes
# pointing at the closed GitHub issue numbers.
python scripts/cleanup_backlog.py \
  --backlog docs/BACKLOG/open.md \
  --apply \
  --confirm-remove
python -m compileall scripts tests
git add docs/BACKLOG/
git commit -m "chore(backlog): move 10 stale sections to done.md"
git push -u origin chore/backlog-cleanup-0.9.0-prep
# Open PR; squash-merge after CI green.
```

**Acceptance:** `BACKLOG/open.md` is shorter; the 10 sections appear
in `BACKLOG/done.md` with their closed-issue references preserved.

---

## Official 0.9.0 Issues (4, fixed scope)

### Issue 1 — Cost-Limit-Forwarding Fix

**Labels:** `kind/bug`, `theme/quality`, `theme/cost`, `priority/1`

**Purpose:** Without this, the validation run cannot enforce cost
limits at the worker level. The 0.9.0 measurement "cost per solved
issue" is meaningless if a single bad run blows the budget. The
flags exist on `solve_issues.py`; `solve_issues_batch.py` and
`run_overnight.py` silently drop them.

**Scope:**

- `solve_issues_batch.py` `build_worker_command` must forward
  `--max-run-cost-usd`, `--max-run-input-tokens`, and
  `--max-run-output-tokens` to spawned `solve_issues.py` workers.
- `run_overnight.py` must do the same.
- Add `tests/test_cost_limit_forwarding.py` asserting the flags are
  present in the spawned command when set on the parent.

**Acceptance criteria:**

- The three cost-limit flags propagate from batch / overnight
  runners to workers.
- `python -m compileall scripts tests` clean.
- `python -m unittest tests.test_cost_limit_forwarding` passes.

**Out of scope:**

- New cost metrics or dashboards.
- Wall-clock timeout work (separate concern).
- Health-timeout tuning.

### Issue 2 — Reviewer Runtime

**Labels:** `kind/feature`, `theme/quality`, `agent/reviewer`, `priority/1`

**Purpose:** The reviewer system introduced in #313 is loadable
artifacts, but nothing invokes them. This release makes it runnable.
The reviewer is a hard dependency for the 0.9.0 validation run —
without it, "did the solver actually fix the issue" cannot be graded
by anything except a human.

**Scope:**

- New script (e.g. `scripts/review_pr.py`):
  - Takes a PR number, fetches the PR diff.
  - Loads one of the 3 prompts from
    `.agents/reviewers/reviewer-{code,architecture,documentation}.md`.
  - Calls the matching role from `config/role_routing.yaml`.
  - Returns a structured verdict (Markdown, see prompt format).
- Subcommand-style usage, e.g.
  `python scripts/review_pr.py --pr 322 --role code`.
- Role selection via flag (default: `code`).
- Tests for prompt loading, role lookup, output schema.

**Architectural invariant:** the reviewer is a **separate script or
subcommand**, not a new flag on `solve_issues.py`. The solver stays
dumb.

**Acceptance criteria:**

- The script can be run on a real PR (e.g. PR #321) and produces a
  verdict in the format defined in `.agents/reviewers/reviewer-code.md`.
- The script loads the prompt dynamically; prompt content is not
  duplicated in the script.
- The script uses the model from `config/role_routing.yaml` for the
  selected role, not a hard-coded model.
- Tests cover: prompt loading, role selection, output schema
  validation, missing-role error, missing-PR error.
- `python -m compileall scripts tests` clean.
- `python -m unittest tests.test_role_routing tests.test_reviewer_runtime`
  passes.

**Out of scope (explicit):**

- Auto-detection of PR type (would need a classifier LLM, contradicts
  "Solver stays dumb"; follow-up if ever needed).
- Wiring into `solve_issues.py`.
- Wiring into GitHub Actions.
- New reviewer sub-roles or new prompts.

### Issue 3 — Validation Metrics & Run

**Labels:** `kind/feature`, `kind/analysis`, `theme/quality`, `priority/1`

**Purpose:** This is the validation itself. The other 0.9.0 issues
are scaffolding; this one is the **deliverable**. The release is
done when this report exists.

**Scope:**

- A validation run script (`scripts/validation_run.py` or as a
  subcommand of an existing runner) that:
  - Selects N issues from the cleaned backlog matching the chosen
    start vertical (e.g. small Python bugfixes with clear repro).
  - Runs the solver + reviewer pipeline against each.
  - Captures per-issue outcomes.
- Generates a validation report at `reports/validation-0.9.0.md` with:
  - **Number of issues processed** (solver attempted)
  - **Number of PRs merged** (hard success)
  - **Number of PRs created but not merged** (partial)
  - **Success rate** = merged / processed
  - **Cost per solved issue** (USD)
  - **Time per solved issue** (wall clock)
  - **Top 5 error classes** (one-line description each)
  - **Cost & time totals**

**Hard acceptance criterion — Definition of Solved:**

> An issue counts as **solved** if and only if:
>
> 1. The solver produced a PR.
> 2. The PR was **merged** into the default branch.
> 3. The merge commit's CI run is **green**.
>
> Anything less — PR created but not merged, tests green locally but
> CI red, "looks good" reviewer opinion — is **NOT** solved.
> "Solved" is a machine-checkable state, not a judgment.

**Out of scope (explicit):**

- A new dashboard for the metrics. The Markdown report is the
  deliverable; the existing `status_dashboard.py` continues to show
  the underlying run data.
- Statistical significance (N issues is a sample, not a population;
  treat the number as a directional signal, not a benchmark).
- Cross-repo validation. This release validates against the
  `ai-issue-solver` repo only.

### Issue 4 — Open Practical Questions (answered during execution)

These questions are part of the 0.9.0 plan but are **answered
during execution**, not in advance. Listed here so the next session
has them on the radar.

- **Which issue type to start with?**
  Suggested vertical: small Python bugfixes with clear repro, or
  small refactorings with explicit acceptance criteria. The point
  is to start narrow.
- **Which models?**
  Suggested default: `minimax/MiniMax-M3` (paid, requires MiniMax
  provider in opencode auth) for code work. Fallback:
  `opencode/minimax-m2.5` (free, older) for cost-sensitive runs.
  The live model list is at `~/.opencode/bin/opencode models` —
  check it before launching; the hard-coded `free_models` list
  in `solve_issues.py` is known stale.
- **Which cost limits?**
  Set `--max-run-cost-usd` per run; the Issue 1 fix makes that flag
  actually take effect. Suggested starting cap: $5 per run, with a
  hard ceiling on the validation run's total.
- **Which reports?**
  Existing `reports/runs/<run-id>/summary.txt` continues to be the
  per-run report. The 0.9.0 deliverable is the aggregated
  `reports/validation-0.9.0.md`.
- **How many issues (N)?**
  Start with N=10 for the first validation pass. If the numbers
  are stable, scale to N=50. The point is a directional signal,
  not statistical significance.

---

## Explicitly excluded from 0.9.0

The following are NOT 0.9.0 work. They are deferred, parked, or out
of scope permanently:

- Handover & Documentation Audit (hygiene, not a release deliverable;
  do as maintenance if needed).
- Knowledge Manager dry run (parked; revisit only if validation
  reveals a knowledge-base gap).
- AI Contributors section / mapping (move into a CONTRIBUTORS.md if
  and when there is something to contribute; not a release deliverable).
- Architecture Agent (parked, see `CURRENT_CONTEXT.md`).
- Planner Context Package (parked, see archived 0.8.0 plan).
- New agents, new skills, new components.
- New documentation files beyond the validation report.
- Solver enhancements (the solver stays dumb).
- Model benchmarking (cost & process control are higher priority than
  model benchmarking — see ROADMAP themes).
- GitHub Actions expansion (deferred; could be a follow-up to Issue 2
  if LLM review is to be triggered automatically).

## Architectural invariants to preserve

These were settled during 0.7.0 and remain non-negotiable:

- **"Solver stays dumb"** — `solve_issues.py` gets the issue, the
  touched files, and one skill. Nothing else.
- **`knowledge_manager` is fail-closed** — the solver role cannot run
  `promote` or `delete`. Same posture for any future destructive op.
- **`.agents/skills/` for workflows with helpers / tests / examples.**
  **`.agents/reviewers/` for LLM invocation profiles.** Do not
  collapse the two.
- **Deterministic workflows preferred** over LLM agents when feasible.

---

## How to use this document

The next session should:

1. Read this file first.
2. Read [`CURRENT_CONTEXT.md`](CURRENT_CONTEXT.md) for the current
   snapshot.
3. Read [`RELEASE_REVIEW_0.7.0.md`](RELEASE_REVIEW_0.7.0.md) for the
   0.7.0 close-out baseline.
4. Run the Pre-Work (Backlog Cleanup).
5. File the 4 issues using the labels, scope, acceptance, and
   out-of-scope sections above. Match the format of the existing
   closed issues in the project (see #311–#315 for the canonical
   style).
6. Update [`CURRENT_CONTEXT.md`](CURRENT_CONTEXT.md) and
   [`ROADMAP.md`](ROADMAP.md) to reflect the start of 0.9.0.

If anything in this document contradicts the user's most recent
direction, **the user's most recent direction wins.**

---

*This release exists to answer one question: how well does
ai-issue-solver actually solve issues? The answer must be a number.*
