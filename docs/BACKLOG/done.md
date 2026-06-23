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

