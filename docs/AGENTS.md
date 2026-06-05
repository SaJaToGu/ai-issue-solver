# Agent Roles and Responsibilities

This document defines the roles, responsibilities, and workflow integration of specialized agents in the ai-issue-solver project.

## Agent Overview

| Agent | Primary Responsibility | Key Workflows | Label Prefix |
|-------|------------------------|---------------|--------------|
| **Triage** | Initial issue classification, label assignment, and routing | GitHub issue creation, label updates, backlog processing | `agent/triage` |
| **Supervisor** | Process monitoring, job health tracking, and targeted cancellation | Solver run supervision, process registry, dashboard updates | `agent/supervisor` |
| **Cost** | Budget tracking, cost estimation, and provider cost analysis | Run cost logging, budget reports, provider selection | `agent/cost` |
| **Research** | Structured research, evidence collection, and report generation | Research issue processing, evidence logging, report creation | `agent/research` |
| **Planner** | Backlog shaping, issue planning, and prioritization | Backlog issue creation, prioritization, cleanup | `agent/planner` |
| **Solver** | Implementation work, coding, and PR creation | Solver runs, code changes, PR generation | `agent/solver` |
| **Reviewer** | PR review, quality assurance, and rework detection | PR review, test validation, rework issue creation | `agent/reviewer` |

## Agent Workflow Integration

### 1. Triage Agent
- **Inputs**: New issues from `NEXT_BACKLOG.md`, GitHub issues, or external sources.
- **Outputs**: Classified issues with labels from the taxonomy, routed to the appropriate agent.
- **Key Scripts**:
  - `create_backlog_issues.py` (issue creation)
  - `label_migration.py` (label updates)
- **Labels Applied**: `theme/*`, `area/*`, `kind/*`, `priority/*`, `agent/*`

### 2. Supervisor Agent
- **Inputs**: Active solver runs, process health metrics, and dashboard data.
- **Outputs**: Process status updates, cancellation recommendations, and health alerts.
- **Key Scripts**:
  - `solver_supervisor.py` (process monitoring)
  - `serve_dashboard.py` (status visualization)
- **Labels Applied**: `theme/supervisor`, `area/runs`

### 3. Cost Agent
- **Inputs**: Run reports, provider metadata, and budget configurations.
- **Outputs**: Cost estimates, budget alerts, and provider recommendations.
- **Key Scripts**:
  - `solver_reporting.py` (cost logging)
  - `status_dashboard.py` (budget visualization)
- **Labels Applied**: `theme/cost`, `area/budget`

### 4. Research Agent
- **Inputs**: Research issues, evidence requirements, and analysis tasks.
- **Outputs**: Research reports, evidence logs, and structured findings.
- **Key Scripts**:
  - `analyze_repos.py` (repository analysis)
  - Custom research scripts (e.g., `evaluate_providers.py`)
- **Labels Applied**: `theme/research`, `kind/analysis`

### 5. Planner Agent
- **Inputs**: Backlog items, prioritization rules, and issue templates.
- **Outputs**: Prioritized backlog, shaped issues, and cleanup recommendations.
- **Key Scripts**:
  - `create_backlog_issues.py` (backlog processing)
  - `cleanup_backlog.py` (backlog maintenance)
- **Labels Applied**: `theme/backlog`, `priority/*`

### 6. Solver Agent
- **Inputs**: Ready issues, repository context, and provider configurations.
- **Outputs**: Code changes, PRs, and run reports.
- **Key Scripts**:
  - `solve_issues.py` (issue solving)
  - `solve_issues_batch.py` (batch processing)
- **Labels Applied**: `theme/workflow`, `agent/solver`

### 7. Reviewer Agent
- **Inputs**: Generated PRs, test results, and review feedback.
- **Outputs**: PR reviews, rework issues, and quality reports.
- **Key Scripts**:
  - `solver_reporting.py` (PR validation)
  - Custom review scripts (e.g., `pr_review.py`)
- **Labels Applied**: `theme/quality`, `agent/reviewer`

## Agent Collaboration
- **Triage → Planner**: New issues are shaped and prioritized before implementation.
- **Planner → Solver**: Ready issues are assigned to solver agents for implementation.
- **Solver → Reviewer**: Generated PRs are reviewed for quality and correctness.
- **Reviewer → Solver**: Rework issues are created and routed back to solver agents.
- **Supervisor → All**: Process health is monitored across all agents.
- **Cost → All**: Budget constraints are enforced for all agent activities.

## Implementation Status
- **Triage**: Partially implemented via `create_backlog_issues.py` and manual label updates.
- **Supervisor**: Partially implemented via `solver_supervisor.py` and dashboard.
- **Cost**: Partially implemented via run reports and dashboard.
- **Research**: Ad-hoc implementation via custom scripts.
- **Planner**: Partially implemented via backlog scripts.
- **Solver**: Core implementation via solver scripts.
- **Reviewer**: Minimal implementation via PR validation.

## Next Steps
1. **Automate Triage**: Enhance `create_backlog_issues.py` to apply the full label taxonomy automatically.
2. **Agent Routing**: Implement logic to route issues to agents based on labels (e.g., `agent/solver` → solver scripts).
3. **Dashboard Integration**: Update the dashboard to filter and group issues by agent role.
4. **Supervisor Enhancements**: Extend `solver_supervisor.py` to track agent-specific processes.
5. **Cost Tracking**: Integrate provider cost data into run reports and dashboard.

---

*Generated for Issue #229: Define label taxonomy and agent-role mapping for issues and files.*