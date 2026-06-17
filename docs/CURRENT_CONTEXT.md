# Current Context

Created: 2026-06-15 (file introduced as part of Release 0.7.0 information
architecture audit, issue #309).
Last rewritten: 2026-06-18 (after Release 0.7.0 close-out).

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
- 0.8.0 planning has not started.

## Current Focus Areas

### 0.8.0 candidates (from the 0.7.0 close-out)

- **Wire reviewer prompts to a runtime** in a separate script (not in
  `solve_issues.py`). Issue to be filed.
- **Handover document audit** — deferred from #309. Issue to be filed.
- **`architecture_agent` (future) — promote or remove.** Issue to be
  filed.
- **Backlog triage for 0.8.0** — `docs/BACKLOG/open.md` is 1043 lines and
  most items are not prioritised.
- **Knowledge Manager first dry-run** for the `archive` rule (no human
  review). `promote` / `delete` stay human-gated.
- **Watchdog cron + dashboard wiring** — verify the JSON status report
  is consumable by `status_dashboard.py`.

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

## Open Questions

- **Handover document audit** — the audit deliverable for #309 was
  deferred. Open.
- **Backlog health** — `docs/BACKLOG/open.md` is large and
  under-prioritised. Open.
