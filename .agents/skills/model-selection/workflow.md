# Model-Selection — Workflow-Dokumentation

Diese Dokumentation beschreibt den vollständigen Workflow, den der
`model-selection`-Skill ausführt. Sie ergänzt die kompakte Beschreibung in
`SKILL.md` und dient als Referenz beim Debugging, beim Schreiben eigener
Helper oder beim Audit einzelner Empfehlungen.

## 1. Aufrufvarianten

Der Skill akzeptiert sieben thematisch zusammenhängende Argumente plus
Format-Optionen. Die wichtigsten Optionen sind in `SKILL.md`
(`## Eingaben`) zusammengefasst; die vollständige Liste liefert:

```bash
bash .agents/skills/model-selection/helpers/parse_args.sh --help
```

Vier typische Aufrufmuster:

1. **Diagnose** — `--issue-text "..." --repo-type python` ohne Solver-Aufruf.
   Nützlich, um vor dem eigentlichen Solver-Lauf zu sehen, welches Modell
   gewählt würde.
2. **Auto-Solver-Bridge** — `--issue 42` lädt implizit die jüngste
   `reports/runs/.../metadata.json` und eskaliert ggf. automatisch.
3. **Manuelle Steuerung** — `--manual-model claude-sonnet-4` setzt ein
   konkretes Modell und behält die Heuristik-Metadaten (Kategorie, Risiko,
   Kosten-Tier) bei.
4. **History-Inspektion** — `helpers/history_check.sh 42` listet vorhandene
   Run-Berichte auf, ohne ein Modell zu empfehlen.

## 2. Phasenmodell

Jeder Aufruf durchläuft fünf klar getrennte Phasen. Anders als der
`solve-issues`-Skill schreibt der `model-selection`-Skill keine eigenen
Run-Reports — er nutzt die `metadata.json` der Solver-Runs als Eingabe und
gibt das Ergebnis als JSON oder als kompakten Textblock aus.

| Phase | Bedeutung | Output |
|-------|-----------|--------|
| `parse` | Argumente validieren, Defaults setzen | `args.json` in stdout |
| `load` | Konfig + Run-Historie laden | Python-Interna |
| `classify` | Issue klassifizieren, Risiko schätzen | `category`, `risk` |
| `select` | Modell auswählen, Kosten filtern, eskalieren | `model`, `cost_tier` |
| `format` | Ergebnis ausgeben (`json` / `text`) | Exit 0 / Exit 2 |

## 3. Routing-Quellen

Der Skill fasst bewusst mehrere Routing-Signale zusammen, damit künftige
Erweiterungen an einer einzigen Stelle ansetzen:

- **Issue-Text** (`--issue-text`) — primäre Quelle für `classify_issue`.
  Keywords wie `refactor`, `test`, `dashboard` fließen direkt in die
  Kategorie ein.
- **Labels** (`--labels`) — vom GitHub-Issue übernommen; überschreiben
  Keyword-Heuristik.
- **Betroffene Dateien** (`--touched-files`) — Dateiendungen (`.py`,
  `.R`, `.md`, `.ts`, `.vue` …) werden gegen `ISSUE_CATEGORIES` geprüft.
- **Repo-Typ** (`--repo-type`) — wird als Fallback benutzt, wenn keine
  andere Quelle eine Kategorie liefert. Wird künftig vom
  `repo_profile.as_model_selection_context` vorbefüllt.
- **Sprache** (`--language`) — wird derzeit nur in `args.json` weitergereicht
  und ist die Grundlage für künftige sprachspezifische Regeln
  (siehe `docs/BACKLOG/open.md` Roadmap).
- **Task-Typ** (`--task-type`) — gleiche Idee für `bug-fix`, `refactor`,
  `docs`, `tests`, `feature`.
- **Run-Historie** (`--history` oder `--issue` + `reports/runs/`) — der
  wichtigste Eskalations-Hebel. Bei `status: failed` oder
  `status: no-change` schlägt der Skill das nächste Modell in
  `MODEL_ESCALATION` vor. Die geladene Historie wird intern als
  `run_history` an `select_model_for_issue` weitergereicht.

## 4. Ausgabe-Schema

Das JSON-Ergebnis hat immer diese Felder (Reihenfolge stabil):

```json
{
  "ok": true,
  "model": "mistral-small",
  "reason": "Erstversuch mit günstigstem passendem Modell: mistral-small",
  "category": "docs-only",
  "risk": "low",
  "cost_tier": "cheap",
  "fallback_plan": [
    "opencode/mimo-v2.5-free",
    "opencode/minimax-m3-free"
  ],
  "inputs": {
    "repo_type": "python",
    "language": "python",
    "task_type": "docs",
    "issue": 42,
    "max_cost_tier": "expensive"
  },
  "routing": {
    "manual_override": false,
    "escalated": false,
    "history_run_id": null
  }
}
```

`--format text` rendert daraus:

```
=== model-selection ===
Model:        mistral-small
Reason:       Erstversuch mit günstigstem passendem Modell: mistral-small
Category:     docs-only
Risk:         low
Cost tier:    cheap
Fallback:     opencode/mimo-v2.5-free, opencode/minimax-m3-free
Inputs:       repo_type=python, language=python, task_type=docs, issue=42
Routing:      manual_override=false, escalated=false
```

Bei Fehlern wird `"ok": false` gesetzt und `"errors"` enthält eine Liste
mit Begründungen. Der Exit-Code ist dann `2` für Schema-/Argumentfehler
und `1` für unerwartete Ausnahmen (z. B. fehlende Heuristik-Datei).

## 5. Beobachtbarkeit

Der Skill setzt bewusst keine eigenen Run-Reports ab, um die Oberfläche
schlank zu halten. Diagnose-Hooks:

- **`--format json`** liefert `inputs` und `routing` für Audit-Tools.
- **`history_check.sh <issue>`** zeigt vorhandene Run-Verzeichnisse aus
  `reports/runs/`, sodass ein Operator manuell prüfen kann, ob die
  Eskalation plausibel ist.
- **`--debug`** (experimentell) schreibt die kompletten Argumente und die
  finale Empfehlung zusätzlich nach stderr.

## 6. Fehlerklassifikation

| Exit | `ok` | Bedeutung | Empfohlene Aktion |
|------|------|-----------|-------------------|
| `0` | `true` | Empfehlung erfolgreich berechnet | An Aufrufer weiterreichen |
| `2` | `false` | Schema-/Argumentfehler | Aufruf korrigieren |
| `1` | `false` | Unerwarteter Fehler (z. B. fehlende Heuristik) | `scripts/model_selection.py` prüfen |

Beispiel-Fehlerobjekt:

```json
{
  "ok": false,
  "errors": [
    "Mindestens eine Quelle (issue-text, labels, touched-files, repo-type, manual-model) ist erforderlich"
  ]
}
```

## 7. Erweiterung

Wenn die Modellauswahl um neue Routing-Signale erweitert werden soll,
empfiehlt sich die folgende Reihenfolge:

1. Neue Konstante in `scripts/model_selection.py` anlegen
   (z. B. `LANGUAGE_TO_STRENGTH`, `TASK_TYPE_HINTS`).
2. `classify_issue` oder `select_model` ergänzen, sodass das neue Signal
   in `category` / `risk` einfließt.
3. `scripts/solver_reporting.py` aktualisieren, damit das neue Feld im
   Run-Report landet (siehe `model_selection_metadata`).
4. Skill-Helfer anpassen: `helpers/parse_args.py` lernt das neue
   `--language` / `--task-type`-Feld (ist bereits vorbereitet); der
   `recommend_model.sh` reicht die Werte an `select_model_for_issue` durch.
5. Tests in `tests/test_skill_workflow.py` und im Repo-Haupttest
   `tests/test_model_selection.py` ergänzen.
6. Diese Doku und `SKILL.md` (`## Eingaben` und `## Standardablauf`)
   aktualisieren.

Diese Reihenfolge hält den Skill, das Solver-Script und die Tests in
einem konsistenten Zustand.
