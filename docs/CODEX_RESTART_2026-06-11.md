Codex Restart Notes – 11.06.2026

Background

The AI Issue Solver project has reached a point where Codex usage limits interrupted development for several days. During this time, work continued with Claude and Mistral-based agents. The repository should be reviewed before further automation is added.

Current Concerns

1. Repository State

The repository may contain:

* unfinished branches
* old agent branches
* partially completed pull requests
* duplicated automation scripts
* obsolete experiments

Before implementing new features:

1. Review git status.
2. Review all local and remote branches.
3. Review open and recently closed PRs.
4. Review open issues.
5. Identify dead code and obsolete automation.

Do not assume the current structure is optimal.

⸻

2. Skills vs. Large Prompts

Investigate whether reusable agent knowledge should be moved from prompts into a skill system.

Goal:

* reduce token consumption
* reduce repeated instructions
* improve consistency between Codex, Claude and Mistral
* improve maintainability

Potential structure:

.skills/
git-cleanup/
issue-solver/
run-tests/
create-pr/
recover-failed-run/
night-run/
batch-run/

Each skill should contain focused instructions for a specific workflow.

⸻

3. Night Script Review

There may currently be multiple night-run scripts.

Tasks:

* identify all night-run scripts
* identify all batch-processing scripts
* determine whether duplication exists
* determine which implementation should become the canonical version

Desired end state:

scripts/
batch_solve_issues.sh
night_run.sh
recover_failed_run.sh

Avoid multiple competing implementations.

⸻

4. Git Cleanup Skill

High-priority skill candidate.

Before any automated work:

1. Check git status.
2. Check active branch.
3. Check uncommitted changes.
4. Check open PRs.
5. Check issue assignment.
6. Refuse potentially destructive actions.

The goal is to prevent agents from creating repository chaos.

⸻

5. Batch Processing Skill

Investigate whether issue batching should be controlled through a dedicated skill instead of repeated prompt instructions.

Possible responsibilities:

* issue selection
* branch naming
* progress tracking
* retry handling
* PR creation

⸻

6. Recovery Skill

Create a recovery workflow for interrupted runs.

Possible checks:

* failed runs
* abandoned branches
* stale PRs
* incomplete issue work

Goal:

Allow agents to resume safely after interruptions.

⸻

7. Hardware Considerations

Current conclusion:

Do not optimize for expensive hardware first.

Primary bottlenecks appear to be:

* model availability
* Codex limits
* repository organization
* prompt efficiency

Investigate workflow improvements before considering high-end hardware upgrades.

⸻

First Action After Restart

Generate a repository health report:

* git status
* branch inventory
* PR inventory
* issue inventory
* automation inventory
* script inventory

Then propose a cleanup and consolidation plan before implementing additional features.

8. Codex Usage Preservation (High Priority)

A major project goal is to avoid exhausting Codex limits prematurely.

Current observation:

* Large repository context consumes significant quota.
* Long-running agent sessions consume quota quickly.
* Repeated repository discovery wastes tokens.
* Large prompts and duplicated instructions increase cost.

Requirements

Before implementing new features, investigate ways to reduce Codex consumption.

Possible improvements:

1. Skills instead of repeated prompt instructions.
2. Repository-specific workflows stored in files.
3. Smaller task batches.
4. Better issue decomposition.
5. Reuse project knowledge instead of rediscovering it.
6. Reduce unnecessary repository scans.
7. Prefer targeted file analysis over full-project analysis.
8. Use lightweight models for routine tasks when appropriate.

Desired Workflow

Heavy Codex usage should be reserved for:

* architecture decisions
* complex bug fixing
* difficult refactoring
* code generation

Routine tasks should consume minimal context.

Success Criteria

The project should be able to run for weeks without repeatedly exhausting the available Codex quota.
9. Token Efficiency and Context Management

A primary project goal is to maximize useful Codex work while minimizing unnecessary token consumption.

The objective is to avoid long periods where Codex usage limits prevent further development.

Principles

Repository Knowledge Belongs in Files

Avoid repeatedly explaining project workflows in prompts.

Store persistent knowledge inside the repository:

docs/
AGENT_GUIDE.md
ARCHITECTURE.md
WORKFLOW.md
NIGHT_RUN.md

.skills/
git-cleanup/
issue-solver/
batch-run/
night-run/
recover-failed-run/

Agents should read documentation instead of rebuilding understanding from prompts.

⸻

Prefer Skills Over Repeated Instructions

Frequently repeated workflows should be implemented as reusable skills.

Examples:

* git-cleanup
* issue-solver
* batch-run
* night-run
* recover-failed-run
* create-pr
* run-tests

Goal:

Reduce duplicated instructions across sessions.

⸻

Reduce Repository-Wide Analysis

Avoid:

* full repository scans
* repeated branch discovery
* repeated workflow discovery
* repeated architecture reconstruction

Prefer:

* targeted file analysis
* targeted issue analysis
* retrieval of relevant files only

⸻

Architecture Documentation

Maintain a concise architecture summary.

Goal:

Allow agents to understand the project without repeatedly exploring the entire codebase.

Suggested files:

docs/ARCHITECTURE.md
docs/PROJECT_STRUCTURE.md

⸻

Workflow Documentation

Document operational procedures.

Examples:

* Night runs
* Batch processing
* Branch naming
* Pull request workflow
* Failure recovery

Agents should consult documentation first.

⸻

Issue Decomposition

Prefer smaller issues over large multi-purpose tasks.

Good:

* create configuration model
* add CLI option
* add tests
* update documentation

Avoid:

* implement entire subsystem in one issue

Smaller issues reduce context requirements and improve reliability.

⸻

State Tracking

Investigate maintaining a persistent project state.

Possible examples:

state.json
project_status.json

Contents may include:

* last processed issue
* active branch
* last PR
* last successful run
* failed runs

Goal:

Avoid rediscovering project state in every session.

⸻

Retrieval-Based Context

Investigate retrieving only the files relevant to an issue.

Preferred workflow:

1. Identify relevant files.
2. Load only those files.
3. Solve the issue.

Avoid loading unrelated project areas.

⸻

Model Allocation Strategy

Reserve Codex for:

* difficult bugs
* architecture changes
* complex refactoring
* code generation

Use lighter models where possible for:

* documentation
* changelogs
* summaries
* planning
* issue decomposition

⸻

Success Criteria

The project should be able to operate for extended periods without repeatedly exhausting Codex limits.

Token efficiency should be treated as a first-class project requirement alongside correctness, reliability, and automation.
