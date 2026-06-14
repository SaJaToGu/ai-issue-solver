# Beispiel 02 — Eskalation nach fehlgeschlagenem Run

Wenn der vorherige Solver-Lauf für Issue #42 mit `mistral-small`
fehlgeschlagen ist, schlägt dieser Skill automatisch das nächste Modell
aus `MODEL_ESCALATION` vor. Damit kann der Solver mit `--auto-model` den
Run retry-en, ohne manuell das Modell zu wechseln.

## Voraussetzungen

- `reports/runs/<run_id>/metadata.json` für Issue #42 existiert
- `metadata.json` enthält mindestens `status` und `model` (schreibt der
  Solver über `scripts/solver_reporting.py`)
- Python ≥ 3.10

## Aufruf

```bash
bash .agents/skills/model-selection/helpers/recommend_model.sh \
    --issue 42 \
    --repo-type python \
    --max-cost-tier expensive \
    --format text
```

Der Skill sucht automatisch den jüngsten `metadata.json` unter
`reports/runs/.../` und liest `status` und `model` als
`run_history`-Eintrag.

## Beispielausgabe (text)

```
=== model-selection ===
Model:        opencode/nemotron-3-ultra-free
Reason:       Eskalation nach fehlgeschlagenem Run: opencode/nemotron-3-ultra-free
Category:     python
Risk:         medium
Cost tier:    cheap
Fallback:     mistral-small, mistral-medium
Inputs:       repo_type=python, language=-, task_type=-, issue=42
Routing:      manual_override=false, escalated=true, history_run_id=run-2026-06-12-abcd
```

## Erwarteter Verlauf

1. **parse** — `parse_args.sh` akzeptiert `--issue=42 --repo-type=python
   --max-cost-tier=expensive --format=text`.
2. **load** — `recommend_model.sh` sucht den jüngsten `metadata.json` und
   baut ein `run_history`-Dict mit `model` und `status=failed`.
3. **select** — `select_model` sieht `status=failed`, ermittelt den Index
   von `mistral-small` in `MODEL_ESCALATION` und wählt den nächsten
   Eintrag (`opencode/nemotron-3-ultra-free`).
4. **format** — textuelle Ausgabe mit `routing.escalated=true` und
   `routing.history_run_id=<run-…>`.

## Mehrstufige Eskalation

Wenn der Retry ebenfalls scheitert, einfach erneut aufrufen:

```bash
# Zweiter Retry
bash .agents/skills/model-selection/helpers/recommend_model.sh \
    --issue 42 --repo-type python --format json
```

Bei jedem Aufruf schreitet die Eskalation einen Schritt weiter
(`mistral-small` → `opencode/nemotron-3-ultra-free` → `mistral-medium`
→ `mistral-large` → `claude-sonnet-3.5` → `claude-sonnet-4` → `gpt-4o-mini`
→ `gpt-4o`).

## Diagnose

```bash
# Welche Run-Berichte gibt es?
bash .agents/skills/model-selection/helpers/history_check.sh 42
```

Das Script listet alle `metadata.json` mit `issue_number=42` auf.
