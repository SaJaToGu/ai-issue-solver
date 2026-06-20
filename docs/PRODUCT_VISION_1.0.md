# Product Vision 1.0

> **Language note:** This document is technical release planning and is kept in
> English so AI workers can process it reliably.

## Goal

AI Issue Solver 1.0 is a runnable workflow app for AI-assisted repository work.

The app does not replace the human operator. It coordinates transparent,
reviewable steps around one repository: triage, planning, model selection,
solver execution, observation, review, rework, recovery, merge preparation, and
reporting.

## Core Product Statement

AI Issue Solver controls AI-backed repository workflows. A repository is always
the backbone: issues, branches, pull requests, tests, run reports, costs, and
human decisions all attach to that repository.

AI tools such as Codex, OpenCode, MiniMax-backed OpenCode models, OpenRouter,
aider, Mistral Vibe, and future workers are interchangeable adapters behind
open CLI/API boundaries.

## 1.0 Success Criteria

A human can open the app and answer these questions without reading raw logs:

- Which repository is active?
- Which issues or pull requests need attention?
- What does the app recommend as the next step?
- Which AI worker and model would be used?
- Why was that model selected, and how can it be changed for this run?
- What is currently running?
- What did the last run produce?
- What did tests, review, and health checks say?
- What does the human need to approve, reject, merge, retry, or rework?

## Required 1.0 Capabilities

- Repository-centered workflow state.
- Human-facing UI or dashboard that shows the current workflow status.
- Deterministic triage for PR congestion, open issues, stale runs, and blocked
  work.
- Conflict-aware issue wave planning.
- Model selection and per-run model override for every AI-backed process step.
- Solver orchestration through replaceable workers.
- Run observation: health, output, cost, token, branch, PR, and report status.
- Standard review gate: deterministic checks first, optional AI reviewer second,
  human triage last.
- Rework and recovery paths for failed, partial, interrupted, or risky runs.
- Open CLI surfaces for AI tools so Codex, OpenCode, MiniMax-backed OpenCode
  models, OpenRouter, aider, Mistral Vibe, and future tools can be swapped or
  combined.

## Out of Scope for 1.0

- Fully autonomous merging.
- Perfect multi-repository management.
- User account management or SaaS-style permissions.
- Exhaustive live benchmarking of every available model.
- Replacing GitHub as the source of truth for issues and pull requests.

## First Production Target

After Release 1.0 reaches a runnable app state, the first repository to process
productively should be `laundry-assistant`.

This target matters because 1.0 should prove the app on a real user-owned
repository, not only on `ai-issue-solver` itself.

## Architecture Direction

The system should converge toward these layers:

1. Repository State
   - issues, PRs, branches, tests, CI, run reports, local worktrees.
2. Workflow Orchestration
   - triage, planning, solver runs, reviewer runs, rework, recovery, cleanup.
3. AI Worker Adapters
   - Codex, OpenCode, MiniMax-backed OpenCode models, OpenRouter, aider,
     Mistral Vibe, future tools.
4. Human UI
   - status, recommendations, costs, risks, actions, and approvals.
5. Reporting and Audit Trail
   - run reports, provider scorecards, review verdicts, costs, and decisions.

## Current Foundation

The repository already contains much of the backend foundation:

- `scripts/solve_issues.py`
- `scripts/solve_issues_batch.py`
- `scripts/run_overnight.py`
- `scripts/plan_issue_batches.py`
- `scripts/model_selection.py`
- `scripts/workflow_congestion.py`
- `scripts/review_pr.py`
- `scripts/rework_workflow.py`
- `scripts/solver_supervisor.py`
- `scripts/status_dashboard.py`
- `scripts/solver_reporting.py`
- worker adapters under `workers/`
- reusable skills under `.agents/skills/`

1.0 is therefore primarily a productization and orchestration milestone, not a
rewrite.

## Near-Term Workstreams

- Define the top-level app workflow and state model.
- Consolidate duplicated solver orchestration.
- Add a deterministic triage orchestrator.
- Standardize model override and model discovery across AI-backed steps.
- Turn the status dashboard into a human-facing workflow control surface.
- Keep AI runs cost-controlled: dry-run first, cheap model by default, stronger
  model only when risk or complexity justifies it.
