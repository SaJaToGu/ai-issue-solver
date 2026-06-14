# Beispiele für den solver-reporting-Skill

Dieses Verzeichnis enthält reproduzierbare Aufrufe für die häufigsten
Reporting-Szenarien. Alle Beispiele gehen davon aus, dass du im
Projekt-Root bist und bereits Solver-Runs unter `reports/runs/`
vorhanden sind.

## Voraussetzungen

```bash
# Python-Abhängigkeiten
pip install -r requirements.txt

# Mindestens ein Solver-Run muss bereits abgeschlossen sein
ls reports/runs/
# → 20260614-153038-myrepo-issue-3/
```

## Beispiele

| Datei | Szenario |
|-------|----------|
| [01_inspect_single_run.md](01_inspect_single_run.md) | Einen einzelnen Run-Report inspizieren |
| [02_diagnose_opencode.md](02_diagnose_opencode.md) | OpenCode-Runtime-Befunde aus Worker-Output extrahieren |
| [03_aggregate_scorecards.md](03_aggregate_scorecards.md) | Provider-Scorecards über mehrere Runs aggregieren |
| [04_cleanup_worktrees.md](04_cleanup_worktrees.md) | Abgelaufene Preserved Worktrees aufräumen |
| [05_heartbeat.md](05_heartbeat.md) | Heartbeat-Zeilen für Solver-Loops erzeugen |
| [06_run_outcome_distribution.md](06_run_outcome_distribution.md) | Verteilung der Run-Outcome-Klassen ausgeben |

## Generelles Muster

Jeder Aufruf folgt diesem Muster:

```bash
# Python-Helper
python .agents/skills/solver-reporting/helpers/<name>.py [--option WERT ...]

# Bash-Helper
bash .agents/skills/solver-reporting/helpers/<name>.sh [--option WERT ...]
```

Die Helper lesen ausschließlich `reports/` und führen **keine**
Solver-Läufe, Commits oder Pushes aus. Sie sind read-only oder
explizit als Dry-Run gekennzeichnet.
