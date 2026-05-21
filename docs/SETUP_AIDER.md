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

### Mistral AI / Magistral
```bash
export MISTRAL_API_KEY=...
aider --model mistral/magistral-medium-latest
```

Der AI Issue Solver verwendet für `--model mistral` standardmäßig
`magistral-medium-latest` und baut daraus den aider-Aufruf
`mistral/magistral-medium-latest`. Laut offizieller Mistral-Dokumentation vom
21. Mai 2026 zeigen `magistral-medium-latest` und `magistral-small-latest` auf
die aktuellen 2509-Reasoning-Modelle. Für schlankere Läufe kann
`--model-name magistral-small-latest` gesetzt werden; feste Versionen wie
`magistral-medium-2509` bleiben möglich, wenn ein Lauf bewusst an eine
bestimmte Modellversion gebunden werden soll.

Im Solver reicht dafür ein Eintrag in `config/.env`:

```env
MISTRAL_API_KEY=dein_mistral_key
```

Danach kann ein Mistral-Lauf so gestartet werden:

```bash
python scripts/solve_issues.py --model mistral
python scripts/solve_issues.py --model mistral --model-name magistral-small-latest
```

Mistral/Magistral passt besonders, wenn Codex rate-limited ist, längere
Batch-Läufe nicht durch Codex blockiert werden sollen, europäische Sprachen oder
mehrsprachiges Reasoning wichtig sind, ein europäischer Anbieter beziehungsweise
EU-/Datensouveränitätsaspekte zählen oder Experimente mit Issue-Läufen günstiger
gehalten werden sollen.

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
