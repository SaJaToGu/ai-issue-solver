# 🛠️ Provider-Einrichtung und Konfiguration

Dieses Dokument enthält detaillierte Anleitungen zur Einrichtung und Konfiguration der verschiedenen KI-Provider für den AI Issue Solver.

---

## GitHub PAT erstellen

Ein **Personal Access Token (PAT)** ist dein persönlicher API-Schlüssel für GitHub.

### Schritt-für-Schritt:

1. Gehe zu: **GitHub → Settings → Developer settings → Personal access tokens → Tokens (classic)**
   Direktlink: https://github.com/settings/tokens/new

2. **Note:** `ai-issue-solver`

3. **Expiration:** 90 days (empfohlen)

4. **Scopes — diese Haken setzen:**
   - ✅ `repo` (vollständiger Repo-Zugriff)
   - ✅ `read:user` (User-Info lesen)
   - ✅ `workflow` (GitHub Actions)

5. Klick **Generate token** → Token kopieren (wird nur einmal angezeigt!)

6. In `config/.env` eintragen:
   ```
   GITHUB_TOKEN=ghp_deinTokenHier
   ```

> ⚠️ **Wichtig:** Den Token NIEMALS in ein Repo committen!
> Die `.env`-Datei ist in `.gitignore` eingetragen.

---

## KI-Modelle konfigurieren

### Claude (Anthropic)
1. API-Key holen: https://console.anthropic.com/
2. In `.env` eintragen: `ANTHROPIC_API_KEY=sk-ant-...`

### OpenAI
1. API-Key holen: https://platform.openai.com/api-keys
2. In `.env` eintragen: `OPENAI_API_KEY=sk-...`

### OpenRouter
OpenRouter ermöglicht den Zugriff auf multiple KI-Modelle über eine API und einen
Key. Der Solver nutzt OpenRouter über `aider` mit dem Modellpräfix
`openrouter/...`.

1. API-Key holen: https://openrouter.ai/keys
2. In `.env` eintragen: `OPENROUTER_API_KEY=sk-or-...`
3. Optional: `aider` installieren falls noch nicht vorhanden: `pip install aider-chat`

Starten mit:
```bash
python scripts/solve_issues.py --model openrouter --repo ai-issue-solver --issue 84
python scripts/solve_issues.py --model openrouter --model-name openrouter/openai/gpt-4o-mini --repo ai-issue-solver
python scripts/solve_issues.py --model openrouter --model-name openrouter/anthropic/claude-3-haiku --repo ai-issue-solver
```

**Empfohlene Modelle:**
- `openrouter/openai/gpt-4o-mini` — Gute Balance aus Kosten und Qualität, standardmäßig im Solver
- `openrouter/openai/gpt-4o` — Höhere Qualität, höhere Kosten
- `openrouter/anthropic/claude-3-haiku` — Schnell und kostengünstig
- `openrouter/anthropic/claude-3-sonnet` — Gute Qualität für Code-Aufgaben
- `openrouter/mistralai/mistral-7b-instruct` — Gutes Open-Source-Modell
- `openrouter/google/gemini-flash-1.5` — Schnelle Google-Alternative

**Hinweise:**
- OpenRouter benötigt `aider` — installiere es mit `pip install -r requirements-aider.txt`
- Die API-Kosten hängen vom gewählten Modell ab, nicht von OpenRouter selbst
- OpenRouter bietet eine kostenlose Test-Stufe mit begrenztem Guthaben
- Modellnamen sind für `aider` im Format `openrouter/{provider}/{model-name}` anzugeben
- Die vollständige Modell-Liste: https://openrouter.ai/models

### OpenCode
OpenCode kann als terminal-nativer Worker verschiedene Provider bündeln. Der
AI Issue Solver nutzt OpenCode nur im isolierten Worktree; Branch, Commit, Push
und PR bleiben beim Wrapper.

```bash
# OpenCode nach offizieller Doku installieren
curl -fsSL https://opencode.ai/install | bash

# Anmelden (Provider-Konfiguration)
opencode auth login

# Diagnose vor dem ersten Lauf
python scripts/solve_issues.py --diagnostic

# Issue lösen (mit Standard-Provider)
python scripts/solve_issues.py --model opencode --repo ai-issue-solver --issue 84

# Mit spezifischem Modell
python scripts/solve_issues.py --model opencode --model-name mistral/mistral-small-2603 --repo ai-issue-solver --issue 84
python scripts/solve_issues.py --model opencode --model-name claude-sonnet-4-20250514 --repo ai-issue-solver --issue 84
python scripts/solve_issues.py --model opencode --model-name gpt-4o --repo ai-issue-solver --issue 84
```

**Empfohlene Modellnamen für OpenCode:**
- `mistral/mistral-small-2603` — Mistral Small, gute Balance
- `mistral/magistral-medium-2509` — Magistral Medium (Reasoning)
- `claude-sonnet-4-20250514` — Anthropic Claude via OpenCode
- `gpt-4o` — OpenAI GPT-4o via OpenCode
- `deepseek-coder` — DeepSeek Coder via OpenCode

Der Solver sucht `opencode` in der aktiven Umgebung, in `.venv/bin` bzw.
`venv/bin` des Arbeitsbaums, in `~/.local/bin`, in `~/.local/share/opencode/`
und danach auf `PATH`. GitHub-Write-Tokens werden nicht an den OpenCode-Worker
weitergereicht.

Vor dem Worker-Start prüft der Solver, ob OpenCode authentifiziert ist
(`opencode auth list`). Fehlt die Authentifizierung, erscheint eine Warnung
mit Login-Hinweis. Der Lauf wird trotzdem gestartet, falls die OpenCode-eigene
Konfiguration einen gültigen Provider bereitstellt.

### SQLite/WAL-Fehler beheben

Falls während der CLI-Ausführung SQLite/WAL-Fehler wie `Failed to run the query 'PRAGMA wal_checkpoint(PASSIVE)'` auftreten, können folgende Schritte zur Wiederherstellung durchgeführt werden:

1. **Prüfen, ob noch OpenCode-Prozesse laufen**
   ```bash
   ps aux | grep opencode
   ```
   Falls Prozesse gefunden werden, diese mit `kill <pid>` beenden.

2. **Authentifizierungsdatei sichern**
   ```bash
   cp ~/.local/share/opencode/auth.json ~/.local/share/opencode/auth.json.backup
   ```

3. **WAL- und SHM-Dateien entfernen**
   ```bash
   rm -f ~/.local/share/opencode/opencode.db-wal ~/.local/share/opencode/opencode.db-shm
   ```
   Dies ist der erste Wiederherstellungsschritt und entfernt nur die WAL- und SHM-Dateien.

4. **OpenCode neu starten**
   ```bash
   python scripts/solve_issues.py --model opencode --repo ai-issue-solver --issue 84
   ```

**Hinweis:** Die SQLite-Hauptdatei (`opencode.db`) und die Authentifizierungsdatei (`auth.json`) bleiben unberührt. Die Wiederherstellung beschränkt sich auf die temporären WAL- und SHM-Dateien.

**Hinweise:**
- Vor dem Worker-Lauf prüft der Solver `opencode auth list` und warnt bei
  fehlender Authentifizierung
- Mit `--diagnostic` lässt sich die OpenCode-Installation unabhängig prüfen
- Der Solver akzeptiert auch `OPENCODE_API_KEY` als Umgebungsvariable

### Mistral AI / Mistral Vibe / Magistral
1. API-Key holen: https://console.mistral.ai/
2. In `.env` eintragen: `MISTRAL_API_KEY=...`
3. Mistral Vibe CLI installieren, z.B. nach offizieller Doku mit:
   ```bash
   curl -LsSf https://mistral.ai/vibe/install.sh | bash
   # alternativ: uv tool install mistral-vibe
   # alternativ: pip install mistral-vibe
   ```
4. Starten mit:
   ```bash
   python scripts/solve_issues.py --model mistral-vibe
   python scripts/solve_issues.py --model mistral
   ```

`mistral-vibe` nutzt die Mistral Vibe CLI direkt und braucht kein aider. Der
Solver sucht `vibe` in der aktiven Umgebung, in `.venv/bin` bzw. `venv/bin` des
Repos, in `~/.local/bin` und im `PATH`. `mistral` bleibt der aider-basierte
Magistral-Modus.

Der Solver nutzt standardmäßig `magistral-medium-2509`. Nach den offiziellen
Mistral-Modellübersichten vom 21. Mai 2026 ist Magistral Medium 1.2 als
aktuelles reasoning-orientiertes Magistral-Modell gelistet; ältere
Magistral-Versionen `2506` und `2507` sind legacy oder retired.
`magistral-small-2509` kann per `--model-name magistral-small-2509` gesetzt
werden, falls es im eigenen Account noch verfügbar ist; die aktuelle
Mistral-Übersicht markiert Magistral Small 1.2 inzwischen als
Legacy/Deprecated und nennt `Mistral Small 4` (`mistral-small-2603`) als
Alternative. Mistral/Magistral ist vor allem sinnvoll für europäische Sprachen,
mehrsprachige Reasoning-Aufgaben und Workflows, bei denen ein europäischer
Anbieter oder EU-Souveränitätsaspekte wichtig sind.

### Ollama (lokal / Raspberry Pi)
```bash
# Ollama installieren
curl -fsSL https://ollama.ai/install.sh | sh

# Modell herunterladen (z.B. für Raspberry Pi: kleines Modell)
ollama pull llama3.2:3b        # klein, schnell (Raspi-tauglich)
ollama pull deepseek-coder:6.7b # gut für Code

# In .env eintragen:
OLLAMA_HOST=http://localhost:11434
OLLAMA_MODEL=deepseek-coder:6.7b
```

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
# OpenCode nach offizieller Doku installieren
curl -fsSL https://opencode.ai/install | bash

# Anmelden
opencode auth login

# Vor dem ersten Lauf: Diagnose ausführen
python scripts/solve_issues.py --diagnostic

# Issue lösen
python scripts/solve_issues.py --model opencode --repo ai-issue-solver --issue 84

# Mit Modellauswahl
python scripts/solve_issues.py --model opencode --model-name mistral/mistral-small-2603 --repo ai-issue-solver --issue 84
python scripts/solve_issues.py --model opencode --model-name claude-sonnet-4-20250514 --repo ai-issue-solver --issue 84
python scripts/solve_issues.py --model opencode --model-name gpt-4o --repo ai-issue-solver --issue 84
python scripts/solve_issues.py --model opencode --model-name deepseek-coder --repo ai-issue-solver --issue 84
```

GitHub-Write-Tokens werden nicht an den OpenCode-Worker weitergereicht. Echte
Secret-Dateien wie `config/.env`, `.env` oder `.env.local` sollen Worker weder
lesen noch kopieren; für Beispiele und Dokumentation wird `config/config.example.env`
oder `.env.example` verwendet.

### SQLite/WAL-Fehler beheben

Falls während der CLI-Ausführung SQLite/WAL-Fehler wie `Failed to run the query 'PRAGMA wal_checkpoint(PASSIVE)'` auftreten, können folgende Schritte zur Wiederherstellung durchgeführt werden:

1. **Prüfen, ob noch OpenCode-Prozesse laufen**
   ```bash
   ps aux | grep opencode
   ```
   Falls Prozesse gefunden werden, diese mit `kill <pid>` beenden.

2. **Authentifizierungsdatei sichern**
   ```bash
   cp ~/.local/share/opencode/auth.json ~/.local/share/opencode/auth.json.backup
   ```

3. **WAL- und SHM-Dateien entfernen**
   ```bash
   rm -f ~/.local/share/opencode/opencode.db-wal ~/.local/share/opencode/opencode.db-shm
   ```
   Dies ist der erste Wiederherstellungsschritt und entfernt nur die WAL- und SHM-Dateien.

4. **OpenCode neu starten**
   ```bash
   python scripts/solve_issues.py --model opencode --repo ai-issue-solver --issue 84
   ```

**Hinweis:** Die SQLite-Hauptdatei (`opencode.db`) und die Authentifizierungsdatei (`auth.json`) bleiben unberührt. Die Wiederherstellung beschränkt sich auf die temporären WAL- und SHM-Dateien.

**Hinweise:**
- Vor dem Worker-Lauf prüft der Solver `opencode auth list` und warnt bei
  fehlender Authentifizierung
- Mit `--diagnostic` lässt sich die OpenCode-Installation unabhängig prüfen
- Der Solver akzeptiert auch `OPENCODE_API_KEY` als Umgebungsvariable

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
