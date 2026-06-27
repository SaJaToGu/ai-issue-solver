# Changelog

## 0.9.0 - 2026-06-23 / closed 2026-06-27

- **Validation infrastructure (§42, PRs #395 / #396 / #397):** shipped the
  0.9.0 validation library end-to-end — models + parsers + metrics
  (PR-A), IO + selection + pr_checks (PR-B), and CLI surface + shim
  (PR-C). 126 unit tests, all module line caps respected, CI green on
  Python 3.10 + 3.12.
- **First validation run (§43, PRs #399 / #400 / #401):** N=3 sweep
  across #386 / #387 / #382; all three PRs merged with CI green.
  Validation report archived at `reports/validation-0.9.0.md`.
- **Backward-split loop (§44, PR #403):** detects oversized PRs via
  LOC + file-count thresholds in `scripts/validation/split.py` and
  routes them to sub-issue decomposition. Closes the "1570-line
  monolith" failure mode that surfaced repeatedly during the §42–§45
  sweep.
- **PR rework loop (§45, PR #405):** added `--rework-pr <N>` to
  `solve_issues.py` — reads review threads, builds a focused prompt,
  spawns a worker on the same branch, pushes follow-up commits.
  Replaces the manual review-feedback loop for solver-produced PRs.
- **RepoLens archive (#406, commit `0095f54`):** the no-longer-
  maintained RepoLens wrapper image moved to `scripts/archive/` +
  `docs/archive/` with revival-checklist READMEs. Tests for the
  deprecated wrapper deleted (kept the archive folder would still be
  picked up by `python -m unittest discover -s tests`).
- **Solver-loop hardening (§56 / §57 / §60, PRs #440 / #442 / #445):**
  rework prompts now anchor to the branch tip and configurable token cap;
  partial patch application and reject-artifact failures are hard stops,
  so failed workers no longer create PRs from partial on-disk changes.
- **Dynamic model catalogs (§58 / §66, PRs #443 / #449):** OpenCode and
  OpenRouter free-model discovery moved away from stale static lists.
  Recently removed patterns are injected into solve prompts so workers do
  not silently reintroduce deleted model slugs or old budget defaults.
- **Free-model benchmark methodology (§62 / §67, PRs #448 / #465):**
  benchmark mode now skips PR creation safely and classifies runs from
  worker run reports instead of treating clean process exit as success.
  The #450 smoke benchmark correctly classified two empty responses and
  two OpenRouter 429 rate-limit failures.
- **0.9.0 close-out (#450 / PR #466):** README repository structure and
  free-model status were updated. Free models remain experimental and
  supervised-only; paid OpenRouter `openai/gpt-4o` stays the strategic
  default for merge-intended issues.

## 0.3.1 - 2026-06-01

- Prevented failed worker runs from opening pull requests when only tool side-effect files changed.
- Ignored known worker artifacts such as `.aider*` files and `.DS_Store` during failed-run change assessment.
- Kept target repository artifacts out of the side-effect filter so real project changes are still reviewed.

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
