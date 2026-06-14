# Beispiel 04 — Plan mit eigenem Basisbranch

Erstellt einen Plan mit einem vom Default (`develop`) abweichenden
Basisbranch. Nützlich, wenn die Zielbranches gegen `main`, `master`
oder einen Release-Branch erzeugt werden sollen.

## Voraussetzungen

- `GITHUB_TOKEN` und `GITHUB_USER` in `config/.env`.
- Offene Issues im Zielrepo.
- Zielbranch existiert im Zielrepo.

## Aufruf

```bash
python scripts/plan_issue_batches.py \
    --repo ai-issue-solver \
    --emit-commands \
    --model codex \
    --base-branch main
```

Mit dem Skill-Wrapper:

```bash
bash .skills/plan-issue-batches/helpers/run_plan.sh \
    --repo ai-issue-solver \
    --emit-commands \
    --model codex \
    --base-branch main
```

## Erwarteter Verlauf

1. Schritte 1–4 wie in [01 — Standardplan](01_standard_plan.md).
2. **Kommandos rendern** — die erzeugten `solve_issues_batch.py`
   -Aufrufe verwenden `--base-branch main` statt `develop`.

## Beispielausgabe

```text
Welle 1:
  #60 - Add optional fallback for batch
    Touches: scripts/solve_issues_batch.py, tests/test_solve_issues_batch.py

  Command: python scripts/solve_issues_batch.py --model codex \
      --repo ai-issue-solver --base-branch main \
      --issue 60 --workers 1
```

## Häufige Basisbranches

| Wert | Wann sinnvoll |
|------|---------------|
| `develop` (Default) | Feature-PRs gegen den Entwicklungsbranch |
| `main` / `master` | Direkt-Releases, z. B. in kleinen Projekten |
| `release/x.y` | Patch-PRs für einen stabilen Release-Zweig |
| `feat/<thema>` | Themenbezogene Bündelung in einem Feature-Branch |

## Hinweise

- Der Planungs-Skill prüft **nicht**, ob der Basisbranch im Remote
  existiert. Die Validierung passiert erst in
  `solve_issues_batch.py` / `solve_issues.py`.
- Mehrere aufeinanderfolgende Wellen mit unterschiedlichen
  Basisbranches sind möglich, müssen aber pro Welle separat
  aufgerufen werden (der Skill unterstützt aktuell nur einen
  Basisbranch pro Aufruf).
