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
