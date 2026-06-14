# Beispiel 03 — Provider-Scorecards aggregieren

Liest alle Run-Reports unter `reports/runs/` und aggregiert die
`provider_scorecard`-Felder zu einer vergleichbaren Tabelle. Nützlich
für Benchmark-Auswertungen und Modellvergleiche.

## Voraussetzungen

- Mehrere Run-Reports unter `reports/runs/`.
- Python ≥ 3.10.

## Aufruf

```bash
# Markdown-Tabelle (Standard)
python .agents/skills/solver-reporting/helpers/aggregate_runs.py \
    --reports-dir reports/runs \
    --format markdown

# TSV für Excel
python .agents/skills/solver-reporting/helpers/aggregate_runs.py \
    --reports-dir reports/runs \
    --format tsv

# JSON für weitere Verarbeitung
python .agents/skills/solver-reporting/helpers/aggregate_runs.py \
    --reports-dir reports/runs \
    --format json
```

## Erwartete Ausgabe (Markdown)

```text
| run_id | status | model (req) | model (act) | fallback | duration_s | exit | test | cost_usd | cost_src |
|--------|--------|-------------|-------------|----------|------------|------|------|----------|----------|
| 20260614-153038-myrepo-issue-3 | pr_created | mistral/mistral-large-latest | mistral/mistral-medium-latest | anthropic/claude-sonnet-4-6 | 120.5 | 0 | passed | 0.15 | provider_api |
| 20260614-160012-myrepo-issue-4 | pr_failed | opencode/deepseek-v4-flash-free | opencode/deepseek-v4-flash-free | | 45.0 | 1 | failed | 0.00 | estimated |
```

## Gefilterte Aggregation

```bash
# Nur erfolgreiche Runs
python .agents/skills/solver-reporting/helpers/aggregate_runs.py \
    --reports-dir reports/runs \
    --format markdown \
    --status-filter pr_created,pr_created_from_existing_branch

# Nur ein bestimmter Repo
python .agents/skills/solver-reporting/helpers/aggregate_runs.py \
    --reports-dir reports/runs \
    --format markdown \
    --repo-filter myrepo
```

## Felder

Der Helper liest `metadata.json.provider_scorecard` und projiziert auf
diese Spalten:

| Spalte | Quelle |
|--------|--------|
| `run_id` | Verzeichnisname |
| `status` | `metadata.status` |
| `model (req)` | `provider_scorecard.requested_model` |
| `model (act)` | `provider_scorecard.actual_model` |
| `fallback` | `provider_scorecard.fallback_source` |
| `duration_s` | `provider_scorecard.duration_seconds` |
| `exit` | `provider_scorecard.worker_exit_code` |
| `test` | `provider_scorecard.test_result` |
| `cost_usd` | `provider_scorecard.estimated_cost` |
| `cost_src` | `provider_scorecard.cost_source` |

## Verwandt: Outcome-Histogramm

Für eine kompakte Verteilung der `run_outcome`-Klassen siehe
[06_run_outcome_distribution.md](06_run_outcome_distribution.md).
