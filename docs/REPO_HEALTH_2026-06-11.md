# Repository Health Report - 2026-06-11

This report captures the post-restart cleanup state and the next priorities for
`ai-issue-solver`. It is intentionally written as project memory so future agent
sessions do not need to rediscover the same repository facts.

## Current State

- Local working tree: clean.
- Active branch after cleanup: `develop`.
- `develop` is aligned with `origin/develop` at PR #264.
- Open pull requests: none at the time of cleanup.
- Local branches were reduced to `develop` and `main`.
- `main` remains behind `origin/main`; normal feature work should continue from
  `develop`.

## Branch Cleanup

The following local branches were reviewed and deleted because they were merged,
superseded, stale, or intentionally abandoned:

- `ai/issue-261-dashboard`
- `ai/issue-263-free-opencode-ensemble`
- `ai/fix-issue-193`
- `ai/fix-issue-223-status-readonly`
- `ai/fix-issue-223-health-pids`
- `ai/fix-issue-223-stop-dry-run`
- `ai/fix-overnight-runner-summary`
- `codex/improve-silent-output`
- `ai/fix-issue-178`
- `ai/fix-issue-186`
- `ai/fix-issue-188`
- `codex/review-pr-171`

Important notes:

- `ai/fix-issue-188` was deleted even though issue #188 remains open. PR #211 was
  intentionally closed because the implementation duplicated GitHub
  repository-intelligence/Linguist-style behavior with a large local detector.
  The issue should be solved later with a smaller GitHub-first design.
- `ai/fix-issue-261` was merged through PR #264 and the stale remote-tracking ref
  was pruned.

Remaining non-standard remote branches after cleanup:

- `origin/ai/fix-issue-263/bench/194918/opencode-mimo-v2.5-free`
- `origin/ai/fix-issue-263/bench/194128/opencode-deepseek-v4-flash-free`
- `origin/codex/fix-issue-84`
- `origin/codex/fix-issue-89`

These should be reviewed separately before deleting remote branches.

## Open Work After PR #264

PR #264 was merged into `develop` after successful Python 3.10 and 3.12 CI. It
covered the initial single-repository URL parameter flow for the dashboard.

Issue #261 remains open because the later design update still requires:

- multi-repository selection through `repos`
- agent tabs
- the revised top repo list plus tab layout

Issue #263 remains open because only preparatory work has landed. The remaining
core scope is:

- parallel model dispatch
- reviewer/ranking step
- promotion of the best result to one PR
- benchmark output schema
- dashboard model-comparison view

## Benchmark Learnings

Claude-era benchmarking produced useful signals, but the current benchmark data
is not yet reliable enough for direct model ranking.

Main findings:

- Several models produced useful changes and passing tests, but the solver marked
  the run as failed at commit/push time.
- `changes=true` and `tests_passed=true` are too coarse. They can hide runtime
  failures such as `UnboundLocalError`, no-op worker runs, failed pushes, and
  preserved worktrees.
- The strongest Bullwhipgame signals came from:
  - `minimax/MiniMax-M3`
  - `opencode/mimo-v2.5-free`
  - `opencode/deepseek-v4-flash-free`
- `mistral/mistral-medium-latest` produced changes but hit binary/read issues.
- `mistral/mistral-large-latest` produced an incomplete/started run, which is a
  runtime stability signal rather than a model-quality signal.
- `opencode/nemotron-*` and `opencode/big-pickle` produced no useful result in
  the inspected run set.

The benchmark pipeline should distinguish these fields before it is used for
automatic model selection:

- `worker_status`
- `worker_exit_code`
- `has_changes`
- `tests_passed`
- `commit_status`
- `push_status`
- `pr_status`
- `preserved_worktree`
- `duration_seconds`
- `repo_type`
- `issue_type`
- `model`
- `review_score`
- `failure_class`

## Parallel Model Run Policy

Parallel model runs should not become the default solver path. They are useful,
but expensive in tokens, wall-clock time, and operational complexity.

Use parallel runs for:

- documentation tasks
- small isolated features
- tests
- low-risk dashboard improvements
- intentionally reproducible benchmark issues

Avoid parallel runs for:

- credentials and authentication
- destructive Git/GitHub operations
- database or state migrations
- large refactors
- ambiguous requirements

Recommended cadence:

- Run parallel model benchmarks periodically, not for every issue.
- Store results in durable JSON files under `reports/benchmarks/` or
  `benchmarks/`.
- Correlate results by repository type, issue type, model, and failure class.
- Surface benchmark summaries in the dashboard.

## Skill Roadmap

Skills are the highest-priority workflow improvement because they reduce repeated
prompt text, lower Codex token consumption, and make Codex/Claude/Mistral
behavior more consistent.

Initial skills:

1. `.skills/git-cleanup/`
   - check branch, status, local changes, open PRs, issue assignment
   - refuse destructive actions unless explicitly confirmed
   - summarize safe branch cleanup candidates

2. `.skills/issue-solver/`
   - select issue
   - choose base branch
   - choose model/provider path
   - run targeted tests
   - produce PR body with exact model and checks

3. `.skills/recovery/`
   - inspect failed runs
   - find preserved worktrees
   - find stale branches and open/closed PRs
   - recommend resume, delete, or retry actions

Next skills:

- `.skills/batch-run/`
- `.skills/night-run/`
- `.skills/create-pr/`
- `.skills/run-tests/`

## Recommended PR Sequence

1. Add this health report and roadmap.
2. Add initial `.skills/git-cleanup/` and `.skills/recovery/`.
3. Improve benchmark result schema and dashboard display.
4. Continue issue #263 with a constrained parallel model runner.
5. Review script inventory and consolidate night/batch/recovery entrypoints.
6. Add concise architecture and project-structure documentation.

## Success Criteria

- Future sessions can start from repository files instead of long chat history.
- Routine tasks use skills and targeted docs instead of large prompts.
- Parallel model runs are used selectively and generate durable benchmark data.
- Dashboard status reflects useful partial work, preserved worktrees, and failure
  classes rather than flattening everything into success/failure.
- The repository can run for extended periods without repeatedly exhausting Codex
  usage limits.
