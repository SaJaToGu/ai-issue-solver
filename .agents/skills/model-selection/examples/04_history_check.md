# Beispiel 04 — Run-Historie prüfen mit `history_check.sh`

Bevor ein Retry gestartet wird, kann ein Operator prüfen, welche
Solver-Runs bereits zu einer Issue-Nummer existieren. Das Script
`history_check.sh` filtert die `metadata.json`-Dateien unter
`reports/runs/` und gibt eine kompakte Tabelle aus.

## Voraussetzungen

- Python ≥ 3.10
- `reports/runs/*/*/metadata.json` mit `issue_number=42` (oder `issue=42`)
  im JSON
- `metadata.json` muss `status`, `model` (oder `model_name`) und
  optional `branch`, `timestamp` enthalten

## Aufruf

```bash
bash .agents/skills/model-selection/helpers/history_check.sh 42
```

## Beispielausgabe

```
=== model-selection history-check für Issue #42 ===
Projekt-Root: /Users/.../ai-issue-solver
Suchpfad:     /Users/.../ai-issue-solver/reports/runs/*/*/metadata.json
3 Einträge:
  • run-2026-06-12-abcd | 2026-06-12T15:22:11Z | model=mistral-small | status=failed | branch=ai/fix-issue-42
  • run-2026-06-12-cdef | 2026-06-12T15:48:02Z | model=opencode/nemotron-3-ultra-free | status=no-change | branch=ai/fix-issue-42
  • run-2026-06-13-ef01 | 2026-06-13T09:05:44Z | model=mistral-medium | status=pr_created | branch=ai/fix-issue-42
→ Tipp: mit `bash helpers/recommend_model.sh --issue N --repo-type T` die Heuristik auf Basis dieser Historie ausführen.
```

## Erwarteter Verlauf

1. **Argumente prüfen** — `history_check.sh` validiert die Issue-Nummer
   (nur Ziffern, ≥ 1) und bricht sonst mit Exit-Code 2 ab.
2. **Pfad scannen** — das Script sucht `metadata.json` unter
   `reports/runs/*/*/metadata.json`.
3. **Filtern** — Python-Helfer filtert nach `issue_number` (oder
   `issue`) im JSON.
4. **Ausgabe** — Tabelle mit `run_id`, Zeitstempel, Modell, Status und
   Branch.

## Edge Cases

- **Keine `reports/runs/`-Verzeichnis** → Exit 1, Hinweis
  `reports/runs existiert nicht`.
- **Keine Treffer für die Issue-Nummer** → Exit 0, Hinweis
  `Keine metadata.json für Issue #N gefunden.`
- **Unlesbare `metadata.json`** → Warnung, andere Einträge werden
  trotzdem ausgegeben.

## Integration in CI

`history_check.sh` eignet sich als Pre-Retry-Check in einer Pipeline:

```bash
# Vor jedem Solver-Retry mit --auto-model
bash .agents/skills/model-selection/helpers/history_check.sh "$ISSUE" || true
python scripts/solve_issues.py --auto-model --issue "$ISSUE"
```
