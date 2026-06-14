# Solver-Reporting — Workflow-Dokumentation

Diese Dokumentation beschreibt den vollständigen Reporting-Workflow, den
der `solver-reporting`-Skill abdeckt. Sie ergänzt die kompakte
Beschreibung in `SKILL.md` und dient als Referenz beim Debugging, beim
Schreiben eigener Helper oder beim Audit von Solver-Runs.

## 1. Überblick

Der Skill bündelt alle Reporting-Aufgaben, die bisher direkt in
`scripts/solver_reporting.py` leben:

1. **Run-Report-Erzeugung** — `create_run_report`, `write_run_report`,
   `write_run_health`.
2. **Metriken und Scorecards** — `create_provider_scorecard`,
   `build_run_outcome`, `infer_test_status`.
3. **Worker-Output-Aufbereitung** — `should_surface_worker_line`,
   `format_worker_output_tail`, `print_git_change_summary`.
4. **OpenCode-Runtime-Diagnose** —
   `detect_opencode_runtime_diagnostics`,
   `opencode_runtime_diagnostic_lines`.
5. **Preserved Worktrees** — `should_preserve_worktree`,
   `preserve_worker_worktree`, `cleanup_preserved_worktrees`,
   `write_preserved_worktree_readme`.
6. **Heartbeat** — `format_heartbeat`, `format_heartbeat_progress`.

Jeder dieser Bereiche wird durch eigene Helper (`helpers/`) und Tests
(`tests/`) ergänzt.

## 2. Run-Report-Lifecycle

Ein Run-Report wird in drei Phasen geschrieben:

| Phase | Funktion | Datei | Trigger |
|-------|----------|-------|---------|
| Initialisierung | `create_run_report` | `reports/runs/<run_id>/` (Verzeichnis) | Solver-Start |
| Laufende Updates | `write_run_health` | `health.json`, `output-tail.log` | Jede Phase, jeder Worker-Tick |
| Abschluss | `write_run_report` | `summary.txt`, `metadata.json`, `worker-output.log` | Nach Assessment / Validation / PR-Versuch |

`<run_id>` ist standardmäßig
`<YYYYMMDD-HHMMSS-ffffff>-<safe_repo>-issue-<N>`. `safe_run_repo_name`
bereinigt den Repo-Namen auf `[A-Za-z0-9_.-]+` und fällt auf `repo`
zurück, falls nichts übrig bleibt.

`create_run_report` setzt `exist_ok=True`, wenn ein `run_dir` explizit
übergeben wird (Resume / Retry). Andernfalls wird strikt ein neues
Verzeichnis angelegt, damit keine alten Reports überschrieben werden.

## 3. health.json

`write_run_health` schreibt regelmäßig ein leichtgewichtiges
Status-Dokument:

```json
{
  "status": "running",
  "phase": "worker_running",
  "last_activity_at": "2026-06-14T15:30:00",
  "last_report_update_at": "2026-06-14T15:30:01",
  "output_tail": "...",
  "process": {
    "runner_pid": 12345,
    "parent_pid": 12340,
    "worker_pid": 12350
  },
  "opencode_runtime": {
    "wal_failure": false,
    "edit_loop": false,
    "edit_failure_count": 0,
    "edit_failure_files": [],
    "diagnostic_lines": []
  }
}
```

`status` durchläuft `"started" → "running" → <terminaler Status>`.
`phase` spiegelt die Phasen aus `.agents/skills/solve-issues`
(`preflight`, `congestion`, `clone`, `worker_running`, `validating`,
`committing`, `creating_pr`).

## 4. metadata.json

`write_run_report` baut ein umfangreiches `metadata.json`. Top-Level-
Felder:

| Feld | Quelle | Beispiel |
|------|--------|----------|
| `status` | solver-Status | `pr_created` |
| `selected_repo` / `repo` | `report.repo` | `BedBoxDrawerRole` |
| `issue_number` / `issue` | `report.issue_number` | `3` |
| `issue_title` | `report.issue_title` | `Readme fehlt` |
| `branch` | `report.branch` | `ai/fix-issue-3` |
| `model` | `report.model` | `opencode` |
| `worker_exit_code` | `worker_result.returncode` | `0` |
| `last_activity_at` | `worker_result.last_activity_at` | `2026-06-14T15:35:42` |
| `last_report_update_at` | jetzt | `2026-06-14T15:36:00` |
| `pr_url` | PR-URL oder leer | `https://github.com/.../pull/123` |
| `note` | optionaler Hinweis | `existing branch reused` |
| `preserved_worktree` | Pfad oder leer | `reports/preserved-worktrees/...` |
| `cleanup_command` | abgeleitet aus `preserved_worktree` | `python scripts/solve_issues.py --cleanup-preserved-worktrees --retention-days 14` |
| `git_change_summary` | Liste von Diff-Stat-Zeilen | `["Git-Änderungsübersicht:", "  README.md | 1 +"]` |
| `vibe_log_snippet` | (nur Mistral Vibe) Snippet | `...` |
| `opencode_runtime` | Diagnose-Dict | siehe unten |
| `resource_diagnostics` | `ResourceDiagnostics.to_report_dict()` | `{...}` |
| `run_outcome` | `build_run_outcome(...)` | siehe unten |
| `model_selection` | `model_selection_metadata` | `{model, reason, category, risk, cost_tier, fallback_plan, ...}` |
| `rework` | optional | `{rework_of, rework_reason, subtask_id, supersedes_pr, follow_up_issue}` |
| `opencode_session` | optional | `{total_cost, total_tokens_*, budget_exceeded}` |
| `provider_scorecard` | `create_provider_scorecard(...)` | siehe unten |

### 4.1 opencode_runtime

| Feld | Typ | Quelle |
|------|-----|--------|
| `wal_failure` | `bool` | `OPENCODE_WAL_FAILURE_RE` in Worker-Output |
| `edit_loop` | `bool` | `len(edit_failures) >= 3` |
| `edit_failure_count` | `int` | Anzahl `Edit <file> failed`-Vorkommen |
| `edit_failure_files` | `list[str]` | eindeutige Dateipfade |
| `diagnostic_lines` | `list[str]` | menschenlesbare Empfehlungen |

### 4.2 run_outcome

`build_run_outcome` aggregiert sechs Felder:

| Feld | Mögliche Werte |
|------|----------------|
| `worker_status` | `not_started`, `succeeded`, `failed` |
| `has_changes` | `bool` |
| `test_status` | `passed`, `failed`, `unknown` |
| `delivery_status` | `pr_created`, `pr_failed`, `push_failed`, `pushed_without_pr`, `not_applicable`, `incomplete`, `unknown` |
| `failure_class` | `success`, `noop`, `pipeline_failure`, `model_failure`, `validation_failure`, `runtime_failure`, `interrupted`, `unknown` |
| `recovery_status` | `none`, `preserved_worktree`, `retry_clean`, `manual_review` |

`failure_class` wird in dieser Priorität bestimmt:

1. `status in NO_CHANGE_STATUSES` → `noop`
2. `pr_url` oder `status.startswith("pr_created")` → `success`
3. `status == "pr_skipped"` → `success` (mit Änderungen) oder `noop`
4. `status in PIPELINE_FAILURE_STATUSES and (has_changes or preserved)` → `pipeline_failure`
5. `worker_result.returncode != 0 and not has_changes` → `model_failure`
6. `status == "validation_failed"` → `validation_failure`
7. `status == "started"` → `interrupted`
8. `status.endswith("_failed")` → `pipeline_failure` oder `runtime_failure`

### 4.3 provider_scorecard

Siehe `SKILL.md` (`## Metriken und Scorecards`). Wird in `summary.txt`
mit den Präfix-Feldern `provider_scorecard_*` zeilenweise gespiegelt,
damit Grep-basierte Auswertungen funktionieren.

## 5. summary.txt

`write_run_report` baut `summary.txt` aus den `summary_lines`:

1. `status:`, `repo:`, `issue:`, `issue_title:`, `branch:`, `model:`,
   `worker_exit_code:`, `last_activity_at:`, `last_report_update_at:`,
   `pr_url:`, `preserved_worktree:`.
2. Sechs `run_outcome_*`-Zeilen.
3. 15 `provider_scorecard_*`-Zeilen.
4. `rework_*`-Zeilen.
5. Optional `model_selection:`-Block.
6. Optional `cleanup_command:` und Preserved-Worktree-Recovery-Block.
7. Optional `note:`, Hinweis auf `worker-output.log`, `git_diff_stat:`,
   `opencode_runtime:`, `opencode_session:`, `output_tail:`,
   `vibe_log_snippet:`, Resource-Diagnose-Summary.

Diese Klartext-Repräsentation ist die Grundlage für den
`.skills/recovery`-Skill und das lokale HTML-Dashboard
(`scripts/status_dashboard.py`).

## 6. Preserved Worktrees

`should_preserve_worktree` ist `True`, wenn `status in
PRESERVE_WORKTREE_STATUSES` und entweder `changes_exist` oder
`worktree_has_recoverable_changes(repo_dir, base_branch)` zutrifft.

```python
PRESERVE_WORKTREE_STATUSES = {
    "nonzero_without_changes",
    "pr_failed",
    "pr_failed_from_existing_branch",
    "push_failed",
    "rate_limit_deferred",
    "validation_failed",
}
```

`preserve_worker_worktree`:

1. Bestimmt einen eindeutigen Zielpfad
   `reports/preserved-worktrees/<run_id>/<repo>[-N]`.
2. Setzt `origin` auf die öffentliche URL
   `https://github.com/<owner>/<repo>.git` zurück und entfernt
   `remote.origin.pushurl`.
3. Verschiebt das Working-Tree mit `shutil.move`.
4. Schreibt `RECOVERY.md` mit manuellen Schritten.
5. Gibt den finalen Pfad zurück.

`sanitize_preserved_remote` ist eine reine Vorbereitungsfunktion und
führt `git remote set-url` plus `git config --unset-all
remote.origin.pushurl` aus.

`write_preserved_worktree_readme` schreibt das `RECOVERY.md` mit den
Schritten `cd`, `git status`, `git diff --stat`, `git push`, manuelle
PR-Erstellung und einem `cleanup_command`-Block.

`cleanup_preserved_worktrees(root, retention_days, dry_run=True)` löscht
Verzeichnisse älter als `retention_days` (Standard 14 Tage). Ohne
`--apply` ist der Aufruf ein Dry-Run.

## 7. Beobachtbarkeit und Metriken

### 7.1 Run-Health-Stream

`write_run_health` wird vom Solver regelmäßig aufgerufen, damit
Dashboard und `.skills/recovery` einen laufenden Run verfolgen können.
Felder siehe `## 3. health.json`.

### 7.2 OpenCode-Session-Metriken

`opencode_session_metrics` fließt direkt in `metadata.json` unter
`opencode_session`. Erwartete Felder:

| Feld | Bedeutung |
|------|-----------|
| `total_cost` | Gesamt-Kosten in USD (oder Modellwährung) |
| `total_tokens_input` | Summe Input-Tokens |
| `total_tokens_output` | Summe Output-Tokens |
| `total_tokens_reasoning` | Summe Reasoning-Tokens |
| `total_tokens_cache_read` | Cache-Reads |
| `total_tokens_cache_write` | Cache-Writes |
| `budget_exceeded` | `True`, wenn das Budget-Limit überschritten wurde |

In `summary.txt` werden diese Felder unter `opencode_session:` mit
zwei Leerzeichen Einrückung gespiegelt.

### 7.3 Resource-Diagnostik

`resource_diagnostics` ist optional. `solver_run_resources.py` liefert
Lock- und Branch-Konflikt-Informationen. Sie landen unter
`metadata.json.resource_diagnostics` und in `summary.txt` nur bei
`has_findings`.

## 8. Aggregation

`helpers/aggregate_runs.py` liest mehrere Run-Verzeichnisse und
erzeugt:

- **Run-Liste** (`--format markdown|tsv|json`).
- **Scorecard-Tabelle** mit `requested_model`, `actual_model`,
  `fallback_source`, `duration_seconds`, `test_result`, `cost_*`.
- **Outcome-Histogramm** mit `worker_status`, `delivery_status`,
  `failure_class`, `recovery_status`.

Beispiel siehe [examples/03_aggregate_scorecards.md](examples/03_aggregate_scorecards.md).

## 9. Fehlerklassifikation und Recovery-Brücke

`build_run_outcome` und `.skills/recovery` teilen die folgende Brücke:

| `failure_class` | Empfehlung Recovery-Skill |
|-----------------|---------------------------|
| `success` | keine Aktion |
| `noop` | `manual-review` oder `retry-clean` (je nach Status) |
| `pipeline_failure` + `preserved` | `preserved_worktree` |
| `model_failure` | `retry-clean` |
| `validation_failure` | `manual-review` |
| `interrupted` | `retry-clean` |
| `runtime_failure` | `retry-clean` |

## 10. Erweiterung

Wenn ein neues Reporting-Feld ergänzt werden soll:

1. Neue Funktion in `scripts/solver_reporting.py` definieren.
2. Falls relevant für `metadata.json`: in `write_run_report` zum
   `metadata`-Dict und zu `summary_lines` hinzufügen.
3. Bei Scorecard-Feldern: `ProviderScorecard` erweitern und in
   `create_provider_scorecard` befüllen.
4. Optional Helper im Skill (`helpers/`) und Tests (`tests/`)
   ergänzen.
5. Diese Doku in den passenden Abschnitten aktualisieren.
