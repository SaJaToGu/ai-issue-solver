# Skill-Tests

Die Tests in diesem Verzeichnis prüfen, dass der
`solver-reporting`-Skill konsistent zusammengesetzt ist und die
Reporting-Bausteine aus `scripts/solver_reporting.py` korrekt
aggregiert. Sie sind **kein** Ersatz für die Pytest-Suite im
Hauptverzeichnis (`tests/test_solver_reporting.py`), sondern ergänzen
sie um Skill-spezifische Checks.

## Schnellstart

```bash
bash .agents/skills/solver-reporting/tests/run_skill_tests.sh
```

Das Script führt nacheinander aus:

1. `tests/test_skill_artifacts.py` — prüft, dass alle erwarteten
   Dateien vorhanden und nicht leer sind.
2. `tests/test_helpers.py` — ruft `aggregate_runs.py`,
   `diagnose_opencode.py` und `format_heartbeat.py` mit synthetischen
   Run-Report-Verzeichnissen auf.
3. `tests/test_skill_workflow.py` — importiert `solver_reporting` und
   prüft Kernbausteine (`create_run_report`, `build_run_outcome`,
   `detect_opencode_runtime_diagnostics`, `create_provider_scorecard`).

Alle Tests sind unabhängig von einem laufenden KI-Worker und benötigen
keinen GitHub-Token.

## Voraussetzungen

- Python ≥ 3.10
- Lokale Klonung des Repos
- Kein GitHub-Token erforderlich

## Manuelles Testen

```bash
# 1. Diagnose-Helper mit echtem Worker-Output
python .agents/skills/solver-reporting/helpers/diagnose_opencode.py \
    --worker-output reports/runs/<run_id>/worker-output.log

# 2. Aggregator über alle Run-Reports
python .agents/skills/solver-reporting/helpers/aggregate_runs.py \
    --reports-dir reports/runs --format markdown

# 3. Heartbeat-Format
python .agents/skills/solver-reporting/helpers/format_heartbeat.py \
    --issue 223 --elapsed-seconds 1020 --job-label PR2

# 4. Cleanup (Dry-Run)
bash .agents/skills/solver-reporting/helpers/cleanup_worktrees.sh \
    --retention-days 14
```

## Continuous Integration

In GitHub Actions genügt ein Schritt:

```yaml
- name: Run skill tests
  run: bash .agents/skills/solver-reporting/tests/run_skill_tests.sh
```

Der Schritt benötigt keinen GitHub-Token, weil alle Tests rein lokal
laufen.
