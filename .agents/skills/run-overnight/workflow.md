# Run-Overnight — Workflow-Dokumentation

Diese Dokumentation beschreibt den vollständigen Workflow, den der
`run-overnight`-Skill ausführt. Sie ergänzt die kompakte Beschreibung in
`SKILL.md` und dient als Referenz beim Debugging, beim Schreiben eigener
Helper oder beim Audit einzelner Overnight-Sessions.

## 1. Aufrufvarianten

Der Skill akzeptiert alle Argumente, die `python scripts/run_overnight.py`
versteht. Die wichtigsten Optionen sind in `SKILL.md` (`## Standardablauf`)
zusammengefasst; die vollständige Liste liefert:

```bash
python scripts/run_overnight.py --help
```

Vier typische Aufrufmuster:

1. **Standard-Nachtlauf** — `--model codex --workers 2`. Übernimmt alle
   erreichbaren Repos mit `ai-generated`-Issues.
2. **Einzelner Issue-Lauf** — `--repo <name> --issue <nummer> --workers 1`.
   Nützlich, um einen hartnäckigen Fall über Nacht zu wiederholen.
3. **macOS wach halten** — zusätzlich `--caffeinate`. Der Runner startet
   `caffeinate -dimsu -w <pid>` und beendet es sauber am Ende.
4. **Smoke-Test** — `--skip-pull --skip-tests --skip-congestion-check`. Nur
   Session-Struktur und Dashboard-Refresh prüfen, keine Worker laufen
   lassen.

## 2. Phasenmodell

Jeder Overnight-Lauf durchläuft sechs klar getrennte Phasen. Jede Phase
schreibt ihren eigenen Log unter `reports/overnight/<session>/` und wird in
der `summary.txt` mit Status, Exit-Code und Dauer festgehalten.

| Phase | Bedeutung | Verhalten bei Fehler |
|-------|-----------|----------------------|
| `caffeinate` | (macOS) Mac wach halten | Optional; übersprungen ohne `--caffeinate` |
| `pull` | `git pull --ff-only origin <base>` | Batch wird **nicht** gestartet |
| `tests` | Standard `python -m unittest discover -s tests` | Batch wird **nicht** gestartet |
| `workflow_congestion` | `solve_issues.py --dry-run` | Batch läuft **trotzdem** weiter (Hinweis) |
| `batch` | `solve_issues_batch.py` mit Worker-Limit | Hinweis in der Summary |
| `dashboard` | `status_dashboard.py` regeneriert HTML | Hinweis in der Summary |

Die `summary.txt` enthält pro Phase Name, Status (`ok` / `failed` /
`skipped`), Exit-Code, Dauer und Log-Pfad. Fehlerhafte Phasen werden
zusätzlich in `failed_steps` zusammengefasst, damit du sofort weißt, wo
du mit der Fehlersuche beginnen musst.

## 3. Session-Layout

```
reports/overnight/<YYYYMMDD-HHMMSS>[-<n>]/
├── caffeinate.log         # nur bei --caffeinate
├── pull.log
├── tests.log
├── workflow_congestion.log
├── batch.log
├── dashboard.log
└── summary.txt            # kompakte Übersicht
```

Bei einer Kollision (zwei Läufe in derselben Sekunde) hängt
`create_session_dir` automatisch `-2`, `-3`, … an.

## 4. Issue-Outcomes

Falls der Batch Reports unter `reports/runs/` erzeugt hat, sammelt
`collect_issue_outcomes` die wichtigsten Felder pro Issue und reiht sie in
die `summary.txt` ein:

- Repo, Issue-Nummer, Titel
- Status-String aus `summary.txt` (`pr_created`, `pr_failed`, …)
- Klassifikation (`successful`, `noop`, `failed`, `archived`, `unknown`)
- Worker-Exit-Code
- PR-URL (sofern vorhanden)
- Warnungsmarker (`conflict`, `syntax`) aus `detect_warning_markers`
- kompakte Liste der geänderten Dateien aus `git_diff_stat`
- Branch-Name, Modell, Run-Verzeichnis

Die Outcomes werden nach Issue-Nummer sortiert, damit du morgens schnell
die Liste der neu erstellten PRs durchgehen kannst.

## 5. Priorisierte Review-Reihenfolge

`get_step_priority` und `get_step_badge` sind die Helper, mit denen
nachgelagerte Tools (z. B. Status-Dashboard) die Schritte einer Overnight-
Session sortieren und einfärben können:

- `[OK]` (Priorität 0) — Phase erfolgreich.
- `[SKIP]` (Priorität 1) — Phase übersprungen (z. B. `--skip-tests`).
- `[FAIL]` (Priorität 2) — Phase fehlgeschlagen, weitergehende Schritte
  wurden ggf. ebenfalls übersprungen.

Diese Priorisierung steht im Einklang mit dem
`.agents/skills/solve-issues`-Workflow (dort: Run-Status-String).

## 6. Beobachtbarkeit

Der Skill setzt mehrere Hooks ein, damit Overnight-Läufe auch im
Hintergrund gut sichtbar bleiben:

- **Step-Logs** — Jeder Schritt schreibt nach
  `reports/overnight/<session>/<step>.log` mit Header (Name, Startzeit,
  Befehl) und Trailer (Dauer, Exit-Code). Damit kannst du einen Schritt
  jederzeit mit `tail` oder `less` inspizieren.
- **Live-Stream** — `run_logged_command` schreibt die Worker-/Test-Ausgabe
  parallel in den Log und nach stdout (`stream_output=True`). Damit siehst
  du im Terminal sofort, was passiert.
- **Issue-Outcomes** — siehe Abschnitt 4.
- **Dashboard** — `status_dashboard.py` liest `reports/runs/…/summary.txt`
  und zeigt die Runs in `reports/status-dashboard.html` an.
- **macOS `caffeinate`** — eigener Log, eigener Prozess, sauberer Shutdown.

## 7. Fehlerklassifikation

Die `summary.txt` und der `summary_check.sh`-Helfer verwenden konsistente
Status-Strings, die das Dashboard und der `.agents/skills/recovery`-Skill
auswerten:

| Status in `summary.txt` | Bedeutung | Empfohlene Aktion |
|-------------------------|-----------|-------------------|
| `status: successful` | Alle Phasen `ok` oder `skipped` | Dashboard öffnen, PRs reviewen |
| `status: failed` | Mindestens eine Phase `failed` | `summary.txt` lesen, betroffene Phase reparieren |
| `failed_steps:` (Liste) | Namen der fehlgeschlagenen Phasen | siehe oben |
| `workflow_congestion: see_dashboard_workflow_status` | Hinweis auf Congestion-Warnung | Dashboard prüfen, ggf. manuell eingreifen |

## 8. Recovery nach Absturz

Falls der Runner mitten in der Nacht abstürzt (Stromausfall, OOM, …), ist
der Zustand aus zwei Quellen rekonstruierbar:

1. `reports/overnight/<session>/summary.txt` — falls geschrieben, gibt
   sie Auskunft über die letzte erfolgreiche Phase.
2. `reports/runs/<run_id>/` — die Run-Reports des Batch-Solvers, die
   auch ohne abschließende Overnight-Summary aussagekräftig sind
   (`summary.txt`, `health.json`, `worker-output.log`).

Der `.agents/skills/recovery`-Skill erklärt die Schritte im Detail; die
wichtigsten Befehle sind in `SKILL.md` (`## Monitoring und Reporting`)
verlinkt.

## 9. Erweiterung

Wenn du den Skill erweitern willst (z. B. um eine neue Preflight-Phase
oder einen anderen Scheduler):

1. Helper in `.agents/skills/run-overnight/helpers/` ergänzen oder
   anpassen.
2. Den `run_overnight.py`-Aufruf in `helpers/run_overnight.sh`
   nachziehen, damit Wrapper und Script synchron bleiben.
3. Beispiel unter `examples/` ergänzen.
4. Tests in `tests/` anpassen (`test_skill_artifacts.py`,
   `test_helpers.py`, `test_skill_workflow.py`).
5. Diese Doku im passenden Abschnitt aktualisieren.
