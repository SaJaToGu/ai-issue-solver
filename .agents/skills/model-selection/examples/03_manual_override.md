# Beispiel 03 — Manuelles Override via `--manual-model`

Manchmal möchte man ein konkretes Modell erzwingen (z. B. für ein
Sicherheits-Review oder einen A/B-Vergleich), ohne die Heuristik komplett
abzuschalten. `--manual-model` setzt das Modell direkt, der Skill liefert
aber weiterhin Kategorie, Risiko und Kosten-Tier aus der Heuristik.

## Voraussetzungen

- Python ≥ 3.10
- `scripts/model_selection.py` im Repo vorhanden
- Der gewählte Modellname muss im Worker-Adapter bekannt sein (siehe
  `.agents/skills/solve-issues/SKILL.md`)

## Aufruf

```bash
bash .agents/skills/model-selection/helpers/recommend_model.sh \
    --repo-type python \
    --issue-text "Refactor the auth middleware" \
    --manual-model claude-sonnet-4 \
    --format json
```

## Beispielausgabe (JSON)

```json
{
  "ok": true,
  "model": "claude-sonnet-4",
  "reason": "Manuell übersteuert: claude-sonnet-4",
  "category": "refactor",
  "risk": "high",
  "cost_tier": "expensive",
  "fallback_plan": [
    "gpt-4o-mini",
    "gpt-4o"
  ],
  "inputs": {
    "repo_type": "python",
    "language": "",
    "task_type": "",
    "issue": 0,
    "max_cost_tier": "expensive"
  },
  "routing": {
    "manual_override": true,
    "escalated": false,
    "history_run_id": null
  }
}
```

## Erwarteter Verlauf

1. **parse** — `parse_args.sh` akzeptiert `--manual-model` als gültige
   Quelle, auch wenn alle anderen Routing-Signale leer sind.
2. **classify** — `classify_issue` ermittelt `refactor` (Keyword
   `Refactor`, Label `refactor`).
3. **select** — `select_model` erkennt `manual_overrides["model"]` und
   überspringt Eskalation sowie Kosten-Filterung.
4. **format** — JSON mit `routing.manual_override=true`; `fallback_plan`
   kommt trotzdem aus `MODEL_ESCALATION`.

## Variante: Override im Solver

`scripts/solve_issues.py` unterstützt `--auto-model` mit Override
über die bestehende `--model` und `--model-name`-Flags. Wer den
`model-selection`-Skill direkt einbindet, kann das JSON mit `jq`
weiterverarbeiten:

```bash
RECOMMENDED=$(bash .agents/skills/model-selection/helpers/recommend_model.sh \
    --issue 42 --repo-type python --format json \
    | python -c "import json,sys;print(json.load(sys.stdin)['model'])")

python scripts/solve_issues.py \
    --model opencode \
    --model-name "$RECOMMENDED" \
    --issue 42
```
