# Beispiel 05 — Integration mit dem Solver (`--auto-model`)

Der `model-selection`-Skill ist die wiederverwendbare Schnittstelle für
Tools, die ein Modell **programmatisch** auswählen wollen, ohne den
Solver direkt aufzurufen. `scripts/solve_issues.py` ruft die Heuristik
bereits über `--auto-model` auf; dieser Skill bietet die gleiche Logik
als eigenständiges CLI.

## Voraussetzungen

- Python ≥ 3.10
- `config/.env` mit `GITHUB_TOKEN` und `GITHUB_USER`
- `requirements-aider.txt` installiert (für die Worker-Adapter)
- `scripts/solve_issues.py` und `scripts/model_selection.py` im Repo

## Variante A — `solve_issues.py` ruft die Heuristik direkt auf

```bash
python scripts/solve_issues.py \
    --auto-model \
    --repo <dein-repo> \
    --issue 42
```

In `scripts/solve_issues.py:3072` wird `select_model_for_issue`
importiert und aufgerufen. Der Solver übernimmt Prompt, Branch, Commit
und PR.

## Variante B — Eigenes Script ruft den Skill + Solver

```bash
# 1) Empfehlung holen
RECOMMENDATION=$(bash .agents/skills/model-selection/helpers/recommend_model.sh \
    --issue 42 \
    --repo-type python \
    --format json)

# 2) Felder extrahieren
MODEL=$(echo "$RECOMMENDATION" | python -c "import json,sys;print(json.load(sys.stdin)['model'])")
COST=$(echo "$RECOMMENDATION" | python -c "import json,sys;print(json.load(sys.stdin)['cost_tier'])")
REASON=$(echo "$RECOMMENDATION" | python -c "import json,sys;print(json.load(sys.stdin)['reason'])")

echo "→ Modell: $MODEL ($COST) — $REASON"

# 3) Solver starten
python scripts/solve_issues.py \
    --model opencode \
    --model-name "$MODEL" \
    --issue 42
```

## Variante C — Benchmark-Runner vergleicht Modelle

Der `model-selection`-Skill hilft auch beim Vergleich mehrerer Modelle.
Ein einfacher Sweep:

```bash
for MODEL in mistral-small mistral-medium mistral-large; do
  RECOMMENDATION=$(bash .agents/skills/model-selection/helpers/recommend_model.sh \
      --repo-type python --issue-text "Refactor auth" --manual-model "$MODEL" \
      --format json)
  echo "$MODEL → $(echo "$RECOMMENDATION" | python -c "import json,sys;d=json.load(sys.stdin);print(d['cost_tier'],d['risk'])")"
done
```

## Variante D — Dashboard zeigt Empfehlungen

Das Status-Dashboard (`scripts/status_dashboard.py`) kann den Skill
einbinden, um pro Issue eine Modell-Empfehlung anzuzeigen, **bevor** der
Solver läuft. Pseudocode:

```python
import json
import subprocess

from pathlib import Path

skill = Path(".agents/skills/model-selection/helpers/recommend_model.sh")
result = subprocess.run(
    ["bash", str(skill), "--issue", str(issue_number), "--repo-type", repo_type,
     "--format", "json"],
    capture_output=True, text=True, check=True,
)
recommendation = json.loads(result.stdout)
print(f"#{issue_number} → {recommendation['model']} ({recommendation['cost_tier']})")
```

## Erwarteter Verlauf

1. **Argument-Parsing** — `parse_args.sh` validiert Repo-Typ, Sprache
   und ggf. Issue-Nummer.
2. **Heuristik** — `select_model_for_issue` klassifiziert und wählt
   das Modell; bei vorhandener Historie wird eskaliert.
3. **Solver** — `solve_issues.py` nutzt das Modell aus
   `--model-name` und führt den Worker aus.
4. **Report** — `scripts/solver_reporting.py` schreibt die
   `model_selection_metadata` in den Run-Report; `history_check.sh`
   kann sie später lesen.

## Sicherheitshinweis

- Niemals echte Secret-Dateien lesen (`.env`, `config/.env`). Für
  Konfigurationsbeispiele ausschließlich `config/config.example.env`
  oder `.env.example` verwenden.
- Pfade im Solver-Prompt werden vom OpenCode-Adapter relativiert
  (`build_opencode_prompt`); absolute Worktree-Pfade wie
  `/tmp/ai-solver-xyz/` werden ignoriert.
