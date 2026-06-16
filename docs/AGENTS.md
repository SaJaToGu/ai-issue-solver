# Agents

This document defines the conceptual agent roles for the `ai-issue-solver`
project. It was rewritten as part of the **Release 0.7.0 information
architecture audit** (issue #309).

For the **operational, label-based agent routing** that GitHub issues use
today (`agent/triage`, `agent/solver`, `agent/reviewer`, etc.), see
[`label_taxonomy.md`](label_taxonomy.md). The 7 label-based agents there map
roughly — but not 1:1 — onto the 4 conceptual roles below. The mapping is
under review (see "Pending Review for 0.7.0" below).

For the current release focus and open questions, see
[`CURRENT_CONTEXT.md`](CURRENT_CONTEXT.md).

For the process we run after each release to revisit this document, see
[`RELEASE_REVIEW_AGENDA.md`](RELEASE_REVIEW_AGENDA.md).

---

## Planner

**Purpose:** Determine what should happen next.

**Responsibilities:**

- Release review preparation
- Backlog planning
- Issue generation
- Issue decomposition
- Context curation
- Promotion of important findings

**Modes:**

- `release-review`
- `backlog-planning`
- `issue-splitting`
- `roadmap-planning`

---

## Solver

**Purpose:** Solve a specific issue.

**Responsibilities:**

- Implement changes
- Run tests
- Create commits
- Create pull requests

**Modes:**

- `solve-issue`
- `resume-issue`
- `rework-issue`

---

## Reviewer

**Purpose:** Evaluate proposed solutions.

**Responsibilities:**

- Validate implementation
- Validate tests
- Check architectural compliance
- Suggest improvements

**Modes:**

- `review-pr`
- `architecture-review`

---

## Watchdog

**Purpose:** Monitor execution.

**Responsibilities:**

- Cost monitoring
- Progress monitoring
- Stuck detection
- Resume recommendations
- Stop recommendations

**Modes:**

- `cost-guard`
- `progress-monitor`
- `stuck-detection`

---

## Architecture Agent (future)

**Purpose:** Challenge assumptions and review project direction.

**Responsibilities:**

- Outside-in reviews
- Architecture reviews
- Assumption checks
- Strategic recommendations

**Modes:**

- `architecture-review`
- `outside-in-review`
- `assumption-check`

---

## Pending Review for 0.7.0

The 0.7.0 release-review discussion raised the following open questions
about the roles above. They are **not yet decided** and may change before
0.7.0 ships.

- **Watchdog may not be an agent.** The watchdog responsibilities above
  (cost monitoring, progress monitoring, stuck detection) are largely
  deterministic. A cron-driven skill or script is probably a better fit
  than an LLM agent. A final decision is pending.
- **Planner may need to be split.** The planner today does release
  planning, context curation, knowledge promotion, and knowledge archiving.
  A future split into **Planning** + **Knowledge Manager** is plausible;
  the knowledge-management side is deterministic and would also belong
  in a script/cron rather than an LLM agent.
- **Reviewer subtypes.** The current reviewer role may need subtypes
  (Code Reviewer, Architecture Reviewer, Documentation Reviewer) to
  match the model-routing config and to keep the reviewer prompt focused.
- **Label-based vs conceptual agents.** The 7 `agent/*` GitHub labels
  (Triage, Supervisor, Cost, Research, Planner, Solver, Reviewer) are an
  **operational** view that predates this document. They are not
  1:1 with the 4 conceptual roles. A clean mapping (probably via
  `config/role_routing.yaml`) is on the 0.7.0 backlog.
- **Solver stays "dumb".** The 0.7.0 review confirmed: solver should
  get the issue, the touched files, the relevant skill — nothing else.
  Smaller context, cheaper model, faster runs.

---

## Implementation Status (carried over from pre-0.7.0 AGENTS.md)

- **Triage** (label-based): partially implemented via
  `scripts/create_backlog_issues.py` and manual label updates.
- **Supervisor** (label-based): partially implemented via
  `scripts/solver_supervisor.py` and the status dashboard.
- **Cost** (label-based): partially implemented via run reports and
  budget dashboard.
- **Research** (label-based): ad-hoc implementation via custom scripts.
- **Planner** (label-based): partially implemented via backlog scripts.
- **Solver** (label-based): core implementation via
  `scripts/solve_issues.py` and `scripts/solve_issues_batch.py`.
- **Reviewer** (label-based): partially implemented via PR validation
  and `scripts/rework_workflow.py`.

## Next Steps

1. Decide whether the **Watchdog** role becomes a skill, a workflow, or
   stays an agent — see "Pending Review for 0.7.0" above.
2. Decide whether **Planner** is split into Planning + Knowledge Manager
   — also under "Pending Review".
3. Add **subtypes** to the Reviewer role (Code / Architecture / Docs).
4. Define a `config/role_routing.yaml` that maps role → provider → model
   → context files (separate issue).
5. Add **agent-based issue routing** in the triage step (label → script).
