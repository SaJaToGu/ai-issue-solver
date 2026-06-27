# Current Context

Created: 2026-06-15 (file introduced as part of Release 0.7.0 information
architecture audit, issue #309).
Last rewritten: 2026-06-27 (0.9.0 release close-out).

This document is a **short-lived snapshot** of where the project stands. It
should be revisited after every release via
[`RELEASE_REVIEW_AGENDA.md`](RELEASE_REVIEW_AGENDA.md) and rewritten
whenever the situation changes materially.

## Current Release

- Release 0.9.0 is closed as of 2026-06-27. The version file remains
  `0.9.0`; the historical `v0.9.0` tag already exists on the earlier
  milestone-sync commit.
- `develop` is the release source branch. The close-out target is to
  fast-forward `main` to the current `develop` head.
- Release notes are in [`CHANGELOG.md`](../CHANGELOG.md). The original
  plan remains in [`PLANNING_0.9.0.md`](PLANNING_0.9.0.md) as a
  historical planning artifact.

## Current Focus After 0.9.0

0.9.0 answered the practical solver-validation question by hardening the
pipeline around real failures:

- worker runs with partial patch application or reject artifacts now
  hard-stop instead of creating misleading PRs;
- rework prompts are anchored to the branch tip and can use a larger
  configurable output cap;
- OpenCode and OpenRouter free-model discovery are dynamic instead of
  relying on stale static lists;
- benchmark sweeps now classify results from run reports, so empty
  responses and OpenRouter 429s are visible as failures instead of
  `success_no_pr`;
- free models are documented as experimental and supervised-only. Paid
  OpenRouter `openai/gpt-4o` remains the strategic default for issues
  whose PRs are intended to merge.

Remaining open work is intentionally narrow:

- §59 — Mode-C patch-mismatch hardening remains watchlist-only until
  there are at least three normal solve-path Mode-C data points.
- §63 — OpenCode app-state conflict remains parked because it depends on
  app-side version alignment rather than a repository-only fix.

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

- **0.10.0 scope** — not yet committed in tracked documentation.
- **Free-model production readiness** — current evidence says
  experimental/supervised-only. Revisit only with fresh benchmark data
  and after §62/§67-style methodology checks remain green.
