# Release 0.7.0 — Close-out Review

> **Status:** Release 0.7.0 closed.
> **Closes:** #309 (Release 0.7.0 Review).
> **Date:** 2026-06-18.
> **Process:** Followed [`RELEASE_REVIEW_AGENDA.md`](RELEASE_REVIEW_AGENDA.md).

This document is the close-out for Release 0.7.0. It answers the five
questions the human architect asked after the final issue (#313) merged,
and it is the input for 0.8.0 planning.

## 0. Timeline

| Date | PR | Title |
|---|---|---|
| 2026-06-16 | (commit `9ed033d`) | docs: resolve agent architecture decisions for 0.7.0 |
| 2026-06-16 | (commit `1079df1`) | feat(config): add role_routing.yaml |
| 2026-06-17 | #316 | docs+feat: 0.7.0 agent architecture decisions + role_routing.yaml |
| 2026-06-17 | #317 (#314) | config/role_routing.yaml — verified OpenRouter slugs + per-role budgets |
| 2026-06-17 | #318 (#311) | Watchdog as deterministic workflow |
| 2026-06-17 | #319 (#312) | Split Planner into LLM Planner + Knowledge Manager |
| 2026-06-17 | #320 (#315) | Unify `.skills/` into `.agents/skills/` |
| 2026-06-17 | #321 (#313) | Reviewer sub-roles: 3 prompt profiles + sub-labels |

Six PRs in one day, all merged to `develop`, all CI-green. HEAD at the
close of 0.7.0: `b8fabf5`.

---

## 1. What was actually improved?

**Honest answer, not aspirational.** The 0.7.0 series delivered five
concrete, testable improvements and a smaller sixth. Each maps to a
closed issue.

### 1.1 Roles have a routing table, not prose only — #314
`config/role_routing.yaml` is now the canonical place where each role
maps to a provider, a verified model slug, a context-files list, and a
monthly budget. Before 0.7.0 the routing was implicit in
`scripts/model_selection.py` heuristics; now it is data, validated at
startup against the live OpenRouter catalog (336 models as of 2026-06-17).

**Concrete benefit**: a new role is one YAML block, not a code change.
Per-role budgets are enforceable instead of aspirational.

### 1.2 Deterministic workflows where LLM was overkill — #311, #312
Two workflows that were previously "LLM agent" became deterministic
scripts with optional LLM escalation only on anomaly:

- `scripts/watchdog.py` (#311) — cost / progress / stuck monitoring.
  Exit codes `0/1/2` are cron-friendly.
- `scripts/knowledge_manager.py` (#312) — `keep / promote / archive /
  delete` lifecycle. Human-in-the-loop for destructive actions, with
  fail-closed governance (the solver can never run `promote` or
  `delete`).

**Concrete benefit**: two fewer LLM round-trips per day; predictable
costs; no risk of the watchdog LLM "interpreting" its own failure
modes.

### 1.3 Reviewer is three roles, not one — #313
Reviewer split into `reviewer_code` (Claude Sonnet 4), `reviewer_architecture`
(GPT-5), and `reviewer_documentation` (M2.5). Each has its own prompt
profile (`.agents/reviewers/reviewer-*.md`), its own model, its own
context, and its own sub-label (`agent/reviewer-{code,architecture,documentation}`).
The 0.7.0 deliverable is the **loadable contracts** — the wiring to
`solve_issues.py` is a follow-up.

**Concrete benefit**: when LLM PR review is actually wired (follow-up
issue), the prompts are ready. Per-concern cost control is possible
from day one.

### 1.4 One canonical skill path — #315
`.agents/skills/` is the only place skills live. The old `.skills/`
folder (4 skills: `git-cleanup`, `plan-issue-batches`, `recovery`,
`rework`) is gone. All 8 skills now share structure, cross-references
resolve, `scripts/knowledge_manager.py` audits one path.

**Concrete benefit**: 36-file mechanical refactor; no skill content
changed; no skill renamed; no skill invented. Discovery, tooling, and
review are easier.

### 1.5 Information architecture is now distinguishable — #309 audit
Before 0.7.0, `NEXT_BACKLOG.md` mixed long-term direction, current
release state, and immediate work. After 0.7.0:

- `docs/ROADMAP.md` — long-term direction (themes, release anchors).
- `docs/CURRENT_CONTEXT.md` — short-lived snapshot (rewritten each
  release).
- `docs/BACKLOG/open.md` — current executable work.
- `docs/BACKLOG/done.md` — closed work, kept for traceability.

`RELEASE_REVIEW_AGENDA.md` is the recurring process that drives the
short-lived snapshot.

### 1.6 What was NOT done
The audit deliverable promised five items. Four are done. The fifth —
**Handover document audit** — was deferred. There is no canonical
inventory of "what's in `docs/handover/`" or "what old handover notes
still apply". This is a real gap, not a solved problem.

---

## 2. What lessons remain?

These are the durable lessons, not the one-off gotchas. The one-off
gotchas live in agent memory; these belong in the project.

### 2.1 Design review before solver
The most valuable single decision of 0.7.0 was the design review on
#313 *before* launching the solver. The issue had been written
before #311, #312, #314, and #315 landed; without the review, a
solver run would have implemented three prompt files in the wrong
path (`agents/`) and three sub-labels that did not yet exist, against
a stale acceptance table.

**Rule for 0.8.0**: For any issue that touches ≥ 2 of the 0.7.0
artefacts (role_routing.yaml, .agents/skills/, .agents/reviewers/,
label_taxonomy.md, CURRENT_CONTEXT), do a 10-minute design review
before launching the solver. Cost: 10 minutes. Saved: hours.

### 2.2 Stale issues are normal, not exceptional
0.7.0 produced two stale issues: #313 (covered above) and arguably the
"depends on issue #4" reference inside #313 (which is a relic of the
audit numbering). Stale-issues are not a bug; they are a consequence of
shipping fast. The fix is the design-review habit, not a process to
prevent staleness.

### 2.3 Sub-skills vs prompts is a real distinction
After 0.7.0, `.agents/skills/` holds **workflows with helpers,
tests, and examples** (8 skills). `.agents/reviewers/` holds **LLM
invocation profiles** (3 prompts). The two folders exist because the
two concepts differ. Keep them separate; do not collapse them in 0.8.0.

### 2.4 "Solver stays dumb" held
0.7.0 did not grow solver responsibilities. The reviewer prompts are
**loadable artifacts**, not invocations. The supervisor, the watchdog,
and the knowledge manager are deterministic. The Solver is still
"issue + touched files + one skill". This is the most important
architectural property of the project; 0.8.0 must preserve it.

### 2.5 Issues written during one architecture state decay fast
0.7.0 shipped 5 issues in one day. Each one assumed a slightly older
state. The decay rate is fast because the project is moving fast. The
fix is the same as 2.1: design review before solver. Plus, on every
release, scan the open backlog for issues written ≥ 1 release ago and
re-validate.

### 2.6 Knowledge Manager is fail-closed by design
`scripts/knowledge_manager.py` was specifically built so the solver
cannot run `promote` or `delete` (sources are restricted to `user`,
`planner`, `manual_tag`; the solver role is rejected). This is the
right safety posture and should be the template for any future
destructive operation in the project.

### 2.7 A future role's name can collide with a present role
`architecture_agent` (future) and `reviewer_architecture` had
identical purpose statements in `role_routing.yaml` for one day. We
fixed it by splitting scope (per-PR vs project-direction). The lesson:
when you add a "future" role, write its **non-overlap** with present
roles, not just its purpose.

---

## 3. Follow-up issues

These are the issues 0.7.0 surfaced. None are "must do for 0.8.0" —
the user picks.

### 3.1 Wire reviewer prompts to runtime
**Origin**: #313 (out of scope).
**Shape**: `--reviewer-role {code,architecture,documentation}` flag on
`solve_issues.py`, or a new subcommand `solve_issues.py review-pr
<PR>`. Loads `.agents/reviewers/reviewer-*.md`, calls the matching
role from `role_routing.yaml`, writes the verdict somewhere.

**Why not done in 0.7.0**: solver discipline. Adding LLM review
responsibilities to `solve_issues.py` would grow the script and risk
the "Solver stays dumb" principle. A separate subcommand or a
separate script is the right shape.

### 3.2 Handover document audit
**Origin**: #309 audit deliverable (deferred).
**Shape**: enumerate `docs/handover/` (if it exists), `BACKLOG/done.md`,
and any other "decision over time" documents. For each: keep, promote
to AGENTS.md, or archive.

**Why not done in 0.7.0**: nobody asked, and it is its own piece of
work. Without an explicit owner it slips.

### 3.3 Auto-detection of PR type
**Origin**: #313 AC (deferred).
**Shape**: classify PRs into `code-only`, `architecture-impacting`,
`docs-only` to drive reviewer selection. Could be a heuristic on
touched paths, or an LLM classifier, or a label-set rule.

**Why not done in 0.7.0**: contradicts "Solver stays dumb" (LLM
classifier is its own LLM call). Defer until reviewer is wired.

### 3.4 `architecture_agent` (future) — promote or remove
**Origin**: #313, overlap resolution.
**Shape**: either implement as a real role for project-direction
reviews, or remove from `role_routing.yaml` and `docs/AGENTS.md`. The
"future" state has now lasted 2 releases; it is time to decide.

### 3.5 Backlog triage for 0.8.0
**Origin**: every release.
**Shape**: `docs/BACKLOG/open.md` is 1043 lines. Most items are not
prioritized for 0.8.0. A triage pass is needed before 0.8.0
planning, ideally with the release-review agenda as the framework.

### 3.6 Skill lifecycle: tests, examples, helpers maturity
**Origin**: #315.
**Shape**: 8 skills, but the helpers/ tests/ examples/ structure
varies in completeness. A consistency pass would help the next skill
author. Lower priority than the rest.

---

## 4. What goes in release notes 0.7.0?

A user-facing version of the close-out lives at
[`RELEASE_NOTES_0.7.0.md`](RELEASE_NOTES_0.7.0.md). Summary:

- New: `config/role_routing.yaml` (per-role model routing, verified
  slugs, monthly budgets).
- New: `scripts/watchdog.py` (deterministic, cron-friendly).
- New: `scripts/knowledge_manager.py` (lifecycle, fail-closed).
- New: `.agents/reviewers/reviewer-{code,architecture,documentation}.md`
  (LLM reviewer prompt profiles).
- Refactored: 8 skills unified under `.agents/skills/`.
- Docs: 5-decision architecture table in `docs/AGENTS.md` resolved
  the 0.7.0 audit's open questions.
- Docs: `docs/CURRENT_CONTEXT.md`, `docs/ROADMAP.md`,
  `docs/BACKLOG/{open,done}.md` separated.
- New process: `docs/RELEASE_REVIEW_AGENDA.md` (recurring).

**Migration**: nothing breaks for existing solver runs. The role
routing is opt-in for new roles; the old `model_selection.py`
heuristics remain. The skill unification was a path move only; no
user-visible behavior change.

**Known limitations**:
- Reviewer prompts are not yet wired to a runtime. A PR can be reviewed
  by hand using the prompt as a checklist, but not by the solver.
- The `architecture_agent` (future) role is still parked.
- Handover documents have not been audited.

---

## 5. What is consciously out of scope for 0.8.0?

These are decisions to keep 0.8.0 small, not oversights.

- **LLM-driven PR review at runtime.** Wiring the reviewer prompts is
  the only blocker. But 0.8.0 should not do this if doing it would
  grow `solve_issues.py`. Separate subcommand or separate script only.
- **Auto-detection of PR type.** Classifier LLM call contradicts the
  architectural principle. Defer.
- **Anything that breaks "Solver stays dumb".** No new LLM
  responsibilities on the hot path. Deterministic workflows first.
- **New solver features before the documentation story is settled.**
  Per the current `ROADMAP.md` "Out of Scope" — still valid. The
  handover audit (3.2) must happen first; the next solver feature
  should be designed with the audited handover in mind.
- **Model benchmarking without a cost-control baseline.** Same as
  above. With `role_routing.yaml` in place and per-role budgets
  enforceable, a 0.8.0 benchmarking pass is now possible — but only
  inside those budgets, not as a parallel track.
- **Long-term direction changes.** 0.8.0's themes will come from
  triaging `docs/BACKLOG/open.md` against the release-review agenda,
  not from new strategic items. Any "we should..." raised in 0.8.0
  review becomes a 0.9.0 candidate.

---

## 6. Suggested 0.8.0 anchors

Not commitments. Anchors for the next release-review discussion.

- **Architecture**: finish the handover audit (3.2); decide
  `architecture_agent` future (3.4).
- **Reviewer**: wire `--reviewer-role` to a runtime (3.1) in a separate
  script, not in `solve_issues.py`.
- **Knowledge**: `knowledge_manager` first dry-run, then enable for
  `archive` (no human review); keep `promote` / `delete` human-gated.
- **Watchdog**: cron the watchdog, validate the JSON output is
  consumable by the dashboard.
- **Process**: every release runs this close-out; the agenda grows
  only when a section has proven value twice in a row.

---

*This document is the canonical close-out for Release 0.7.0. The next
release-review session should begin by reading sections 1, 3, 5 of
this file as the input for 0.8.0 planning.*
