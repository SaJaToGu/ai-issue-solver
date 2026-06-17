# Beispiel 02 — Plan mit Batch-Kommandos

Erstellt den Wellenplan und gibt pro Welle ein fertiges
`solve_issues_batch.py`-Kommando aus. Geeignet, um den Plan direkt im
Anschluss auszuführen.

## Voraussetzungen

- `GITHUB_TOKEN` und `GITHUB_USER` in `config/.env`.
- Offene Issues im Zielrepo.
- Gewähltes Modell (`opencode`, `codex`, `claude`, …) muss in
  `MODEL_CONFIGS` aus `scripts/solve_issues.py` registriert sein.

## Aufruf

```bash
python scripts/plan_issue_batches.py \
    --repo ai-issue-solver \
    --emit-commands \
    --model opencode
```

Mit dem Skill-Wrapper:

```bash
bash .agents/skills/plan-issue-batches/helpers/run_plan.sh \
    --repo ai-issue-solver \
    --emit-commands \
    --model opencode
```

## Erwarteter Verlauf

1. Schritte 1–4 wie in [01 — Standardplan](01_standard_plan.md).
2. **Kommandos rendern** — pro Welle wird ein
   `solve_issues_batch.py`-Aufruf mit `--model`, `--repo`,
   `--base-branch` (Default `develop`), `--issue <N>` und
   `--workers <anzahl>` erzeugt.

## Beispielausgabe

```text
Welle 1:
  #60 - Add optional fallback for batch
    Touches: scripts/solve_issues_batch.py, tests/test_solve_issues_batch.py

  #64 - Add local conflict-aware issue scheduler
    Touches: scripts/plan_issue_batches.py, tests/test_plan_issue_batches.py

  Command: python scripts/solve_issues_batch.py --model opencode \
      --repo ai-issue-solver --base-branch develop \
      --issue 60 --issue 64 --workers 2
```

## Ausführen

Die ausgegebenen Kommandos können direkt nacheinander in einer Shell
ausgeführt werden:

```bash
# Erst die Planausgabe erzeugen und in eine Datei umleiten
python scripts/plan_issue_batches.py \
    --repo ai-issue-solver \
    --emit-commands \
    --model opencode > /tmp/plan.txt

# Nur die "Command:"-Zeilen extrahieren und ausführen
grep '^  Command:' /tmp/plan.txt | sed 's/^  Command: //' | bash
```

Alternativ direkt aus dem Plan-Puffer:

```bash
python scripts/plan_issue_batches.py \
    --repo ai-issue-solver \
    --emit-commands \
    --model opencode \
    | awk '/^  Command: /{print substr($0,12)}' \
    | bash
```

## Hinweise

- `--workers` wird automatisch auf `len(wave.issues)` gesetzt.
- Wellen sind aktuell mono-repo. Für Multi-Repo-Pläne muss pro Repo
  ein eigener Plan erzeugt werden.
