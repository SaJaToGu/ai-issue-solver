# KI-Modelle & Provider Setup

> ⚠️ **Aider is deprecated.** The Aider worker adapter (`workers/aider_adapter.py`)
> is deprecated as of the 0.9.0 release and will be removed in the next minor
> release. New solver runs should use one of the three supported paths:
>
> - **`opencode`** (default model `opencode/deepseek-v4-flash-free`, proven free path)
> - **`openrouter_direct`**
> - **`codex`**
>
> This file is kept temporarily for legacy setups only. See issue #411 / §47
> in `docs/BACKLOG/open.md` for migration notes and the removal timeline.

Dieser Guide erklärt die Einrichtung der verschiedenen KI-Modelle und Provider für den AI Issue Solver.

## Voraussetzungen

- Python ≥ 3.10
- `aider` (für Claude, OpenAI, OpenRouter, Magistral)
- GitHub PAT (für Repository-Zugriff)

Installiere die optionalen Abhängigkeiten für KI-Modelle:

```bash
pip install -r requirements-aider.txt
```

---

## Provider-Konfiguration

### GitHub PAT erstellen

1. Gehe zu: [GitHub → Settings → Developer settings → Personal access tokens → Tokens (classic)](https://github.com/settings/tokens/new)
2. **Note:** `ai-issue-solver`
3. **Expiration:** 90 days (empfohlen)
4. **Scopes:** `repo`, `read:user`, `workflow`
5. Token in `config/.env` eintragen:
   ```
   GITHUB_TOKEN=ghp_deinTokenHier
   ```

> ⚠️ **Wichtig:** Den Token NIEMALS in ein Repo committen!

---

## KI-Modelle

### Claude (Anthropic)
1. API-Key holen: [Anthropic Console](https://console.anthropic.com/)
2. In `.env` eintragen:
   ```
   ANTHROPIC_API_KEY=sk-ant-...
   ```
3. Starten:
   ```bash
   python scripts/solve_issues.py --model claude --repo <repo-name>
   ```

---

### OpenAI
1. API-Key holen: [OpenAI API Keys](https://platform.openai.com/api-keys)
2. In `.env` eintragen:
   ```
   OPENAI_API_KEY=sk-...
   ```
3. Starten:
   ```bash
   python scripts/solve_issues.py --model openai --repo <repo-name>
   ```

---

### OpenRouter
1. API-Key holen: [OpenRouter Keys](https://openrouter.ai/keys)
2. In `.env` eintragen (für beide Pfade wird derselbe Key benötigt):
   ```
   OPENROUTER_API_KEY=sk-or-...
   ```

OpenRouter kann über zwei verschiedene Pfade angesprochen werden. Die Wahl
des Pfads beeinflusst, wie das Modell Änderungen am Code zurückgibt:

- **`--model openrouter`** (Aider-basiert, Legacy-Pfad): Übergibt Aufgaben
  an `aider`, das intern mit OpenRouter spricht. Aider steuert den
  Edit-Workflow (Dateien lesen, Patches anwenden, Tests laufen lassen).
- **`--model openrouter_direct`** (direkter OpenRouter-API-Pfad): Ruft die
  OpenRouter-API direkt auf und erwartet, dass das Modell unified-diff
  Patches (im `patch -p1`-Format) zurückgibt. Vorteil: schlanker, keine
  Aider-Abhängigkeit zur Laufzeit für das Edit-Protokoll.

3. Starten – Aider-basierter Pfad (empfohlen für komplexere Issues):
   ```bash
   python scripts/solve_issues.py --model openrouter --repo <repo-name> \
       --model-name openrouter/openai/gpt-4o-mini
   ```

4. Starten – direkter OpenRouter-Pfad (erwartet unified-diff Patches):
   ```bash
   python scripts/solve_issues.py --model openrouter_direct --repo <repo-name> \
       --model-name openrouter/openai/gpt-4o-mini
   ```

**Empfohlene Modelle:**
- `openrouter/openai/gpt-4o-mini` (Standard)
- `openrouter/anthropic/claude-3-haiku`
- `openrouter/mistralai/mistral-7b-instruct`

---

### OpenCode
1. OpenCode installieren:
   ```bash
   curl -fsSL https://opencode.ai/install | bash
   ```
2. Anmelden:
   ```bash
   opencode auth login
   ```
3. Starten:
   ```bash
   python scripts/solve_issues.py --model opencode --repo <repo-name> --issue <issue-number>
   ```

**Empfohlene Modelle:**
- `mistral/mistral-small-2603`
- `claude-sonnet-4-20250514`
- `gpt-4o`

---

### Mistral AI / Magistral
1. API-Key holen: [Mistral Console](https://console.mistral.ai/)
2. In `.env` eintragen:
   ```
   MISTRAL_API_KEY=...
   ```
3. Mistral Vibe CLI installieren:
   ```bash
   curl -LsSf https://mistral.ai/vibe/install.sh | bash
   ```
4. Starten:
   ```bash
   python scripts/solve_issues.py --model mistral --repo <repo-name>
   ```

**Standardmodell:** `magistral-medium-2509`

---

### Ollama (lokal)
1. Ollama installieren:
   ```bash
   curl -fsSL https://ollama.ai/install.sh | sh
   ```
2. Modell herunterladen:
   ```bash
   ollama pull llama3.2:3b        # Raspi-tauglich
   ollama pull deepseek-coder:6.7b # Gut für Code
   ```
3. In `.env` eintragen:
   ```
   OLLAMA_HOST=http://localhost:11434
   OLLAMA_MODEL=deepseek-coder:6.7b
   ```
4. Starten:
   ```bash
   python scripts/solve_issues.py --model ollama --repo <repo-name>
   ```