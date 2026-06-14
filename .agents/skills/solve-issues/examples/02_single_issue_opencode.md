# Beispiel 02 — Einzelnes Issue mit kostenlosem OpenCode-Modell

Löst ein Issue mit einem der freien OpenCode-Modelle (kein API-Key
erforderlich). Voraussetzung: `opencode auth login` wurde einmalig
ausgeführt, damit die Provider-Defaults gesetzt sind.

## Voraussetzungen

- `opencode` im PATH (`curl -fsSL https://opencode.ai/install | bash`).
- `opencode auth list` zeigt mindestens einen Provider.
- `GITHUB_TOKEN` und `GITHUB_USER` in `config/.env`.

## Aufruf

```bash
python scripts/solve_issues.py \
    --model opencode \
    --model-name opencode/deepseek-v4-flash-free \
    --issue 3
```

Weitere freie Modelle, die ohne API-Key funktionieren:

- `opencode/deepseek-v4-flash-free`
- `opencode/mimo-v2.5-free`
- `opencode/minimax-m3-free`
- `opencode/nemotron-3-ultra-free`

## Was passiert beim Start?

Der Skill ruft `prepare_opencode_worker_environment` auf, um:

- `XDG_STATE_HOME` und `OPENCODE_SERVER_PASSWORD` zu entfernen, damit
  der CLI-Aufruf eine neue, saubere Session bekommt.
- `OPENCODE_CACHE_DIR` auf das solver-lokale Cache-Verzeichnis zu
  setzen.

Der Prompt wird zusätzlich durch `build_opencode_prompt` geleitet:

- Echte Secret-Pfade (`.env`, `config/.env`, …) werden durch
  `config/config.example.env` ersetzt.
- Absolute Worktree-Pfade (z. B. `/tmp/ai-solver-xyz/...`) werden
  entfernt oder in repo-relative Pfade umgeschrieben.

## Diagnose vor dem ersten Run

```bash
python scripts/solve_issues.py --diagnostic
# bzw. nur OpenCode-Authentifizierung prüfen:
opencode auth list
```
