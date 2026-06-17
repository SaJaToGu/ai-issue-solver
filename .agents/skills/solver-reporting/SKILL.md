---
name: solver-reporting
description: Use when solver run reports, metrics, health data, provider scorecards, OpenCode runtime diagnostics, or preserved-worktree artifacts need to be inspected, aggregated, summarised, or cleaned up in ai-issue-solver. Wraps the result aggregation, metrics, and reporting workflow from scripts/solver_reporting.py into a single Codex Skill. Trigger on requests like "summarise the last solver runs", "show provider scorecards", "aggregate run reports into a benchmark summary", "diagnose OpenCode runtime errors", "cleanup preserved worktrees", or any reference to scripts/solver_reporting.py.
---

# Solver Reporting

Dieser Skill kapselt das Reporting des Solver-Runs aus
`scripts/solver_reporting.py` als wiederverwendbaren Codex-Skill. Er
übernimmt das Erzeugen und Lesen von Run-Reports, das Aggregieren von
Metriken und Scorecards, das Erkennen von OpenCode-Runtime-Problemen, das
Sichern und Aufräumen von Worktrees sowie das Filtern und Aufbereiten
von Worker-Output.

## Wann einsetzen

Verwende diesen Skill, wenn eines der folgenden Szenarien zutrifft:

- Ein einzelner oder mehrere Run-Reports unter `reports/runs/...` sollen
  ausgewertet oder zusammengefasst werden.
- Provider-Scorecards (Modellauswahl, Fallback, Kosten) sollen für
  Benchmarks oder Dashboards aggregiert werden.
- OpenCode-Runtime-Diagnosen (`wal_checkpoint`, Edit-Loops) sollen aus
  Worker-Outputs gefiltert und dokumentiert werden.
- Preserved Worktrees unter `reports/preserved-worktrees/...` sollen
  inspiziert, dokumentiert oder nach Retention abgelaufen.
- `git_status_porcelain` und `format_git_change_summary` sollen in
  Skripten ohne den vollen Solver-Stack genutzt werden.
- Heartbeat-Zeilen für langlaufende Jobs sollen formatiert werden.

Nicht verwenden für reine Solver-Läufe (`.agents/skills/solve-issues`),
reine Analyse (`analyze_repos.py`) oder Rework eines bestehenden PRs
(`.agents/skills/rework`).

## Voraussetzungen

Bevor der Skill läuft, müssen diese Voraussetzungen erfüllt sein:

| Komponente | Zweck | Pfad/Setup |
|------------|-------|-----------|
| Python ≥ 3.10 | Reporting-Module | `requirements.txt` |
| `git` | Diff-Stat, Status, Branch-Informationen | PATH |
| Run-Reports | Vorhandene `reports/runs/<run_id>/` Verzeichnisse | werden vom Solver angelegt |
| Optional `opencode` | Edit-Loop-Diagnose aus Worker-Output | siehe `docs/SETUP_AIDER.md` |

Sicherheitsregel: Niemals echte Secret-Dateien lesen oder committen
(`.env`, `.env.*`, `config/.env`, `config/.env.*`). Für Konfigurationsbeispiele
ausschließlich `config/config.example.env` oder `.env.example` verwenden.

## Module und Datenstrukturen

Der Skill integriert sich in die bestehenden Reporting-Bausteine:

| Baustein | Zweck |
|----------|-------|
| `scripts/solver_reporting.py` | `create_run_report`, `write_run_report`, `write_run_health`, `format_worker_output_tail`, `detect_opencode_runtime_diagnostics`, `build_run_outcome`, `create_provider_scorecard`, `preserve_worker_worktree`, `cleanup_preserved_worktrees`, `format_heartbeat` |
| `scripts/utils.py` | `clean_path_candidate`, `print_warn` (wird intern verwendet) |
| `scripts/solver_repository.py` | `git_status_porcelain`, `branch_has_changes_against_base`, `git_output` (wird intern verwendet) |
| `reports/runs/<run_id>/` | Ablageort pro Run (summary.txt, metadata.json, health.json, worker-output.log) |
| `reports/preserved-worktrees/<run_id>/<repo>/` | Gesicherter Worktree inkl. `RECOVERY.md` |

Zusätzlich enthält der Skill eigene, dünnere Helfer unter
`.agents/skills/solver-reporting/`:

- `helpers/aggregate_runs.py` — sammelt Run-Reports, aggregiert
  Scorecards und gibt eine Markdown-Tabelle aus.
- `helpers/diagnose_opencode.py` — filtert OpenCode-Runtime-Befunde aus
  einem Worker-Output und gibt sie strukturiert aus.
- `helpers/cleanup_worktrees.sh` — löscht abgelaufene Preserved
  Worktrees (Standard-Retention 14 Tage).
- `helpers/format_heartbeat.py` — Heartbeat-Helfer für Solver-Loops.

## Ergebnis-Aggregation

Der Skill liefert drei übliche Aggregations-Perspektiven:

| Perspektive | Eingabe | Ausgabe |
|-------------|---------|---------|
| **Run-Liste** | `reports/runs/*/metadata.json` | Tabelle mit Status, Repo, Issue, Branch, Modell, Exit-Code, PR-URL |
| **Provider-Scorecard** | `metadata.json.provider_scorecard` | Tabelle mit requested/actual_model, Fallback, Dauer, Test-Result, Kosten |
| **Run-Outcome** | `metadata.json.run_outcome` | Verteilung von `worker_status`, `delivery_status`, `failure_class`, `recovery_status` |

`build_run_outcome` übersetzt einen rohen `status`-String plus
`worker_result`, `pr_url`, `preserved_worktree_path` und
`git_change_summary` in ein einheitliches Schema mit sechs Feldern
(`worker_status`, `has_changes`, `test_status`, `delivery_status`,
`failure_class`, `recovery_status`), das von Dashboard, Benchmark und
`.agents/skills/recovery` ausgewertet wird.

## Metriken und Scorecards

Jeder Run-Report enthält in `metadata.json` einen Block
`provider_scorecard` mit folgenden Feldern:

| Feld | Quelle | Beispiel |
|------|--------|----------|
| `requested_model` | `model_selection_metadata.model` | `mistral/mistral-large-latest` |
| `actual_model` | `report.model` + `model_name` | `mistral/mistral-medium-latest` |
| `fallback_source` | `model_selection_metadata.fallback_from` | `claude/claude-sonnet-4-20250514` |
| `duration_seconds` | `worker_result.duration_seconds` | `120.5` |
| `worker_exit_code` | `worker_result.returncode` | `0` |
| `run_status` | solver-Status-String | `pr_created` |
| `pr_url` | PR-URL oder leer | `https://github.com/owner/repo/pull/123` |
| `test_command` | optionaler Test-Befehl | `pytest tests/` |
| `test_result` | Test-Ergebnis-String | `passed` |
| `no_change` | abgeleitet aus `status` | `false` |
| `fallback_used` | abgeleitet aus `fallback_source` | `true` |
| `estimated_cost` | `model_selection_metadata.estimated_cost` | `0.15` |
| `cost_currency` | `model_selection_metadata.cost_currency` | `USD` |
| `cost_confidence` | `model_selection_metadata.cost_confidence` | `high` |
| `cost_source` | `model_selection_metadata.cost_source` | `provider_api` |

Für Aggregationen siehe [examples/03_aggregate_scorecards.md](examples/03_aggregate_scorecards.md).

## OpenCode-Runtime-Diagnose

`detect_opencode_runtime_diagnostics(output)` scannt einen
Worker-Output nach zwei bekannten Problemen:

- **SQLite/WAL-Fehler** — `PRAGMA wal_checkpoint(PASSIVE)`,
  `journal_mode = WAL`. Recovery: OpenCode-Prozesse beenden, nur
  `opencode.db-wal` und `opencode.db-shm` entfernen, **niemals**
  `auth.json` oder `opencode.db` löschen.
- **Edit-Loop** — ab `OPENCODE_EDIT_FAILURE_REPEAT_THRESHOLD = 3`
  fehlgeschlagenen `Edit <file> failed`-Versuchen werden Datei und
  Anzahl gemeldet.

Ausgabe als `OpenCodeRuntimeDiagnostics`-Dataclass mit den Feldern
`wal_failure`, `edit_loop`, `edit_failure_count`, `edit_failure_files`
und einer `has_findings`-Property. `opencode_runtime_diagnostic_lines`
rendert daraus menschenlesbare Empfehlungen.

## Worker-Output-Filter

Live-Ausgabe des Workers wird über `should_surface_worker_line(line)`
gefiltert. Drei Regex-Klassen steuern das Verhalten:

- `WORKER_LIVE_OUTPUT_RE` — behält Zeilen mit Schlüsselwörtern
  (`task`, `plan`, `warn`, `error`, `failed`, `done`, `commit`, `test`,
  `read`, `write`, `edit`, …) und Strukturmuster (`===`, `##`,
  `→ ✓ ✗ •`).
- `WORKER_NOISY_OUTPUT_RE` — verwirft Diff-Blöcke (`diff --git`,
  `@@ `, `+/-`-Zeilen) und Shell-Commands.
- `WORKER_NOISY_FRAGMENT_RE` — verwirft Code-Fragmente
  (Variablenzuweisungen, `assert*`-Aufrufe, Dictionary-Keys).

`format_worker_output_tail(output)` behält maximal die letzten
`WORKER_OUTPUT_TAIL_LINES = 25` Zeilen und kürzt auf
`WORKER_OUTPUT_TAIL_CHARS = 4000` Zeichen.

## Git-Änderungsübersicht

`format_git_change_summary(repo_dir, git_status)` baut eine kompakte
Liste aus `git diff --stat HEAD` und nicht-getrackten Dateien. Konfig:

| Konstante | Wert | Bedeutung |
|-----------|------|-----------|
| `GIT_SUMMARY_MAX_STATUS_LINES` | 20 | Wie viele Pfade maximal ohne `git diff --stat` gezeigt werden |
| `GIT_SUMMARY_MAX_STAT_LINES` | 12 | Wie viele Diff-Stat-Zeilen in der Zusammenfassung stehen |
| `GIT_SUMMARY_STAT_GRAPH_WIDTH` | 30 | Maximale `+`-Anzahl pro Datei in der Untracked-Übersicht |

`print_git_change_summary` gibt die Liste eingerückt auf stdout aus.

## Preserved Worktrees

Bei Status-Codes in `PRESERVE_WORKTREE_STATUSES` (z. B. `push_failed`,
`pr_failed`, `validation_failed`, `rate_limit_deferred`) und vorhandenen
Änderungen wird der Worktree nach
`reports/preserved-worktrees/<run_id>/<repo>/` verschoben und ein
`RECOVERY.md` mit manueller Anleitung geschrieben.

Recovery-Schritte im README:

```bash
cd reports/preserved-worktrees/<run_id>/<repo>
git status --short
git diff --stat origin/<base>...HEAD
git push origin HEAD:<branch>
# Danach PR manuell erstellen oder den Solver erneut starten.
```

Cleanup mit Retention (`cleanup_preserved_worktrees`):

```bash
python scripts/solve_issues.py --cleanup-preserved-worktrees \
    --retention-days 14 --apply
```

`PRESERVED_WORKTREE_RETENTION_DAYS = 14` ist der Standard.

## Run-Status-Werte

`build_run_outcome` und `write_run_report` verwenden die folgenden
`status`-Strings konsistent:

| Status | Bedeutung | Delivery-Status |
|--------|-----------|-----------------|
| `pr_created` | PR erfolgreich erstellt | `pr_created` |
| `pr_created_with_warning` | Vibe-Turn-Limit erreicht, PR offen | `pr_created` |
| `pr_created_from_existing_branch` | `--continue-run`, vorhandene Änderungen genutzt | `pr_created` |
| `pr_skipped` | `--skip-pr` (Benchmark-Modus) | `pushed_without_pr` / `not_applicable` |
| `pr_failed` | PR-API-Aufruf fehlgeschlagen | `pr_failed` |
| `push_failed` | Commit/Push fehlgeschlagen | `push_failed` |
| `validation_failed` | Syntax/Schreibrechte/Konfliktmarker | `incomplete` |
| `no_changes` | Worker ohne Änderungen beendet | `not_applicable` |
| `nonzero_with_changes` | Worker-Fehler, aber Änderungen da | `incomplete` |
| `nonzero_without_changes` | Worker-Fehler ohne Änderungen | `incomplete` |
| `rate_limit_deferred` | Codex-Rate-Limit erreicht | `incomplete` |
| `started` | Initialer Zustand, kein Worker-Output | `incomplete` |
| `skip_existing_pr` / `skip_merged_pr` / `skip_closed_pr` | Recovery-Skip | `not_applicable` |

## Heartbeat

`format_heartbeat(issue_number, elapsed_seconds, job_label=None,
width=None)` erzeugt kompakte, phone-freundliche Zeilen wie
`#223 PR2 ....+....+....+.. 17min`.

- Progress-Marker: alle 5 Zeichen ein `+`, dazwischen `.`.
- Breite wächst mit `elapsed_minutes // 2` (mindestens 1).
- Suffix ist `Nmin` mit den abgerundeten Minuten.

`format_heartbeat_progress(elapsed_seconds, width=None)` liefert nur
den Progress-String ohne Issue-Präfix.

## Beispiele

Minimale Beispiele liegen unter
[`.agents/skills/solver-reporting/examples/`](examples/README.md).
Häufige Aufrufe:

```bash
# Aktuelle Run-Reports aggregieren (Markdown-Tabelle)
python .agents/skills/solver-reporting/helpers/aggregate_runs.py \
    --reports-dir reports/runs --format markdown

# OpenCode-Runtime-Diagnose für einen Worker-Output
python .agents/skills/solver-reporting/helpers/diagnose_opencode.py \
    --worker-output reports/runs/<run_id>/worker-output.log

# Abgelaufene Preserved Worktrees aufräumen (Dry-Run, Retention 14 Tage)
bash .agents/skills/solver-reporting/helpers/cleanup_worktrees.sh --retention-days 14

# Heartbeat-Zeile für einen laufenden Solver-Job
python .agents/skills/solver-reporting/helpers/format_heartbeat.py \
    --issue 223 --elapsed-seconds 1020 --job-label PR2
```

## Sicherheits- und Geheimnisschutz-Regeln

- **Repo-relative Pfade**: Verwende ausschließlich Pfade wie
  `scripts/datei.py`. Absolute Worktree-Pfade wie `/tmp/ai-solver-xyz/...`
  werden in `clean_path_candidate` ersetzt.
- **Keine Secret-Dateien lesen oder schreiben**: Die Reporting-Helfer
  lesen ausschließlich `metadata.json`, `summary.txt`, `health.json`,
  `worker-output.log` und `RECOVERY.md` aus `reports/`. Sie berühren
  niemals `.env`, `.env.*`, `config/.env`, `config/.env.*`.
- **Keine destruktiven Schreiboperationen ohne Bestätigung**:
  `cleanup_preserved_worktrees` läuft standardmäßig als
  `dry_run=True` und gibt nur die Kandidatenpfade aus.

## Test-Workflow

Der Skill liefert einen Test-Workflow unter
[`.agents/skills/solver-reporting/tests/`](tests/README.md):

- `tests/test_skill_artifacts.py` — prüft, dass alle erwarteten
  Dateien vorhanden und nicht leer sind.
- `tests/test_helpers.py` — validiert `aggregate_runs.py`,
  `diagnose_opencode.py` und `cleanup_worktrees.sh` mit synthetischen
  Run-Report-Verzeichnissen.
- `tests/test_skill_workflow.py` — importiert `solver_reporting` und
  prüft, dass die Kernbausteine (`create_run_report`,
  `build_run_outcome`, `detect_opencode_runtime_diagnostics`,
  `create_provider_scorecard`) korrekt funktionieren.
- `tests/run_skill_tests.sh` — Convenience-Wrapper für
  `python -m unittest discover` aus dem Skill-Verzeichnis.

Ausführen mit:

```bash
bash .agents/skills/solver-reporting/tests/run_skill_tests.sh
```

## Verwandte Skills

- `.agents/skills/solve-issues` — erzeugt die Run-Reports, die dieser
  Skill aggregiert.
- `.agents/skills/recovery` — inspiziert einzelne Run-Report-Artefakte und
  empfiehlt Resume / Push / Retry / Delete.
- `.agents/skills/rework` — zielt auf gezielte Nacharbeit an generierten PRs.
- `.agents/skills/git-cleanup` — löscht gemergte AI-Branches.

Diese Skills ergänzen den hier beschriebenen Reporting-Workflow.
