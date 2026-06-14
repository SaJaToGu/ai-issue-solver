# Skill-Tests

Die Tests in diesem Verzeichnis prüfen, dass der `solve-issues`-Skill
konsistent zusammengesetzt ist und sich korrekt in die bestehende Solver-
Pipeline integriert. Sie sind **kein** Ersatz für die Pytest-Suite im
Hauptverzeichnis (`tests/`), sondern ergänzen sie um Skill-spezifische
Checks.

## Schnellstart

```bash
bash .agents/skills/solve-issues/tests/run_skill_tests.sh
```

Das Script führt nacheinander aus:

1. `tests/test_skill_artifacts.py` — prüft, dass alle erwarteten
   Dateien vorhanden und nicht leer sind.
2. `tests/test_helpers.py` — ruft `parse_args.py` und die Bash-Helfer
   mit gültigen und ungültigen Argumenten auf.
3. `tests/test_skill_workflow.py` — End-to-End-Dry-Run gegen ein
   lokales Fake-Repo; stellt sicher, dass `plan_branch_recovery`,
   `clone_repo` und `commit_and_push` zumindest importierbar sind.

Alle Tests sind unabhängig von einem laufenden KI-Worker und benötigen
keinen GitHub-Token. Nur für den Helper-Test wird ein
`config/.env` mit Platzhaltern erstellt.

## Voraussetzungen

- Python ≥ 3.10
- Lokale Klonung des Repos
- Keine aktiven Solver-Runs auf demselben Branch (Tests sind read-only)

## Manuelles Testen

```bash
# 1. Argument-Parser
python .agents/skills/solve-issues/helpers/parse_args.py --model opencode --issue 3
python .agents/skills/solve-issues/helpers/parse_args.py --model unknown
# → zweiter Aufruf muss Exit-Code 2 liefern

# 2. Bash-Helfer
bash .agents/skills/solve-issues/helpers/parse_args.sh --model opencode --issue 3
bash .agents/skills/solve-issues/helpers/parse_args.sh --model unknown
# → zweiter Aufruf muss Exit-Code 2 liefern
```

## Continuous Integration

In GitHub Actions genügt ein Schritt:

```yaml
- name: Run skill tests
  run: bash .agents/skills/solve-issues/tests/run_skill_tests.sh
```

Der Schritt benötigt keinen GitHub-Token, weil alle Tests rein lokal
laufen.
