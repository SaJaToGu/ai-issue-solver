# Current Context

Created: 2026-06-15 (file introduced as part of Release 0.7.0 information
architecture audit, issue #309).
Last rewritten: 2026-06-18 (pivot from 0.8.0 to 0.9.0 Solver Validation).

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

1. **Backlog Cleanup** (Pre-Work, no issue) — 10 stale sections in
   `docs/BACKLOG/open.md` to be moved to `done.md` with provenance.
2. **Cost-Limit-Forwarding Fix** — `solve_issues_batch.py` and
   `run_overnight.py` must forward `--max-run-cost-usd`,
   `--max-run-input-tokens`, `--max-run-output-tokens` to spawned
   `solve_issues.py` workers. Without this, validation cannot
   enforce a budget.
3. **Reviewer Runtime** — separate script (not a flag on
   `solve_issues.py`) that loads one of the 3 reviewer prompts and
   produces a structured verdict for a PR. Hard dependency for
   the validation run.
4. **Validation Metrics & Run** — a `reports/validation-0.9.0.md`
   with solved/partial/quote, cost per solved issue, time per
   solved issue, top 5 error classes. **Hard Definition of Solved:
   PR merged + CI green.** Anything less does not count.

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

## Open Questions

- **Backlog health** — `docs/BACKLOG/open.md` is 1043 lines and
  under-prioritised. Backlog cleanup is Pre-Work for 0.9.0; not yet
  done. Open.
- **Solver effectiveness** — no empirical data yet on the solver's
  real-world success rate, cost per issue, or common failure modes.
  This is the 0.9.0 question.
