# Beispiel 03 — Einzelnes Issue über Nacht

Manchmal hängt ein einzelnes Issue fest: vielleicht hat ein vorheriger
Solver-Lauf gemischte Änderungen erzeugt, der Branch wurde nie gepusht
oder du willst die Wirkung eines neuen Modells auf ein konkretes Issue
beobachten. In diesen Fällen lohnt sich ein gezielter Nachtlauf mit
`--repo` und `--issue`.

## Voraussetzungen

- `codex`-Binary im PATH.
- `GITHUB_TOKEN` und `GITHUB_USER` in `config/.env`.
- Issue #42 in `myrepo` ist offen.

## Aufruf

```bash
python scripts/run_overnight.py \
    --model codex \
    --repo myrepo \
    --issue 42 \
    --workers 1
```

Mit dem Skill-Wrapper:

```bash
bash .agents/skills/run-overnight/helpers/run_overnight.sh \
    --model codex \
    --repo myrepo \
    --issue 42 \
    --workers 1
```

## Erwarteter Verlauf

1. **Preflight** — wie im Standardlauf (Pull, Tests, Congestion-Check).
2. **Batch** — `solve_issues_batch.py` mit `--repo myrepo --issue 42
   --workers 1`. Es wird genau **ein** Issue bearbeitet.
3. **Dashboard** — `status-dashboard.html` zeigt den einzelnen Run
   prominent.
4. **Summary** — `summary.txt` enthält einen Eintrag unter
   `issue_outcomes:` mit PR-URL, Branch und ggf. Warnungsmarkern.

## Mehrere Issues

Du kannst `--issue` mehrfach angeben:

```bash
python scripts/run_overnight.py \
    --model codex \
    --repo myrepo \
    --issue 42 --issue 43 --issue 44 \
    --workers 2
```

`run_overnight.py` leitet alle Issue-Nummern als wiederholtes `--issue`
an `solve_issues_batch.py` weiter.

## Diagnose

```bash
bash .agents/skills/run-overnight/helpers/summary_check.sh --latest --issues-only
```

Damit werden nur die Issue-Outcomes der jüngsten Session angezeigt —
ideal, um morgens die PR-URLs schnell einzusammeln.
