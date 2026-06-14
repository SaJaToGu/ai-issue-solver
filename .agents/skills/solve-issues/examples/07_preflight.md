# Beispiel 07 — Preflight ohne Solver-Start

`helpers/preflight.sh` prüft die wichtigsten Voraussetzungen, **bevor**
der `python scripts/solve_issues.py`-Solver gestartet wird. Es führt
keine Commits, Pushes oder PRs aus.

## Aufruf

```bash
bash .agents/skills/solve-issues/helpers/preflight.sh
# oder mit konkretem Modell:
bash .agents/skills/solve-issues/helpers/preflight.sh --model opencode
```

## Was wird geprüft?

1. `config/.env` existiert und enthält `GITHUB_TOKEN` + `GITHUB_USER`.
2. Python-Modul `requests` ist installiert.
3. Das passende Worker-Binary (`codex`, `opencode`, `aider`, `vibe`) ist
   im PATH — sofern das Modell es benötigt.
4. `OPENROUTER_API_KEY` ist gesetzt, wenn `--model openrouter_direct`
   geplant ist.
5. Die GitHub-API ist erreichbar (HEAD-Request mit dem Token).

## Exit-Code

- `0` — alle Checks bestanden.
- `1` — kritische Bedingung fehlt (z. B. kein Token, keine API-Erreichbarkeit).
- `2` — unbekanntes Argument.

## Anwendungsfälle

- In CI-Pipelines vor dem Solver-Start.
- Bei einmaliger Einrichtung auf einem neuen Rechner.
- Nach Konfigurationsänderungen (`config/.env` neu befüllt).
