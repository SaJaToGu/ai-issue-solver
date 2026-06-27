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

## 61. ~~Update README for current solver workflow~~ **DONE in PR #447 (squash 9b85570)**

Resolved 2026-06-26. See `done.md` for the closure summary.

The §61 task covered three README areas that were missing or
outdated before the fix: dynamic OpenCode free-model discovery
(`scripts/model_catalog.py`), the recently-removed-patterns guard
(`docs/AGENTS.md`), and the new safety behavior for partial / reject
patch failures (§57 / §60). The final PR also includes a small
correction to an overstated claim about the reviewer's use of the
model_catalog mechanism.

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


---

## 62. ~~Fix benchmark/open-PR workflow methodology~~ **DONE in PR #448 (squash 0d08679)**

Resolved 2026-06-26. See `done.md` for the closure summary.

Three commits on the PR branch (squashed):
- `e145a54` — Codex's main fix: `get_open_pull_requests` alias +
  `--benchmark` CLI flag + benchmark-mode handling in
  `scripts/benchmark_free_models.py` + tests.
- `da02e17` — Mavis portability fix: derive `REPO` from `__file__`
  instead of hardcoded `/Users/Guido/...` (CI was failing with
  `FileNotFoundError` for the missing local path).
- merge → `0d08679` on develop.

Scope discipline: §62 was kept strictly to the methodology fix.
No Free-Model-Qualitätsbewertung (§64) and no §59-Prompt-Hardening
was mixed into this PR.

Next: §64 (Free-Models-Robustheit-Studie, priority/4) is now
unblocked for proper data collection.

---

## 63. OpenCode app-state conflict resolution (2026-06-26) — parked, diagnostic scope moved to §65

Labels: `kind/bug`, `theme/opencode`, `area/runtime`, `priority/3`

Priority: `3` — **parked** (the diagnostic + docs subset is split off as
§65, see below; the real resolution remains unstarted).

Observed on Mavis's macOS environment (2026-06-26):

- `~/.opencode/bin/opencode` (CLI): version `1.15.13`
- `/Applications/MiniMax Code.app/Contents/Resources/resources/opencode/opencode` (app-bundled): version `1.14.28`
- Killing the opencode-serve process triggers an app-launchd respawn that re-launches the OLD version, so the conflict is permanent until either the app bundle or the launchd config changes

**Impact:** the 5 OpenCode Free-Models (`opencode/big-pickle`, `opencode/deepseek-v4-flash-free`, `opencode/mimo-v2.5-free`, `opencode/nemotron-3-ultra-free`, `opencode/north-mini-code-free`) are untestable on this machine. The OpenCode Free-Model production-readiness question cannot be answered empirically until the conflict is resolved.

The current workaround (`--allow-opencode-state-conflict`) is a **diagnostic** tool, not a production-ready path.

Scope split (per User directive 2026-06-26 — keep §63 narrow, no app updates):

- **§65 (active, narrow, repo-side)** — diagnostic script + docs.
  Makes the App-State-Conflict reproducible and explainable on
  every developer machine. Scope: `scripts/opencode_state_diagnostic.py`
  + `docs/OPENCODE_APP_STATE.md` + README cross-reference.
- **§63 (parked, wide)** — actual resolution. Needs app-side
  changes (option A: update MiniMax Code.app bundle) OR
  project-side option C (always use configured `OPENCODE_BIN`).
  Out of scope for the 0.9.0 release; revisit only if OpenCode
  Free-Models become a strategic priority.

Touches: `docs/OPENCODE_APP_STATE.md` (new, in §65),
`scripts/opencode_state_diagnostic.py` (new, in §65).

Checks:
- §65's diagnostic script prints the conflict clearly
- §63's full-resolution remains parked until §65 confirms the
  conflict is real on multiple developer machines

---

## 64. ~~Free-model robustness study~~ **CLOSED with smoke-benchmark evidence (2026-06-26)**

Status: **closed without full activation**. The smoke-benchmark
(`scripts/benchmark_free_models.py --issue 390 --models
openrouter_direct:deepseek/deepseek-chat-v3.1:free,openrouter_direct:qwen/qwen3-coder:free,openrouter_direct:openai/gpt-oss-20b:free,openrouter_direct:meta-llama/llama-3.3-70b-instruct:free`)
provided enough signal to close this item without burning the
planned 5×5 sweep budget.

**Results (4/4 attempted, 0/4 PR-relevant):**

| Model | rc | Real cause |
|-------|----|-----------|
| `deepseek/deepseek-chat-v3.1:free` | 0 | 404 Not Found — slug drift (provider may have renamed) |
| `qwen/qwen3-coder:free` | 0 | 429 Too Many Requests — provider rate limit |
| `openai/gpt-oss-20b:free` | 0 | Worker exit_code=2 — empty / whitespace response |
| `meta-llama/llama-3.3-70b-instruct:free` | 0 | 429 Too Many Requests — provider rate limit |

**Conclusion:** for issue-classes comparable to #390 (Periodic
doc benchmark, low-risk), free OpenRouter models produce
**zero PR-relevant results**. The failure surface is **not** a
single bug — it is a stability profile (provider rate limits +
slug drift + empty responses). Each additional run would just
re-confirm the same profile, not extend the picture.

**§62 methodology fix is validated by this benchmark:** all 4
runs were actually attempted (the previous sweep had 24/31
aborted by the open-PR guard). Data-quality is now clean even
if the underlying signal is "free stays wobbly".

**Recommendation table produced from smoke (not a full study, but enough to act):**

- `qwen/qwen3-coder:free`, `meta-llama/llama-3.3-70b-instruct:free`
  → 429-Rate-Limit-Hit on first call within a sweep window. Not
  useful without provider-side rate-limit coordination.
- `openai/gpt-oss-20b:free` → empty response on this issue-class.
  May work for smaller scopes; needs re-test on a text-only
  issue before any production use.
- `deepseek/deepseek-chat-v3.1:free` → 404 (slug drift). Re-test
  with the current OpenRouter slug list before any production use.

**0.9.0 decision (per User, 2026-06-26):** paid OpenRouter / `gpt-4o`
is the strategic default. Free-Models stay **experimental /
supervised / docs-only candidates**. The full 5×5 sweep is
explicitly **not** planned unless a new use case emerges that
justifies burning the budget.

The smoke-run JSON lives at
`reports/benchmarks/smoke-free-models-2026-06-26.json` /
`.log` for future reference.

---

## 65. OpenCode app-state diagnostic script (2026-06-26)

Labels: `kind/tooling`, `theme/opencode`, `area/runtime`, `priority/3`

Priority: `3` — **scope: repo-side only, no app updates**.

A narrow companion to §63. The full §63 spec is parked (App-
update, bundle-rewrite, project-side configure-always-use-
OPENCODE_BIN option), but a small diagnostic + documentation
tool is valuable immediately because the App-State-Conflict
itself is **reproducible and explainable** on every developer
machine that has both `~/.opencode/bin/opencode` and a bundled
app. The diagnostic makes the state visible; the docs explain
why the conflict happens and what the three resolution options
are.

Scope:

- `scripts/opencode_state_diagnostic.py` — Python script (no
  external deps beyond the standard library) that prints:
  - which opencode binaries are on `PATH` (with versions)
  - which `opencode-serve` process is running and which binary
    it uses (with version)
  - which `.app` bundle owns the launchd respawn (by scanning
    `/Applications/` and matching the running binary path)
  - the configured `OPENCODE_BIN` env-var if set
- `docs/OPENCODE_APP_STATE.md` — documentation covering:
  - what the conflict looks like (CLI 1.15.13 vs Serve 1.14.28)
  - why it happens (app-launchd respawn with the app-bundled binary)
  - three resolution options (A: app update, B: rename the app-
    bundled binary, C: project-side always-use-configured-`OPENCODE_BIN`)
  - when to use `--allow-opencode-state-conflict` (diagnostic only,
    never as a production-ready path)
- README "Free-Models" section gets a short paragraph cross-
  referencing `docs/OPENCODE_APP_STATE.md`

**Out of scope (deliberately):** the full §63 implementation
(app update, bundle rewrite, project-side option C). Those
remain parked and would need their own Handover to Codex.

Touches: `scripts/opencode_state_diagnostic.py` (new),
`docs/OPENCODE_APP_STATE.md` (new), README small cross-reference.

Checks:
- `python scripts/opencode_state_diagnostic.py` produces a clear
  status report (path + version + launchd owner + env-var)
- `git diff --check`
- README cross-reference is in place

---

## 66. ~~Dynamic OpenRouter free-model discovery for benchmark sweeps~~ **DONE in PR #449 (squash e38c1f4)**

Labels: `kind/tooling`, `theme/openrouter`, `area/model-catalog`, `priority/2`

Priority: `2` — active methodology fix, not a production-default change.

OpenCode free-model discovery is now dynamic via
`scripts/model_catalog.py`, but OpenRouter free-model benchmark
selection is still backed by a static list in
`scripts/benchmark_free_models.py`. The 2026-06-26 smoke benchmark
proved why that is not enough: `deepseek/deepseek-chat-v3.1:free`
returned `404 Not Found`, which is classic provider slug drift.

Goal: make OpenRouter free-model benchmark inputs come from the live
OpenRouter catalog, with cache + fallback semantics similar to the
OpenCode path. Static lists may remain as fallback, but must not be
treated as source of truth for real benchmark sweeps.

Scope:

- Add OpenRouter free-model discovery to the shared model catalog layer
  or a small helper reused by `scripts/model_catalog.py` and
  `scripts/benchmark_free_models.py`.
- Reuse existing live OpenRouter catalog plumbing from
  `scripts/verify_openrouter_slugs.py` where practical instead of
  creating a second API client.
- Filter only live catalog entries that are actually free according to
  provider metadata; `:free` suffix alone is a useful hint but should
  not override the live catalog.
- Add cache + fallback behavior:
  - fresh live catalog → use live free-model list
  - API/network unavailable → use clearly-labelled fallback list
  - live catalog says a fallback slug is missing → do not benchmark it
    unless explicitly requested via `--models`
- Make `scripts/benchmark_free_models.py` default to the dynamic
  OpenRouter free-model list plus the existing OpenCode free-model
  list.
- Preserve explicit `--models` behavior exactly; user-specified models
  are allowed even if they are not in the live free-model list.

Acceptance criteria:

- `python scripts/benchmark_free_models.py --issue 390 --models ...`
  keeps working for explicit model lists.
- A default benchmark run no longer includes OpenRouter slugs that the
  live catalog reports as missing.
- Unit tests cover:
  - live OpenRouter catalog with free + paid + missing/stale examples
  - fallback behavior when the OpenRouter API is unavailable
  - benchmark default model selection uses dynamic OpenRouter discovery
  - explicit `--models` bypasses dynamic filtering
- README/Free-Models status is updated only if wording is needed to
  explain dynamic OpenRouter discovery.

Out of scope:

- Free-model quality evaluation / large 5×5 robustness study (§64 is
  closed with smoke evidence).
- §59 patch-mismatch hardening.
- Changing the strategic production default away from paid
  OpenRouter / `gpt-4o`.
- OpenCode App-State resolution (§63 / §65).

Stop criteria:

- If the OpenRouter catalog does not expose enough pricing/free-tier
  metadata to distinguish free models reliably, stop and document the
  limitation instead of guessing from names only.
- If the fix grows beyond roughly 250 LOC, split into a Handover for
  Codex before implementation.

---

## 67. ~~Fix `benchmark_free_models.classify()` so Worker-Failures stop looking like successes (2026-06-26)~~ **DONE in PR #465 (squash 5fbc6f6)**

Labels: `kind/bug`, `theme/solver`, `area/benchmark`, `priority/1`

Priority: `1` — pipeline-correctness blocker. **Do this BEFORE any
further Free-Model-Benchmark-Sweep.** Without this fix, every
benchmark run's aggregate output (`reports/benchmarks/*.json`)
systematically mislabels worker-failures as `success_no_pr`, which
poisons any subsequent decision-making on Free-Models.

Repro (2026-06-26, Issue #450 benchmark sweep with 4 Free-Models):

```
$ python scripts/benchmark_free_models.py --issue 450 \
    --models openrouter_direct:liquid/lfm-2.5-1.2b-instruct:free,\
              openrouter_direct:qwen/qwen3-coder:free,\
              openrouter_direct:google/gemma-4-26b-a4b-it:free,\
              openrouter_direct:cohere/north-mini-code:free

=== Run 1/4 END: rc=0, classification=success_no_pr ===
=== Run 2/4 END: rc=0, classification=success_no_pr ===
=== Run 3/4 END: rc=0, classification=success_no_pr ===
=== Run 4/4 END: rc=0, classification=success_no_pr ===
=== Free-Models-Benchmark END (4 runs, counts={'success_no_pr': 4}) ===
```

But every run-report (`reports/runs/20260626-222516/...-issue-450/summary.txt`)
shows the workers actually **failed**:

| Run | Model | worker_exit_code | Real failure |
|-----|-------|------------------|--------------|
| 1 | liquid/lfm-2.5-1.2b-instruct:free | 2 | 1387 chars Prosa, kein Unified-Diff-Patch |
| 2 | qwen/qwen3-coder:free | 1 | 429 Too Many Requests |
| 3 | google/gemma-4-26b-a4b-it:free | 1 | 429 Too Many Requests |
| 4 | cohere/north-mini-code:free | 2 | 0 Zeichen Antwort, 135s request |

All 4 runs have `has_changes=False` and `status=nonzero_without_changes`
in their summary.txt.

Root cause (`scripts/benchmark_free_models.py:100-117`):

```python
def classify(model_arg, model_name, rc, log_text):
    if rc != 0:
        # ... returns specific failure classes
    if "PR erstellt" in log_text or "pr_created" in log_text:
        return "success_pr_created"
    if "Keine Patches" in log_text:
        return "no_patches"
    return "success_no_pr"   # ← fall-through treats every rc=0+no-PR as success
```

`solve_issues.py` returns rc=0 even when the worker truly failed
(as long as no partial commits were made — `status="no_changes"`).
The fall-through classifies any such run as `success_no_pr`,
which is the inverse of what the name suggests.

Goal: make `classify()` consult the run-report's `summary.txt`
(`worker_exit_code` + `has_changes` + `status` fields) for ground
truth, and only fall back to log-text heuristics if the run-report
cannot be located.

Scope:

- Read the matching run-report per `subprocess.run` invocation
  via pid/issue-number + timestamp-window match (report dir format:
  `<YYYYMMDD-HHMMSS-mics>-<repo>-issue-<N>/summary.txt`).
- Add canonical classification classes:
  - `success_pr_skipped` — worker_exit_code=0, has_changes=True,
    `--skip-pr` was set (the "actual" success in benchmark mode)
  - `no_changes` — worker_exit_code=0, has_changes=False (worker
    ran cleanly but produced no patch)
  - `empty_response_rc2` — worker_exit_code=2 (output empty)
  - `model_failure_rc1` — worker_exit_code=1 (general worker error)
  - `patch_validation_failed_rc5` — worker_exit_code=5 (reject artifacts)
  - `partial_patch_failure_rc6` — worker_exit_code=6 (partial patch)
  - `openrouter_429` — 429 Too Many Requests (separate from openrouter_400)
- Keep existing log-text heuristics as fallback when no run-report
  is found (e.g. tests with mocked subprocess).
- Existing classes that remain semantically correct:
  `success_pr_created`, `infrastructure_opencode_state_conflict`,
  `patch_validation_failed_rc5`, `no_patches` (parseable fallback),
  `patch_mismatch_mode_c`, `openrouter_400`,
  `infrastructure_or_unknown_failure`.
- Update the aggregate JSON `runs[i].classification` field to use
  the new classes; the `--json` shape stays backward-compatible
  (no breaking field changes).
- Tests for: run-report with each new class, run-report missing
  (fallback path), 429 detection, log-text fallback preservation.
- Update README "Free-Models"-block + `docs/BACKLOG/done.md`
  closure entry on completion.

Acceptance criteria:

- Re-running the Issue #450 benchmark with the same 4 Free-Models
  produces 4 distinct failure classifications (no `success_no_pr`
  in the aggregate), matching the per-run `worker_exit_code` and
  `has_changes` from the run-reports.
- A run with worker_exit_code=0 + has_changes=True + `--skip-pr`
  is classified as `success_pr_skipped`.
- A run with worker_exit_code=0 + has_changes=False is classified
  as `no_changes`, **not** `success_no_pr`.
- A run with worker_exit_code=2 is classified as `empty_response_rc2`,
  **not** `success_no_pr`.
- A run with 429 in worker output is classified as `openrouter_429`.
- A run without a matching run-report (test mock) falls back to
  existing log-text heuristics.
- All existing benchmark-related tests pass.

Out of scope:

- §66 OpenRouter dynamic discovery (already done in PR #449).
- Changing the production default (still `gpt-4o`).
- §59 Mode-C Patch-Mismatch-Hardening.
- §63/§65 OpenCode-App-State.
- Issue #450 itself — to be addressed **after** this bugfix,
  via gpt-4o (Mavis-as-dev is acceptable once the bugfix lands).

Stop criteria:

- If the run-report timestamp-correlation logic cannot reliably
  find the right report (e.g. multiple runs in the same second),
  stop and add a `--run-report-dir` flag to `solve_issues.py`
  that prints the absolute path; do not guess.
- If the fix grows beyond roughly 250 LOC, split into a Handover
  for Codex before implementation (same rule as §66).

---
