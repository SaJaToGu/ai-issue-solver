# Beispiel 01 — Standardplan

Erstellt den Standard-Wellenplan für das Default-Repo `ai-issue-solver`
ohne Ausgabe von Batch-Kommandos. Geeignet für eine schnelle Sichtung,
welche Konflikte aktuell im Backlog bestehen.

## Voraussetzungen

- `GITHUB_TOKEN` und `GITHUB_USER` in `config/.env`.
- Offene Issues im Repo `ai-issue-solver`.

## Aufruf

```bash
python scripts/plan_issue_batches.py --repo ai-issue-solver
```

Mit dem Skill-Wrapper:

```bash
bash .skills/plan-issue-batches/helpers/run_plan.sh --repo ai-issue-solver
```

## Erwarteter Verlauf

1. **Config laden** — `GITHUB_TOKEN` und `GITHUB_USER` werden geprüft.
2. **Issues laden** — alle offenen Issues (ohne PRs) werden über die
   GitHub-API geholt.
3. **Touches bestimmen** — pro Issue werden explizite `Touches:`
   -Hinweise, Stichwörter und Fallback-Pfade zusammengeführt.
4. **Wellen planen** — `plan_waves` baut eine konfliktarme Wellenliste.
5. **Plan rendern** — Wellen, Touches und Begründungen werden auf
   stdout ausgegeben.

## Beispielausgabe

```text
Welle 1:
  #60 - Add optional fallback for batch
    Touches: scripts/solve_issues_batch.py, tests/test_solve_issues_batch.py

  #64 - Add local conflict-aware issue scheduler
    Touches: scripts/plan_issue_batches.py, tests/test_plan_issue_batches.py

Welle 2:
  #66 - Show recovered failed runs in dashboard
    Touches: scripts/status_dashboard.py, tests/test_status_dashboard.py
    Grund: getrennt von Welle 1: keine Ueberschneidung in frueheren Wellen
```

## Diagnose

Wenn keine Wellen erscheinen, prüfe:

- `gh issue list --state open --limit 20` — sind Issues vorhanden?
- `python -c "from utils import load_env, require_config_value; ..."` —
  sind Token und User gesetzt?
- `python scripts/plan_issue_batches.py --label <name>` — schränkt
  den Plan auf bestimmte Labels ein.
