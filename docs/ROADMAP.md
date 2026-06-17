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
- **0.8.0** — TBD. Candidate anchors in
  [`RELEASE_REVIEW_0.7.0.md` §6](../../docs/RELEASE_REVIEW_0.7.0.md#6-suggested-080-anchors).

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
