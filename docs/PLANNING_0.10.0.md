# 0.10.0 Planning — AIS Tooling Interface (CLI + Contracts)

> Language note: This is technical release planning for AI workers and is kept
> in English. User-facing CLI text can still remain German per
> `docs/LANGUAGE_POLICY.md`.

## Goal

Make AIS usable as a stable tool interface for humans, CI, apps, and agents by
shipping a thin CLI with a stable JSON contract, secret-redaction, and a clean
library surface. This is the bridge between 0.9.0 validation and 1.0.0 workflow
app.

## Non-Goal

- MCP server, background run manager, cancel/resume, auto-issue-creation —
  these belong to **0.10.1**.
- Odysseus-specific integration — not in scope for either 0.10.0 or 0.10.1.
- TUI / Web UI for `needs_confirmation` lifecycle — out of scope until
  user-interaction model is defined.
- Multi-repo dashboard — out of scope.
- Aider worker — already deprecated in 0.9.0 (§47).

## Out of Scope (explicit deferral to 0.10.1)

The following are **explicitly excluded** from 0.10.0:

- MCP server (`ais_mcp/`) and any agent-facing tool surface
- Background run manager (PID-files, lifecycle > 4 states, polling)
- Cancel/resume semantics for running jobs
- Auto-issue-creation from natural-language problem text
- Mutating actions in `ais solve-problem` (only `--dry-run` and
  `--emit-issue-body` are permitted in 0.10.0)
- Lifecycle states `needs_confirmation` and `cancelled`
- Odysseus integration

Tracking issue: **TBD — "Release 0.10.1 — AIS MCP and Background Run Manager"**
(parent: not yet created, will be linked from the 0.10.0 parent issue).

## Package Layout

- **PyPI-Distribution:** `ai-issue-solver` (existing; PyPI-`ais` 0.0.0/2015 is
  unrelated and does not conflict because console-scripts are distribution-
  internal)
- **Console-Entry-Point:** `ais` (mapped to `ais_cli.main:main` in
  `pyproject.toml`)
- **Import-Packages:** `ais_core/` (library) and `ais_cli/` (CLI)

```toml
[project.scripts]
ais = "ais_cli.main:main"
```

## MUST-HAVE

1. `ais_core/` library (delivered as 4 narrow PRs: #1a/#1b/#1c/#1d, each
   < 500 LOC net)
2. AIS-CLI with 5 commands: `resolve-repo`, `solve-issue`, `status`,
   `plan-batches`, `solve-problem`
3. JSON-Contract v1.0 (success/error shape, canonical error codes,
   `schema_version`)
4. Secret-Redaction-Filter (mandatory in all JSON outputs, logs, reports)
5. Test suite: unit (ais_core) + CLI (smoke + dry-run) + secret-redaction +
   JSON-contract

## SHOULD-HAVE

6. Run-ID format documented and implemented (`<UTC>-<repo-short>-<hash>`)
7. `ais` as preferred entry-point in README + `pyproject.toml` console-script
8. Migration-Guide (`docs/MIGRATION_0.10.0.md`) for existing script users

## EXPLICITLY OUT OF SCOPE (0.10.1+)

- MCP-Server (`ais_mcp/`)
- Background-Runs with lifecycle > 4 states
- Cancel/Resume
- Auto-Issue-Creation without explicit `--issue N`
- Odysseus-specific integration
- TUI / Web UI for `needs_confirmation`
- Multi-Repo-Dashboard

## Child-Issues (7 narrow PRs — Issue #4 renamed from "Legacy-Wrapper" to "Docs")

> Note: Originally planned as 8 issues, but the **Legacy-Wrapper step was
> removed from 0.10.0** because wrapping existing scripts to call `ais
> solve-issue` risks a cycle when `ais` itself relies on script logic.
> Legacy-wrapper work moves to **0.11.0** (see Follow-up). The 8th slot is
> reused for the **Migration-Guide + README-Update** work.

### #1a — `ais_core` Skeleton + pure helpers (Foundation)

| Field | Value |
|---|---|
| **Goal** | `ais_core/` module directory + empty module stubs with docstrings + test fixtures |
| **Why separate** | Clean foundation WITHOUT behaviour change; minimal risk PR |
| **Dependencies** | none |
| **Acceptance** | `ais_core/{__init__.py, repo_resolve.py, issue_resolve.py, secret_filter.py, json_contract.py, run_state.py}` exist; all stubs have docstrings + type-hints; no logic from scripts is migrated |
| **Files** | `ais_core/*` (NEW stubs), `tests/test_ais_core/` (NEW), `pyproject.toml` (UPDATE for package-discovery) |
| **Tests** | smoke-only (imports must work) |
| **Risk** | LOW |
| **LOC-Budget** | < 200 net |
| **Model** | small coding (`gpt-4o-mini`) |
| **Parallel** | no (Wave 1) |

### #1b — Repo-Resolution extrahieren (ein Script nutzt es)

| Field | Value |
|---|---|
| **Goal** | `repo_resolve`-Logik aus `scripts/solve_issues.py` in `ais_core/repo_resolve.py` extrahieren, Tests dafür, Script ruft Library |
| **Why separate** | Beweist das Library-Pattern funktioniert BEVOR weitere Scripts refactored werden |
| **Dependencies** | #1a |
| **Acceptance** | `ais_core/repo_resolve.py` hat ≥90% Coverage; `solve_issues.py` importiert `repo_resolve`; smoke-Tests grün; Verhalten unverändert |
| **Files** | `ais_core/repo_resolve.py` (NEW with logic), `scripts/solve_issues.py` (REFACTOR ~50 LOC), `tests/test_ais_core/test_repo_resolve.py` (NEW) |
| **Tests** | unit tests + regression (verifies solve_issues.py behaviour unchanged) |
| **Risk** | MEDIUM |
| **LOC-Budget** | < 400 net |
| **Model** | strong coding (`gpt-4o` paid OpenRouter) |
| **Parallel** | no (Wave 1, after #1a) |

### #1c — JSON-Contract + Run-State pure helpers

| Field | Value |
|---|---|
| **Goal** | `ais_core/json_contract.py` und `ais_core/run_state.py` with pure functions |
| **Why separate** | JSON-Contract ist zentrale Stability-Anforderung; Run-State ist Voraussetzung für spätere Background-Runs |
| **Dependencies** | #1a |
| **Acceptance** | `json_contract.schema_version` ist canonical; `run_state.make_run_id()` produziert eindeutige IDs; Tests grün |
| **Files** | `ais_core/json_contract.py` (NEW), `ais_core/run_state.py` (NEW), `tests/test_ais_core/test_json_contract.py` (NEW), `tests/test_ais_core/test_run_state.py` (NEW) |
| **Tests** | schema-validation, run-id-uniqueness |
| **Risk** | LOW |
| **LOC-Budget** | < 300 net |
| **Model** | small coding (`gpt-4o-mini`) |
| **Parallel** | yes (Wave 1, parallel with #1b and #1d) |

### #1d — Secret-Redaction-Filter pure helper

| Field | Value |
|---|---|
| **Goal** | `ais_core/secret_filter.py` with pattern-based secret detection |
| **Why separate** | Security-kritisch; verdient eigene Review |
| **Dependencies** | #1a |
| **Acceptance** | Filter detects GitHub-PAT, OpenAI-Key, AWS-Key, generic high-entropy strings; no false-positives in production logs |
| **Files** | `ais_core/secret_filter.py` (NEW), `tests/test_ais_core/test_secret_filter.py` (NEW) |
| **Tests** | ≥20 secret-patterns, false-positive-tests, performance-tests |
| **Risk** | MEDIUM-HIGH |
| **LOC-Budget** | < 400 net |
| **Model** | strong coding + manual security review |
| **Parallel** | yes (Wave 1, parallel with #1b and #1c) |

### #2 — AIS-CLI Scaffold + resolve-repo / solve-issue / status

| Field | Value |
|---|---|
| **Goal** | `ais_cli/` module + 3 initial commands (resolve-repo, solve-issue, status) |
| **Why separate** | First user-facing surface |
| **Dependencies** | #1b, #1c |
| **Acceptance** | `ais resolve-repo`, `ais solve-issue`, `ais status` work with `--json`; tests green |
| **Files** | `ais_cli/__init__.py` (NEW), `ais_cli/main.py` (NEW), `ais_cli/commands/resolve_repo.py` (NEW), `ais_cli/commands/solve_issue.py` (NEW), `ais_cli/commands/status.py` (NEW), `pyproject.toml` (UPDATE for `[project.scripts] ais = "ais_cli.main:main"`), `tests/test_ais_cli/` (NEW) |
| **Tests** | CLI smoke + integration (real local repo + mocked GitHub) |
| **Risk** | LOW |
| **LOC-Budget** | < 500 net |
| **Model** | small coding (`gpt-4o-mini`) |
| **Parallel** | no (Wave 2) |

### #3 — AIS-CLI plan-batches + solve-problem (STRICT NO-WRITE)

| Field | Value |
|---|---|
| **Goal** | The 2 remaining commands; `solve-problem` strictly without GitHub-write |
| **Why separate** | Smaller second wave; less risk than initial commands |
| **Dependencies** | #2, #1d (Secret-Redaction available) |
| **Acceptance** | `ais plan-batches`, `ais solve-problem` work; `solve-problem --emit-issue-body` produces markdown locally without GitHub-call; tests verify "kein GitHub-Write" |
| **Files** | `ais_cli/commands/plan_batches.py` (NEW), `ais_cli/commands/solve_problem.py` (NEW), `tests/test_ais_cli/test_solve_problem_no_write.py` (NEW) |
| **Tests** | smoke + dry-run + explicit no-write-verification (kein Mock für GitHub-Create) |
| **Risk** | LOW |
| **LOC-Budget** | < 500 net |
| **Model** | small coding (`gpt-4o-mini`) |
| **Parallel** | no (Wave 3) |

### #4 — Migration-Guide + README-Update

| Field | Value |
|---|---|
| **Goal** | User-Docs for 0.10.0 + migration from script calls |
| **Why separate** | Doc-only; no code risk |
| **Dependencies** | #3 |
| **Acceptance** | `docs/MIGRATION_0.10.0.md` exists with all breaking-changes documented; README refers to `ais` as preferred entry-point; CHANGELOG.md 0.10.0-block written; ROADMAP.md updated |
| **Files** | `docs/MIGRATION_0.10.0.md` (NEW), `README.md` (UPDATE), `CHANGELOG.md` (UPDATE 0.10.0-block), `docs/ROADMAP.md` (UPDATE 0.10.0 done + 0.10.1 geplant) |
| **Tests** | none (docs) |
| **Risk** | LOW |
| **LOC-Budget** | < 500 net (docs + README) |
| **Model** | small coding / manual |
| **Parallel** | no (Wave 4, final) |

## Wave-Plan

| Wave | Issues | Purpose | Key Files | Parallel | Recommended Model |
|------|--------|---------|-----------|----------|-------------------|
| 1a   | #1a | Foundation Scaffolding | `ais_core/*` (NEW stubs) | no | small (`gpt-4o-mini`) |
| 1b   | #1b, #1c, #1d | Library-Extractor parallel | `ais_core/{repo_resolve,json_contract,run_state,secret_filter}.py` + `scripts/solve_issues.py` | yes | strong (`gpt-4o`) for #1b/#1d; small for #1c |
| 2    | #2 | CLI-Initial-Commands | `ais_cli/main.py` + `ais_cli/commands/{resolve_repo,solve_issue,status}.py` + `pyproject.toml` | no | small (`gpt-4o-mini`) |
| 3    | #3 | CLI-Commands round-out | `ais_cli/commands/{plan_batches,solve_problem}.py` | no | small (`gpt-4o-mini`) |
| 4    | #4 | Docs + Migration | `docs/`, `README.md`, `CHANGELOG.md`, `docs/ROADMAP.md` | no | small / manual |

**File-Conflict-Map:**
- Wave 1a: `ais_core/` (alle NEW stubs) — kein Konflikt
- Wave 1b: jeder Issue eigener File-Scope + #1b touched auch `scripts/solve_issues.py` (einziger Script → kein Cross-Conflict)
- Wave 2-4: jede Issue hat eigenen File-Scope

**Note on existing Scripts in 0.10.0:** `scripts/solve_issues.py` and other
existing entry points stay compatible and may consume `ais_core/`-helpers
directly, but they are NOT turned into wrappers that call `ais solve-issue`
in 0.10.0. Wrapping scripts with CLI-delegation risks a cycle when `ais`
itself relies on script logic. The wrapper/deprecation work moves to 0.11.0
(see Follow-up section).

## Modell-Empfehlungen

| Worker | Use-Cases |
|---|---|
| `gpt-4o-mini` (small) | #1a, #1c, #2, #3, #4, #5 — Boilerplate, CLI-Scaffolding, JSON-Schemas, Docs |
| `gpt-4o` paid OpenRouter (strong) | #1b (first Script-Refactor with side-effect init), #1d (Security-Critical Secret-Redaction) |
| Manual security review | #1d before merge |
| Strategic paid default for merge-intended issues | `gpt-4o` (per 0.9.0 close-out) |

## CLI Contract (5 commands, 0.10.0)

### Commands

```bash
# Repo-Resolution
ais resolve-repo <repo_hint> --json

# Single-Issue
ais solve-issue --owner X --repo Y --issue N [--dry-run] [--create-pr] --json

# Status
ais status --run-id <run_id> --json

# Plan-Batches (read-only)
ais plan-batches --owner X --repo Y [--label <l>] --json

# Problem-to-Issue (STRICT NO-WRITE in 0.10.0)
ais solve-problem --repo <hint> [--issue N] --problem-file problem.md \
                  [--dry-run] [--emit-issue-body] --json
#   0.10.0 strikt:
#     - Validiert Problemtext
#     - Löst Repo auf
#     - Optional --emit-issue-body: erzeugt Issue-Markdown-Local, schreibt NICHTS nach GitHub
#     - Optional mit vorhandenem --issue N: reicht durch, kein Auto-Create
#   0.10.1+: GitHub-Write mit expliziten Gates (create_issue, push, PR)
```

### JSON Output Shape (success)

```json
{
  "schema_version": "1.0",
  "ok": true,
  "command": "solve-issue",
  "data": { },
  "warnings": [],
  "elapsed_ms": 1234
}
```

### JSON Output Shape (error)

```json
{
  "schema_version": "1.0",
  "ok": false,
  "command": "solve-issue",
  "error": {
    "code": "issue_not_found",
    "message": "Issue #123 not found in SaJaToGu/ai-issue-solver",
    "hint": "Check issue number and repo visibility"
  },
  "elapsed_ms": 234
}
```

### Canonical Error Codes

`repo_hint_ambiguous`, `repo_not_found`, `path_not_git_repo`,
`issue_not_found`, `issue_not_ai_solvable`,
`worker_init_failed`, `worker_timeout`, `worker_rate_limited`,
`pr_creation_failed`, `merge_conflict`, `validation_failed`,
`internal_error`

## Run Lifecycle (4 states)

```
queued → running → (succeeded | failed)
                  ↘ (failed via worker_exit_code != 0)
```

`needs_confirmation` und `cancelled` kommen mit 0.10.1.

### Run-ID Format

```
<UTC-timestamp>-<repo-short>-<8-char-hash>
Beispiel: 20260627T192412Z-bulwipgame-7f3a2b1c
```

### Report Files

- `reports/runs/<run-id>/metadata.json` — **maschinenlesbar**, structured
  data (run_id, status, timestamps, worker_exit_code, model, cost, pr_url,
  report_summary fields)
- `reports/runs/<run-id>/summary.md` — **human-readable**, markdown
  summary of the run
- `reports/runs/<run-id>/worker.log` — Worker stdout/stderr (verbatim)

## Test Strategy

### Unit Tests

- `ais_core/repo_resolve.py`: ≥90% line coverage; Tests mit Mocked Git/Remote
- `ais_core/issue_resolve.py`: Tests mit Mocked GitHub API
- `ais_core/secret_filter.py`: ≥20 Secret-Patterns (GitHub-PAT, OpenAI-Key,
  AWS-Key, Generic-High-Entropy)
- `ais_core/json_contract.py`: Schema-Validation für alle Commands
- `ais_core/run_state.py`: Run-ID-Uniqueness, State-Persistence

### CLI Tests (smoke + integration)

- `tests/test_ais_cli/test_solve_issue.py`: mocked solve_issues.py-Subprocess
- `tests/test_ais_cli/test_resolve_repo.py`: real local repos + mocked remote
- `tests/test_ais_cli/test_status.py`: state-file roundtrip
- `tests/test_ais_cli/test_solve_problem_no_write.py`: verifies no GitHub-write

### Dry-Run Integration Tests

- `tests/integration/test_ais_dry_run.py`: end-to-end mit `--dry-run` auf
  real repo (small fixture); keine externen API-Calls

### Failure-Mode Tests

- Network-Failure (GitHub API 5xx)
- Worker-Exit-Codes (0, 1, 5, 6)
- Token-Expired
- Repo-Not-Found

### Packaging / Console-Entry-Point Tests

- `tests/test_ais_cli/test_entrypoint.py`: `ais --help` resolves to the
  local console-script entry (defined in `pyproject.toml
  [project.scripts] ais = "ais_cli.main:main"`); verifies the entry-point
  wiring works without any PyPI lookup
- Verifies that the local distribution install (e.g. `pip install -e .`)
  exposes `ais` as a runnable command

### Secret-Redaction Tests

- GitHub PAT in log output → redacted
- OpenAI key in error message → redacted
- Bash-History-Dump → redacted
- JSON-Output mit Secrets → redacted vor schema-wrap

## Follow-up: Release 0.10.1 — AIS MCP + Background Run Manager

Tracked in separate issue: **TBD — "Release 0.10.1 — AIS MCP and Background
Run Manager"**.

### Scope (sketch — to be detailed in 0.10.1 planning)

- MCP-Server (`ais_mcp/`) als Side-Car auf `ais_core`
- Background-Run-Manager (PID-files + Status-Polling)
- Cancel/Resume
- Auto-Issue-Creation aus Problem-Text (mit Rate-Limiting)
- Lifecycle-States `needs_confirmation` + `cancelled` mit User-Interaction-
  Modell
- Codex-Skill-Update für `ais`-Aufrufe

Depends on: 0.10.0 `ais_core/` + `ais_cli/`.

### Cross-Agent Handoff-Format (0.10.1 or 0.11.0)

**Motivation:** Codex and Mavis currently exchange context via User-relayed
chat text, which is slow and lossy. Long-term, the two agents should
collaborate via structured files tied to a `run_id` — no manual copy-paste
through the user.

**Planned shape (sketch — to be detailed in 0.10.1/0.11 planning):**

- Canonical report files in `reports/runs/<run-id>/`:
  - `metadata.json` — maschinenlesbar, structured data
  - `summary.md` — human-readable markdown
- Optional per-agent handoff files (created by whichever agent finished
  the leg of work):
  - `handoff-codex.md` — Codex leg notes for Mavis (e.g. "PR open, needs
    review", "worker flagged this as code-review-blocker")
  - `handoff-mavis.md` — Mavis leg notes for Codex (e.g. "review verdict:
    APPROVE", "backlog item to file")
- Later CLI convenience (0.11.0+):
  - `ais handoff --run-id <id> --to codex|mavis` writes the handoff file
    using the canonical schema

**Naming convention (preliminary):** `handoff-<agent>.md` so that future
agents (e.g. `handoff-odysseus.md`) can opt-in without schema changes.

**Why this is 0.10.1/0.11 and not 0.10.0:** Requires (a) `metadata.json` /
`summary.md` canonical format to be stable (it is introduced in 0.10.0),
and (b) the Background-Run-Manager to track which agent wrote which leg
(in scope for 0.10.1). Before both exist, hand-offs would still need
manual glue.

Depends on: 0.10.0 `metadata.json` + `summary.md` schema.

## Open Questions

1. **PyPI-Conflict-Dokumentation** — Kommentar in `pyproject.toml` über
   `ais` Console-Script vs. PyPI-`ais` 0.0.0/2015 nötig? Oder reicht
   implizit (Console-Scripts sind distribution-internal)?
2. **Test-Fixture-Repo** — kleines Public-Repo oder fixture auf Disk?
3. **Pre-0.10.0-Signaling-Issue** — separate Issue/Discussion im Repo zur
   MCP-Verschiebung anlegen?

## Definition of Done (0.10.0)

- All 8 child-issues closed
- `ais resolve-repo`, `ais solve-issue`, `ais status`, `ais plan-batches`,
  `ais solve-problem` working with `--json`
- All tests green (unit + CLI + integration + secret-redaction +
  json-contract)
- `docs/MIGRATION_0.10.0.md` exists
- README updated
- CHANGELOG.md 0.10.0-block written
- ROADMAP.md updated (0.10.0 done + 0.10.1 planned)
- v0.10.0 Git-Tag + GitHub-Release created after merge to main
- Follow-up issue for 0.10.1 filed and visible