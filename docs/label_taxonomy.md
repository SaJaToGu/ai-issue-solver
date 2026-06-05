# Label Taxonomy for ai-issue-solver

This document defines a structured taxonomy for GitHub issue labels in the ai-issue-solver project. The taxonomy enables consistent classification, filtering, and agent-based routing of issues.

## Label Dimensions

### 1. Theme (`theme/*`)
Labels that describe the high-level domain or focus area of the issue.

| Label | Description |
|-------|-------------|
| `theme/dashboard` | Issues related to the status dashboard UI/UX and data visualization |
| `theme/model` | Model selection, provider integration, and performance tuning |
| `theme/cost` | Budget tracking, cost estimation, and provider cost analysis |
| `theme/provider` | Provider-specific features, APIs, and compatibility |
| `theme/workflow` | Workflow automation, process improvements, and state management |
| `theme/backlog` | Backlog management, prioritization, and cleanup |
| `theme/supervisor` | Process monitoring, job cancellation, and health tracking |
| `theme/distributed-workers` | Worker distribution, parallel execution, and resource management |
| `theme/github` | GitHub API integration, issue/PR management, and webhooks |
| `theme/quality` | Code quality, testing, validation, and safety checks |
| `theme/research` | Research tasks, literature review, and evidence collection |
| `theme/codex` | Codex-specific features, sandboxing, and compatibility |

### 2. Area (`area/*`)
Labels that describe specific modules, components, or technical areas.

| Label | Description |
|-------|-------------|
| `area/pwa` | Progressive Web App (dashboard front-end) |
| `area/reports` | Run reports, summaries, and analytics |
| `area/runs` | Solver runs, job execution, and process management |
| `area/prs` | Pull request handling, review, and merge workflows |
| `area/issues` | Issue creation, classification, and lifecycle management |
| `area/labels` | Label taxonomy, classification, and maintenance |
| `area/model-selection` | Model selection logic, policies, and cost optimization |
| `area/provider-interface` | Provider abstraction layer and API adapters |
| `area/budget` | Budget tracking, cost controls, and spending reports |
| `area/worker-node` | Worker node management, resource allocation, and scaling |
| `area/opencode` | OpenCode CLI integration and compatibility |
| `area/openrouter` | OpenRouter API integration and provider routing |
| `area/mistral` | Mistral-specific features and optimizations |
| `area/minimax` | MiniMax provider integration and model support |
| `area/anthropic` | Anthropic (Claude) provider integration and model support |

### 3. Kind (`kind/*`)
Labels that describe the type or nature of the work.

| Label | Description |
|-------|-------------|
| `kind/feature` | New functionality or capability |
| `kind/bug` | Bug fixes and issue resolution |
| `kind/refactor` | Code refactoring and structural improvements |
| `kind/docs` | Documentation updates and improvements |
| `kind/test` | Test coverage, test infrastructure, and validation |
| `kind/analysis` | Data analysis, metrics, and reporting |
| `kind/automation` | Automation scripts and workflow improvements |
| `kind/research` | Research tasks and exploratory work |
| `kind/cleanup` | Code cleanup, maintenance, and technical debt reduction |

### 4. State (`state/*`)
Labels that describe the current state or phase of the issue.

| Label | Description |
|-------|-------------|
| `state/backlog` | Issue is in the backlog and not yet prioritized |
| `state/ready` | Issue is ready for implementation |
| `state/in-progress` | Issue is actively being worked on |
| `state/blocked` | Issue is blocked and cannot proceed |
| `state/review` | Issue is under review (PR or design) |
| `state/on-hold` | Issue is temporarily paused |
| `state/duplicate` | Issue is a duplicate of another |
| `state/wontfix` | Issue will not be addressed |

### 5. Priority (`priority/*`)
Labels that describe the urgency or importance of the issue.

| Label | Description |
|-------|-------------|
| `priority/1-critical` | Critical priority, requires immediate attention |
| `priority/2-high` | High priority, should be addressed soon |
| `priority/3-medium` | Medium priority, normal queue |
| `priority/4-low` | Low priority, can wait |

### 6. Agent (`agent/*`)
Labels that map issues to specific agent roles for automated routing.

| Label | Description |
|-------|-------------|
| `agent/triage` | Issues for initial classification and routing |
| `agent/supervisor` | Issues for process monitoring and job management |
| `agent/cost` | Issues for budget tracking and cost analysis |
| `agent/research` | Issues for research and evidence collection |
| `agent/planner` | Issues for planning and backlog shaping |
| `agent/solver` | Issues for implementation and coding work |
| `agent/reviewer` | Issues for PR review and quality assurance |

## Mapping: Existing Labels to New Taxonomy

| Existing Label | New Label(s) |
|---------------|--------------|
| `automation` | `theme/workflow`, `kind/automation` |
| `quality` | `theme/quality`, `kind/test` |
| `codex` | `theme/codex`, `agent/solver` |
| `documentation` | `kind/docs` |
| `github` | `theme/github`, `area/prs`, `area/issues` |
| `good-first-issue` | `priority/4-low` |
| `safety` | `theme/quality` |
| `setup` | `kind/feature` |
| `workflow` | `theme/workflow` |
| `analysis` | `theme/research`, `kind/analysis` |
| `dashboard` | `theme/dashboard` |
| `provider` | `theme/provider` |
| `research` | `theme/research` |
| `opencode` | `area/opencode` |
| `sandbox` | `theme/codex` |

## File/Module to Label Mapping

| File/Module | Primary Label(s) | Secondary Label(s) |
|-------------|------------------|--------------------|
| `scripts/status_dashboard.py` | `theme/dashboard`, `area/pwa` | `agent/supervisor` |
| `scripts/solver_supervisor.py` | `theme/supervisor`, `area/runs` | `agent/supervisor` |
| `scripts/solve_issues.py` | `theme/workflow`, `area/runs` | `agent/solver` |
| `scripts/create_backlog_issues.py` | `theme/backlog`, `area/issues` | `agent/planner` |
| `scripts/create_issues.py` | `theme/github`, `area/issues` | `agent/triage` |
| `scripts/serve_dashboard.py` | `theme/dashboard`, `area/pwa` | `agent/supervisor` |
| `scripts/solver_reporting.py` | `theme/quality`, `area/reports` | `agent/reviewer` |
| `scripts/solver_repository.py` | `theme/workflow`, `area/runs` | `agent/solver` |
| `scripts/analyze_repos.py` | `theme/research`, `kind/analysis` | `agent/research` |

## Migration Plan

1. **Label Creation**: Add all new labels to the GitHub repository using the `create_backlog_issues.py` script or manually via the GitHub UI.
2. **Issue Relabeling**: 
   - Use a script to batch-update existing issues with the new taxonomy.
   - Preserve existing labels where they map directly to the new taxonomy.
   - Add new labels incrementally to avoid noise in the issue history.
3. **Backlog Integration**: Update `create_backlog_issues.py` to support the new label dimensions when creating issues from `NEXT_BACKLOG.md`.
4. **Dashboard Updates**: Ensure the dashboard can filter and group issues by the new label dimensions.
5. **Agent Routing**: Implement logic in `agent/triage` to route issues to the appropriate agent based on the new labels.

## Implementation Notes

- The taxonomy is designed to be **non-exclusive**: Issues can and should have multiple labels from different dimensions.
- **Backward Compatibility**: Existing labels (e.g., `automation`, `quality`) will be mapped to the new taxonomy but retained during the transition.
- **Agent Mapping**: The `agent/*` labels enable future automation where specific agents handle issues based on their role.

## Follow-Up Issues

1. Update `create_backlog_issues.py` to generate issues with the new label taxonomy.
2. Implement dashboard filtering by label dimensions.
3. Add agent-based issue routing in `agent/triage`.
4. Create a script to migrate existing issues to the new taxonomy.

---

*Generated for Issue #229: Define label taxonomy and agent-role mapping for issues and files.*