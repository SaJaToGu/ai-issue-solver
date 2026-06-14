# Beispiele für den model-selection-Skill

Dieses Verzeichnis enthält reproduzierbare Aufrufe für die häufigsten
Szenarien. Alle Beispiele gehen davon aus, dass du im Projekt-Root bist
und `scripts/model_selection.py` importierbar ist (im Repo vorhanden).

## Voraussetzungen

```bash
# Python-Abhängigkeiten
pip install -r requirements.txt
```

## Beispiele

| Datei | Szenario |
|-------|----------|
| [01_auto_select_python_docs.md](01_auto_select_python_docs.md) | Automatische Auswahl für ein Docs-Issue (`--max-cost-tier cheap`) |
| [02_escalate_after_failure.md](02_escalate_after_failure.md) | Eskalation nach fehlgeschlagenem Run via `run_history` |
| [03_manual_override.md](03_manual_override.md) | Manuelles Override via `--manual-model` |
| [04_history_check.md](04_history_check.md) | `history_check.sh` für Diagnose vor einem Retry |
| [05_integration_with_solver.md](05_integration_with_solver.md) | Einbindung in `solve_issues.py` und eigene Skripte |

## Generelles Muster

Jeder Aufruf folgt diesem Muster:

```bash
bash .agents/skills/model-selection/helpers/recommend_model.sh \
    [--repo-type T] [--language L] [--task-type T] \
    [--issue N] [--issue-text TEXT] [--labels A,B] [--touched-files A,B] \
    [--max-cost-tier cheap|medium|expensive] \
    [--history PATH] [--manual-model NAME] \
    [--format json|text]
```

Mindestens eine Quelle (`--repo-type`, `--language`, `--task-type`,
`--issue`, `--issue-text`, `--labels`, `--touched-files`, `--history` oder
`--manual-model`) muss gesetzt sein, sonst beendet der Skill mit
Exit-Code 2.

Die Helper `helpers/parse_args.py` und `helpers/parse_args.sh` validieren
die Argumente vorab; `history_check.sh` ist ein read-only Diagnose-Werkzeug.
