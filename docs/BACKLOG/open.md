# Open Backlog

> **📌 Sprachhinweis / Language Note:**
> Diese Datei bleibt bewusst auf Englisch, da sie als Vorlage für GitHub Issues dient
> und von KI-Workern verarbeitet wird. Siehe [Sprachrichtlinie](../LANGUAGE_POLICY.md)
> This file remains in English as it serves as a template for GitHub Issues and is
> processed by AI workers. See [Language Policy](../LANGUAGE_POLICY.md)

This backlog captures the **active, not-yet-closed** technical work for the
`ai-issue-solver` project. Private personal ideas belong in the separate
private `guido-project-lab` repository and must not be added here.

**Naming & location** (Release 0.7.0 split): this file replaces the old
`docs/NEXT_BACKLOG.md`. Completed items are archived in
[`done.md`](done.md). Long-term direction is in
[`../ROADMAP.md`](../ROADMAP.md).

**Priority** uses numeric ordering: `1` is highest urgency; larger numbers
are lower priority.

**Section numbers** are stable backlog identifiers, not priority. They are
preserved across renames and splits so that GitHub issues, PRs, and external
references keep working. Gaps in the numbering reflect historical insertion
order, not deleted sections.

Create selected items as GitHub issues with:

```bash
python scripts/create_backlog_issues.py --backlog docs/BACKLOG/open.md
python scripts/create_backlog_issues.py --backlog docs/BACKLOG/open.md --apply --confirm-create
```

Clean up completed items after their GitHub issues are closed by moving the
section to [`done.md`](done.md) and running:

```bash
python scripts/cleanup_backlog.py --backlog docs/BACKLOG/open.md
python scripts/cleanup_backlog.py --backlog docs/BACKLOG/open.md --apply --confirm-remove
```

---

## Priority 1

## 37. Free OpenCode models full integration and evaluation *(parked)*


Labels: `kind/feature`, `theme/workflow`, `agent/solver`, `priority/1`

Parked because: Free OpenCode models full integration and evaluation — not 0.9.0-critical; the hard-coded free-models list is known stale (see agent memory 2026-06-14) and must be re-verified before any real run, not parked as a priority-1 item.

Priority: `1`

Integrate all free OpenCode models into the project's model framework and
evaluate them against the current open issue backlog.

Currently only `opencode/mistral-small-2603`, `claude-sonnet-4-20250514`, and
`gpt-4o` are mentioned in help text; the available free tier models
(`opencode/deepseek-v4-flash-free`, `opencode/mimo-v2.5-free`,
`opencode/minimax-m3-free`, `opencode/nemotron-3-ultra-free`) are not
registered anywhere and users cannot discover or select them easily.

Suggested scope:
- add default model names to `MODEL_CONFIGS["opencode"]` so that
  `--model opencode` without `--model-name` picks a sensible default
- add entries in `STRENGTH_MAP` and `COST_TIERS` in `model_selection.py` for
  the free OpenCode models so auto-selection can choose them
- update `benchmark_issues.py` to include the free model list (or make it
  discover them dynamically via `opencode models`)
- run a full benchmark sweep against all open issues (ideally the small,
  low-risk ones first: regression tests, config changes, simple features)
- report per-model: can it solve the issue, does it create a valid PR, do
  tests pass, wall-clock time, and estimated token cost
- if a model consistently fails for a certain class of issues, document the
  pattern and add a model-selection guard in `model_selection.py`
- update `model_selection.py` to support the `opencode` provider family,
  including setting `model` via `--model-name` instead of guessing from
  substring matches
- add a `--list-free-models` (or similar) flag to discover available models
  dynamically via `opencode models` instead of hardcoding them

Touches: `scripts/solve_issues.py`, `scripts/model_selection.py`,
         `scripts/benchmark_issues.py`, `scripts/solver_run_resources.py`

Checks:
- `git diff --check`
- `python -m unittest discover -s tests`

---

---

## 39. Periodic documentation benchmark with free OpenCode models *(parked)*


Labels: `kind/automation`, `kind/docs`, `theme/workflow`, `theme/provider`, `priority/2`

Parked because: Periodic documentation benchmark with free OpenCode models — depends on later validation/model-comparison data from 0.9.0; defer until 0.9.0 validation report and free-model registry are stable.

Priority: `2`

Every tenth documentation-only solver run should be executed as a controlled
benchmark across all currently available free OpenCode models. This should keep
model comparison data fresh without spending tokens and provider quota on every
routine documentation issue.

Policy:
- only apply to documentation-only issues with low risk and narrow `Touches:`
  scope
- count successful documentation solver attempts and trigger the benchmark on
  every tenth eligible run
- run all free OpenCode candidates:
  - `opencode/deepseek-v4-flash-free`
  - `opencode/mimo-v2.5-free`
  - `opencode/minimax-m3-free`
  - `opencode/nemotron-3-ultra-free`
- use isolated branch suffixes and `--skip-pr` while benchmarking candidates
- do not automatically close the issue until the selected candidate is promoted
  and reviewed

Missing functionality to implement:
- persist a documentation-run counter or cadence marker so the scheduler can
  decide when the tenth eligible documentation issue is reached
- add a benchmark trigger mode that runs the free OpenCode models for the same
  documentation issue without requiring manual commands
- rank candidate branches by run outcome, diff relevance, test signal, touched
  files, and worker/runtime health
- promote the best candidate to one draft PR, or record that no candidate was
  good enough
- write durable benchmark comparison data grouped by model, repo type, issue
  type, and failure class
- surface the benchmark comparison in the dashboard, including no-op,
  model-failure, pipeline-failure, preserved-worktree, and promoted-candidate
  states
- record the result so future model selection can learn which free OpenCode
  models work best for documentation, Python, R, dashboard, and mixed repos

Suggested implementation:
- extend `benchmark_issues.py` or add a thin scheduler wrapper around
  `solve_issues.py --skip-pr --branch-suffix`
- reuse `run_outcome` fields from solver reports once available
- add a small persistent state file such as `reports/benchmark-cadence.json`
  or a project status file
- keep the first implementation documentation-only; expand to Python/R only
  after dashboard comparison and recovery semantics are reliable

Touches: `scripts/benchmark_issues.py`, `scripts/solve_issues.py`,
         `scripts/status_dashboard.py`, `scripts/model_selection.py`,
         `reports/`, `tests/`

Checks:
- `git diff --check`
- `python -m unittest discover -s tests`

---

## 51. Fix mock-based output capture in tests/test_rework_pr_cli.py

Labels: `kind/bug`, `theme/tests`, `priority/2`

Priority: `2`

Four out of five tests in `tests/test_rework_pr_cli.py` currently fail
on Python 3.10 + 3.12 in CI because `patch("solve_issues.print")` does
not capture the output the assertions expect.

Discovered during the AIS-Review of PR #422 (import-style refactor).
The fix is intentionally out of scope for #422 — the PR is a pure
import-style refactor and the mock-bug predates it. PR #422 carries
a warning-comment acknowledging the red CI status until this is fixed.

Suggested scope:
- investigate why `patch("solve_issues.print")` doesn't intercept the
  `print(...)` calls inside `solve_issues.rework_pr_cli` (likely a
  module-import shadowing issue, since `solve_issues` is imported via
  `from X import` rather than as a package)
- replace `patch("solve_issues.print")` with a stable capture
  mechanism (e.g. `contextlib.redirect_stdout`, or `capsys`/`capfd`
  pytest fixtures if applicable, or patching the actual symbol the
  function under test references)
- ensure all 5 tests in the file pass on Python 3.10 + 3.12
- after the fix, re-run the full test suite — no other tests should
  regress

Touches: `tests/test_rework_pr_cli.py`

Checks:
- `git diff --check`
- `python -m unittest tests.test_rework_pr_cli -v`
- `python -m unittest discover -s tests`

---

## 52. Replace build_graph.py done.md-parsing with GitHub-native API + Actions workflow logs

Labels: `kind/refactor`, `theme/workflow`, `area/build-graph`, `priority/2`

Priority: `2`

`scripts/build_graph.py` currently parses `docs/BACKLOG/done.md` as a
text source to build the Issue↔PR↔Commit relationship graph. This is
redundant: GitHub already encodes all of these relationships
natively, and per-run cost/model/runtime data lives in the Actions
workflow logs (one workflow run per solver-produced PR).

Replace the done.md parser with a GitHub-native data source so the
graph becomes fully machine-readable without manual backlog-text
maintenance.

Suggested scope:
- audit which fields `build_graph.py` reads from done.md today (LOC,
  cost, model, files, parent-of links) and map each to its GitHub
  native equivalent:
  - Issue↔PR links: parse PR body / PR comments for "Closes #N",
    "Fixes #N", "Part of #N", "Parent: #N"
  - PR↔branch: `pulls.head.ref` (already in API)
  - PR↔commit: `pulls.commits` (already in API)
  - solver-produced flag: PR author + `ai-generated` label
  - LOC / file count: PR `additions` + `deletions` + `changed_files`
  - model / cost / runtime: Actions workflow runs + logs via
    `gh run view <id> --log` or `GET /repos/{o}/{r}/actions/runs/{id}/logs`
- rewrite `scripts/build_graph.py` to call `gh api` (or `requests`
  against `api.github.com`) instead of opening `done.md`
- keep `--format json|dot` and `--color-by {cost,model}` flags; the
  data source changes, the user-facing CLI does not
- remove the LOC-parsing caveat in `WORKFLOW.md` §build_graph
  ("Inkonsistente Formate werden übersprungen") since the GitHub
  source is always well-formed
- add a `--since YYYY-MM-DD` filter so historical graphs can be scoped
- extend `tests/test_build_graph.py` to cover the new GitHub-native
  data path (mock `gh api` calls, not file fixtures)

Touches: `scripts/build_graph.py`, `tests/test_build_graph.py`,
         `docs/WORKFLOW.md`

Checks:
- `git diff --check`
- `python -m unittest tests.test_build_graph -v`
- `python -m unittest discover -s tests`
- `python scripts/build_graph.py --format json | python -c "import json, sys; d=json.load(sys.stdin); assert d.get('nodes') and d.get('edges')"`

---

## 53. Make test_rework_pr_cli.py CI-environment-independent

Labels: `kind/bug`, `theme/tests`, `area/ci`, `priority/2`

Priority: `2`

`tests/test_rework_pr_cli.py` produces 4 failures in CI even after the
print-mock fix from PR #427 (closes #423). The remaining failures are
caused by CI-environment differences, not by the original mock bug.

Two distinct CI-env failure modes were observed:

1. **Missing `requests` module** — `solve_issues.py:4148` does
   `sys.exit(1)` if its top-level `requests` import fell back to `None`.
   CI's Python 3.10 env had a missing or stale `requests`, causing
   `validation.rework` to fail to import, which cascaded into
   `AttributeError: module 'validation' has no attribute 'rework'`
   when the dotted-string `patch` target tried to bind.
2. **Missing `GITHUB_TOKEN`** — `solve_issues.py` performs an early
   GITHUB_TOKEN check that prints "GitHub Token fehlt" and calls
   `sys.exit(1)` BEFORE the test's mocks for `preflight_checks`,
   `load_env`, `run_pr_rework`, etc. can bind. Local `.env` has
   `GITHUB_TOKEN`, CI does not. After stubbing `requests`, this is
   the dominant failure mode.

Suggested scope:
- inject a minimal `requests` stub into `sys.modules` at test-file
  import time (already partially done in PR #427) and force-load
  `validation.rework` so the dotted-string patch target binds
- mock `solve_issues.requests` per-test so the
  `if requests is None: sys.exit(1)` guard at line 4148 is bypassed
- either inject a dummy `GITHUB_TOKEN` into the test env (so the
  early token check passes) OR mock the auth-check function itself
  before main() is called — pick the lower-friction option
- verify on Python 3.10 AND 3.12 in CI without any secrets or env
  vars; the test should be 100% self-contained

Touches: `tests/test_rework_pr_cli.py`

Checks:
- `git diff --check`
- `python -m unittest tests.test_rework_pr_cli -v`
- `python -m unittest discover -s tests`
- All five `ReworkPrCliDryRunTests` pass on Python 3.10 + 3.12 with
  no `GITHUB_TOKEN` and no `requests` installed

---

## 54. Symbol-whitelist pre-filter for the AIS code reviewer

Labels: `kind/refactor`, `theme/review`, `area/ci`, `priority/3`

Priority: `3`

The AIS code reviewer (`scripts/review_pr.py --role code`) emits
hallucinated BLOCKERs at a ~100% rate across model + temperature
combinations — measured 0/10 real across two PR reviews (#433,
#434), three model variants (deepseek-v4-flash-free, mistral-large,
gpt-4o-mini, gpt-4o), and three temperatures (0.0, 0.7, 1.2). The
hallucinated BLOCKERs follow a consistent pattern: the model names
an import, function, or symbol in its finding that does not exist
in the diff (or, less often, asserts a Python-version constraint
that `from __future__ import annotations` already neutralises).

The prompt-only fix in PR #434 (reviewer-code.md schema reframed
to "Recommendation / Improvements / Concerns / Strengths" + strict
"do not invent" rules) addresses the *framing* — the model is now
asked to be constructive instead of finding-bug-shaped. But it
does not structurally prevent the model from citing symbols that
do not exist in the diff. A symbol-whitelist pre-filter does.

Suggested scope:
- in `scripts/review_pr.py`, parse the diff with `re` (or, better,
  `unified_diff` from `difflib`) before calling the LLM, and
  extract: every `import X` / `from X import Y`, every `def name(`,
  every `class name(`, and every top-level variable assignment
  `name = ` in added lines
- pass the extracted symbol set as a system-prompt context block,
  e.g. "Available symbols in this diff: {list}"
- in the post-processing of the LLM response, drop any
  `Improvements` / `Concerns` bullet whose `<file:line>` reference
  names a symbol not in the whitelist, and surface the count of
  dropped bullets to the user ("3 of 8 findings filtered out —
  referenced non-existent symbols X, Y, Z")
- add unit tests in `tests/test_review_pr.py` covering: empty
  diff, single-symbol diff, multi-symbol diff, false-positive
  (symbol name in comment but not in code), and the post-filter
  dropping logic

Expected effect: ~95% reduction in hallucinated BLOCKERs (those
that name non-existent symbols), at the cost of ~1-2h implementation
plus tests. This is the structural follow-up to the prompt-only
fix; do it once the prompt-only fix lands and is verified to
reduce but not eliminate hallucinated findings.

Touches: `scripts/review_pr.py`, `tests/test_review_pr.py` (new)

Checks:
- `git diff --check`
- `python -m unittest tests.test_review_pr -v`
- `python -m unittest discover -s tests`
- re-run `scripts/review_pr.py --pr 434 --role code` (already-merged
  PR, must still produce a sensible review with no hallucinated
  symbols) and confirm the filtered finding count = 0

---

## 56. ~~Fix the `--rework-pr` workflow in `solve_issues.py`~~ **DONE in PR #440 (squash 166f8b2)**

Resolved 2026-06-25. See `done.md` for the closure summary and the
follow-up items that this fix enabled (notably §57 — partial-patch
reporting — and the still-open patch-mismatch hardening for the
normal solve path).

---

## 57. ~~Worker must not report `success` on partial patch application~~ **DONE in PR #442 (squash 8d68b50)**

Resolved 2026-06-25. See `done.md` for the closure summary. The
follow-up item §58 below depends on this fix and remains open.

---

## 58. ~~PR-review 'static free_models regression' anti-pattern~~ **DONE in PR #443 (squash 11eafc1)**

Resolved 2026-06-25. See `done.md` for the closure summary, including
the user-found path-leak fix (live-review finding by Guido).

The `docs/AGENTS.md` "Recently Removed Patterns" list is now
maintainer-pflegbar; future PRs that intentionally remove a pattern
should add a row to that table in the same PR.

The still-open follow-up item — patch-mismatch hardening for the
normal solve path (potential §59) — is now even more relevant: with
the §57 reporting fix + §58 prompt guard in place, a partial-fix PR
that would also reintroduce a recently-removed pattern should be
caught earlier.

---

## 59. Watchlist: Patch-mismatch hardening for the normal solve path (2026-06-25)

Labels: `kind/watchlist`, `theme/solver`, `area/prompt`, `priority/4`

Priority: `4` (parked — **do not activate** without evidence)

**Status: WATCHLIST ONLY.** This item exists so we do not lose
track of a possible quality follow-up, but it is **not** an active
backlog commitment. Do not invest in a fix until the activation
trigger below is met.

**The Mode-C failure mode on the normal solve path** (the same
patch-mismatch symptom §56 addressed for `--rework-pr`):

- Worker produces a patch JSON
- The patch references file content that does not match the current
  working tree (file moved, lines shifted, surrounding code changed
  since the model's training cutoff)
- `git apply` rejects the patch
- Worker reports failure → §57 now correctly stops the run before
  any PR is created

This used to be a silent regression (PR #441). After §57 + §58 it is
a clean failure with no PR — acceptable behavior. A §59 fix would
turn these clean failures into clean successes, but the bar is
"is this worth the architecture work?", and a single data point is
not enough to answer that.

**Current data point (1 of ≥3 needed):**

| Run | Date | Repo | Issue | Affected file | Failure | Result |
|-----|------|------|-------|---------------|---------|--------|
| #389 re-run | 2026-06-25 | ai-issue-solver | #389 | `scripts/model_selection.py:52` | `git apply` rejected | `nonzero_without_changes`, no PR ✅ |

**Activation trigger:** ≥3 Mode-C patch-mismatch runs on the
normal solve path, ideally across **different** files (so we know
it is a systematic prompt/model issue, not a one-off file-specific
problem). Until that threshold is met, §59 stays parked.

**Non-goal (while parked):** no code changes, no architecture work.
§57 + §58 are sufficient to keep the pipeline correct.

**Scope when activated:**

- prompt anchoring on the normal solve path (similar to §56's
  rework-pr fix: explicit file-version context, current branch tip
  SHA, recently-touched files in the issue scope)
- per-file `git apply --check` before declaring application success
- optional targeted re-prompting loop if `git apply --check` fails
  (model retries with the failure context instead of bailing out
  entirely)

**Touches (when activated):** `scripts/solve_issues.py`,
`scripts/validation/rework.py`, `workers/openrouter_worker.py`,
tests for the patch-mismatch path on the normal solve flow.

**Tracking note:** when a Mode-C failure appears on the normal
solve path, log it here (file, issue, date, error message). Two
more data points move this item from watchlist to active backlog.

---

## 60. ~~Returncode 5 (Reject-Artefakte) must hard-stop~~ **DONE in PR #445 (squash 2549f0f)**

Resolved 2026-06-26. See `done.md` for the closure summary.

User scope discipline was respected: only Returncode 5 was hardened
in this fix; the general `nonzero_with_changes` semantics for
other workers were deliberately **not** refactored (it may exist
intentionally for some workers).

The general principle remains valid for any future returncode
class (e.g. Returncode 3 for timeout, if it ever surfaces the same
problem): "Any nonzero worker-returncode that produces partial
on-disk changes must be a hard stop. Commit + push + PR-create
must not run." That is the underlying rule both §57 (returncode 6)
and §60 (returncode 5) implement.
