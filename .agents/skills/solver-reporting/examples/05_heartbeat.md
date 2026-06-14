# Beispiel 05 — Heartbeat-Zeilen für Solver-Loops

Erzeugt kompakte, phone-freundliche Heartbeat-Zeilen für langlaufende
Solver-Jobs. Verwendet `format_heartbeat` und
`format_heartbeat_progress` aus `scripts/solver_reporting.py`.

## Voraussetzungen

- Python ≥ 3.10.

## Aufruf

```bash
# Standard: Issue-Nummer + verstrichene Sekunden
python .agents/skills/solver-reporting/helpers/format_heartbeat.py \
    --issue 223 --elapsed-seconds 1020
# → #223 ....+....+....+....+....+....+ 17min

# Mit Job-Label
python .agents/skills/solver-reporting/helpers/format_heartbeat.py \
    --issue 223 --elapsed-seconds 1020 --job-label PR2
# → #223 PR2 ....+....+....+....+....+....+ 17min

# Eigene Breite
python .agents/skills/solver-reporting/helpers/format_heartbeat.py \
    --issue 223 --elapsed-seconds 1020 --width 8
# → #223 ....+... 17min
```

## Format-Spezifikation

| Position | Wert |
|----------|------|
| Präfix | `#<issue>` |
| Job-Label | optional, zwischen Issue und Progress |
| Progress | `<width>` Zeichen, alle 5 Positionen ein `+`, sonst `.` |
| Suffix | `<min>min` mit `elapsed_seconds // 60` |

Die Breite wächst mit der Zeit (`width = elapsed_minutes // 2`,
mindestens 1). Damit bleibt die Anzeige stabil, ohne dass der
Progress-String explodiert.

## Beispiel-Loop

```python
from solver_reporting import format_heartbeat

elapsed = 0
while job_running:
    print(format_heartbeat(issue_number=223, elapsed_seconds=elapsed, job_label="PR2"))
    time.sleep(60)
    elapsed += 60
```

Ausgabe:

```text
#223 PR2 . 0min
#223 PR2 . 1min
#223 PR2 .. 2min
#223 PR2 .. 3min
#223 PR2 ... 4min
#223 PR2 ....+ 5min
...
```

## Wann ist das sinnvoll?

- In CI-Logs für Solver-Runs, die mehrere Minuten dauern.
- In der Konsole während `python scripts/solve_issues.py`-Läufen.
- Im Status-Dashboard, um auf einen Blick zu sehen, welche Jobs aktiv
  sind und wie lange sie laufen.
