# Repository Profile Provider — GitHub-First Design

The solver used to assume every target repository was a Python project and
hard-coded `repo_type="python"` into the auto-model path. That assumption
broke for low-code, R, Node.js, Shiny, and documentation-only
repositories (see issue #188 and the rejected PR #211). This document
describes the provider-neutral replacement that ships with issue #213.

## Goals

1. Use GitHub's existing repository intelligence as the **primary**
   source for `repo_type`, `dominant_language`, framework and test
   hints, and project metadata.
2. Keep a **thin local fallback** for offline runs, non-GitHub forges,
   and already-checked-out repositories.
3. Expose a structured `RepoProfile` in every run report so downstream
   tooling (dashboards, benchmarks, model selection) can use the same
   source of truth.
4. Never read or expose secret files such as `.env`, provider auth
   files, or API keys.

## Architecture

```
solve_issues.py  ─┐
                  │   build_repo_profile()    (GitHub-first)
analyze_repos.py  ─┤   select_profile_provider()  ──>  GitHubRepoProfileProvider  ─┐
                  │                                                       │
scripts/cli      ─┘                                                       ▼
                                                              LocalRepoProfileProvider
                                                                  (fallback / offline)
```

### Provider contract (`scripts/repo_profile.py`)

```python
class RepoProfileProvider(ABC):
    provider_name: str

    @abstractmethod
    def get_profile(self, repo: str, branch: str | None = None) -> RepoProfile
```

The `RepoProfile` dataclass is provider-neutral and contains:

| Field | Source on GitHub | Source on local |
|-------|------------------|-----------------|
| `provider` | `"github"` | `"local"` |
| `repo` | repo metadata `full_name` | configured `repo_name` |
| `dominant_language` | `/repos/.../languages` (byte max) | `infer_marker_language(paths)` |
| `language_percentages` | `/repos/.../languages` | derived from the same map |
| `repo_kind` | language + topics + paths | language + paths |
| `framework_hints` | topics + marker files | marker files |
| `test_hints` | tree markers + workflows | tree markers |
| `recommended_worker` | policy table | policy table |
| `python_required` | language == `python` or marker | marker-based |
| `default_branch` | metadata | branch argument |
| `is_archived` / `is_private` | metadata | always `False` |
| `topics` | `/repos/.../topics` | — |
| `marker_files` | recursive tree, secret-filtered | `rglob`, secret-filtered |
| `extra.workflows` | `/repos/.../contents/.github/workflows` | — |
| `extra.remote_state` | `/pulls?state=open` + `/issues?state=open` | — |
| `source` | `"github_rest"` | `"local_marker_heuristics"` |

### GitHub-first selection (`select_profile_provider`)

Resolution order:

1. If `offline=True` or the requested `prefer` target is not implemented,
   return `LocalRepoProfileProvider`.
2. If a GitHub session can be built (`token`/`owner`/`session` is
   supplied or `GITHUB_TOKEN` / `GITHUB_OWNER` is set in the
   environment), return `GitHubRepoProfileProvider`.
3. Otherwise return `LocalRepoProfileProvider`.

The `build_repo_profile()` wrapper additionally swallows transient
`RuntimeError` / `ConnectionError` / `TimeoutError` from the GitHub
provider and falls back to the local provider, so a flaky GitHub
response never blocks a solver run.

### Secret safety

Both providers run their file lists through `is_secret_path()` (and
`filter_secret_paths()`) which recognises:

- `.env`, `.env.local`, `.env.production`, `.env.development`,
  `.env.test`
- `auth.json`, `credentials`, `credentials.json`,
  `secrets.json`, `secrets.yaml`, `secrets.yml`
- `config.json`, `config.yaml`, `config.yml`
- Anything inside `.github/secrets/`, `secrets/`, `private/`, `auth/`

Workflow run commands that target any of those files are stripped from
`test_hints` via `_run_command_targets_secrets()`. The
`write_run_report()` writer additionally calls
`_sanitize_repo_profile_for_report()` before persisting to disk, so a
profile that somehow contains a secret path can never end up in
`metadata.json` or `summary.txt`.

## Run-report integration

`scripts/solver_reporting.py::write_run_report()` now accepts a
`repo_profile: dict | None` keyword. The dict is written to
`metadata.json` under `repo_profile` and rendered into `summary.txt`
under the `repo_profile:`, `repo_profile_remote_state:`, and
`repo_profile_workflows:` sections.

`scripts/solve_issues.py::solve_issue()` calls
`build_repo_profile_for_run()` right after `clone_repo()` succeeds and
threads the result through every `write_run_report()` call site,
including the early `skip` paths (existing PR, closed issue) and the
auto-model path that used to hard-code `python`.

## Acceptance criteria mapping

| Criterion | Implementation |
|-----------|----------------|
| `#188` solvable without Python assumption | `infer_repo_kind()` returns `r`, `node`, `r-shiny`, `docs-only`, `unknown`, etc. |
| GitHub language data used where available | `GitHubRepoProfileProvider` calls `/repos/.../languages` first |
| Local detection is fallback, not primary | `select_profile_provider()` prefers GitHub; the local provider only runs when explicitly chosen or when GitHub fails |
| Tests cover GitHub API fixtures and local fallback | `tests/test_repo_profile.py` (22 cases) and `tests/test_solver_reporting.py` (18 cases) |
| No secret files are read or exposed | `is_secret_path()` / `filter_secret_paths()` / `_sanitize_repo_profile_for_report()` |

## Out of scope

- GitLab / Forgejo / Bitbucket implementations are not built — the
  contract and `PROVIDER_TARGETS` registry leave room for them, but
  they remain a follow-up issue (similar to the GitLab backlog entry
  that already lives in `NEXT_BACKLOG.md`).
- `LocalRepoProfileProvider` does not try to be a Linguist clone; it
  only inspects marker files and language hints. Anything more
  elaborate would be a separate provider, not a fallback.
