# Beispiel 01 — Smoke-Test ohne Worker

`run_overnight.py` lässt sich auch ohne echte KI-Worker ausführen, um die
Preflight-Kette und die Session-Struktur zu prüfen. Das ist sinnvoll, wenn
du eine neue Maschine initial einrichtest, das Scheduling gerade umstellst
oder schlicht die Konfiguration validieren willst.

## Voraussetzungen

- `config/.env` ist befüllt (`GITHUB_TOKEN`, `GITHUB_USER`).
- Optional: ein Worker-Binary im PATH, wenn `--model` gesetzt ist.

## Aufruf

```bash
bash .agents/skills/run-overnight/helpers/run_overnight.sh \
    --model codex \
    --workers 1 \
    --skip-pull \
    --skip-tests \
    --skip-congestion-check
```

Mit dem reinen Python-Script:

```bash
python scripts/run_overnight.py \
    --model codex \
    --workers 1 \
    --skip-pull \
    --skip-tests \
    --skip-congestion-check
```

## Erwarteter Verlauf

1. **Session-Verzeichnis** — `reports/overnight/<timestamp>/` wird
   angelegt.
2. **`pull.log`** — enthält `skipped: --skip-pull`.
3. **`tests.log`** — enthält `skipped: --skip-tests`.
4. **`workflow_congestion.log`** — enthält `skipped: --skip-congestion-check`.
5. **`batch.log`** — `solve_issues_batch.py` läuft mit `--workers 1`,
   findet ggf. keine offenen Issues und endet schnell.
6. **`dashboard.log`** — `status_dashboard.py` regeneriert
   `reports/status-dashboard.html`.
7. **`summary.txt`** — listet alle Schritte als `ok` oder `skipped`.

## Diagnose

```bash
bash .agents/skills/run-overnight/helpers/summary_check.sh --latest
```

Erwartete Ausgabe (gekürzt):

```
=== Overnight-Session: reports/overnight/20260614-020000 ===
Status:    successful
Started:   2026-06-14T02:00:00
Finished:  2026-06-14T02:00:30
Duration:  30s

--- Schritte ---
- name: pull
  status: skipped
  duration: 0s
- name: tests
  status: skipped
  duration: 0s
- name: workflow_congestion
  status: skipped
  duration: 0s
- name: batch
  status: ok
  duration: 25s
- name: dashboard
  status: ok
  duration: 5s
```

## Anwendungsfälle

- Erstkonfiguration einer neuen Maschine.
- CI-Smoke-Test vor dem ersten echten Lauf.
- Nach Konfigurationsänderungen (`config/.env` neu befüllt).
