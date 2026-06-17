# Beispiel 06 — Run-Outcome-Verteilung

Aggregiert die `run_outcome`-Felder über alle Run-Reports und gibt
eine kompakte Verteilung aus. Nützlich, um Drift in der
Solver-Pipeline frühzeitig zu erkennen (z. B. plötzlich viele
`pipeline_failure`-Runs).

## Voraussetzungen

- Mehrere Run-Reports unter `reports/runs/`.

## Aufruf

```bash
# Standard: Markdown-Verteilung
python .agents/skills/solver-reporting/helpers/aggregate_runs.py \
    --reports-dir reports/runs \
    --format outcome
```

## Erwartete Ausgabe

```text
=== Run-Outcome-Verteilung (42 Runs) ===

worker_status:        succeeded=30, failed=10, not_started=2
delivery_status:      pr_created=28, push_failed=4, not_applicable=8, incomplete=2
failure_class:        success=28, pipeline_failure=4, noop=8, model_failure=2
recovery_status:      none=30, preserved_worktree=4, retry_clean=2, manual_review=6
test_status:          passed=32, failed=6, unknown=4
has_changes:          True=30, False=12
```

## Felder

`build_run_outcome` produziert sechs Felder. Die Verteilung wird über
alle Run-Reports aggregiert:

| Feld | Mögliche Werte |
|------|----------------|
| `worker_status` | `not_started`, `succeeded`, `failed` |
| `has_changes` | `True`, `False` |
| `test_status` | `passed`, `failed`, `unknown` |
| `delivery_status` | `pr_created`, `pr_failed`, `push_failed`, `pushed_without_pr`, `not_applicable`, `incomplete`, `unknown` |
| `failure_class` | `success`, `noop`, `pipeline_failure`, `model_failure`, `validation_failure`, `runtime_failure`, `interrupted`, `unknown` |
| `recovery_status` | `none`, `preserved_worktree`, `retry_clean`, `manual_review` |

## Interpretation

- **Hoher Anteil `pipeline_failure`**: Push oder PR-API ist instabil.
  Token-Scope prüfen, ggf. `.agents/skills/recovery` einsetzen.
- **Hoher Anteil `model_failure`**: Worker liefert reproduzierbar keinen
  Output. `.agents/skills/rework` und ggf. Modell-Wechsel.
- **Hoher Anteil `runtime_failure`** + `preserved_worktree`:
  Worktrees sichern, Recovery mit `RECOVERY.md` anstoßen.
- **`noop` dominant**: Worker macht keine Änderungen. Prompt oder
  Branch-Plan prüfen.
- **`interrupted`**: Run wurde abgebrochen, kein Worker-Output.
  `.agents/skills/recovery` für Resume-Empfehlung.

## JSON-Ausgabe für Dashboards

```bash
python .agents/skills/solver-reporting/helpers/aggregate_runs.py \
    --reports-dir reports/runs \
    --format outcome --json
```

Liefert ein Dict, das direkt in `scripts/status_dashboard.py`
weiterverwendet werden kann.
