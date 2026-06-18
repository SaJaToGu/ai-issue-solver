# Current Context

Created: 2026-06-15 (file introduced as part of Release 0.7.0 information
architecture audit, issue #309).
Last rewritten: 2026-06-18 (0.9.0 Solver Validation — first run prep landed).

This document is a **short-lived snapshot** of where the project stands. It
should be revisited after every release via
[`RELEASE_REVIEW_AGENDA.md`](RELEASE_REVIEW_AGENDA.md) and rewritten
whenever the situation changes materially.

## Current Release

- Release 0.7.0 closed (see
  [`RELEASE_REVIEW_0.7.0.md`](RELEASE_REVIEW_0.7.0.md) and
  [`RELEASE_NOTES_0.7.0.md`](RELEASE_NOTES_0.7.0.md)).
- HEAD at close: `b8fabf5`. Five architecture issues (#311, #312, #313,
  #314, #315) plus the #309 audit all delivered.
- Issue #309 is the meta-issue and is closed by the release review
  document.
- 0.8.0 was scoped (Handover Audit + Reviewer Runtime + Knowledge Dry
  Run) but the scoping itself became the work. 30+ messages of
  meta-planning revealed the 0.8.0 scope had no independent identity.
  Pivoted to 0.9.0. See [`PLANNING_0.9.0.md`](PLANNING_0.9.0.md).

## Current Focus: 0.9.0 — Solver Validation

The goal of 0.9.0 is **empirical evidence that ai-issue-solver
resolves real GitHub issues end-to-end**. This is the first release
whose success criterion is a number, not a feature.

**Scope (4 fixed pieces, see `PLANNING_0.9.0.md` for details):**

1. **Backlog Cleanup** (Pre-Work, **landed** via PR #330 / commit
   `f515ac7`) — 10 stale sections in `docs/BACKLOG/open.md` moved
   to `done.md` with provenance; §37 and §39 parked.
2. **Cost-Limit-Forwarding Fix** (**landed** via PR #328 / commit
   `85c8821`) — `solve_issues_batch.py` and `run_overnight.py`
   now forward `--max-run-cost-usd`, `--max-run-input-tokens`, and
   `--max-run-output-tokens` to spawned `solve_issues.py` workers.
   9/9 new tests in `tests/test_cost_limit_forwarding.py`.
3. **Reviewer Runtime** (**landed** via PR #329 / commit `bfc65c7`)
   — `scripts/review_pr.py` loads one of the 3 reviewer prompts and
   produces a structured verdict. Separate script, not a flag on
   `solve_issues.py`. 45/45 new tests in
   `tests/test_reviewer_runtime.py`. Also a separate `--local-branches`
   mode landed via PR #332 / commit `5d1513f` (17 new tests pin
   the safety rule for `post_merge_cleanup.py`).
4. **Validation Metrics & Run** (the deliverable, **in progress**)
   — generates `reports/validation-0.9.0.md` with solved/partial/
   quote, cost per solved issue, time per solved issue, top-5 error
   classes. **Hard Definition of Solved: PR merged + CI green,
   produced by the Solver pipeline itself.** Anything less does not
   count. Skeleton in place at `reports/validation-0.9.0.md`;
   first real run pending. Validation-target issue opened: **#333**
   (small, well-scoped docstring change in `review_pr.py`).

**Important:** the four landed pieces above are all **Mavis-as-dev
infrastructure** (the human-equivalent work of building the
machine). They do NOT count toward the 0.9.0 metric. The 0.9.0
metric is the empirical evidence from the Solver itself, not from
Mavis in chat. The validation report at
`reports/validation-0.9.0.md` explicitly distinguishes
pipeline-produced PRs from human/AI-assisted PRs. See the
"Mavis-as-dev vs the system Mavis is being measured on" entry
in agent memory (2026-06-18).

**Out of scope:** Handover Audit, Knowledge Dry Run, AI Contributors,
new agents, new architecture, model benchmarking, cross-repo
validation.

### Architectural invariants to preserve

- "Solver stays dumb" — the solver gets the issue, the touched files,
  and one skill. Nothing else. 0.8.0 must not add LLM
  responsibilities to `solve_issues.py`.
- `.agents/skills/` for workflows with helpers/tests/examples;
  `.agents/reviewers/` for LLM invocation profiles. Do not collapse.
- Knowledge Manager is fail-closed: the solver role cannot run
  `promote` or `delete`. The same posture applies to any future
  destructive operation.

## Resolved Questions (closed by 0.7.0)

- ~~Should `NEXT_BACKLOG.md` be renamed?~~ Yes — done in the audit
  (`BACKLOG/open.md` + `BACKLOG/done.md` + `ROADMAP.md`).
- ~~How should context be routed to agents?~~ `config/role_routing.yaml`
  (delivered in #314).
- ~~How should outdated information be removed?~~ `keep / promote /
  archive / delete` lifecycle, deterministic script
  (`scripts/knowledge_manager.py`), human-in-the-loop for destructive
  actions.
- ~~How should outside-in reviews be performed?~~ `architecture_agent`
  (future, parked) for project direction; `reviewer_architecture`
  for per-PR review. Roles split to avoid overlap.
- ~~Should 0.8.0 ship as planned?~~ No. The planned scope had no
  independent identity. Pivoted to 0.9.0 Solver Validation.

## Resolved Questions (closed by 0.9.0 prep, 2026-06-18)

- ~~Backlog health~~ — `docs/BACKLOG/open.md` was 648 lines, ten
  stale sections moved to `done.md` via PR #330 (commit `f515ac7`).
  §37 and §39 parked under `## Parked / Future` with explicit
  `Parked because:` annotations. Old `NEXT_BACKLOG.md` references
  inside §22 replaced with `open.md`. File is now a reliable input
  for the validation run's issue selection.
- ~~Cost-limit flags on batch / overnight~~ — `--max-run-cost-usd`,
  `--max-run-input-tokens`, `--max-run-output-tokens` now flow from
  `solve_issues_batch.py` and `run_overnight.py` to the worker
  process. PR #328 (commit `85c8821`), 9 new tests.
- ~~Reviewer runtime~~ — `scripts/review_pr.py` exists; can be invoked
  as `python scripts/review_pr.py --pr N --role code` (or
  `architecture` / `documentation`). PR #329 (commit `bfc65c7`),
  45 new tests.
- ~~Local branch cleanup helper~~ — `post_merge_cleanup.py
  --local-branches [--base develop] [--apply] [--show-unmerged]`
  exists with the safety rule pinned by 17 tests. PR #332 (commit
  `5d1513f`).

## Open Questions

- **Solver effectiveness** — no real pipeline run yet. Validation
  target issue opened (#333) for the first Solver run. The
  validation report skeleton is in place at
  `reports/validation-0.9.0.md` and will be populated when the
  first run lands. This is THE 0.9.0 question.
- **GITHUB_TOKEN validity for the first Solver run** — `gh auth
  status` returns "Bad credentials" as of 2026-06-18 02:25 UTC.
  Needs a fresh token before the first `solve_issues.py` run can
  push branches and open PRs.
