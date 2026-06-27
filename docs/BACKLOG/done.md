# Done Backlog

> **📌 Sprachhinweis / Language Note:**
> Diese Datei bleibt bewusst auf Englisch, da sie als Vorlage für GitHub Issues dient
> und von KI-Workern verarbeitet wird. Siehe [Sprachrichtlinie](../LANGUAGE_POLICY.md)
> This file remains in English as it serves as a template for GitHub Issues and is
> processed by AI workers. See [Language Policy](../LANGUAGE_POLICY.md)

This file archives **completed** backlog items from the `ai-issue-solver`
project. Items are moved here from [`open.md`](open.md) once their GitHub
issue is closed. The original section numbers, labels, and priority are
preserved for traceability.

For active work, see [`open.md`](open.md). For long-term direction, see
[`../ROADMAP.md`](../ROADMAP.md).

---

## Done — Skill: model-selection (foundation for routing)


Closed via skill conversion. `scripts/model_selection.py` is now exposed
as a reusable Codex Skill at
[`.agents/skills/model-selection/`](.agents/skills/model-selection/SKILL.md).
The skill accepts `--repo-type`, `--language`, `--task-type`, `--issue`,
`--issue-text`, `--labels`, `--touched-files`, `--max-cost-tier`,
`--history` and `--manual-model`, and returns a stable JSON or text
result with `model`, `category`, `risk`, `cost_tier`, `fallback_plan`,
`inputs` and `routing`. The skill is the foundation for the future
routing rules referenced throughout this backlog (see #37, #38, #39,
and the language- and task-type-aware heuristics discussed in #16).

Touches: `.agents/skills/model-selection/`,
         `scripts/model_selection.py` (unchanged), `README.md`

---
## Done — Repo-Profile: GitHub-first, local-fallback (#16, #188, #213)


Closed via the provider-neutral `RepoProfile` abstraction. The solver now
asks `build_repo_profile()` for a profile whenever a run starts:

- `GitHubRepoProfileProvider` is the primary source: it pulls language byte
  shares from `/repos/{owner}/{repo}/languages`, repo metadata for the
  default branch / archived / private / size / description, topics,
  workflows, open PRs and open issues, plus a recursive git tree filtered
  through `is_secret_path()`.
- `LocalRepoProfileProvider` is the thin offline fallback that walks the
  checked-out files and uses marker heuristics (`DESCRIPTION`, `renv.lock`,
  `app.R`, `pyproject.toml`, `package.json`, …) without ever reading
  `.env`, `auth.json`, or other secret files.
- `build_repo_profile()` selects the provider via `select_profile_provider`
  (GitHub-first, but switches to local when `offline=True` or no token is
  configured) and transparently falls back to local on transient GitHub
  errors so solver runs keep moving.
- `solve_issues.py` uses the resulting `repo_kind` (e.g. `python`, `r`,
  `node`, `docs-only`) for the `auto_model` path instead of hard-coded
  `python`; the serialized profile is persisted to `metadata.json` and
  `summary.txt` of every run report and is never allowed to leak secret
  file paths.

Touches: `scripts/repo_profile.py`, `scripts/solver_reporting.py`,
         `scripts/solve_issues.py`, `tests/test_repo_profile.py`,
         `tests/test_solver_reporting.py`

---
## Done — §36 Persist dashboard repo, tab and agent selection in URL parameters (#261)

Closed via #261. Persist dashboard repo, tab and agent selection in URL parameters.

Original labels: `kind/feature`, `theme/dashboard`, `theme/quality`, `agent/solver`

Touches: `scripts/status_dashboard.py`, `scripts/serve_dashboard.py`

---
## Done — §38 Parallel Solver Ensemble – mehrere Modelle auf ein Issue, beste Lösung gewinnt (#263)

Closed via #263. Parallel Solver Ensemble — multiple models on one issue, best wins.

Original labels: `kind/feature`, `theme/workflow`, `agent/solver`, `priority/1`

Touches: `scripts/solve_issues.py`, `scripts/benchmark_issues.py`, `scripts/status_dashboard.py`, `tests/`

---
## Done — §26 Run tests after each solver fix and include the result in the PR body (#281)

Closed via #281. Run tests after each solver fix and include the result in the PR body.

Original labels: `kind/automation`, `theme/quality`, `theme/workflow`

---
## Done — §28 Track solver success rate with a benchmark script (#247)

Closed via #247. Track solver success rate with a benchmark script (`scripts/benchmark_solver.py`).

Original labels: `kind/automation`, `theme/quality`, `theme/workflow`, `theme/provider`

---
## Done — §31 Implement agent/triage — automated issue classification and routing (#256)

Closed via #256. Implement `agent/triage` — automated issue classification and routing.

Original labels: `kind/automation`, `theme/workflow`, `theme/github`, `agent/triage`

---
## Done — §32 Implement agent/cost — dedicated cost tracking and budget alert agent (#257)

Closed via #257. Implement `agent/cost` — dedicated cost tracking and budget alert agent.

Original labels: `kind/automation`, `theme/workflow`, `theme/dashboard`, `agent/cost`

---
## Done — §33 Implement agent/research — structured research report framework (#258)

Closed via #258. Implement `agent/research` — structured research report framework.

Original labels: `kind/automation`, `theme/research`, `theme/workflow`, `agent/research`

---
## Done — §34 Implement agent/planner — idea-to-issue shaping pipeline (#259)

Closed via #259. Implement `agent/planner` — idea-to-issue shaping pipeline.

Original labels: `kind/automation`, `theme/backlog`, `theme/workflow`, `agent/planner`

---
## Done — §35 Implement agent/reviewer — automated PR review and rework detection (#260)

Closed via #260. Implement `agent/reviewer` — automated PR review and rework detection.

Original labels: `kind/automation`, `theme/quality`, `theme/workflow`, `agent/reviewer`

---
## Done — §40 Add compact growing progress heartbeat for long-running solver jobs (#286)

Closed via #286. Add compact growing progress heartbeat for long-running solver jobs.

Original labels: `kind/feature`, `theme/workflow`, `agent/supervisor`, `priority/2`

Touches: `scripts/solve_issues.py`, `scripts/solve_issues_batch.py`, `tests/`

---

## Done — §5 Evaluate mobile-first Claude Code alternative to Codex (#191)

Closed via #191. Evaluate mobile-first Claude Code alternative to Codex.

Original labels: `kind/automation`, `theme/quality`, `theme/provider`, `theme/workflow`

---
## Done — §16 Use GitHub repository intelligence before local repo type detection (#213)

Closed via #213. Use GitHub repository intelligence before local repo type detection.

Original labels: `kind/automation`, `kind/analysis`, `theme/quality`, `theme/workflow`, `theme/github`

---
## Done — §17 Add workflow control for backlog and PR queue congestion (#216)

Closed via #216. Add workflow control for backlog and PR queue congestion.

Original labels: `kind/automation`, `theme/workflow`, `theme/dashboard`, `theme/quality`

---
## Done — §18 Harden Codex sandbox and escalated-command workflow handling (#217)

Closed via #217. Harden Codex sandbox and escalated-command workflow handling.

Original labels: `kind/automation`, `theme/workflow`, `theme/codex`, `theme/quality`

---
## Done — §19 Add structured rework workflow with sub-issues and separate PRs (#220)

Closed via #220. Add structured rework workflow with sub-issues and separate PRs.

Original labels: `kind/automation`, `theme/workflow`, `theme/quality`, `theme/github`

---
## Done — §21 Add solver process supervisor for monitoring and targeted cancellation (#223)

Closed via #223. Add solver process supervisor for monitoring and targeted cancellation.

Original labels: `kind/automation`, `theme/workflow`, `theme/dashboard`, `theme/quality`

---
## Done — §24 Trigger the solver automatically via GitHub Actions when an issue is labeled (#243)

Closed via #243. Trigger the solver automatically via GitHub Actions when an issue is labeled.

Original labels: `kind/automation`, `theme/workflow`, `theme/github`

---
## Done — §6 Support low-code and non-code repositories without Python assumptions (#188)

Closed via #188. Support low-code and non-code repositories without Python assumptions.

Original labels: `kind/automation`, `theme/quality`, `theme/workflow`, `kind/analysis`

---
## Done — §15 Add vertical process quality analysis and periodic workflow retrospective (#218)

Closed via #218. Add vertical process quality analysis and periodic workflow retrospective.

Original labels: `kind/automation`, `theme/quality`, `theme/workflow`, `theme/dashboard`

---
## Done — §25 Decompose oversized issues into sub-issues automatically (#244)

Closed via #244. Decompose oversized issues into sub-issues automatically.

Original labels: `kind/automation`, `theme/workflow`, `theme/github`, `theme/quality`

---
## Done — §41 Add label_taxonomy + label_usage_health checks to analyze_repos (#391)

Closed via #391 (PR #392). Added two new onboarding checks to
`scripts/analyze_repos.py`:

- `label_taxonomy_exists` — flags repos without a documented label
  taxonomy (`docs/label_taxonomy.md` or label section in `CONTRIBUTING.md`),
  with suggestion to derive from the AIS standard template.
- `label_usage_health` — flags labels defined but never used, untriaged
  open issues/PRs, and issue labels not present in the repo's taxonomy
  documentation.

Implementation notes: 13 unit tests added in `tests/test_analyze_repos.py`
covering all three sub-cases (defined-but-unused, untriaged, undefined)
plus an empty-list edge case. CI green on Python 3.10 + 3.12.

Review verdict: `request changes` (2 blockers + 5 suggestions); user opted
to merge as-is after manual review of the suggestions.

Original labels: `kind/feature`, `theme/quality`, `area/labels`, `priority/3`

---
## Done — §42 0.9.0 Validation Metrics & Run (GitHub #326)

Closed via #326 (PR #395 + #396 + #397, merged into develop @ 4b2589b).

3-PR stacked delivery:
- PR-A #395 (library, models+parsers+metrics, 49 tests)
- PR-B #396 (IO, github_client+runner+pr_checks+selection, 101 tests)
- PR-C #397 (CLI surface, cli+shim+__init__, 123 tests, +follow-up fix → 126 tests)

Module line caps all respected (largest: github_client.py 231/250). All 9
modules under their caps. CI green on Python 3.10 + 3.12.

Definition of Solved (per the issue): code ships; the actual first
validation run with N=3 issues is a follow-up to demonstrate
end-to-end (deferred to a separate issue to keep #326 PR-reviewable).

User code-review feedback mid-PR: removed hardcoded defaults
('validation-0.9.0' as title, 'SaJaToGu' as owner fallback,
'opencode/deepseek-v4-flash-free' as model default) — now all
fail-fast if not in config or supplied via CLI / env var.

Original labels: `kind/analysis`, `kind/feature`, `theme/quality`, `priority/1`

---
## Done — §43 First validation pass with N=3 (GitHub #398)

Closed via #398 (PRs #399, #400, #401, all merged into develop).

3 PRs created + merged (3/3 per-issue success on PR creation, 0/3
on the strict "merged + CI green" definition at first read — since
then: 3 PRs merged, all CI green). Validation infrastructure from
#326 is now end-to-end proven.

The validation-0.9.0.md report at reports/validation-0.9.0.md is the
deliverable.

Original labels: `kind/analysis`, `kind/feature`, `theme/quality`, `priority/2`

---

## Done — §44 Add backward-split loop: detect oversized PRs and route to sub-issues (GitHub #402)

Closed via #402 (PR #403, squash-merged into develop at 2026-06-22T20:17:06Z).

PR #403 head `ai/fix-issue-402` (+964/-6, 12 files) was followed by a
review-rework commit on the same branch addressing 2 review blockers
(github_client.py over line cap; hardcoded "#402" in close comment) and
3 minor suggestions.

Final file layout (LOC vs cap):
- `scripts/validation/github_client.py` 231 / 250 ✓
- `scripts/validation/split.py` 182 / 300 ✓
- `scripts/validation/git_notes.py` 81 / 150 ✓
- `scripts/validation/split_client.py` 105 (new — split off from
  github_client.py via composition)
- `scripts/validation/cli.py` 395 / 700 ✓

Tests: 165/165 validation tests pass (Python 3.10 + 3.12 CI green).

Open follow-up: §45 / Issue #404 (PR rework loop via model call) so
future PRs with review feedback can be reworked through the solver
pipeline instead of manual Mavis-as-dev refactor.

Original labels: `kind/refactor`, `theme/workflow`, `area/runs`, `priority/2`

---

## Done — §45 Add PR rework loop: apply review feedback via model call (GitHub #404)

Closed via #404 (PR #405, squash-merged into develop at 2026-06-22T21:54:22Z).

PR #405 (+1032/-4, 9 files) introduced the `--rework-pr` CLI flag
end-to-end: read PR review threads, fetch the diff, build a focused
prompt, spawn a worker on the same branch (no `skip_existing_pr`
fight), push follow-up commits, re-run CI. Initial CI run failed
3 tests because `REWORK_PROMPT_PATH` was CWD-relative; follow-up
commit `3737d58` resolved it to `Path(__file__).resolve().parents[2]`.

Files (final layout):
- `prompts/rework_pr.md` (new, 38 lines) — focused prompt template
- `scripts/validation/rework.py` (new, 462 lines) — orchestrator
  (prompt build, worker subprocess, clone/checkout/commit/push,
  run-report, git notes)
- `scripts/validation/runner.py` (+23) — `run_rework_for_pr()` entry
- `scripts/validation/github_client.py` (+77) — `get_pr_review_threads`
  + `get_pr_diff` helpers
- `scripts/validation/git_notes.py` (+32) — `add_rework_to_note()`
- `scripts/solve_issues.py` (+58/-3) — `--rework-pr` CLI flag
- `tests/test_validation/test_rework.py` (new, 11 unit tests)
- `tests/test_rework_pr_cli.py` (new, 5 CLI tests)
- `docs/BACKLOG/open.md` (+1/-1) — §45 entry

Tests: 176/176 validation tests pass + 5 CLI tests + 11 rework
tests (Python 3.10 + 3.12 CI green after fix).

Original labels: `kind/feature`, `theme/workflow`, `area/runs`, `priority/2`

---

## Done — §46 Sync VERSION file and CHANGELOG to current 0.9.0 milestone (GitHub #410)

Closed via #410 (PR #413, squash-merged into develop at commit `74b08cb`).

Single-commit diff:
- `VERSION` (+1/-1) — bumped from `0.3.1` to `0.9.0`
- `CHANGELOG.md` (+25) — new top section `## 0.9.0 - 2026-06-23`
  summarising §42–§45 work (validation library, first validation run,
  backward-split loop, PR rework loop) plus the RepoLens archive (#406)
- `docs/BACKLOG/open.md` (+135) — §46/§47/§48 entries (the two
  follow-up items got their own done.md entries below)

Tag `v0.9.0` pushed to origin immediately after the squash-merge.

Original labels: `kind/refactor`, `priority/3`, `theme/workflow`

---

## Done — §47 Deprecate Aider worker adapter in favour of opencode/openrouter/codex (GitHub #411)

Closed via #411 (PR #414, squash-merged into develop at commit `a16fbd6`).

Adapter stays functional — only a deprecation signal was added. Four
files touched (+92/-2):
- `workers/aider_adapter.py` — new `_emit_aider_deprecation_warning()`
  helper + module-level `_AIDER_DEPRECATION_EMITTED` guard. Called from
  `AiderAdapter.__init__` with `stacklevel=2`. Module docstring now has a
  Sphinx-style `.. deprecated::` directive listing the three supported
  paths.
- `requirements-aider.txt` — header rewritten with a deprecation banner
  and migration note. The `aider-chat` pin stays.
- `docs/SETUP_AIDER.md` — top-of-file banner flags the deprecation and
  points at opencode / openrouter_direct / codex.
- `tests/test_worker_adapters.py` — new
  `test_aider_emits_deprecation_warning_on_init` asserts the warning
  fires exactly once and references all three supported paths.

Local tests: 94/94 `TestWorkerAdapters` green, including the new test.
The once-per-process guard keeps existing tests printing the warning to
stderr once but not failing.

Follow-up (separate issue, NOT here): actual removal of
`workers/aider_adapter.py`, `requirements-aider.txt`, and
`docs/SETUP_AIDER.md` after 1–2 releases confirm zero usage in
`reports/runs/.../metadata.json`.

Original labels: `kind/refactor`, `priority/3`, `theme/workflow`, `theme/provider`

---

## Done — §48 Consolidate rework/retry flag surface across solve_issues.py (GitHub #412)

Closed via #412 (PR #415, squash-merged into develop at commit `5304258`
after a rebase onto the post-§46 develop — no semantic conflict, just
the open.md § entries had to be re-applied). Tag cleanup followed.

Scope delivered (no flag removal yet — that is the explicit follow-up):
- `scripts/solve_issues.py` (+56) — new module-level
  `REWORK_FLAG_USAGE_LOG` constant pointing at
  `reports/usage/rework-flags.jsonl`, plus `_log_rework_flag_use()`
  helper that appends one JSON line per invocation when any of
  `--rework` / `--retry` / `--rework-pr` / `--compare-models` is set.
  Best-effort I/O with a single `print_warn` on failure. Env-var
  opt-out (`AIS_REWORK_FLAG_NO_LOG`) for unit tests.
- `docs/WORKFLOW.md` (+27) — new "Which rework path do I want?" decision
  matrix covering all four entry points plus `rework_workflow.py`, with
  a cheat rule of thumb. Linked from the existing `rework_workflow.py`
  section.
- `docs/BACKLOG/open.md` (-10) — housekeeping: removed duplicated
  `Touches:` / `Checks:` tail block in §39 (pre-existing copy-paste
  artifact from earlier § cleanup work).
- `tests/test_solve_issues.py` (+120) — new `TestReworkFlagUsageLog`
  class with 4 unit tests covering no-op without flag, single-flag
  entry, `--rework-pr` records PR number + `dry_run`, and combined
  `--retry --compare-models`.

Local tests: 163/163 `test_solve_issues` green, including the new
4 tests. CI green on Python 3.10 + 3.12.

Follow-up (separate issue, NOT here): after one release of telemetry,
analyse `reports/usage/rework-flags.jsonl` for actual flag usage, pick
the canonical rework path, deprecate the others with a clear migration
note.

Original labels: `kind/refactor`, `priority/3`, `theme/workflow`, `area/runs`

---

## Done — §357 Consolidate solver orchestration across single, batch, overnight, benchmark, and dashboard workflows (GitHub #357)

Closed via #357 (PR #416, squash-merged into develop at commit `f17783f`).

**Scope delivered: Step 1 of the proposed refactor only.** The PR
introduces `scripts/solver_commands.py` (175 new lines) as the shared
command-spec module and wires it into seven caller scripts:

- `scripts/solve_issues.py` (+8/-68)
- `scripts/solve_issues_batch.py` (+27/-19)
- `scripts/run_overnight.py` (+24/-29)
- `scripts/solver_supervisor.py` (+2/-22)
- `scripts/status_dashboard.py` (+4/-23)
- `scripts/watchdog.py` (+7/-10)
- `workers/codex_adapter.py` (+2/-2)

Net effect: -168 lines of duplicated command-construction code. New
test module `tests/test_solver_commands.py` (+135) covers the shared
spec.

PR diff: +384/-205 across 9 files. CI green on Python 3.10 + 3.12
(after the opencode WAL/SHM state was clean). Within the §48 size
thresholds (500 LOC / 10 files).

**Steps 2-5 from the original issue body are still pending:**

- Step 2: provider-specific diagnostics (OpenCode WAL/SQLite,
  Codex rate-limit, Mistral Vibe log-tail) into adapter-owned modules
- Step 3: consolidate run-report reading and health classification
  across solver_reporting / dashboard / supervisor / watchdog /
  benchmark / overnight
- Step 4: provider/model catalog and discovery plumbing
- Step 5: full legacy-helper removal (this is what #383 covers once
  the shared layers are stable)

The worker solved the broad issue by hitting Step 1 of the proposed
5-step refactor and stopping there, which produced a PR that fits
the §48 size envelope. The full scope was originally recognised as
BROAD by `split_planning.py` (see audit comment on #357) — the
remaining 4 steps will be picked up via follow-up issues and
`#383 Retired legacy orchestration helpers`.

Original labels: `agent/solver`, `theme/workflow`, `theme/provider`, `area/runs`, `priority/2`, `kind/refactor`

---

## Done — §383 Retire legacy orchestration helpers after shared solver layers land (GitHub #383)

Closed via #383 (PR #417, squash-merged into develop at commit `64d28a8`).

**Scope delivered:** Final cleanup slice for parent #357.

- `scripts/run_overnight.py` (+12/-68) — removed duplicate
  `build_batch_command` / `build_dashboard_command`, dead
  `classify_status`. 56 lines of duplicate code eliminated.
- `scripts/status_dashboard.py` (+9/-68) — consolidated four
  duplicate parsers (`parse_summary`, `parse_datetime_value`,
  `parse_created_at`, `latest_datetime`) into one place in
  `solver_reporting.py`.
- `scripts/solver_reporting.py` (+37/-16) — public API additions
  for the consolidated parsers.
- `scripts/solver_supervisor.py` (+2/-2) — imports updated to use
  `solver_reporting`.
- `scripts/watchdog.py` (+4/-8) — small refactor for shared
  helpers.
- `docs/WORKFLOW.md` (+57/-0) — added section pointing at the
  shared command/outcome layers introduced in #357 (PR #416).
- 4 test files updated.

Net diff: +157/-291 across 10 files = -134 LOC of duplicate
orchestration removed. With #357 (PR #416, +384/-205) and #383
(PR #417) together, the consolidation effort removed ~302 lines of
duplicate code from the solver orchestration surface.

**⚠️ Follow-up:** 5 unit tests in `tests/test_cost_limit_forwarding.py`
fail on Python 3.10 + 3.12 after this PR landed. This is the
**known cost-limit-forwarding gap for run_overnight** — the batch
path was fixed in commit `d811692`; the overnight path was never
done. The #383 refactor surfaces the gap because the now-removed
duplicate `build_batch_command` in `run_overnight.py` was the only
code path the tests were still exercising. Tracked as the new
backlog §50.

Original labels: `agent/solver`, `theme/workflow`, `area/runs`, `priority/2`, `kind/refactor`

---

## Done — §49 Forward --max-run-cost-usd / --max-run-input-tokens / --max-run-output-tokens in run_overnight.py build_batch_command (GitHub #418)

Closed via #418 (PR #419, squash-merged into develop at commit `0a2864b`).

Closes the `d811692` → `run_overnight.py` gap. All three solver
entry points (single, batch, overnight) now accept and forward
`--max-run-cost-usd` / `--max-run-input-tokens` /
`--max-run-output-tokens` / `--max-post-worker-runtime-seconds` to
spawned workers.

**Files (+186/-6 across 5):**

- `scripts/run_overnight.py` (+12/-0) — `build_pull_command` and
  worker spawning both forward all four flags.
- `scripts/solve_issues_batch.py` (+12/-0) — extra flag forwarding
  in `build_worker_command`.
- `scripts/solver_commands.py` (+6/-0) — shared command-spec
  accepts and emits the runtime flag.
- `tests/test_cost_limit_forwarding.py` (+67/-6) — test imports
  updated to the post-#383 structure (no more `build_batch_command`
  direct import); 6 new tests cover the runtime flag forwarding.
- `tests/test_run_overnight.py` (+89/-0) — new
  `OvernightCostLimitForwardingTests` class with 8 tests mirroring
  the batch-side coverage.

**Pre-flight gate workaround (Huhn-Ei-Pattern):**

The first run with the default pre-flight test gate crashed with
`exit_code 1`: the 5 pre-existing `test_cost_limit_forwarding`
failures (`ImportError: cannot import name 'build_batch_command'`)
tripped the wrapper's "Tests fehlgeschlagen; Batch wird nicht
gestartet" gate before the worker could even start. Worker could
not fix the imports because it never ran. Re-run with `--skip-tests`
bypassed the gate; the worker then fixed the test imports AND
implemented the forwarding in the same run, producing a clean PR
with CI green on Python 3.10 + 3.12.

**Lesson for future refactors:** when a refactor removes a function
that existing tests import, the test suite goes red on the wrapper's
pre-flight check, which blocks the worker that would fix it. Either
fix the test imports in a separate small PR first, or pass
`--skip-tests` to let the worker resolve the Huhn-Ei in a single
combined PR.

Original labels: `kind/bug`, `kind/refactor`, `priority/2`, `area/runs`, `theme/cost`

---

## Done — check-prs handles merged PRs with deleted branches + correct CI status (GitHub #420)

Closed via #420 (PR #420, squash-merged into develop at commit `99baa44`).

Surfaced as part of post-#418 follow-up (the user asked "Können wir
eigentlich das Validierung Skript für solche manuellen Änderungen
verwenden?"). Three bugs in `validation_run check-prs` made it
unusable for the common post-merge case:

1. **Head-branch lookup fails for merged PRs** — `cmd_check_prs`
   searched by `head=ai/fix-issue-{N}`. After `--delete-branch` on
   squash-merge, the branch is gone and the lookup returns no PRs.
   Refactored to call `get_pull_request(N)` first (works for any PR
   by number, including merged with deleted branches), with the
   branch-name lookup kept as a fallback for legacy open-PR support.

2. **CI queried on the wrong SHA** — the script queried CI on
   `merge_commit_sha`, but PR CI runs on the PR head SHA, not the
   merge commit. Switched to `head_sha` (with `merge_commit_sha` as
   fallback). Added `head_sha` to the `PullRequestInfo` dataclass
   and populated it in both `get_pull_request` and `get_pull_requests`.

3. **Empty commit-statuses misread as 'pending'** — GitHub's legacy
   commit-statuses API returns `state='pending'` for commits with
   zero legacy statuses (PRs that only use the Check Runs API). The
   combined check then failed. `get_ci_status` now normalises
   empty-statuses to `missing`.

**Argparse:** added `--numbers` as the primary flag; `--issues`
remains as a deprecated alias (hidden from help via
`argparse.SUPPRESS`) and is concatenated with `--numbers` in the
resolver, with deduplication.

**Files (+215/-25 across 5):**

- `scripts/validation/cli.py` — `cmd_check_prs` refactor + new
  `_resolve_pr_for_number` helper + argparse
- `scripts/validation/github_client.py` — `head_sha` field +
  empty-statuses fix
- `tests/test_validation/test_cli.py` — 5 new/updated tests
- `tests/test_validation/test_github_client.py` — 1 new test
- `docs/WORKFLOW.md` — new "Validierung gemergter PRs" section

**Validation (local, 181/181 tests pass):**

```
$ python3 scripts/validation_run.py check-prs --numbers 416 417 419
Checking PRs for up to 3 numbers...
  #416 [MERGED] CI:GREEN  [AI] Fix: Consolidate solver orchestration
  #417 [MERGED] CI:RED     [AI] Fix: Retire legacy orchestration helpers
  #419 [MERGED] CI:GREEN  [AI] Fix: Forward --max-run-cost-usd
```

**Lesson captured (memory):** `validation_run check-prs` should
default to PR-by-number lookup with branch-name as fallback, and
CI should be queried on `head_sha` for both open and merged PRs.
The `--issues` flag remains as a deprecated alias for `--numbers`
to keep older commands working.

---

## Done — build_graph.py: issue/PR/commit network with cost/LOC/color (PR #421)

Closed via #420 (PR #421, squash-merged into develop at commit `e3b7bbb`).

Surfaced from the user question "Wird der Zusammenhang zwischen Issues,
PR's und Brunches aufgelöst und wie ein Netzwerk zusammengebaut?" on
2026-06-23. Answer before this PR was: partial via distributed
sources, no consolidated graph view. Delivered Option 1 of the four
proposed (CLI script with cost/LOC + color-by, half day, ~313 LOC).

**Scope delivered:**

- `scripts/build_graph.py` (313 LOC) — reads `docs/BACKLOG/open.md`,
  `docs/BACKLOG/done.md`, and `reports/runs/*/metadata.json` +
  `summary.txt`. Builds a graph with `issue` / `pr` / `commit` node
  types and `closes` / `merged_into` / `parent_of` edge types.
- Output formats: JSON (default, app-friendly) or DOT (Graphviz).
- Annotations: cost (USD), model, loc_add / loc_del / files, head_sha.
- `--color-by <dimension>` for `model` (discrete map),
  `cost` (green→red gradient), `loc` (green→red gradient),
  `time` (placeholder), `difficulty` (heuristic matching the
  WORKFLOW decision matrix: narrow / medium / broad / unsolved).
- `tests/test_build_graph.py` (24 unit tests, all pass).
- `docs/WORKFLOW.md` — new "Issue/PR/Commit Netzwerk" section
  with usage examples, color-by reference, output schema, and
  limitations called out.

**Parser robustness:**

- Handles backticks around commit SHA: `commit `0a2864b``
- Accepts done.md headers with or without `§N` prefix
- Missing files return empty lists, no crash
- LOC parsing accepts both `across N files` and `in N files`
  format variants

**Out of scope (deferred):**

- **Git notes auto-population** (`refs/notes/ais`): helpers exist in
  `scripts/validation/git_notes.py` but are not actively called by
  the solver pipeline. Could be added to `rework.py` so every
  solver run writes a note.
- **status_dashboard.py tab**: 1-1.5 days of refactor in a 3280-line
  file. JSON output is already dashboard-ready.
- **Native app view**: JSON is app-friendly; deferred to app timeline.

**Note:** AIS-Review (`scripts/review_pr.py`) was NOT run on this
PR before opening it — caught by the user post-merge. Going
forward, AIS-Review is mandatory BEFORE opening a PR.

Original labels: (none — ad-hoc feature, not from a backlog §)

---

## Done — §57: Worker must not report `success` on partial patch application

Closed 2026-06-25 via PR #442 (squash `8d68b50` on develop). 7 files,
+94/-5.

**Bug:** `workers/openrouter_worker.py` returned `returncode: 0`
whenever at least one generated patch applied successfully, regardless
of how many other patches failed. Run-report then recorded
`status: pr_created` and `failure_class: success`, and the worker
proceeded to commit + push + open a PR with a partial diff.

**Repro that triggered the fix:** Issue #389 / PR #441 (closed
2026-06-25, gpt-4o via `--model openrouter_direct`). 2 patches
produced, 1 applied, 1 failed (`scripts/benchmark_issues.py:90`
patch-mismatch — same Mode-C symptom as §56 Rework-pr). PR #441
opened anyway. Reviewer (Guido) caught the regression against
PR #439 only after push (the applied patch reintroduced a stale
static `free_models` list).

**Fix:**

- `workers/base.py`: new `PARTIAL_PATCH_FAILURE_RETURN_CODE = 6`.
- `workers/openrouter_worker.py`: `returncode` semantics reordered —
  `0 = ALL patches applied`, `6 = partial`. Decision tree now
  distinguishes `len(successful) == len(patch_results)` (full success),
  `0 < len(successful) < len(patch_results)` (partial → 6 with
  `PARTIAL-PATCH-FAILURE` log line + per-failed-patch detail), and
  `len(successful) == 0` (all-failed → 1).
- `workers/execution.py` `classify_worker_outcome`: `returncode == 6`
  maps to `WorkerOutcome(should_continue=False, has_changes=True,
  failure_class="partial_patch_failure")`. **Hard stop even when
  files changed** — no commit, no push, no PR-create.
- `scripts/solve_issues.py` docstring updated to match the new
  returncode semantics.

**Acceptance test (User-specified, now codified in tests):**

- Simulated worker with `total_patches=2`, `applied=1`, `failed=1`
- Returns `returncode: 6`, `failure_class: partial_patch_failure`.
- `should_continue: False` even though `has_changes=True`.
- No commit, no push, no PR-create.
- Run-report records non-empty `failed_patches: [{file, error}]`.

**Verification:**

- `./.venv/bin/python -m unittest tests.test_openrouter_worker -v`: 53 OK
- `./.venv/bin/python -m unittest tests.test_worker_execution -v`: 21 OK
- `./.venv/bin/python -m unittest tests.test_worker_adapters -v`: 95 OK
- `./.venv/bin/python -m unittest tests.test_solve_issues -v`: 163 OK
- `git diff --check develop..HEAD` (PR branch): clean
- GitHub CI: Python 3.10 + 3.12 both pass
- User live review: "Keine Findings. PR #442 ist mergebereit."

**Out of scope (deferred / separate items):**

- §58 (priority/3): worker-prompt layer hardening against
  re-introducing recently-removed patterns (e.g. the static
  `free_models` list). Tracked separately in `open.md`.
- Patch-mismatch hardening for the normal solve path (the
  Mode-C fix §56 introduced only for `--rework-pr`). Suggested
  in the original §57 body and still relevant — would prevent
  the partial-patch failure mode from being triggered in the
  first place. Could become §59 once §58 is closed.

Original labels: `kind/bug`, `theme/solver`, `area/validation`,
`priority/1`

---

## Done — §56: Fix the `--rework-pr` workflow in `solve_issues.py`

Closed 2026-06-25 via PR #440 (squash `166f8b2` on develop). 6 files,
+254/-5.

**Bug:** the `--rework-pr` workflow in `solve_issues.py` was broken
across three distinct failure modes, all reproducible:

- **Mode A — OpenRouter 400 before any token output.** Triggered by
  4 different models across 2 providers (e.g. `opencode/deepseek-v4-flash-free`
  via `--model opencode`, `mistral/mistral-large-latest` via
  `--model openrouter_direct`). Slug-format was valid (same slugs
  worked in the normal solve path); the issue was the rework code
  path's request shape (forced `response_format` + `provider.require_parameters=True`).
- **Mode B — output truncated by 4096-token cap** → `status: no_patches`.
  Smaller models (e.g. `openai/gpt-4o-mini`) hit the cap mid-JSON.
- **Mode C — model writes full rewrite-from-scratch diff** that
  `git apply` rejects against the current branch tip →
  `status: patches_failed`, `worker_exit_code: 3`. The rework prompt
  gave the model the PR diff but didn't anchor it to the current
  branch tip SHA or the existing PR commits.

**Fix:**

- `prompts/rework_pr.md`: now carries current head SHA + PR commit
  list (`<existing_commits_list>`) + explicit instruction #6
  "return only an incremental patch for the current branch tip".
- `scripts/validation/rework.py`: `use_structured_output=False` +
  `worker.build_patch_prompt(structured=False)` in the rework code
  path (drops `response_format` + `require_parameters=True` from
  the OpenRouter payload). New `_rework_max_tokens_from_env()` reads
  `OPENROUTER_REWORK_MAX_TOKENS` (default 16384, was hardcoded 8192
  on top of the 4096 cap). New `_format_pr_commits_for_prompt()`
  helper formats the PR commit list for the prompt.
- `scripts/validation/github_client.py`: new
  `get_pull_request_commits(repo, number)` returning commit metadata
  for the PR (404 returns `[]`).

**Verification:**

- `./.venv/bin/python -m unittest tests.test_validation.test_github_client tests.test_validation.test_rework -v`: 39 OK
- `./.venv/bin/python -m unittest tests.test_openrouter_worker -v`: 52 OK
- `./.venv/bin/python -m unittest tests.test_solve_issues -v`: 163 OK
- `git diff --check`: clean
- GitHub CI: Python 3.10 + 3.12 both pass
- User live review: "Sieht gut aus" → squash merge

**Live 3-run rework validation: not executed** (no open PRs were
available to repro against right now). Tracked as a follow-up —
verify against the next real rework case (any new PR that needs
follow-up commits).

**Out of scope (deferred / separate items):**

- §57 (priority/1, now also closed via PR #442): worker must not
  report `success` on partial patch application — same reporting
  layer that hid the §56 Mode-C failures.
- §58 (priority/3): worker-prompt layer hardening against
  re-introducing recently-removed patterns.
- Patch-mismatch hardening for the **normal solve path** (the
  Mode-C fix in §56 only covers `--rework-pr`). The same prompt-
  anchoring + `git apply --check` discipline should be applied
  to the normal solve path too. Could become §59.

Original labels: `kind/bug`, `theme/solver`, `area/cost-cap`,
`priority/2`

---

## Done — §58: PR-review 'static free_models regression' anti-pattern

Closed 2026-06-25 via PR #443 (squash `11eafc1` on develop). 3 files,
+179/-5 (includes the user-found path-leak fix from live review).

**Problem:** the AIS solver can re-introduce patterns the project
explicitly removed in a recently merged PR. The PR #441 episode was
the canonical example: PR #439 had just removed the static
`free_models` list (incl. `opencode/minimax-m3-free`), and the solver
for Issue #389 re-introduced a near-identical list. §57 (PR #442) stops
the resulting partial-patch PR from being opened; §58 stops the
regression at the **source** — the solver's prompt now sees the
recently-removed pattern list and avoids it explicitly.

**Fix:**

- **`docs/AGENTS.md`**: new "Recently Removed Patterns (last 90 days)"
  section with a maintainer-pflegbare Markdown-Tabelle. Initial
  entries: PR #439 (static `free_models` list), PR #437 (hard
  `$20/$20` cost-cap defaults).
- **`scripts/solve_issues.py`**: new `build_solve_prompt(number, title,
  body)` function that appends a "=== RECENTLY REMOVED PATTERNS ===
  (DO NOT RE-INTRODUCE)" section to the normal solve prompt when the
  pattern list is non-empty. Includes the `git log develop` cross-
  check hint and the "explain in PR description if you think you
  need to restore one" rule.
- **`tests/test_solve_issues.py`**: 5 new tests (3 for the pattern-
  file cases, 2 for the path-leak fix from live review).

**Live-review finding (Guido):** the initial implementation included
the local absolute path of `docs/AGENTS.md` in the worker prompt
(leaking the operator's filesystem layout into the LLM context).
Fixed in a follow-up commit on the same branch before merge —
`build_solve_prompt` now displays the pattern-file path as
repo-relative when it lives under `PROJECT_ROOT` (and preserves the
absolute path verbatim when the operator explicitly sets
`AIS_RECENTLY_REMOVED_PATTERNS_FILE` to an out-of-tree path).

**Verification:**

- `./.venv/bin/python -m unittest tests.test_solve_issues -v`: 168 OK
  (was 163 before §58; +3 for pattern cases, +2 for path-leak fix)
- `git diff --check develop..HEAD` (PR branch): clean
- Manual probe of `build_solve_prompt(389, "Test", "Test body")`:
  contains `RECENTLY REMOVED PATTERNS`, `opencode/minimax-m3-free`,
  `PR #439`, `git log develop`, `DO NOT RE-INTRODUCE` markers; does
  NOT contain `PROJECT_ROOT`, `/Users/`, or `tempfile.gettempdir()`.
- GitHub CI: Python 3.10 + 3.12 both pass
- User live review: "Keine neuen Findings. squash merge + delete branch."

**Maintainer obligation going forward:** when a PR intentionally
removes a pattern that future solver runs are likely to rediscover,
add a row to the `Recently Removed Patterns` table in `docs/AGENTS.md`
in the same PR (or a follow-up). Without this, the §58 guard loses
its memory.

**Out of scope (deferred / separate items):**

- §59 (potential): patch-mismatch hardening for the normal solve
  path. With §57 + §58 in place, the failure mode that triggered
  PR #441 should now be caught earlier (no partial PR, no pattern
  re-introduction), but the underlying patch-mismatch itself is
  still possible. A separate item can be filed if/when desired.

Original labels: `kind/process`, `theme/review`, `priority/3`

---

## Done — §60: Returncode 5 (Reject-Artefakte) must hard-stop

Closed 2026-06-26 via PR #445 (squash `2549f0f` on develop). 6 files,
+39/-5.

**Bug:** `workers/execution.py` `classify_worker_outcome` only
hardened against `PARTIAL_PATCH_FAILURE_RETURN_CODE = 6` (PR #442 /
§57). It did **not** generalize to "any nonzero worker-returncode
that produces partial on-disk changes must be a hard stop".

`returncode = 5` (reject artifacts in `OpenRouterWorker`, i.e.
`.orig`/`.rej` files left in the working tree after a partial
`git apply`) still fell through to the generic `nonzero_with_changes`
branch with `failure_class: success`. The run then proceeded to
commit + push + open a PR with whatever changes had been partially
applied.

**Repro (PR #444):** Issue #390 validation run, 2026-06-26, gpt-4o
via `openrouter_direct`:

- `worker_exit_code: 5` (Reject-Artefakte)
- `run_outcome_worker_status: failed`
- `run_outcome_has_changes: True`
- `run_outcome_failure_class: success` (lie classification)
- `run_outcome_delivery_status: pr_created`
- PR #444 was a 5-LOC trivial dummy function
  (`increment_documentation_run_counter` with `pass`)
- `provider_scorecard_test_result: not_run` (timeout 300s on
  partial state)

Run report: `reports/runs/20260625-233528-360515-ai-issue-solver-issue-390/summary.txt`.
Closed PR #444 + deleted branch `ai/fix-issue-390`.

**Fix:**

- **`workers/base.py`**: new shared constant
  `PATCH_VALIDATION_FAILED_RETURN_CODE = 5`. Reason
  `patch_validation_failed` documented in the outcome taxonomy.
- **`workers/execution.py`** `classify_worker_outcome`: new branch
  **between** `partial_patch_failure` and `changed` —
  `returncode == PATCH_VALIDATION_FAILED_RETURN_CODE` →
  `WorkerOutcome(False, has_changes, "patch_validation_failed")`.
  Returns before the generic `nonzero_with_changes` branch.
- **`workers/openrouter_worker.py`**: uses the shared constant
  instead of the magic `5` literal. Doc-string for the
  returncode semantics updated.
- **`scripts/solve_issues.py`**: doc-string for
  `run_openrouter_direct_worker` returncode semantics updated.

**Scope discipline:** user explicitly forbade refactoring the
generic `nonzero_with_changes` semantics for other workers — it
may exist intentionally to let some workers proceed for further
review despite nonzero exit. Only Returncode 5 is now an explicit
hard-stop. Other returncodes (e.g. 3 for timeout) would need a
separate item if the same problem recurs.

**Verification:**

- `./.venv/bin/python -m unittest tests.test_worker_execution -v`: 22 OK (was 21, +1)
- `./.venv/bin/python -m unittest tests.test_worker_adapters -v`: 96 OK (was 95, +1)
- `./.venv/bin/python -m unittest tests.test_openrouter_worker -v`: 53 OK
- `./.venv/bin/python -m unittest tests.test_solve_issues -v`: 168 OK (no regression)
- `git diff --check develop..HEAD`: clean
- GitHub CI: Python 3.10 + 3.12 both pass
- User live review: "Mein OK: squash merge + delete branch"

**General principle (documented for future returncode classes):**

> Any nonzero worker-returncode that produces partial on-disk
> changes must be a hard stop. Commit + push + PR-create must not
> run.

§57 (returncode 6) and §60 (returncode 5) both implement this rule.
If a future returncode (e.g. 3 for timeout) shows the same
behavior, apply the same treatment: explicit hard-stop branch in
`classify_worker_outcome` + shared constant in `workers/base.py` +
doc-string updates.

**Out of scope (deferred / separate items):**

- Splitting `nonzero_with_changes` into specific classes
  (`reject_artifacts`, `partial_state`, etc.). Would be a larger
  refactor of the classification taxonomy. Worth doing eventually
  if the run-report starts carrying too many partial-state
  classes; not urgent.
- General `WorkerOutcome` invariant test
  ("`should_continue=True` implies `returncode == 0`"). Would
  prevent this entire class of bug by construction. A good
  follow-up; not urgent because the explicit per-class checks
  (§57, §60) already cover the known cases.

Original labels: `kind/bug`, `theme/solver`, `area/validation`,
`priority/1`

---


## Done — §61: Update README for current solver workflow

Closed 2026-06-26 via PR #447 (squash `9b85570` on develop). 1 file
(README.md), +30/-6 total across three commits on the PR branch
(initial AI-generated fix from liquid/lfm-2.5-1.2b-instruct:free,
then a manual extension by Mavis to add the dynamic-discovery and
recently-removed-patterns sections, then a small correction removing
an inaccurate claim about the reviewer's use of `model_catalog.py`).

**Problem:** the README had drifted behind the actual solver
workflow after several pipeline safeguards landed (PR #439 dynamic
OpenCode free-model discovery, PR #437 cost-cap update, §56 rework-
pr fix, §57 partial-patch-failure fix, §58 anti-pattern-doc fix,
§60 reject-artifact fix). The README's free-model references and
safety-behavior section were either missing or incorrect.

**Fix (three commits on the PR branch):**

1. Initial AI-generated fix (commit `57352f2`): adds a Hard-Stop
   paragraph to the README noting that partial-patch and reject-
   artifact runs do not create PRs. Updates the Backlog-Status
   block at the bottom of the README to reflect the current
   pipeline state.
2. Mavis extension (commit `83e414a`): adds two new README blocks
   covering the OpenCode-free-model dynamic discovery
   (`scripts/model_catalog.py`) and the recently-removed-patterns
   guard (`docs/AGENTS.md`) with the two current entries
   (PR #439 static `free_models`, PR #437 hard `$20/$20` cost-cap).
3. Correction (commit `3ad749a`): removes an overstated claim in
   the dynamic-discovery block that "the Reviewer-Prompt" uses the
   model_catalog mechanism. `scripts/review_pr.py` does not consult
   `model_catalog.py` (it loads reviewer prompt files and does
   role-routing only), so the claim was incorrect. Live review
   by Guido caught this on the second pass.

**Verification:**

- `./.venv/bin/python -m unittest tests.test_validation.test_rework tests.test_validation.test_github_client`: 39 OK
- `./.venv/bin/python -m unittest tests.test_reviewer_runtime`: 65 OK
- `./.venv/bin/python -m unittest tests.test_solve_issues`: 168 OK (no regression; full discover was skipped per the well-known slow-path caveat that also affected PR #440 / PR #442 / PR #445)
- `git diff --check develop..HEAD`: clean
- GitHub CI: Python 3.10 + 3.12 both pass
- User live review: "mergebereit" (after the §61 entry was extended
  and the review-claim was corrected)

**Out of scope (deferred / separate items):**

- Full Free-Models benchmark sweep (31 free models via OpenRouter +
  OpenCode, sequenced through Issue #446). The §61 PR is the
  README update only; the benchmark was run separately as a
  diagnostic exercise and lives in
  `reports/benchmarks/free-models-2026-06-26.json` /
  `.log`. Result: 1 / 31 actually completed (liquid/lfm-2.5-1.2b-instruct:free
  — the only solver that produced a PR before solve_issues.py's
  "Issue hat bereits offene PRs"-guard kicked in for the rest of
  the sweep). 5 OpenCode Free models fail with the opencode-cli/serve
  version conflict (MiniMax Code.app bundles OpenCode 1.14.28;
  `~/.opencode/bin/opencode` is 1.15.13). A corrected methodology
  (PR-close-before-each-run or `--retry`) is tracked as a future
  exercise; not a §61 deliverable.

Original labels: `kind/docs`, `theme/workflow`, `priority/2`

---


## Done — §62: Fix benchmark/open-PR workflow methodology

Closed 2026-06-26 via PR #448 (squash `0d08679` on develop). 6 files,
+204/-4 across three commits on the PR branch (Codex's main fix
`e145a54` + Mavis portability fix `da02e17` + the squash itself).

**Bug:** `scripts/solve_issues.py:3866` called
`client.get_open_pull_requests(repo)`, but that method did not
exist on `GitHubClient` (the real name was `get_pull_requests`).
Result: every run that hit the workflow-congestion check raised
`AttributeError: GitHubClient object has no attribute
'get_open_pull_requests'`. Even worse: in benchmark sweeps
(`scripts/benchmark_free_models.py`), the open-PR guard
correctly aborted subsequent runs after the first successful PR
opened. The 31-model Free-Models-Benchmark-Sweep on 2026-06-26
saw 24 of 31 runs aborted as `Issue #446 hat bereits offene
PRs; ueberspringe (--retry zum Erzwingen)` without ever
attempting the solve.

**Fix:**

- **`scripts/validation/github_client.py`**: added backwards-
  compatible alias `get_open_pull_requests(repo, head=None)`
  → `get_pull_requests(repo, state="open", head=None)`. New code
  should call `get_pull_requests` directly.
- **`scripts/solve_issues.py`**: added CLI flag `--benchmark`
  (requires `--skip-pr` together; if `--benchmark` is set without
  `--skip-pr`, the solver refuses to commit/push/PR-create with
  a clear error message). The open-PR guard now respects
  `--benchmark` (or `--skip-pr`) and only blocks when an
  *open foreign* PR exists for the issue.
- **`scripts/benchmark_free_models.py`**: every solver-call
  inside the sweep now passes `--benchmark --skip-pr` so the
  sweep can compare all N models on the same issue without
  being aborted by the first PR.
- **`scripts/benchmark_free_models.py`** (Mavis portability
  fix `da02e17`): `REPO` was hardcoded to
  `/Users/Guido/Documents/GitHub/ai-issue-solver`, which made
  the test `test_run_one_uses_benchmark_skip_pr_flags` pass
  locally but fail on CI (where that path does not exist). Fixed
  with `REPO = Path(__file__).resolve().parent.parent`, the same
  pattern as `SCRIPT_DIR` / `PROJECT_ROOT` in `solve_issues.py`.

**Verification:**

- `./.venv/bin/python -m unittest tests.test_benchmark_free_models`: 1 OK
- `./.venv/bin/python -m unittest tests.test_solve_issues`: 173 OK (+5 from §62's own tests)
- `./.venv/bin/python -m unittest tests.test_validation.test_github_client`: 25 OK (+1 from §62's `test_get_open_pull_requests_*`)
- `git diff --check develop..HEAD`: clean
- GitHub CI: Python 3.10 + 3.12 both pass (after the Mavis
  portability fix; the first CI run failed on the hardcoded path)
- User live review: "PR #448 nach grünem CI als merge-ready"
  (after the path-leak fix was confirmed)

**Scope discipline (per User directive):** this PR is **only**
the methodology fix. Free-Model-Qualitätsbewertung (§64) and
§59-Prompt-Hardening are explicitly NOT touched. The
`--benchmark` flag is the enabler for §64's planned re-run of
the benchmark sweep with valid data.

**Unblocked:** §64 (Free-Models-Robustheit-Studie, priority/4,
parked) can now be activated — the open-PR guard no longer
corrupts the sweep data.

Original labels: `kind/bug`, `theme/solver`, `area/methodology`,
`priority/2`

---

## Done — §66: Dynamic OpenRouter free-model discovery for benchmark sweeps

Closed 2026-06-26 via PR #449 (squash `e38c1f4` on develop). 5 files,
+338/-51, single Codex commit `cbf8bd6` on
`codex/openrouter-dynamic-discovery`.

**Background:** OpenCode free-model discovery was already dynamic
(PR #439, via `fetch_opencode_free_models()` in
`scripts/model_catalog.py`), but OpenRouter free-model benchmark
selection was still backed by a static list in
`scripts/benchmark_free_models.py`. The 2026-06-26 smoke benchmark
on Issue #390 surfaced the cost of that: `deepseek/deepseek-chat-v3.1:free`
returned `404 Not Found` (provider slug drift) and we had no
automated way to detect missing slugs before starting a sweep.

**Fix:**

- **`scripts/model_catalog.py`** (Codex `cbf8bd6`):
  - New `fetch_openrouter_free_models(*, use_cache, ttl_seconds,
    now_epoch, api_key) -> OpenrouterModelCache` (analog to
    `fetch_opencode_free_models()`). Reuses
    `verify_openrouter_slugs.fetch_openrouter_models` + the existing
    dual-import `try scripts.X / except ModuleNotFoundError: X`
    pattern from `load_default_catalog()`.
  - Free-filter is **pricing-based** via `_is_free_openrouter_model()`:
    `pricing.prompt == "0"` AND `pricing.completion == "0"`
    (using `_price_is_zero` helper). The `:free` suffix is **not**
    a fallback signal — only pricing-metadata counts.
  - Cache: 1h TTL, `XDG_CACHE_HOME`-aware, file
    `~/.cache/ai-issue-solver/openrouter_models.json`.
    `OpenrouterModelCache` dataclass mirrors `OpencodeModelCache`
    (`fetched_at`, `models`, `source`, `age_seconds()`).
  - Static fallback tuple `OPENROUTER_FALLBACK_FREE_MODELS` is the
    single source of truth (was previously duplicated as a list in
    `benchmark_free_models.py`).
  - On any API/network/import failure → return
    `OpenrouterModelCache(source="fallback", models=OPENROUTER_FALLBACK_FREE_MODELS)`.
- **`scripts/benchmark_free_models.py`**:
  - Removed old `OPENROUTER_FREE_MODELS` and `OPENCODE_FREE_MODELS`
    module-level lists (now in `model_catalog.py` as
    `OPENROUTER_FALLBACK_FREE_MODELS` and the existing
    `OPENCODE_FREE_MODELS` tuple).
  - New helpers `explicit_model_specs(raw_models)` and
    `default_model_specs() -> (models, source_label)`. Default path
    now calls `fetch_openrouter_free_models()` +
    `fetch_opencode_free_models()` and prepends
    `openrouter_direct:` / `opencode:` accordingly. Source label
    (`openrouter:live|cache|fallback/opencode:...`) is logged at
    sweep start and persisted into the aggregate JSON as
    `model_source`.
  - `--models` flag unchanged in behaviour: explicit lists still
    bypass dynamic discovery and are passed through verbatim.
- **`README.md`**: new block "OpenRouter Free Models (dynamisch für
  Benchmarks)" between the OpenCode-block and the App-State-Conflict
  block. Documents the pricing-based filter and that explicit
  `--models` is unaffected.
- **`tests/test_model_catalog.py`**: 3 new tests in
  `FetchOpenrouterFreeModelsTests`:
  - `test_live_catalog_filters_via_pricing_metadata` — mixed
    free/paid/fake-free model fixtures, asserts only true-free pass.
  - `test_fallback_when_openrouter_api_unavailable` — mocked
    `RuntimeError` from `fetch_openrouter_models` → `source="fallback"`.
  - `test_cache_used_when_fresh` — fresh cache file → no API call,
    `source="cache"`.
- **`tests/test_benchmark_free_models.py`**: 2 new tests:
  - `test_default_model_specs_uses_dynamic_discovery` — patches
    both catalog functions, asserts the dynamic source label and
    the composed `[(provider, model), ...]` list.
  - `test_explicit_models_bypass_dynamic_discovery` —
    `explicit_model_specs()` does not call `default_model_specs()`.

**Verification:**

- `./.venv/bin/python -m unittest tests.test_model_catalog.FetchOpenrouterFreeModelsTests
  tests.test_benchmark_free_models.BenchmarkFreeModelsTests`: 6 OK
- Live API call:
  `fetch_openrouter_free_models()` returns
  `source="live", count=26` (matches fallback list size after
  pricing filter; cache TTL=3600s, file
  `~/.cache/ai-issue-solver/openrouter_models.json`)
- `git diff --check origin/develop...origin/codex/openrouter-dynamic-discovery`: clean
- GitHub CI: Python 3.10 + 3.12 both pass
- User live review: "Ja kannst du mergen, habe ich reviewed"
  (after Mavis post-PR review verdict APPROVE).

**Scope discipline (per User directive):** the PR is **only** the
methodology fix. §59 (Mode-C watchlist), §63/§65 (OpenCode-App-State),
and the strategic production default (`gpt-4o` via paid OpenRouter)
are explicitly NOT touched.

**Unblocked:** future Free-Model-Benchmark-Sweeps no longer
silently waste runs on stale slugs; slugs missing from the live
catalog are excluded from the default list unless the user
explicitly passes `--models`.

Original labels: `kind/tooling`, `theme/openrouter`,
`area/model-catalog`, `priority/2`

---

## Done — §67: Fix `benchmark_free_models.classify()` so Worker-Failures stop looking like successes

Closed 2026-06-27 via PR #465 (squash `5fbc6f6` on develop). 2 files,
+440/-9, single Mavis-as-dev commit `f786818` on
`fix/s67-benchmark-classify`. Two prior solver attempts (Mistral-
Medium-3-5 + gpt-4o via `solve_issues.py --skip-slug-verification`)
both failed at patch-application (`patch: **** malformed patch`),
so this was Mavis-as-dev with explicit User approval per the
established "Mavis-as-dev ≠ system-under-test" carve-out for
non-benchmark-target issues.

**Background:** the Free-Models-Benchmark-Sweep on 2026-06-26 ran
4 Free-Models against Issue #450. All four workers actually failed
(rc=1 for 429 rate-limits, rc=2 for empty responses), but the
aggregate (`reports/benchmarks/benchmark-issue-450-4free.json`)
misreported `success_no_pr` for every run. The bug:

```python
def classify(model_arg, model_name, rc, log_text):
    if rc != 0:
        # ...specific failure classes...
    if "PR erstellt" in log_text or "pr_created" in log_text:
        return "success_pr_created"
    if "Keine Patches" in log_text:
        return "no_patches"
    return "success_no_pr"   # ← fall-through treats rc=0+no-PR as success
```

`solve_issues.py` returns rc=0 even when the worker truly failed
(no partial commits → `status="no_changes"`), so the fall-through
was hit on every run.

**Fix (`scripts/benchmark_free_models.py`):**

- **`_find_run_report(issue_number, started_at, finished_at)`** —
  walks `reports/runs/` for the most-recently-modified
  `*-<repo>-issue-<N>/` directory whose mtime falls inside
  `[started_at-5s, finished_at+30s]`. Returns `None` on miss.
- **`_read_run_report_summary(run_report)`** — single-line
  `key: value` parser for `summary.txt`. Inline implementation
  avoids the `scripts.solver_reporting` import, whose bare
  `from utils import ...` lines break in the test harness.
- **`classify(... run_report=None)`** — Run-Report-Primary with
  log-text fallback. New canonical classes (replacing the
  fall-through):

  | worker_exit_code | has_changes | status | class |
  |---|---|---|---|
  | 0 | True | `pr_created*` | `success_pr_created` |
  | 0 | True | `pr_skipped` | `success_pr_skipped` |
  | 0 | False | any | `no_changes` *(was `success_no_pr`)* |
  | 1 | any | any | `model_failure_rc1` |
  | 2 | any | any | `empty_response_rc2` |
  | 5 | any | any | `patch_validation_failed_rc5` |
  | 6 | any | any | `partial_patch_failure_rc6` |
  | any | any | + `429 Too Many Requests` | `openrouter_429` |

- The legacy log-text fallback now returns `no_changes` for the
  rc=0+no-PR case instead of `success_no_pr`, so a missing
  run-report cannot accidentally label a silent failure as
  success.

**Tests (`tests/test_benchmark_free_models.py`):**

- 12 new tests across two new classes:
  - `ClassifyFromRunReportTests` (10 tests) — one per new
    canonical class plus the fallback paths.
  - `FindRunReportTests` (2 tests) — in-window match + no-match.
- Existing 3 tests preserved; total 15 OK.

**Verification:**

- `./.venv/bin/python -m unittest tests.test_benchmark_free_models`: 15 OK
- `pytest tests/test_benchmark_free_models.py tests/test_benchmark_issues.py
  tests/test_analyze_repos.py`: 37 OK (cross-module regression check)
- GitHub CI: Python 3.10 + 3.12 both pass (squash-merge fast-forwarded)
- User live review: "OK zum Squash-Merge" (after AIS `code`-review
  verdict `ready to merge`, 0 blockers).
- AIS review strengths noted: window-based matching with
  configurable slack, clear precedence order with comprehensive
  docstring, proper 429 handling before worker exit code, elegant
  test context manager.

**Scope discipline (per User directive):** the PR is **only** the
classifier fix + tests. §66 (OpenRouter dynamic discovery), §59
(Mode-C watchlist), §63/§65 (OpenCode-App-State), and the
strategic production default (`gpt-4o` via paid OpenRouter) are
explicitly NOT touched.

**Unblocked:** Issue #450 can now be solved (Mavis-as-dev is
acceptable again per §67 spec). Re-running the 4 Free-Models
benchmark on Issue #450 as an acceptance test will produce 4
distinct failure classifications instead of 4× `success_no_pr`.

Original labels: `kind/bug`, `theme/solver`, `area/benchmark`,
`priority/1`

---

## Done — Issue #450: Update README directory structure for current repo layout

Closed 2026-06-27 via PR #466 (squash `d7ea03f` on develop). 1 file,
+54/-31, single Mavis-as-dev commit on `fix/450-readme-tree`.
Originally designed as a Free-Model benchmark target; §67 (Run-Report
classification) was fixed first so the post-fix sweep correctly
classified the 4 Free-Model failures (no more `success_no_pr`
fall-through).

**Background:** the README `Verzeichnisstruktur` block had drifted
from the actual repo layout. Stale path `docs/docs/BACKLOG/open.md`,
missing directories (`workers/`, `prompts/`, `benchmarks/`),
incomplete `scripts/` list, stale `docs/` references, and a
redundant `---` separator before `## Verzeichnisstruktur`.

**Fix (`README.md` only):**

- Removed `docs/docs/BACKLOG/open.md` → now correctly
  `docs/BACKLOG/open.md` (also grouped under a `BACKLOG/`
  subdirectory block with `open.md` and `done.md`).
- Added missing directories: `workers/` (Worker-Adapter block with
  opencode, openrouter, aider, codex, mistral_vibe, diagnostics,
  session reader, execution), `prompts/` (Codex-Skill-Prompts,
  `rework_pr.md`), `benchmarks/` (local benchmark artifacts).
- Expanded `scripts/` to include current model/benchmark/
  runtime-relevant files (`model_catalog.py`,
  `benchmark_free_models.py`, `opencode_state_diagnostic.py`,
  `verify_openrouter_slugs.py`, `solver_reporting.py`,
  `watchdog.py`, `validation_run.py`, `workflow_congestion.py`,
  `review_pr.py`, plus the rest of the live scripts).
- Expanded `docs/` to reference current core docs (`AGENTS.md`,
  `OPENCODE_APP_STATE.md`, `MODEL_OVERRIDE_POLICY.md`,
  `PLANNING_0.9.0.md`, `PRODUCT_VISION_1.0.md`, `ROADMAP.md`,
  `label_taxonomy.md`).
- Updated `tests/` block to reference representative current test
  modules (`test_benchmark_free_models.py`, `test_model_catalog.py`,
  `test_solve_issues*.py`, `test_opencode_state_diagnostic.py`,
  `test_reviewer_runtime.py`) instead of the stale subset.
- Added inline hints to `reports/` subpaths (`runs/`,
  `benchmarks/`, `preserved-worktrees/`).
- Removed the duplicate `---` separator.

**Acceptance criteria (all met):**

- README no longer contains `docs/docs/BACKLOG/open.md`.
- Tree includes all current major directories (`.github/`,
  `.agents/`, `config/`, `scripts/`, `workers/`, `prompts/`,
  `templates/`, `reports/`, `docs/`, `tests/`, `benchmarks/`).
- `scripts/` includes the current model/benchmark/runtime-relevant
  files at a representative level.
- `workers/` listed with adapter purpose.
- `docs/` references current core docs.
- Redundant separator removed.
- `git diff --check` passes.

**Pre-merge live-review caught two path bugs that the AIS
documentation review missed:**

1. `docs/PLANNING_0.10.0_DESIGN_BRIEF.md` was referenced but the
   file is untracked / not part of the repo. Per User directive
   "Den PLANNING_0.10.0_DESIGN_BRIEF.md nicht anfassen!" — line
   removed from README, file left alone.
2. `tests/test_review_pr.py` was referenced but the actual file
   is `tests/test_reviewer_runtime.py` — renamed in fix commit
   `378df27`.

**Scope discipline (per User directive):** README-only, no code,
benchmark, or backlog changes.

**Verification:**

- `./.venv/bin/python -c "..."` on aggregate JSON confirms §67
  fix classifies the 4 Free-Models correctly (no `success_no_pr`).
- `grep -c 'docs/docs/BACKLOG/open.md' README.md` returns 0.
- `git diff --check` passes.
- AIS documentation review: `request changes` (conservative —
  lacks filesystem access). User live review after the
  two path-fix commits: "Jetzt OK zum Squash-Merge."
- Squash-merge body cleaned up post-review (no mentions of the
  removed/renamed paths in the merge commit).

Original labels: `kind/feature`, `theme/documentation`,
`area/readme`, `priority/2`

---
