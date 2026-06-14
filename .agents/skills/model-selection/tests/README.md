# Skill-Tests

Die Tests in diesem Verzeichnis prüfen, dass der `model-selection`-Skill
konsistent zusammengesetzt ist und sich korrekt in die bestehende
`scripts/model_selection.py`-Heuristik integriert. Sie sind **kein**
Ersatz für die Pytest-Suite im Hauptverzeichnis (`tests/`), sondern
ergänzen sie um Skill-spezifische Checks.

## Schnellstart

```bash
bash .agents/skills/model-selection/tests/run_skill_tests.sh
```

Das Script führt nacheinander aus:

1. `tests/test_skill_artifacts.py` — prüft, dass alle erwarteten Dateien
   vorhanden und nicht leer sind.
2. `tests/test_helpers.py` — ruft `parse_args.py`, `parse_args.sh` und
   `history_check.sh` mit gültigen und ungültigen Argumenten auf.
3. `tests/test_skill_workflow.py` — führt die Heuristik auf
   reproduzierbaren Eingaben aus und vergleicht die Auswahl gegen die
   Erwartungen aus `tests/test_model_selection.py`; zusätzlich wird der
   Bash-Wrapper `recommend_model.sh` validiert.

Alle Tests sind unabhängig von einem laufenden KI-Worker und benötigen
keinen GitHub-Token.

## Voraussetzungen

- Python ≥ 3.10
- Lokale Klonung des Repos
- `scripts/model_selection.py` importierbar (im Repo vorhanden)

## Manuelles Testen

```bash
# 1. Argument-Parser
python .agents/skills/model-selection/helpers/parse_args.py \
    --repo-type python --issue-text "Refactor tests"
python .agents/skills/model-selection/helpers/parse_args.py
# → zweiter Aufruf muss Exit-Code 2 liefern

# 2. Bash-Helfer
bash .agents/skills/model-selection/helpers/parse_args.sh \
    --repo-type python --issue-text "Refactor tests"
bash .agents/skills/model-selection/helpers/parse_args.sh
# → zweiter Aufruf muss Exit-Code 2 liefern

# 3. Empfehlung
bash .agents/skills/model-selection/helpers/recommend_model.sh \
    --repo-type python --issue-text "Update the docs" --format text

# 4. Historie prüfen
bash .agents/skills/model-selection/helpers/history_check.sh 42
```

## Continuous Integration

In GitHub Actions genügt ein Schritt:

```yaml
- name: Run model-selection skill tests
  run: bash .agents/skills/model-selection/tests/run_skill_tests.sh
```

Der Schritt benötigt keinen GitHub-Token, weil alle Tests rein lokal
laufen.
