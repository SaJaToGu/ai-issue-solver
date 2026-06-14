# Skill-Tests

Die Tests in diesem Verzeichnis prüfen, dass der `run-overnight`-Skill
konsistent zusammengesetzt ist und sich korrekt in die bestehende
Runner-Pipeline integriert. Sie sind **kein** Ersatz für die Pytest-Suite
im Hauptverzeichnis (`tests/`), sondern ergänzen sie um Skill-spezifische
Checks.

## Schnellstart

```bash
bash .agents/skills/run-overnight/tests/run_skill_tests.sh
```

Das Script führt nacheinander aus:

1. `tests/test_skill_artifacts.py` — prüft, dass alle erwarteten
   Dateien vorhanden und nicht leer sind.
2. `tests/test_helpers.py` — ruft `parse_args.py` und die Bash-Helfer
   `parse_args.sh`, `scheduling_hint.sh`, `summary_check.sh` und
   `preflight.sh` mit gültigen und ungültigen Argumenten auf.
3. `tests/test_skill_workflow.py` — End-to-End-Smoke-Test gegen ein
   lokales Fake-Repo; stellt sicher, dass die zentralen Helfer aus
   `scripts/run_overnight.py` importierbar sind und sich wie erwartet
   verhalten.

Alle Tests sind unabhängig von einem laufenden KI-Worker und benötigen
**keinen** GitHub-Token.

## Voraussetzungen

- Python ≥ 3.10
- Lokale Klonung des Repos
- Keine aktiven Overnight-Läufe auf demselben System (Tests sind
  read-only mit Ausnahme temporärer Verzeichnisse)

## Manuelles Testen

```bash
# 1. Argument-Parser
python .agents/skills/run-overnight/helpers/parse_args.py --model opencode --workers 2
python .agents/skills/run-overnight/helpers/parse_args.py --model unknown
# → zweiter Aufruf muss Exit-Code 2 liefern

# 2. Bash-Helfer
bash .agents/skills/run-overnight/helpers/parse_args.sh --model opencode --workers 2
bash .agents/skills/run-overnight/helpers/parse_args.sh --model unknown
# → zweiter Aufruf muss Exit-Code 2 liefern

# 3. Scheduling-Vorlage
bash .agents/skills/run-overnight/helpers/scheduling_hint.sh --type systemd --hour 3

# 4. Summary prüfen
bash .agents/skills/run-overnight/helpers/summary_check.sh --latest
```

## Continuous Integration

In GitHub Actions genügt ein Schritt:

```yaml
- name: Run overnight skill tests
  run: bash .agents/skills/run-overnight/tests/run_skill_tests.sh
```

Der Schritt benötigt keinen GitHub-Token, weil alle Tests rein lokal
laufen.
