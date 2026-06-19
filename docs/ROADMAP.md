# Roadmap

> **📌 Sprachhinweis / Language Note:**
> Englisch für technische Inhalte; Release-Planung wird von KI-Workern verarbeitet.
> English for technical content; release planning is processed by AI workers.

This document captures the **long-term direction** for the `ai-issue-solver`
project. It is intentionally lean and strategic; concrete tasks live in
[`BACKLOG/open.md`](BACKLOG/open.md).

## Themes

- **Information architecture** — every agent only gets the context it needs.
  See [Release 0.7.0 planning discussion](#).
- **Agent-specific context routing** — Planner gets more, Solver gets less,
  Reviewer gets the diff + rules, Watchdog gets cost + status.
- **Cost & process control** over model benchmarking. See #16, #37, #38, #39.
- **Provider abstraction** — GitHub-first, OpenRouter, native APIs as fallback.
  See [`REPO_PROFILE_PROVIDER.md`](REPO_PROFILE_PROVIDER.md).
- **Knowledge lifecycle** — every piece of information either gets
  `kept` / `promoted` / `archived` / `deleted`. Nothing lingers.

## Release Anchors

- **0.6.0** done — skills + rework + batch cost forwarding.
- **0.7.0** done — Information architecture, role-based context
  routing, release-review process. Close-out:
  [`RELEASE_REVIEW_0.7.0.md`](RELEASE_REVIEW_0.7.0.md).
  Release notes: [`RELEASE_NOTES_0.7.0.md`](RELEASE_NOTES_0.7.0.md).
- **0.8.0** skipped — planned as Governance & Knowledge Release,
  but the scope (Handover Audit + Reviewer Runtime + Knowledge
  Dry Run) had no independent identity once meta-planning began.
  Pivoted.
- **0.9.0** planned — Solver Validation Release. The first release
  whose success criterion is empirical evidence that the solver
  resolves real GitHub issues end-to-end. Plan:
  [`PLANNING_0.9.0.md`](PLANNING_0.9.0.md).
  Four pieces: Backlog Cleanup (Pre-Work), Cost-Limit-Forwarding
  Fix, Reviewer Runtime, Validation Metrics & Run. Hard Definition
  of Solved: PR merged + CI green.
- **1.0.0** target — Runnable workflow app for AI-assisted repository
  work. The app coordinates transparent, reviewable steps around one
  repository: triage, planning, model selection, solver execution,
  observation, review, rework, recovery, merge preparation, and
  reporting. Product vision:
  [`PRODUCT_VISION_1.0.md`](PRODUCT_VISION_1.0.md).

## Strategic Items (not yet in Backlog)

These need decomposition into `BACKLOG/open.md` items before they become
executable:

- Knowledge Manager as deterministic workflow (not LLM agent).
- Watchdog as cron-driven skill (not LLM agent).
- Per-role model routing as a config file (`config/role_routing.yaml`).
- Documentation lifecycle automation (archive / promote scripts).

## Out of Scope

- New solver features before the documentation & context story is settled.
- Model benchmarking without a cost-control baseline in place.
