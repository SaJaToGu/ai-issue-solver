# Beispiel 03 — Dry-Run zur PR-Planung

`--dry-run` führt alle Schritte **außer** dem Worker-Start, Commit, Push
und PR aus. Damit lässt sich prüfen, welcher Branch gewählt würde, ob
ein bestehender PR den Run blockiert und welche Base-Branch-Auflösung
genutzt wird.

## Aufruf

```bash
python scripts/solve_issues.py \
    --model claude \
    --repo BedBoxDrawerRole \
    --issue 3 \
    --dry-run
```

## Was wird angezeigt?

- Token- und Repo-Status.
- Erkannter Default-Branch (z. B. `main`).
- `plan_branch_recovery` — der gewählte Branch (`ai/fix-issue-3` oder
  `ai/fix-issue-3-20260614-133900-2`).
- Eventuell vorhandene PRs zu dem Branch.
- Eine `[DRY-RUN]`-Zeile pro Phase, die bei einem echten Run ausgeführt
  würde.

## Wann ist Dry-Run sinnvoll?

- Vor dem ersten Lauf in einem neuen Repo: Ist der Default-Branch
  korrekt? Gibt es bereits einen PR, der übersehen wurde?
- Bei `--ensemble`, um vorab die fünf möglichen Modelle zu sehen.
- Nach einer abgebrochenen Aktion, um den Branch-Plan zu verifizieren.
