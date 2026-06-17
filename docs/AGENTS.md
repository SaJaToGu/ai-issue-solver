# Agents & Workflows

This document defines the conceptual agent roles and deterministic workflows
for the `ai-issue-solver` project. It was rewritten as part of the **Release
0.7.0 information architecture audit** (issue #309) and updated again with
the **0.7.0 agent architecture decisions** recorded at the bottom of this
file.

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

# Agents

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

**Note:** The Planner does **not** handle knowledge lifecycle actions
(`keep` / `promote` / `archive` / `delete`). Those are the responsibility
of the **Knowledge Manager** (a deterministic workflow, not an LLM
agent, implemented via issue #312) — see below.

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

# Workflows

## Watchdog (deterministic workflow)

**Status:** Implemented as of issue #311. The Watchdog is **not** an LLM
agent. The responsibilities below are deterministic; a cron-driven script
runs the checks. LLM escalation is optional and used only when the
deterministic checks detect anomalies that need explanation.

**Responsibilities:**

- Cost monitoring (per-run, per-day, per-budget ratio)
- Progress monitoring (no phase change within N minutes)
- Stuck detection (no log activity within M minutes)
- Status report generation (JSON for dashboard ingestion)

**Implementation shape:**

```
Watchdog
├── scripts/watchdog.py          # deterministic checks (implemented)
│   ├── check cost               # per-run, per-day, budget-ratio
│   ├── check progress           # no-progress timeout
│   ├── check stuck              # no-activity timeout
│   └── status                   # JSON status report
├── cron / nightly run           # scheduling
├── reports/watchdog-status.json # structured output for dashboard
└── --llm-escalate flag          # only when anomaly is detected
```

**Configuration:**

- `WATCHDOG_PROGRESS_TIMEOUT_MINUTES` — default 30
- `WATCHDOG_STUCK_TIMEOUT_MINUTES` — default 15
- `WATCHDOG_PER_RUN_COST_USD` — default 5.0
- `WATCHDOG_PER_DAY_COST_USD` — default 20.0
- `WATCHDOG_BUDGET_RATIO` — default 0.8

---

## Knowledge Manager (deterministic workflow)

**Status:** Implemented via issue #312. Not an LLM agent — a
deterministic script with human-in-the-loop approval for destructive
actions. Runs as a scheduled job (cron / launchd).

**Purpose:** Manage the lifecycle of project knowledge — keep, promote,
archive, delete.

**Responsibilities:**

- Detect outdated documents (mtime + reference analysis)
- Run `archive` automatically for items that match the archive rules
- Require human approval for `promote` (move to permanent knowledge)
  and `delete` (irreversible)
- Audit `docs/`, `.agents/skills/`, and `.skills/` on a schedule
- Maintain a human review queue (`reports/knowledge-review-queue.json`)

**Implementation shape:**

```
Knowledge Manager
├── scripts/knowledge_manager.py    # lifecycle engine
│   ├── scan                        # run all rules, output candidates
│   ├── archive                     # execute automatic archive moves
│   ├── queue                       # show human review queue
│   └── status                      # knowledge base health summary
├── config/lifecycle_rules.yaml     # what counts as outdated (rules)
└── reports/knowledge-review-queue.json  # human approval queue
```

**Typical workflow:**

1. `python scripts/knowledge_manager.py scan` — scans all knowledge
   directories, identifies archive/promote/delete candidates, adds
   promote/delete entries to the review queue.
2. `python scripts/knowledge_manager.py archive` — moves automatic
   archive candidates to `docs/archive/` (dry-run with `--dry-run`).
3. `python scripts/knowledge_manager.py queue` — displays pending
   promote/delete entries that require human approval.
4. A human edits `reports/knowledge-review-queue.json` to set
   `status: approved` or `status: rejected` for each entry.
5. On the next scan, stale approved/rejected entries are cleaned up.

**Archive rules** (automatic, no human needed):
- `mtime_older_than`: files that haven't been modified in N days
- `no_incoming_references`: files with zero cross-references

**Promote rules** (human review required):
- `frequently_referenced`: files referenced N+ times
- `manual_tag`: files starting with a `promote-candidate` marker

**Delete rules** (human review required):
- `archived_longer_than`: archived files untouched for N days
- `orphaned_long_term`: non-archived files with zero refs and old mtime

---

## Decisions for 0.7.0 (resolved, replacing the prior "Pending Review")

The following five decisions were made during the 0.7.0 planning
discussion and resolved the questions that were open in the audit
deliverable. Each is now a follow-up **issue** for implementation.

| # | Decision | Follow-up issue |
|---|---|---|
| 1 | **Watchdog** is a deterministic workflow (`scripts/watchdog.py` + cron), not an LLM agent. Optional LLM escalation only on anomalies. | #311: Watchdog as deterministic workflow |
| 2 | **Planner** is split: Planner (LLM) handles roadmap, issue creation, prioritization, architecture decisions. **Knowledge Manager** (deterministic script) handles `keep` / `promote` / `archive` / `delete`. | #312: Implemented — `scripts/knowledge_manager.py`, `config/lifecycle_rules.yaml` |
| 3 | **Reviewer** is split into **Code Reviewer**, **Architecture Reviewer**, **Documentation Reviewer**. | #313: Reviewer subtypes |
| 4 | **`config/role_routing.yaml`** is the canonical place to map role → provider → model → context. Implementation requires verified OpenRouter model slugs and per-role budget fields. | #314: role_routing.yaml draft |
| 5 | **Skill folder split** (`.agents/skills/` + `.skills/`) is unified into one canonical path. The audit documented 8 skills; the unified structure maps them, it does not invent new skills. | #315: Skill folder unification |

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
  budget dashboard; consolidated by the deterministic Watchdog workflow.
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

## Implementation Status

| Decision | Status |
|---|---|
| #1 Watchdog as deterministic workflow (#311) | Implemented |
| #2 Planner vs Knowledge Manager split (#312) | Implemented |
| #3 Reviewer subtypes (#313) | Open — follow-up issue needed |
| #4 role_routing.yaml draft (#314) | Implemented |
| #5 Skill folder unification (#315) | Open — follow-up issue needed |

The remaining open items above should be tracked as separate GitHub
issues. Add **agent-based issue routing** in the triage step (label →
script) once all role definitions are stable — this is the operational
layer that uses `role_routing.yaml`.
