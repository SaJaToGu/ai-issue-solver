# Model Override Policy

> **Language note:** This document is technical workflow policy and is kept in
> English so AI workers can process it reliably.

## Purpose

AI Issue Solver should not hardcode one preferred model into workflow logic.
Model availability, quality, price, and provider reliability change over time.
Every AI-backed process step must therefore make model choice explicit,
reviewable, and overridable for a single run without editing source code.

This policy supports issue #366 and complements the model catalog/discovery
work tracked in #364.

## Selection Order

For every AI-backed step, the effective model is selected in this order:

1. **Per-run CLI override** for that command invocation.
2. **Role or provider default** from `config/role_routing.yaml` or the relevant
   provider adapter default.
3. **Discovery/catalog validation** from the model catalog workstream when that
   exists.

An override must apply only to the current run. It must not rewrite
`config/role_routing.yaml` or provider defaults.

## Reporting Contract

Where practical, dry-run or diagnostic output should show:

- configured/default model
- effective model
- model source: config/default vs override

Run reports should persist the effective model and, where useful, the requested
or configured model so later scoring can compare model choice against outcome.

## Current Surfaces

The shared provider/model inventory lives in `scripts/model_catalog.py`.
Inspect it without a live provider call:

```bash
python scripts/model_catalog.py
```

Use `--verify-openrouter` when the current OpenRouter `/models` catalogue should
mark configured slugs as verified or missing.

The implemented rows below reflect existing `argparse` surfaces in the listed
scripts. Rows marked "not yet wired" are future surfaces and must not be read as
implemented behavior.

| Process step | Entry point | Current override surface | Notes |
| --- | --- | --- | --- |
| Single solver run | `scripts/solve_issues.py` | `--model`, `--model-name`, `--auto-model`, `--max-cost` | Provider choice and provider-specific model are explicit. Auto-selection uses `scripts/model_selection.py`. |
| Batch solver | `scripts/solve_issues_batch.py` | `--model`, `--model-name`, fallback flags | Shared command helpers forward model flags to `solve_issues.py`. |
| Overnight wrapper | `scripts/run_overnight.py` | `--model`, `--model-name`, fallback flags | Shared command helpers forward model flags to the batch solver. |
| PR reviewer runtime | `scripts/review_pr.py` | `--model-override` | Overrides the role model from `config/role_routing.yaml` for one review run. Dry-run prints the model source. |
| Benchmark/model comparison | `scripts/benchmark_issues.py` | `--models`, `--ensemble` | Explicit model list for OpenCode benchmark runs. |
| Batch planning command emission | `scripts/plan_issue_batches.py` | `--model` | Determines the model emitted into generated batch commands. |
| Future architecture/outside-in agent | not yet wired | role config expected | Should use `config/role_routing.yaml` plus a per-run override. |
| Future watchdog LLM escalation | not yet wired | role config expected | Deterministic watchdog remains `provider: none`; optional LLM escalation should be explicit. |

## Naming Convention

- Use `--model` and `--model-name` for solver-style worker execution where
  provider and provider-specific model are separate concepts.
- Use `--model-override` for role-based OpenRouter calls where the role already
  has a configured default model. Current reviewer roles are
  `reviewer_code`, `reviewer_architecture`, and `reviewer_documentation` in
  `config/role_routing.yaml`.
- Avoid introducing new flag names for the same concept unless the workflow has
  a materially different model-selection shape.

## Implementation Checklist

For each AI-backed entry point:

- parse the override flag
- print the effective model in dry-run/diagnostic output
- forward model flags through wrapper layers
- persist effective model metadata in run reports where reports exist
- add focused tests for parse, dry-run display, forwarding, and metadata

## Open Gaps

- `plan_issue_batches.py` emits `--model`, but does not yet display a
  model-source line because it does not call a model itself.
- Future architecture/watchdog LLM surfaces need implementation before their
  override behavior can be tested.
