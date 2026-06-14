---
name: run-overnight
description: Use when an ai-issue-solver batch run should execute unattended over night (or any long period) with full preflight checks, log rotation, dashboard refresh, and a final summary. Wraps the python scripts/run_overnight.py pipeline into a reusable Codex Skill that handles scheduling hints, batch execution, monitoring of session logs, and reporting via reports/overnight/<timestamp>/. Trigger on requests like "start an overnight run", "schedule an unattended batch", "watch the overnight summary", or any reference to scripts/run_overnight.py.
---

# Run Overnight

Dieser Skill kapselt den unbeaufsichtigten Nachtlauf aus
`scripts/run_overnight.py` als wiederverwendbaren Codex-Skill. Er übernimmt
Scheduling-Hinweise (launchd / cron / systemd / macOS `caffeinate`), die
Preflight-Kette (Git-Pull, Tests, Workflow-Congestion-Check), die Ausführung
des begrenzten Batch-Solvers, die Regeneration des Status-Dashboards sowie
Monitoring- und Reporting-Hooks.

## Wann einsetzen

Verwende diesen Skill, wenn eines der folgenden Szenarien zutrifft:

- Ein begrenzter Batch soll über Nacht unbeaufsichtigt laufen, ohne dass
  ein Terminal-Watcher nötig ist.
- Du willst morgens eine kompakte Zusammenfassung in
  `reports/overnight/<timestamp>/summary.txt` lesen.
- Du brauchst einen Smoke-Test, der Preflight + leeren Batch ausführt, bevor
  der echte Lauf startet.
- Du willst einen bestehenden, abgebrochenen Overnight-Lauf über den
  `.skills/recovery`-Skill mit den Session-Logs rekonstruieren.
- Du möchtest den Nachtlauf auf einem Mac mit `caffeinate` am Schlafen
  hindern.

Nicht verwenden für einzelne Issue-Solver-Runs (dafür
`.agents/skills/solve-issues`) oder für reine Batch-Planung
(`scripts/plan_issue_batches.py`).

## Voraussetzungen

Bevor der Skill läuft, müssen diese Voraussetzungen erfüllt sein:

| Komponente | Zweck | Pfad/Setup |
|------------|-------|-----------|
| Python ≥ 3.10 | Runner und Solver-Scripts | `requirements.txt` |
| `git` | Pull, Branch, Commit | PATH |
| GitHub PAT | `GITHUB_TOKEN` + `GITHUB_USER` in `config/.env` | siehe `config/config.example.env` |
| Optional `caffeinate` | macOS wach halten | System-Binary (macOS only) |
| Optional `launchd` / `cron` / `systemd` | Scheduling | siehe `## Scheduling` |
| Dashboard-Tools | `status_dashboard.py` | `python scripts/status_dashboard.py --help` |

Sicherheitsregel: Niemals echte Secret-Dateien lesen oder committen
(`.env`, `.env.*`, `config/.env`, `config/.env.*`). Für Konfigurationsbeispiele
ausschließlich `config/config.example.env` oder `.env.example` verwenden.

## Helper Scripts

Der Skill integriert sich in die bestehenden Helfer im Projekt:

| Helper | Zweck |
|--------|-------|
| `scripts/utils.py` | `print_banner`, `print_step`, `print_ok`, `print_err`, `print_warn` |
| `scripts/solve_issues.py` | `MODEL_CONFIGS`, Single-Issue-Solver |
| `scripts/solve_issues_batch.py` | `DEFAULT_WORKERS`, `positive_int`, begrenzter Batch |
| `scripts/status_dashboard.py` | HTML-Dashboard aus `reports/runs/` |
| `scripts/workflow_congestion.py` | Congestion-Check vor dem Batch |

Zusätzlich enthält der Skill eigene, dünnere Helfer unter
`.agents/skills/run-overnight/`:

- `helpers/run_overnight.sh` — kapselt die häufigsten
  `python scripts/run_overnight.py`-Aufrufe.
- `helpers/parse_args.py` — kleiner Python-Validator für die
  wichtigsten Skill-Argumente (Modell, Worker, Issues, Log-Root).
- `helpers/scheduling_hint.sh` — druckt eine passende
  `launchd`-/`cron`-/`systemd`-Vorlage für den aktuellen Lauf.
- `helpers/summary_check.sh` — liest die letzte Session-Summary und
  meldet Erfolg, Fehlschlag oder Hinweise.

## Standardablauf

1. **Argumente prüfen** — mindestens `--model` und (optional)
   `--repo` / `--issue` setzen. Standard-Branch ist `main`, Label
   `ai-generated`, Workers `DEFAULT_WORKERS` aus `solve_issues_batch.py`.
2. **Session-Verzeichnis anlegen** — `create_session_dir` erzeugt
   `reports/overnight/<timestamp>/` (mit Kollisions-Suffix). Jeder Lauf
   bekommt einen eigenen, nicht überschriebenen Ordner.
3. **Optional: `caffeinate`** — auf macOS hält `keep_awake` den Mac
   während des gesamten Laufs wach (deaktivierbar via `--no-caffeinate`).
4. **Git-Pull** — `git pull --ff-only origin <base-branch>`. Bei Fehler
   wird der Batch **nicht** gestartet, Tests und Congestion-Check werden
   übersprungen.
5. **Tests** — Standard: `python -m unittest discover -s tests`. Bei
   Fehler wird der Batch **nicht** gestartet.
6. **Workflow-Congestion-Check** — `solve_issues.py --skip-congestion-check
   --dry-run`. Bei Warnungen wird der Batch trotzdem gestartet (Hinweis
   im Log); bei Fehlern ebenfalls (kein harter Stopp).
7. **Batch-Solver** — `solve_issues_batch.py` mit denselben
   Modell-/Worker-/Label-Argumenten. Logs landen unter
   `reports/runs/<run_id>/`.
8. **Dashboard** — `status_dashboard.py` regeneriert
   `reports/status-dashboard.html` aus den Run-Reports.
9. **Finale Summary** — `write_final_summary` schreibt
   `summary.txt` mit Schritt-Ergebnissen, Issue-Outcomes, PR-URLs,
   Warnungsmarkern und priorisierten Review-Schritten.

Eine ausführliche Beschreibung der Phasen, der Log-Struktur und der
Fehlerklassifikation liegt unter [workflow.md](workflow.md).

## Scheduling

Der Skill ist bewusst scheduling-neutral — du kannst ihn manuell starten,
in `launchd` einplanen oder per `cron` ausführen. `helpers/scheduling_hint.sh`
gibt eine zur Umgebung passende Vorlage aus.

| Umgebung | Empfehlung |
|----------|------------|
| macOS, interaktiv | `bash .agents/skills/run-overnight/helpers/run_overnight.sh --caffeinate --model codex --workers 2` |
| macOS, täglich 02:00 | `launchd` mit `StartCalendarInterval` (siehe Hinweis) |
| Linux-Server, täglich 02:00 | `systemd`-Timer oder `cron` |
| CI / temporär | Manuell in einem Schritt nach `git pull` und `pip install` |

`launchd`-Beispiel:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>de.local.ai-issue-solver.overnight</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>/Pfad/zum/Repo/.agents/skills/run-overnight/helpers/run_overnight.sh</string>
    <string>--model</string><string>codex</string>
    <string>--workers</string><string>2</string>
  </array>
  <key>StartCalendarInterval</key><dict><key>Hour</key><integer>2</integer><key>Minute</key><integer>0</integer></dict>
  <key>StandardOutPath</key><string>/Pfad/zum/Repo/reports/overnight/launchd.out.log</string>
  <key>StandardErrorPath</key><string>/Pfad/zum/Repo/reports/overnight/launchd.err.log</string>
</dict>
</plist>
```

`cron`-Beispiel (Linux, täglich 02:00):

```cron
0 2 * * * cd /Pfad/zum/Repo && /usr/bin/env bash .agents/skills/run-overnight/helpers/run_overnight.sh --model codex --workers 2 >> reports/overnight/cron.log 2>&1
```

`systemd`-Timer-Beispiel liegt unter
[examples/04_scheduling.md](examples/04_scheduling.md).

## Beispiele

Minimale Beispiele liegen unter
[`.agents/skills/run-overnight/examples/`](examples/README.md). Häufige
Aufrufe:

```bash
# Standard-Nachtlauf mit Codex und 2 Workern
python scripts/run_overnight.py --model codex --workers 2

# Nur ein einzelnes Issue über Nacht bearbeiten
python scripts/run_overnight.py --model codex --repo myrepo --issue 42 --workers 1

# macOS wach halten und OpenCode-Modell nutzen
python scripts/run_overnight.py --model opencode --model-name opencode/deepseek-v4-flash-free --workers 2 --caffeinate

# Smoke-Test ohne Worker (Preflight + leere Session)
python scripts/run_overnight.py --model codex --workers 1 --skip-tests --skip-congestion-check --skip-pull
```

Der Skill-Wrapper `helpers/run_overnight.sh` nimmt dieselben Argumente und
normalisiert den Aufruf:

```bash
bash .agents/skills/run-overnight/helpers/run_overnight.sh \
    --model opencode --model-name opencode/deepseek-v4-flash-free --workers 2 --caffeinate
```

## Monitoring und Reporting

| Artefakt | Pfad | Zweck |
|----------|------|-------|
| Session-Log | `reports/overnight/<timestamp>/` | Step-Logs (`pull.log`, `tests.log`, `batch.log`, `dashboard.log`, `caffeinate.log`) |
| Zusammenfassung | `reports/overnight/<timestamp>/summary.txt` | Kompakte Übersicht inkl. Issue-Outcomes |
| Run-Reports | `reports/runs/<run_id>/` | Solver-Output, Health, Resource-Diagnostics |
| Dashboard | `reports/status-dashboard.html` | Visuelle Übersicht aller Runs |

`helpers/summary_check.sh <session_dir>` greift die wichtigsten Felder der
Session-Summary ab und gibt sie in einer Zeile pro Issue zurück (PR-URL,
Status, Warnungsmarker, geänderte Dateien). Damit lässt sich der Skill
auch in andere Skripte einbinden, zum Beispiel in
`scripts/post_merge_cleanup.py`.

Für die Fehlersuche nach einem Absturz sind die Hinweise im
`.skills/recovery`-Skill weiterhin gültig: dort wird Schritt für Schritt
erklärt, wie du aus den Run-Reports und den Session-Logs den Zustand
rekonstruierst.

## Sicherheits- und Geheimnisschutz-Regeln

Diese Regeln werden vom Runner und seinen Helpern durchgesetzt und sind
**nicht** verhandelbar:

- **Repo-relative Pfade**: Verwende ausschließlich Pfade wie
  `scripts/run_overnight.py`. Absolute Worktree-Pfade wie
  `/tmp/ai-solver-xyz/...` werden in den Worker-Prompts entfernt oder
  durch Platzhalter ersetzt.
- **Keine Secret-Dateien lesen oder schreiben**: `.env`, `.env.*`,
  `config/.env`, `config/.env.*` werden vom Runner niemals
  weitergereicht. Konfigurationsbeispiele stammen aus
  `config/config.example.env` oder `.env.example`.
- **macOS `caffeinate`** wird **ausschließlich** mit `-dimsu` gestartet und
  beim Beenden sauber terminiert (`terminate` + 5 s Timeout, danach
  `kill`). Ein Abbruch des Runners killt den `caffeinate`-Prozess
  ebenfalls.
- **Keine Commits/Pushes durch den Worker**: Der Worker schreibt nur
  Dateien. `commit_and_push` und die PR-Erstellung laufen zentral in
  `scripts/solve_issues.py`.

## Test-Workflow

Der Skill liefert einen Test-Workflow unter
[`.agents/skills/run-overnight/tests/`](tests/README.md):

- `tests/test_skill_artifacts.py` — prüft, dass alle erwarteten Dateien
  vorhanden und nicht leer sind.
- `tests/test_helpers.py` — validiert `helpers/parse_args.py` und die
  Bash-Helfer in einer temporären Umgebung.
- `tests/test_skill_workflow.py` — führt einen End-to-End-Smoke-Test
  gegen ein lokales Fake-Repo aus und prüft die Session-Struktur.
- `tests/run_skill_tests.sh` — Convenience-Wrapper für
  `python -m unittest discover` aus dem Skill-Verzeichnis.

Ausführen mit:

```bash
bash .agents/skills/run-overnight/tests/run_skill_tests.sh
```

## Verwandte Skills

- `.agents/skills/solve-issues` — der eigentliche Issue-Solver, der vom
  Batch im Overnight-Lauf aufgerufen wird.
- `.skills/recovery` — Recovery nach abgebrochenen Solver-Runs.
- `.skills/rework` — Gezielte Nacharbeit an generierten PRs.
- `.skills/git-cleanup` — Branch- und PR-Bereinigung nach Merge.

Diese Skills ergänzen den hier beschriebenen Workflow und sollten nach
jedem Nachtlauf in Betracht gezogen werden.
