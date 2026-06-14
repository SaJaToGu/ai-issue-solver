# Beispiel 01 — Automatische Modellauswahl für ein Python-Docs-Issue

Wählt automatisch ein günstiges Modell für ein reines Dokumentations-Issue
in einem Python-Repository. Da `--max-cost-tier cheap` gesetzt ist, fällt
die Empfehlung auf einen Eintrag aus dem `low`-Tier (`mistral-small`,
`deepseek-coder:6.7b`, `qwen-coder`).

## Voraussetzungen

- Python ≥ 3.10
- `scripts/model_selection.py` im Repo vorhanden
- Optional `reports/runs/` für Eskalations-Quellen (hier nicht nötig)

## Aufruf

```bash
bash .agents/skills/model-selection/helpers/recommend_model.sh \
    --repo-type python \
    --language python \
    --task-type docs \
    --issue-text "Update the README and add a quickstart section" \
    --max-cost-tier cheap
```

## Beispielausgabe (JSON)

```json
{
  "ok": true,
  "model": "mistral-small",
  "reason": "Erstversuch mit günstigstem passendem Modell: mistral-small",
  "category": "docs-only",
  "risk": "low",
  "cost_tier": "cheap",
  "fallback_plan": [
    "opencode/mimo-v2.5-free",
    "opencode/minimax-m3-free"
  ],
  "inputs": {
    "repo_type": "python",
    "language": "python",
    "task_type": "docs",
    "issue": 0,
    "max_cost_tier": "cheap"
  },
  "routing": {
    "manual_override": false,
    "escalated": false,
    "history_run_id": null
  }
}
```

## Erwarteter Verlauf

1. **parse** — `parse_args.sh` validiert `--repo-type`, `--language`,
   `--task-type`, `--issue-text` und `--max-cost-tier=cheap`. Exit 0.
2. **load** — keine `run_history`; `RUN_HISTORY_JSON = "[]"`.
3. **classify** — `classify_issue` erkennt `docs-only` (Keyword `README`
   bzw. Label `docs`).
4. **select** — `select_model` wählt `mistral-small` (günstigster Eintrag
   im `low`-Tier).
5. **format** — JSON-Ausgabe mit `fallback_plan` (nächste zwei Modelle
   in `MODEL_ESCALATION`).

## Diagnose

```bash
# Menschen-lesbare Variante
bash .agents/skills/model-selection/helpers/recommend_model.sh \
    --repo-type python \
    --issue-text "Update the README" \
    --format text
```

Dieser Aufruf ist read-only und eignet sich, um vor einem
Solver-Lauf mit `--auto-model` die erwartete Modellwahl zu inspizieren.
