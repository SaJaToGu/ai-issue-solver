# Current Context

Created: 2026-06-15 (file introduced as part of Release 0.7.0 information
architecture audit, issue #309).

This document is a **short-lived snapshot** of where the project stands. It
should be revisited after every release via
[`RELEASE_REVIEW_AGENDA.md`](RELEASE_REVIEW_AGENDA.md) and rewritten
whenever the situation changes materially.

## Current Release

- Release 0.6.0 completed.
- `develop` merged into `main`.
- Version 0.6.0 released.
- Issue #309 opened as starting point for Release 0.7.0 planning.

## Current Focus Areas

### Information Architecture

Review and simplify project documentation.

**Questions:**

- What information belongs where?
- Which documents are still needed?
- Which documents are obsolete?

### Agent Context Routing

**Define:**

- Planner context
- Solver context
- Reviewer context
- Watchdog context

**Goal:** Provide each agent only the information required for its role.

### Release Review Process

Introduce a repeatable release review workflow.
Planner should eventually prepare release review discussions.

### Knowledge Structure

Current discussion suggests separation between:

- Long-term project context
- Current release context
- Discussions
- Issues

Exact structure still under review.

## Open Questions

- Should `NEXT_BACKLOG.md` be renamed? → **Yes, done in this audit** (now
  `docs/BACKLOG/open.md` + `docs/BACKLOG/done.md` + `docs/ROADMAP.md`).
- Which existing documents can be removed? → see the
  [Release 0.7.0 audit document](#) (or issue #309) for the per-document
  decisions.
- How should discussion results be captured? → **Rule:** a discussion
  result only becomes permanent project knowledge if it survives the
  release-review process. Otherwise it stays as a discussion artifact.
- How should context be routed to agents? → `config/role_routing.yaml`
  (planned, not yet implemented).
- How should outdated information be removed? → lifecycle: `keep`,
  `promote`, `archive`, `delete`. Handled via the release-review agenda.
- How should outside-in reviews be performed? → Architecture Agent
  (future); see [`AGENTS.md`](AGENTS.md).
