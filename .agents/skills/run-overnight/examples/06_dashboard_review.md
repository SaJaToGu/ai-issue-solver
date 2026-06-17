# Beispiel 06 — Dashboard und Session-Summary prüfen

Nach einem Overnight-Lauf willst du morgens in unter einer Minute wissen,
was passiert ist. Dafür liefert der Skill zwei Anlaufpunkte:

1. `reports/overnight/<session>/summary.txt` — kompakte Text-Summary
   pro Session.
2. `reports/status-dashboard.html` — visuelles Dashboard mit allen
   Run-Reports aus `reports/runs/`.

## Session-Summary lesen

```bash
bash .agents/skills/run-overnight/helpers/summary_check.sh --latest
```

Ausgabe (gekürzt):

```
=== Overnight-Session: reports/overnight/20260614-020000 ===
Status:    successful
Started:   2026-06-14T02:00:00
Finished:  2026-06-14T05:31:12
Duration:  3h 31m 12s

--- Schritte ---
- name: pull
  status: ok
  duration: 4s
- name: tests
  status: ok
  duration: 1m 12s
- name: workflow_congestion
  status: ok
  duration: 12s
- name: batch
  status: ok
  duration: 3h 24m
- name: dashboard
  status: ok
  duration: 6s

--- Issue-Outcomes (4) ---
- issue: 12
  repo: myrepo
  title: Add smoke test for solver
  status: pr_created
  category: successful
  worker_exit_code: 0
  pr_url: https://github.com/me/myrepo/pull/45
  changed_files: tests/test_solver.py
  branch: ai/fix-issue-12
  model: codex
  run_dir: 20260614-020000-abc12
...
```

Eine bestimmte Session inspizieren:

```bash
bash .agents/skills/run-overnight/helpers/summary_check.sh \
    reports/overnight/20260614-020000
```

Nur die Issue-Outcomes:

```bash
bash .agents/skills/run-overnight/helpers/summary_check.sh \
    --latest --issues-only
```

## Dashboard ansehen

```bash
python scripts/serve_dashboard.py \
    --reports-dir reports \
    --port 8765
```

Danach `http://localhost:8765/` im Browser öffnen. Das Dashboard zeigt
alle Run-Reports aus `reports/runs/`, gruppiert nach Status
(`successful`, `failed`, `noop`, `archived`, `unknown`) und mit Health-
und Resource-Diagnostik pro Run.

## Step-Logs

Für eine tiefergehende Analyse:

```bash
# Welche Schritte sind gelaufen?
ls reports/overnight/<session>/

# Letzte 100 Zeilen des Batch-Logs
tail -n 100 reports/overnight/<session>/batch.log

# Fehlgeschlagene Phasen
grep -A 1 'status: failed' reports/overnight/<session>/summary.txt
```

## Integration in andere Skripte

`summary_check.sh` ist auch maschinenlesbar: der Exit-Code ist `0` für
erfolgreiche Sessions, `1` für fehlgeschlagene, `3` für nicht
abgeschlossene. Damit kannst du den Skill in eigene Automation einbinden,
zum Beispiel in `scripts/post_merge_cleanup.py` als Vorprüfung.

```bash
if bash .agents/skills/run-overnight/helpers/summary_check.sh --latest; then
    echo "Letzter Lauf war erfolgreich"
else
    case $? in
      1) echo "Letzter Lauf hatte Fehler — bitte prüfen" ;;
      3) echo "Letzter Lauf nicht abgeschlossen" ;;
    esac
fi
```

## Verwandte Skills

- `.agents/skills/recovery` — wenn einzelne Runs Recovery brauchen.
- `.agents/skills/rework` — wenn die erzeugten PRs nachgearbeitet werden müssen.
- `.agents/skills/git-cleanup` — nach erfolgreichem Merge der AI-PRs.
