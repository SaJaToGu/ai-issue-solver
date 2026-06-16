# Agents

This document defines the conceptual agent roles for the `ai-issue-solver`
project. It was rewritten as part of the **Release 0.7.0 information
architecture audit** (issue #309) and updated again with the **0.7.0 agent
architecture decisions** recorded at the bottom of this file.

For the **operational, label-based agent routing** that GitHub issues use
today (`agent/triage`, `agent/solver`, `agent/reviewer`, etc.), see
[`label_taxonomy.md`](label_taxonomy.md). The 7 label-based agents there
map roughly — but not 1:1 — onto the conceptual roles below. The mapping
lives in `config/role_routing.yaml` (planned for 0.7.0).

For the current release focus and open questions, see
[`CURRENT_CONTEXT.md`](CURRENT_CONTEXT.md).

For the process we run after each release to revisit this document, see
[`RELEASE_REVIEW_AGENDA.md`](RELEASE_REVIEW_AGENDA.md).

---

## Planner (LLM agent)

**Purpose:** Determine what should happen next.

**Responsibilities:**

- Release review preparation
- Backlog planning
- Issue generation
- Issue decomposition
- Context curation
- Architecture decisions (human-in-the-loop)

**Modes:**

- `release-review`
- `backlog-planning`
- `issue-splitting`
- `roadmap-planning`

**Note:** Knowledge lifecycle actions (`keep` / `promote` / `archive` /
`delete`) used to be Planner responsibilities. As of the 0.7.0 decisions,
they moved to the **Knowledge Manager** (a deterministic workflow, not
an LLM agent).

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

**Settled principle (from 0.7.0 review):** Solver gets minimal context —
the issue, the touched files, the relevant skill. Nothing else. Smaller
context, cheaper model, faster runs.

---

## Reviewer (subtypes)

The Reviewer role is split into three sub-roles as of the 0.7.0 decisions.
Each subtype has its own prompt, its own context, and (eventually) its own
model in `config/role_routing.yaml`.

### Code Reviewer

**Purpose:** Validate code changes and tests.

**Responsibilities:**

- Code review of the PR diff
- Test coverage check
- Lint / type / style validation
- Logic correctness check

**Modes:**

- `review-pr-code`
- `review-test-coverage`

### Architecture Reviewer

**Purpose:** Validate architectural compliance and challenge assumptions.

**Responsibilities:**

- Architecture review of the PR
- Outside-in review (does the change fit the larger direction?)
- Assumption check
- Strategic recommendation

**Modes:**

- `review-architecture`
- `review-outside-in`

### Documentation Reviewer

**Purpose:** Keep documentation in sync with code.

**Responsibilities:**

- Documentation completeness check
- Documentation accuracy check
- Cross-reference validation (links, anchors, examples)

**Modes:**

- `review-docs-completeness`
- `review-docs-accuracy`

---

## Watchdog (workflow, not an agent)

**Status:** The Watchdog is **not** an LLM agent as of the 0.7.0
decisions. The responsibilities below are deterministic; a cron-driven
script is the right shape. LLM-based escalation is optional and used
only when the deterministic checks detect anomalies that need explanation.

**Responsibilities:**

- Cost monitoring
- Progress monitoring
- Stuck detection
- Resume recommendations
- Stop recommendations

**Implementation shape:**

```
Watchdog
├── scripts/watchdog.py        # deterministic checks
├── cron / nightly run         # scheduling
└── optional LLM escalation    # only when anomaly is detected
```

---

## Knowledge Manager (deterministic workflow)

**Status:** New role as of the 0.7.0 decisions. Not an LLM agent — a
deterministic script with human-in-the-loop approval for destructive
actions.

**Purpose:** Manage the lifecycle of project knowledge — keep, promote,
archive, delete.

**Responsibilities:**

- Detect outdated documents (mtime + reference analysis)
- Run `archive` automatically for items that match the archive rules
- Require human approval for `promote` (move to permanent knowledge)
  and `delete` (irreversible)
- Audit `docs/` and skills on a schedule

**Implementation shape:**

```
Knowledge Manager
├── scripts/knowledge_manager.py    # lifecycle engine
├── config/lifecycle_rules.yaml     # what counts as outdated
└── human review queue              # for promote / delete
```

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

## Decisions for 0.7.0 (resolved, replacing the prior "Pending Review")

The following five decisions were made during the 0.7.0 planning
discussion and resolved the questions that were open in the audit
deliverable. Each is now a follow-up **issue** for implementation.

| # | Decision | Follow-up issue |
|---|---|---|
| 1 | **Watchdog** is a deterministic workflow (`scripts/watchdog.py` + cron), not an LLM agent. Optional LLM escalation only on anomalies. | #TBD: Watchdog as deterministic workflow |
| 2 | **Planner** is split: Planner (LLM) handles roadmap, issue creation, prioritization, architecture decisions. **Knowledge Manager** (deterministic script) handles `keep` / `promote` / `archive` / `delete`. | #TBD: Planner vs Knowledge Manager split |
| 3 | **Reviewer** is split into **Code Reviewer**, **Architecture Reviewer**, **Documentation Reviewer**. | #TBD: Reviewer subtypes |
| 4 | **`config/role_routing.yaml`** is the canonical place to map role → provider → model → context. Implementation requires verified OpenRouter model slugs and per-role budget fields. | #TBD: role_routing.yaml draft |
| 5 | **Skill folder split** (`.agents/skills/` + `.skills/`) is unified into one canonical path. The audit documented 8 skills; the unified structure maps them, it does not invent new skills. | #TBD: Skill folder unification |

The skill list to be unified, with their current locations:

- `model-selection` (`.agents/skills/`)
- `run-overnight` (`.agents/skills/`)
- `solve-issues` (`.agents/skills/`)
- `solver-reporting` (`.agents/skills/`)
- `git-cleanup` (`.skills/`)
- `plan-issue-batches` (`.skills/`)
- `recovery` (`.skills/`)
- `rework` (`.skills/`)

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

The label-based agents above are the **operational** view that predates
this document. They are not 1:1 with the conceptual roles. A clean
mapping (probably via `config/role_routing.yaml`) is on the 0.7.0
backlog.

## Next Steps

1. Create follow-up issues for the five 0.7.0 decisions above (one
   issue per row in the table).
2. Implement `config/role_routing.yaml` (issue #TBD) — depends on
   decisions #1, #2, #3.
3. Unify the skill folder structure (issue #TBD).
4. Add **agent-based issue routing** in the triage step (label →
   script) — this is the operational layer that uses `role_routing.yaml`.
