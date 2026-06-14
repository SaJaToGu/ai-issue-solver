# Beispiel 01 — Einzelnen Run-Report inspizieren

Liest die wichtigsten Felder eines Run-Report-Verzeichnisses und gibt
sie als Klartext aus. Nützlich für ein schnelles Audit nach einem
Solver-Lauf.

## Voraussetzungen

- Ein Run-Report unter `reports/runs/<run_id>/` (vom Solver angelegt).
- Python ≥ 3.10.

## Aufruf

```bash
# Direkt mit jq
jq '.status, .repo, .issue, .branch, .model, .worker_exit_code, .pr_url' \
    reports/runs/20260614-153038-myrepo-issue-3/metadata.json

# Über den Skill-Aggregator
python .agents/skills/solver-reporting/helpers/aggregate_runs.py \
    --reports-dir reports/runs \
    --run-id 20260614-153038-myrepo-issue-3 \
    --format text
```

## Erwartete Felder

| Feld | Quelle | Beispiel |
|------|--------|----------|
| `status` | `metadata.status` | `pr_created` |
| `repo` | `metadata.repo` | `myrepo` |
| `issue` | `metadata.issue` | `3` |
| `branch` | `metadata.branch` | `ai/fix-issue-3` |
| `model` | `metadata.model` | `opencode` |
| `worker_exit_code` | `metadata.worker_exit_code` | `0` |
| `pr_url` | `metadata.pr_url` | `https://github.com/.../pull/123` |

## Erweiterte Felder

- `run_outcome` (sechs Felder, siehe [workflow.md](../workflow.md)).
- `provider_scorecard` (15 Felder, siehe SKILL.md).
- `opencode_runtime` (`wal_failure`, `edit_loop`, …).
- `rework` (`rework_of`, `rework_reason`, `subtask_id`, …).

## Alternative: Manuelle Inspektion

```bash
# Klartext-Summary
cat reports/runs/20260614-153038-myrepo-issue-3/summary.txt

# Health-Status
jq '.status, .phase, .last_activity_at, .opencode_runtime' \
    reports/runs/20260614-153038-myrepo-issue-3/health.json

# Worker-Output (gefiltert)
tail -30 reports/runs/20260614-153038-myrepo-issue-3/output-tail.log
```
