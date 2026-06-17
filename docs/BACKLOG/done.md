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
