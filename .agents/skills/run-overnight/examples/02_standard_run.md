# Beispiel 02 — Standard-Nachtlauf mit Codex

Der Standardfall: alle erreichbaren Repos mit `ai-generated`-Issues werden
mit Codex bearbeitet. Zwei parallele Worker, vollständige Preflight-Kette,
Dashboard-Refresh und finale Summary.

## Voraussetzungen

- `codex`-Binary im PATH (Codex Desktop oder `codex-cli`).
- `GITHUB_TOKEN` und `GITHUB_USER` in `config/.env`.
- `reports/overnight/` ist beschreibbar.

## Aufruf

```bash
python scripts/run_overnight.py \
    --model codex \
    --workers 2 \
    --base-branch main \
    --label ai-generated
```

Mit dem Skill-Wrapper:

```bash
bash .agents/skills/run-overnight/helpers/run_overnight.sh \
    --model codex \
    --workers 2
```

## Erwarteter Verlauf

1. **Session-Verzeichnis** — `reports/overnight/<timestamp>/`.
2. **`pull.log`** — `git pull --ff-only origin main` mit Exit 0.
3. **`tests.log`** — `python -m unittest discover -s tests`.
4. **`workflow_congestion.log`** — Dry-Run-Solver für Congestion-Check.
5. **`batch.log`** — `solve_issues_batch.py` mit 2 Workern. Run-Reports
   landen in `reports/runs/<run_id>/`.
6. **`dashboard.log`** — `reports/status-dashboard.html` aktualisiert.
7. **`summary.txt`** — listet alle Schritte plus Issue-Outcomes.

## Verwandte Optionen

- `--fallback-model opencode` — fällt bei Codex-Rate-Limits auf
  OpenCode zurück.
- `--worker-health-timeout-minutes 30` — Warnung, wenn ein Worker länger
  als 30 Minuten ohne Output ist.
- `--unhealthy-action stop` — bricht den Batch ab, sobald ein Worker als
  unhealthy erkannt wird.
- `--unhealthy-retries 2` — versucht einen unhealthy Job bis zu zweimal
  erneut.
- `--verbosity verbose` — druckt die volle Worker-Ausgabe.

## Empfehlung

Plane den ersten Lauf mit `--skip-tests` oder einem leichten Repo, damit
du das Verhalten von `caffeinate`, `launchd` und der `summary.txt`
kennenlernst, bevor du einen vollen Batch anstößt.
