# Release Notes — 0.7.0

> **Status:** Released 2026-06-17.
> **HEAD at release:** `b8fabf5`.
> **Close-out:** [`RELEASE_REVIEW_0.7.0.md`](RELEASE_REVIEW_0.7.0.md).

Release 0.7.0 is the **architecture release**. The previous releases
added solver features; 0.7.0 makes the *context* and *routing* explicit
and gives the project a recurring release-review process.

## What's new

### Per-role model routing — `config/role_routing.yaml`

Each role (`planner`, `solver`, `reviewer_code`, `reviewer_architecture`,
`reviewer_documentation`, `architecture_agent`) now has its own
provider, model, context-files list, and monthly budget. Slugs are
verified against the live OpenRouter catalog at startup; missing or
stale slugs are a hard fail, not a silent fallback. Total monthly
budget: **55 USD** across all LLM roles.

### Deterministic workflows

Two workflows that were "LLM agents" became deterministic scripts
with optional LLM escalation only on anomaly:

- **`scripts/watchdog.py`** — cost / progress / stuck monitoring.
  Cron-friendly exit codes (`0/1/2`).
- **`scripts/knowledge_manager.py`** — `keep / promote / archive /
  delete` lifecycle for project knowledge. Human-in-the-loop for
  destructive actions; fail-closed so the solver can never run
  `promote` or `delete`.

### Reviewer sub-roles

Reviewer is now three roles with their own model, context, and prompt:

- `reviewer_code` — Claude Sonnet 4 — `.agents/reviewers/reviewer-code.md`
- `reviewer_architecture` — GPT-5 — `.agents/reviewers/reviewer-architecture.md`
- `reviewer_documentation` — M2.5 — `.agents/reviewers/reviewer-documentation.md`

Selectable via labels `agent/reviewer-{code,architecture,documentation}`.
The prompts are **loadable artifacts**; runtime wiring is a 0.8.0
follow-up. The 0.7.0 release delivers the contracts.

### Skill unification

All 8 skills now live under `.agents/skills/`. The old `.skills/`
folder is gone. No skill renamed, no skill invented, no skill content
changed.

### Information architecture

The docs hierarchy is now distinguishable by lifetime:

- `docs/ROADMAP.md` — long-term direction.
- `docs/CURRENT_CONTEXT.md` — short-lived snapshot, rewritten each
  release.
- `docs/BACKLOG/open.md` — current executable work.
- `docs/BACKLOG/done.md` — closed work, kept for traceability.
- `docs/RELEASE_REVIEW_AGENDA.md` — recurring release-review process.

## Migration

No breaking changes. Existing solver runs continue to work; the
`model_selection.py` heuristics remain. The role routing and the
reviewer sub-roles are opt-in.

## Known limitations

- **Reviewer prompts are not yet wired to a runtime.** A PR can be
  reviewed by hand using the prompt as a checklist, but not by the
  solver. (Follow-up issue planned for 0.8.0.)
- **`architecture_agent` (future)** is still parked — purpose documented
  but no implementation.
- **Handover document audit** — the audit deliverable that discovered
  this release is itself a candidate for the same audit. Deferred.
