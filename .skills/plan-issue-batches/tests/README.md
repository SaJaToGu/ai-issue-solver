# Skill-Tests

Die Tests in diesem Verzeichnis prüfen, dass der `plan-issue-batches`-Skill
konsistent zusammengesetzt ist und sich korrekt in die bestehende
Planungs-Pipeline integriert. Sie sind **kein** Ersatz für die
Pytest-Suite im Hauptverzeichnis (`tests/test_plan_issue_batches.py`),
sondern ergänzen sie um Skill-spezifische Checks.

## Schnellstart

```bash
bash .skills/plan-issue-batches/tests/run_skill_tests.sh
```

Das Script führt nacheinander aus:

1. `tests/test_skill_artifacts.py` — prüft, dass alle erwarteten
   Dateien vorhanden und nicht leer sind.
2. `tests/test_helpers.py` — ruft `parse_args.py` mit gültigen und
   ungültigen Argumenten auf und testet den Bash-Wrapper.
3. `tests/test_skill_workflow.py` — End-to-End-Test der Planungs-
   Logik (`plan_waves`, `render_plan`, `batch_command_for_wave`,
   `separation_reason`, `infer_issue_touches`) mit synthetischen
   Issues.

Alle Tests sind unabhängig von einem laufenden KI-Worker und benötigen
**keinen** GitHub-Token. Sie rufen weder die GitHub-API auf noch
starten sie Worker.

## Voraussetzungen

- Python ≥ 3.10
- Lokale Klonung des Repos
- Keine aktiven Solver-Runs auf demselben Branch (Tests sind read-only)

## Manuelles Testen

```bash
# 1. Argument-Parser
python .skills/plan-issue-batches/helpers/parse_args.py --repo ai-issue-solver
python .skills/plan-issue-batches/helpers/parse_args.py --model unknown
# → zweiter Aufruf muss Exit-Code 2 liefern

# 2. Bash-Helfer
bash .skills/plan-issue-batches/helpers/run_plan.sh --repo ai-issue-solver --emit-commands
```

## Continuous Integration

In GitHub Actions genügt ein Schritt:

```yaml
- name: Run plan-issue-batches skill tests
  run: bash .skills/plan-issue-batches/tests/run_skill_tests.sh
```

Der Schritt benötigt keinen GitHub-Token, weil alle Tests rein lokal
laufen.
