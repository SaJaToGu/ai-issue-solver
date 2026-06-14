# Plan-Issue-Batches — Workflow-Dokumentation

Diese Dokumentation beschreibt den vollständigen Workflow, den der
`plan-issue-batches`-Skill ausführt. Sie ergänzt die kompakte Beschreibung
in `SKILL.md` und dient als Referenz beim Audit einzelner Pläne, beim
Schreiben eigener Helfer oder beim Anpassen der Konflikt-Heuristiken.

## 1. Aufrufvarianten

Der Skill akzeptiert alle Argumente, die `python scripts/plan_issue_batches.py`
versteht. Die wichtigsten Optionen sind in `SKILL.md`
(`## Unterstützte Argumente`) zusammengefasst; die vollständige Liste
liefert:

```bash
python scripts/plan_issue_batches.py --help
```

Vier typische Aufrufmuster:

1. **Sichtung** — ohne `--emit-commands`. Nützlich, um vorab Wellen,
   Begründungen und Touches zu sehen, ohne sofort Batch-Kommandos zu
   erzeugen.
2. **Vorbereiteter Batch** — `--emit-commands` mit `--model` und
   optional `--base-branch`. Erzeugt pro Welle ein fertiges
   `solve_issues_batch.py`-Kommando.
3. **Gefilterte Sichtung** — `--label <name>`. Schränkt die Planung auf
   Issues mit bestimmtem Label ein.
4. **Modell-Wechsel** — `--model <name>`. Wählt das Modell für die
   ausgegebenen Batch-Kommandos (`codex`, `opencode`, `claude`, …).

## 2. Phasenmodell

Jeder Planungs-Lauf durchläuft vier klar getrennte Phasen.

| Phase | Bedeutung | Exit-Strategie |
|-------|-----------|----------------|
| `load_config` | `load_env`, `require_config_value` für `GITHUB_TOKEN` + `GITHUB_USER` | Bei Fehler Exit 1, kein Plan |
| `load_issues` | `GitHubClient.get_open_issues`, PRs filtern, `PlannedIssue` bauen | Bei Netzwerk-/API-Fehler: `RuntimeError` |
| `plan_waves` | `plan_waves` baut die konfliktarme Wellenliste | Bei 0 Issues: Warnung + Exit 0 |
| `render_plan` | `render_plan` schreibt Wellen, Begründungen, optionale Batch-Kommandos | Ausgabe auf stdout |

## 3. Priorisierung im Detail

Die Priorisierung folgt zwei Stufen:

1. **Issue-Reihenfolge** — `sorted(issues, key=lambda item: (item.repo, item.number))`.
   Garantiert, dass derselbe Eingabe-Zustand immer zum gleichen Plan führt.
2. **Wave-Platzierung** — pro Issue wird die erste Welle gesucht, die
   konfliktfrei aufgenommen werden kann. Die Suche ist **greedy** und
   **first-fit**: das Issue landet in der ersten Welle, die keine
   Konflikte erzeugt.

Diese Strategie ist nicht zwingend optimal (das ist ein
Bin-Packing-Problem), aber sie ist deterministisch, gut nachvollziehbar
und für die typische Größe des Issue-Backlogs ausreichend. Bei sehr
großen Backlogs (≥ 50 Issues) sollte das Ergebnis manuell geprüft werden.

## 4. Gruppierung im Detail

### 4.1 Touches-Bestimmung

Pro Issue werden die `touches` in dieser Reihenfolge bestimmt:

1. **Explizit** — `Touches:`-Zeile im Issue-Body. Akzeptiert werden:
   - Backtick-Werte: `Touches: \`scripts/foo.py\`, \`tests/test_foo.py\``
   - Komma-/Semikolon-getrennte Listen ohne Backticks
2. **Implizit** — Stichwort-Erkennung in Titel, Body und Labels über
   `KEYWORD_TOUCHES` aus `scripts/plan_issue_batches.py`.
3. **Fallback** — wenn weder explizit noch implizit etwas erkannt wird:
   `("README.md", "scripts/")`.

### 4.2 Konflikterkennung

`touches_conflict(left, right)` in `plan_issue_batches.py` erkennt
folgende Konfliktarten:

- **Gleicher Pfad** — exakte Übereinstimmung (mit oder ohne führendes
  `./`).
- **Datei in Verzeichnis** — ein Pfad `a` liegt unter einem
  Verzeichnis-Pfad `b` (`a.startswith(b.rstrip("/") + "/")`).
- **Verzeichnis in Verzeichnis** — analog für zwei Verzeichnisse.

Bei mehrdeutigen Konflikten wählt die Implementierung den längeren
Pfad als Konflikt-Repräsentation.

### 4.3 Wellen-Aufbau

```python
for issue in sorted_issues:
    placed = False
    for wave in waves:
        if touches_conflict(issue.touches, wave.touches):
            continue
        wave.touches = unique_paths([*wave.touches, *issue.touches])
        wave.issues = (*wave.issues, issue)
        placed = True
        break
    if not placed:
        waves.append(PlannedWave((issue,), issue.touches))
```

## 5. Ausführungsplanung im Detail

`batch_command_for_wave` baut pro Welle einen fertigen
`solve_issues_batch.py`-Aufruf:

```bash
python scripts/solve_issues_batch.py \
    --model <model> \
    --repo <repo> \
    [--base-branch <base>] \
    --issue <N1> --issue <N2> ... \
    --workers <anzahl>
```

Eigenschaften:

- `repo` wird aus dem ersten Issue der Welle übernommen
  (`wave.issues[0].repo`). Wellen sind aktuell mono-repo.
- `--workers` wird auf `max(1, len(wave.issues))` gesetzt.
- Argumente werden mit `shlex.quote` geschützt.
- `--base-branch` ist optional und wird nur gesetzt, wenn ein
  Basisbranch übergeben wurde.

## 6. Plan-Format

Der Plan wird mit `render_plan` ausgegeben. Beispiel:

```text
Welle 1:
  #1 - Add optional fallback
    Touches: scripts/solve_issues_batch.py
  #2 - Add scheduler
    Touches: scripts/solve_issues_batch.py, scripts/solve_issues.py
    Grund: getrennt von Welle 1: scripts/solve_issues_batch.py

  Command: python scripts/solve_issues_batch.py --model codex \
      --repo ai-issue-solver --base-branch develop \
      --issue 1 --issue 2 --workers 2
```

Felder pro Welle:

- **Welle N** — laufende Nummer, 1-basiert
- **Issue-Zeilen** — `<#nummer> - <titel>`
- **Touches** — bereinigte, eindeutige Liste der berührten Pfade
- **Grund** — nur ab Welle 2; erklärt die Trennung von früheren Wellen
- **Command** — nur bei `--emit-commands`; fertiges
  `solve_issues_batch.py`-Kommando

## 7. Fehlerklassifikation

| Status | Bedeutung | Empfohlene Aktion |
|--------|-----------|-------------------|
| `ok` | Plan erfolgreich erzeugt | Wellen manuell prüfen, ggf. `--emit-commands` |
| `no_issues` | Keine offenen Issues gefunden | Filter (`--label`, `--repo`) prüfen |
| `config_missing` | `GITHUB_TOKEN` oder `GITHUB_USER` fehlt | `config/.env` prüfen |
| `runtime_error` | `requests` fehlt oder GitHub-API-Fehler | Dependencies/Netzwerk prüfen |
| `invalid_args` | Unbekanntes Modell oder fehlerhafte Argumente | `--help` lesen, erneut aufrufen |

## 8. Integration mit dem solve-issues-Skill

Der Plan, den dieser Skill erzeugt, ist die direkte Eingabe für den
`.agents/skills/solve-issues`-Skill:

1. `plan-issue-batches --emit-commands --model codex` → Liste fertiger
   Batch-Kommandos.
2. Pro Welle wird `solve_issues_batch.py` aufgerufen, das intern
   `solve_issues.py` pro Issue startet.
3. Nach dem Lauf: `.skills/recovery` und `.skills/rework` wie in
   `SKILL.md` (`## Verwandte Skills`) beschrieben.

## 9. Erweiterung

Wenn die Planungs-Heuristik angepasst werden soll:

1. `KEYWORD_TOUCHES` in `scripts/plan_issue_batches.py` ergänzen oder
   anpassen.
2. Eigene Touches-Logik in `infer_issue_touches` einbringen.
3. Falls eine andere Wave-Strategie benötigt wird (z. B. prioritäts-
   gewichtetes Packen): neuen Algorithmus in `plan_waves` ergänzen und
   in `tests/test_plan_issue_batches.py` absichern.
4. Diese Doku in `## 3. Priorisierung im Detail` und
   `## 4. Gruppierung im Detail` synchron halten.
