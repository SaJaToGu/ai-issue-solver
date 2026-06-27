# 0.10.0 Design Brief — AIS Tooling Interface

> Language note: This is technical release planning for AI workers and is kept
> in English. User-facing CLI text can still remain German per
> `docs/LANGUAGE_POLICY.md`.

## Purpose

Release 0.9.0 proved that `ai-issue-solver` can solve real GitHub issues
end-to-end. Release 0.10.0 should make AIS usable as a stable tool interface
for humans, apps, and agents.

The working theme is:

> **0.10.0 — AIS Tooling Interface Release**

The goal is not an Odysseus-specific integration. AIS should remain an
independent orchestration layer that can be called from:

- CLI / terminal / CI
- Odysseus or another app as an input layer
- Codex skills
- MiniMax Code / OpenCode workflows
- MCP-capable agent systems

## User Scenario

The motivating user input is natural, not issue-centric:

```text
Löse das folgende Problem im Repo bulwipgame mit AIS:
[P]
```

The system should turn this into a structured run:

1. Resolve `repo_hint=bulwipgame`.
2. Find the local repository path if available.
3. Infer GitHub `owner/repo` from `origin` or explicit configuration.
4. Optionally create a GitHub issue from problem text `P`.
5. Run split-planning when the problem is broad.
6. Start a solver run against the resulting issue.
7. Use Codex, MiniMax Code/OpenCode, or another configured worker.
8. Produce branch, commit, PR, and run report.
9. Return machine-readable status and final result.

## Proposed Architecture Direction

AIS should be split into a common core plus two frontends:

```text
                 +----------------+
                 |    AIS Core    |
                 | repo, issue,   |
                 | planning, runs |
                 +--------+-------+
                          |
        +-----------------+-----------------+
        |                                   |
        v                                   v
+---------------+                   +---------------+
| AIS CLI       |                   | AIS MCP       |
| humans/apps   |                   | agents/tools  |
+---------------+                   +---------------+
        |                                   |
        v                                   v
Terminal / CI / Apps              Odysseus / Codex / OpenCode
```

### AIS Core

Shared Python functions should own the stable behavior:

- resolve repository hints into `owner`, `repo`, `repo_path`, and `remote`
- create or locate GitHub issues
- classify broad vs narrow work
- call split-planning and batch-planning
- start solver runs
- persist run lifecycle state
- read and summarize reports

This should be introduced incrementally around the current scripts rather than
as a large rewrite.

### AIS CLI

The CLI should be usable by humans and apps. It should support JSON output and
background execution:

```bash
ais resolve-repo bulwipgame --json
ais solve-issue --owner pewdiepie-archdaemon --repo bulwipgame --issue 123 --json
ais solve-problem --repo bulwipgame --problem-file problem.md --create-issue --background --json
ais plan-batches --repo bulwipgame --label ai-generated --json
ais status --run-id 20260626-183012-bulwipgame --json
ais cancel --run-id 20260626-183012-bulwipgame --json
```

The initial CLI can be a thin wrapper over existing scripts:

- `scripts/solve_issues.py`
- `scripts/solve_issues_batch.py`
- `scripts/split_planning.py`
- `scripts/plan_issue_batches.py`
- `scripts/solver_reporting.py`

### AIS Background Runs

Apps such as Odysseus should be able to launch AIS and then poll status:

```text
App -> ais solve-problem --background --json
App <- { run_id, status, status_command, report_path }
App -> ais status --run-id ... --json
```

Suggested lifecycle states:

- `queued`
- `running`
- `needs_confirmation`
- `succeeded`
- `failed`
- `cancelled`

### AIS MCP

MCP should expose safe, structured tools rather than free shell access:

- `ais_resolve_repo`
- `ais_solve_problem`
- `ais_solve_issue`
- `ais_plan_batches`
- `ais_split_issue`
- `ais_run_status`
- `ais_cancel_run`

Agent-facing defaults should be conservative:

- `dry_run=true` by default
- no raw shell command arguments
- explicit confirmation for issue creation, push, PR creation, branch deletion,
  or other mutating actions
- secret redaction in prompts, logs, reports, and tool outputs

## Existing Relevant Entry Points

Current AIS behavior already exists in script form:

- `scripts/solve_issues.py` — single issue solver, workers, PR creation
- `scripts/solve_issues_batch.py` — bounded parallel issue solving
- `scripts/split_planning.py` — broad parent issue decomposition
- `scripts/plan_issue_batches.py` — conflict-aware waves
- `scripts/run_overnight.py` — unattended batch runs
- `scripts/solver_reporting.py` — reports, metrics, diagnostics

Existing Codex/AIS skills should remain compatible and can become thin
instructions around the new CLI/MCP contracts:

- `.agents/skills/solve-issues/`
- `.agents/skills/plan-issue-batches/`
- `.agents/skills/model-selection/`
- `.agents/skills/recovery/`
- `.agents/skills/rework/`
- `.agents/skills/solver-reporting/`

## Integration Picture

```text
User / App
  -> AIS CLI or AIS MCP
      -> AIS Core
          -> GitHub issue/PR APIs
          -> split-planning / batch-planning
          -> Codex or MiniMax Code/OpenCode worker
          -> run reports
  <- status, links, report summary
```

For Odysseus specifically, the app can act as an input layer:

1. User writes: `Löse das folgende Problem im Repo R mit AIS: [P]`.
2. Odysseus extracts `repo_hint` and `problem`.
3. Odysseus starts `ais solve-problem ... --background --json`, or calls the
   equivalent MCP tool.
4. Odysseus polls `ais status` or `ais_run_status`.
5. Odysseus displays issue link, PR link, run status, and errors.

Odysseus should not need to import AIS internals.

## Design Constraints

- No large rewrite for 0.10.0.
- Keep existing script entry points compatible.
- Add stable contracts around current behavior first.
- GitHub identity must support explicit `owner/repo`, not only
  `GITHUB_USER/repo`.
- Repo resolution must support:
  - explicit `owner` + `repo`
  - `owner/repo`
  - `repo_hint`
  - `repo_path`
  - `git remote origin`
- Agent and MCP calls default to safe dry-runs.
- Mutating actions need explicit gates.
- Secrets must never leak into prompts, reports, logs, or JSON output.
- Background runs need durable IDs and report paths.
- The implementation should be decomposed into small PRs with limited file
  conflicts.

## Questions For MiniMax Review

Please review this design direction as a senior architecture task.

Focus on whether the proposed 0.10.0 scope is:

- coherent as a bridge between 0.9.0 validation and 1.0.0 workflow app
- small enough for reviewable implementation
- safe enough for agent/app use
- explicit enough for CLI and MCP consumers
- compatible with Codex skills and MiniMax Code/OpenCode workers

## Requested MiniMax Output

Produce a concrete design proposal with the following sections.

### 1. Architecture Decision Record

Include:

- decision
- rationale
- alternatives considered
- risks
- consequences

### 2. Target Architecture Diagram

Include AIS Core, AIS CLI, AIS MCP, apps/Odysseus, Codex, MiniMax
Code/OpenCode, GitHub, and run reports.

### 3. CLI Contract

Define:

- commands
- arguments
- JSON output shapes
- error format
- examples
- compatibility plan for existing scripts

### 4. MCP Tool Contract

Define:

- tool names
- input schemas
- output schemas
- safety defaults
- which tools are read-only vs mutating

### 5. Run Lifecycle

Define:

- state model
- run ID format
- report files
- polling behavior
- cancel/resume behavior
- how background processes are tracked

### 6. Migration Plan

Prefer phases:

1. Thin CLI wrapper.
2. Repo resolution and problem-mode contracts.
3. Background run state.
4. MCP server.
5. Codex/Odysseus/OpenCode documentation and examples.

### 7. Release 0.10.0 Scope

Separate:

- must-have
- should-have
- explicitly out of scope

### 8. Backlog Decomposition

Do not produce one broad implementation issue. Produce a parent plan and 5 to
10 narrow child issues.

For each child issue include:

- title
- goal
- why this issue is separate
- dependencies
- acceptance criteria
- affected files/modules
- tests
- risk/complexity: low, medium, or high
- recommended worker model: small model, strong coding model, or large
  architecture model
- whether it can be worked on in parallel

Also provide an execution-wave table:

| Wave | Issue | Purpose | Files | Parallelizable | Recommended Model |
| ---- | ----- | ------- | ----- | -------------- | ----------------- |

Mark file conflicts explicitly. If two issues touch the same core module, put
them in different waves.

### 9. Test Strategy

Cover:

- unit tests
- CLI tests
- MCP contract tests
- dry-run integration tests
- background lifecycle tests
- secret-redaction tests
- failure-mode tests

## Quality Bar

The proposal should be pragmatic. Prefer small, reviewable steps over a new
platform. The target is a stable 0.10.0 interface layer that lets AIS be called
by apps and agents before the larger 1.0.0 workflow app exists.
