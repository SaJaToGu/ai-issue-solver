# 🛠️ Aider einrichten — Morpheus-Methode

`aider` ist der KI-Pair-Programmer, der die eigentlichen Code-Änderungen durchführt.  
Er wurde von Morpheus407 in mehreren YouTube-Videos vorgestellt.

---

## Was ist aider?

`aider` ist ein Kommandozeilen-Tool, das:
- Deinen Code versteht (per Repo-Map)
- KI-Modelle über ihre APIs aufruft
- Änderungen direkt in Dateien schreibt
- Automatisch Git-Commits erstellt

---

## Installation

```bash
pip install aider-chat
```

Verifizieren:
```bash
aider --version
```

---

## Verwendung mit den Modellen

### Claude (Anthropic)
```bash
export ANTHROPIC_API_KEY=sk-ant-...
aider --model claude-sonnet-4-20250514
```

### OpenAI
```bash
export OPENAI_API_KEY=sk-...
aider --model gpt-4o
```

### Mistral AI / Mistral Vibe / Magistral
Mistral Vibe ist der bevorzugte Mistral-Coding-Worker, wenn die CLI installiert
ist. Er braucht kein aider:

```bash
curl -LsSf https://mistral.ai/vibe/install.sh | bash
# alternativ: uv tool install mistral-vibe
# alternativ: pip install mistral-vibe

export MISTRAL_API_KEY=...
python scripts/solve_issues.py --model mistral-vibe
```

Der aider-basierte Mistral-Modus bleibt verfügbar:

```bash
export MISTRAL_API_KEY=...
aider --model mistral/magistral-medium-2509
```

Der AI Issue Solver verwendet für `--model mistral` standardmäßig
`magistral-medium-2509`. `--model-name magistral-small-2509` ist möglich,
falls Magistral Small 1.2 im eigenen Account noch verfügbar ist; die aktuelle
Mistral-Dokumentation markiert es inzwischen als Legacy/Deprecated und nennt
`mistral-small-2603` als offene Small-Alternative ausserhalb Magistral.
Mistral/Magistral passt besonders für europäische Sprachen, mehrsprachiges
Reasoning und Workflows, in denen ein europäischer Anbieter oder
EU-Souveränitätsaspekte wichtig sind.

### OpenCode CLI
OpenCode ist kein aider-Backend, sondern ein eigener terminal-nativer Worker,
der mehrere Provider bündeln kann. Der AI Issue Solver startet OpenCode im
isolierten Worktree und behält Branch, Commit, Push und PR-Erstellung selbst.

```bash
# OpenCode nach offizieller Doku installieren und Provider dort konfigurieren.
curl -fsSL https://opencode.ai/install | bash
opencode auth login

python scripts/solve_issues.py --model opencode --repo ai-issue-solver --issue 84
python scripts/solve_issues.py --model opencode --model-name mistral/mistral-small-2603 --repo ai-issue-solver --issue 84
```

GitHub-Write-Tokens werden nicht an den OpenCode-Worker weitergereicht.

### Ollama (lokal)
```bash
# Ollama muss laufen: ollama serve
export OLLAMA_API_BASE=http://localhost:11434
aider --model ollama/deepseek-coder:6.7b
```

---

## Wie es der AI Issue Solver nutzt

Das Script `solve_issues.py` ruft aider nicht-interaktiv auf:

```bash
aider --model claude-sonnet-4-20250514 \
      --yes \
      --no-auto-commits \
      --subtree-only \
      --message "Löse Issue #3: Fehlende README" \
      README.md
```

- `--yes` — beantwortet alle Rückfragen automatisch mit Ja
- `--no-auto-commits` — das Script übernimmt das Committen
- `--subtree-only` — begrenzt den Repo-Kontext auf den geklonten Arbeitsbaum
- `--message` — direkter Prompt ohne interaktive Eingabe
- Dateiargumente wie `README.md` — werden automatisch aus dem Issue-Text erkannt, gegen das Repo validiert und nur bei plausiblen Treffern übergeben

---

## Tipps für Raspberry Pi

Auf einem Raspberry Pi mit **Ollama** ist die Performance begrenzt.  
Empfohlene Modelle nach RAM:

| RAM   | Modell              | Geschwindigkeit |
|-------|---------------------|-----------------|
| 4 GB  | `llama3.2:3b`       | ~2-5 tok/s      |
| 8 GB  | `deepseek-coder:6.7b` | ~1-3 tok/s    |
| 8 GB  | `llama3.2:7b`       | ~1-2 tok/s      |

```bash
# Auf dem Raspberry Pi:
ollama pull llama3.2:3b
ollama serve  # Im Hintergrund lassen

# In config/.env auf dem Haupt-PC:
OLLAMA_HOST=http://192.168.1.XXX:11434
OLLAMA_MODEL=llama3.2:3b
```
