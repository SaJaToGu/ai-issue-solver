# Beispiel 05 — Ensemble mit drei Modellen

`--ensemble N` führt die ersten `N` Modelle aus einem internen Pool
parallel aus und wählt anschließend das beste Ergebnis aus.

## Aufruf

```bash
python scripts/solve_issues.py \
    --model opencode \
    --issue 3 \
    --ensemble 3 \
    --skip-pr
```

`--skip-pr` verhindert, dass direkt ein PR erstellt wird — sinnvoll,
wenn du das Ergebnis erst manuell prüfen willst. Ohne `--skip-pr` legt
der Skill den Branch des Gewinner-Modells als PR an.

## Pool (Reihenfolge im Code)

```
[
    "opencode/deepseek-v4-flash-free",
    "opencode/mimo-v2.5-free",
    "claude-sonnet-4-20250514",
    "gpt-4o",
    "mistral/mistral-small-2603",
]
```

Mit `--ensemble 3` werden die ersten drei Einträge dieses Pools
verwendet.

## Score-Berechnung

`evaluate_results` bewertet jedes Modell:

| Kriterium | Punkte |
|-----------|--------|
| Hat Änderungen erzeugt | +3 |
| `returncode == 0` | +2 |
| `should_continue` ist `True` | +1 |
| Anzahl geänderter Dateien | +min(N, 5) |

Das Modell mit dem höchsten Score gewinnt. Haben alle Modelle keine
Änderungen erzeugt, fällt der Skill auf das erste Modell zurück und
markiert das im PR-Body (`evaluate_results`).

## PR-Body

Der Skill schreibt eine Tabelle mit Exit-Code, Änderungsstatus und
Dateianzahl in den PR-Body, inklusive einer Markierung "← **Ausgewählt**"
beim Gewinner-Modell.
