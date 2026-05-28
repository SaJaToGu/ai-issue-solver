# Changelog

## 0.3.0 - 2026-05-28

- Refactored worker command construction, dashboard lifecycle helpers, and batch retry/result bookkeeping without changing core behavior.
- Added clearer dashboard handling for historical failed runs, recovered work, merged PRs with open issues, and Vibe turn-limit warning runs.
- Expanded overnight run summaries with per-issue outcome fields and prioritized PR review order.
- Added backlog cleanup tooling for completed NEXT_BACKLOG items.
- Improved Mistral Vibe run report context and batch result review summaries.

## 0.2.0 - 2026-05-27

- Added Mistral Vibe and OpenCode worker support.
- Added bounded batch solving, conflict-aware batch planning, and fallback handling for rate-limited Codex runs.
- Added worker health reporting, queued run reports, and richer status dashboard lifecycle views.
- Added unattended overnight runner support.
- Added RepoLens report import and constrained Docker audit tooling.
- Added post-merge cleanup helpers for merged AI pull requests and stale AI branches.
- Added documentation for workflow, setup, language policy, and release stabilization.
