# 🤖 AI Issue Solver — Morpheus-Style Workflow

> Automatisches Analysieren, Erstellen und Lösen von GitHub Issues mit KI-Unterstützung  
> Inspiriert von [TheMorpheus407](https://www.youtube.com/user/TheMorpheus407) / [the-morpheus.de](https://www.the-morpheus.de)

---

## 📋 Inhaltsverzeichnis

- [Was macht dieses Repo?](#was-macht-dieses-repo)
- [Repository-Metadaten](#repository-metadaten)
- [Voraussetzungen](#voraussetzungen)
- [Setup & Installation](#setup--installation)
- [Workflow im Überblick](#workflow-im-überblick)
- [Branch-Modell](#branch-modell)
- [Scripts im Detail](#scripts-im-detail)
- [GitHub PAT erstellen](#github-pat-erstellen)
- [KI-Modelle konfigurieren](#ki-modelle-konfigurieren)
- [Verzeichnisstruktur](#verzeichnisstruktur)

---

## Was macht dieses Repo?

Dieses Repo implementiert einen vollautomatischen **KI-gestützten Verbesserungs-Workflow** für GitHub-Projekte:

```
Repos analysieren  →  Issues erstellen  →  KI löst Issues  →  PR erstellen
```

**Schritt 1 — Analyse:** `analyze_repos.py` scannt alle deine GitHub-Repos per API,  
analysiert Code-Qualität, fehlende Dokumentation, Sicherheit und Best Practices.

**Schritt 2 — Issues erstellen:** `create_issues.py` legt für jeden gefundenen  
Verbesserungsvorschlag automatisch ein strukturiertes GitHub Issue an.

**Schritt 3 — Issues lösen:** `solve_issues.py` ruft wahlweise **Codex**, **Claude**,
**OpenAI** oder **Ollama (lokal)** auf, liest das Issue, bearbeitet den Code
und erstellt einen Branch + Commit.

## Repository-Metadaten

**Beschreibung:** Automatisiert GitHub-Repository-Analysen, Issue-Erstellung und
KI-gestützte Issue-Lösung mit Codex oder aider.

**Empfohlene GitHub Topics:**
`ai`, `aider`, `automation`, `codex`, `developer-tools`, `github`, `github-api`,
`issue-automation`, `python`, `repository-analysis`

Die versionierbare Referenz für diese Angaben liegt in
[.github/settings.yml](.github/settings.yml). Falls eine GitHub Settings App im
Repo aktiv ist, kann sie daraus das About-Feld und die Topics synchronisieren.

---

## Voraussetzungen

| Tool | Version | Zweck |
|------|---------|-------|
| Python | ≥ 3.10 | Haupt-Scriptsprache |
| `gh` CLI | aktuell | GitHub-Zugriff |
| Codex CLI | optional | KI-Worker über deinen Codex-Zugang |
| `aider` | optional | KI-Worker für Claude/OpenAI/Ollama |
| `git` | aktuell | Versionskontrolle |
| Ollama | optional | Lokale KI-Modelle |

---

## Setup & Installation

### 1. Repo klonen

```bash
git clone https://github.com/SaJaToGu/ai-issue-solver.git
cd ai-issue-solver
```

### 2. Python-Abhängigkeiten installieren

```bash
pip install -r requirements.txt
```

Für die Modi `claude`, `openai` oder `ollama` zusätzlich:

```bash
pip install -r requirements-aider.txt
```

### 3. GitHub PAT einrichten

→ Siehe [GitHub PAT erstellen](#github-pat-erstellen) weiter unten.

```bash
cp config/config.example.env config/.env
# .env mit deinen Werten befüllen (NIEMALS committen!)
```

Die Scripts erkennen fehlende Werte und Platzhalter wie `DEIN_TOKEN_HIER` und
geben sichere Hinweise aus, ohne Secret-Werte im Terminal anzuzeigen.

### 4. KI-Modell wählen

```bash
python scripts/solve_issues.py --model codex     # Codex CLI
python scripts/solve_issues.py --model claude    # Anthropic Claude
python scripts/solve_issues.py --model openai    # OpenAI GPT-4
python scripts/solve_issues.py --model ollama    # Lokales Modell
```

---

## Workflow im Überblick

```
┌─────────────────────────────────────────────────────────┐
│                    AI ISSUE SOLVER                       │
│                  (Morpheus-Methode)                      │
└─────────────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────┐
│ 1. analyze_repos │  ← Scannt alle Repos per GitHub API
│    .py           │    Prüft: README, Lizenz, Code-Qualität
└────────┬────────┘    Sicherheit, CI/CD, Dokumentation
         │
         ▼
┌─────────────────┐
│ 2. create_issues │  ← Erstellt strukturierte Issues
│    .py           │    mit Labels, Priorität, Beschreibung
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ 3. solve_issues  │  ← Wählt KI-Modell (Codex/Claude/OpenAI/Ollama)
│    .py           │    Nutzt Codex oder aider als Code-Worker
└────────┬────────┘    Erstellt Branch → Commit → PR
         │
         ▼
┌─────────────────┐
│   GitHub PR      │  ← Du reviewst und mergst
└─────────────────┘
```

---

## Branch-Modell

Die Projektarbeit läuft über `develop`: `main` bleibt stabil, `develop` sammelt
laufende Änderungen, und Feature-Branches referenzieren GitHub Issues, zum
Beispiel `ai/fix-issue-10`. Pull Requests gehen zurück nach `develop`.

Details stehen in [docs/WORKFLOW.md](docs/WORKFLOW.md#branch-modell).

---

## Scripts im Detail

### `analyze_repos.py`
Analysiert alle Repos eines GitHub-Users und erstellt einen JSON-Report.

```bash
python scripts/analyze_repos.py --user SaJaToGu --output reports/analysis.json
```

**Prüft auf:**
- Fehlendes README / schlechte README-Qualität
- Fehlende LICENSE-Datei
- Fehlende `.gitignore`
- Keine CI/CD-Pipeline (GitHub Actions)
- Veraltete Dependencies
- Sicherheitslücken (hardcoded secrets)
- Fehlende Code-Kommentare
- Fehlende Issues-Templates

---

### `create_issues.py`
Liest den Analysis-Report und erstellt GitHub Issues.

```bash
python scripts/create_issues.py --report reports/analysis.json --dry-run
python scripts/create_issues.py --report reports/analysis.json --confirm-create  # echte Issues
python scripts/create_backlog_issues.py                         # Backlog-Dry-Run
python scripts/create_backlog_issues.py --apply --confirm-create # echte Backlog-Issues
```

**Flags:**
- `--dry-run` — zeigt Issues mit Titel, Labels und Body an ohne sie zu erstellen
- `--confirm-create` — erforderlich, bevor echte GitHub-Issues erstellt werden
- `--repo` — nur für ein bestimmtes Repo
- `--priority high` — nur High-Priority Issues

`create_backlog_issues.py` liest [docs/BACKLOG.md](docs/BACKLOG.md) und erstellt
daraus die initialen Projekt-Issues. Ohne `--apply --confirm-create` läuft es
als Dry-Run.

---

### `solve_issues.py`
Löst offene Issues automatisch mit KI + Codex oder aider.

```bash
python scripts/solve_issues.py --model codex --repo BedBoxDrawerRole
python scripts/solve_issues.py --model claude --repo BedBoxDrawerRole
python scripts/solve_issues.py --model ollama --model-name llama3
```

Im Codex-Modus streamt das Script die Worker-Ausgabe live und wertet danach
den Git-Status aus. Ein erfolgreicher Worker-Lauf ohne Dateiänderungen wird
als No-op behandelt und erzeugt keinen Commit. Falls Codex mit einem
Nicht-Null-Exitcode beendet, aber Änderungen im Arbeitsbaum liegen, prüft das
Script diese Änderungen weiter und zeigt die letzten Worker-Zeilen als Diagnose.

**Flags:**
- `--model` — `codex`, `claude`, `openai`, oder `ollama`
- `--model-name` — spezifisches Modell, z.B. für Codex oder Ollama
- `--dry-run` — zeigt Plan ohne Änderungen
- `--issue` — nur ein bestimmtes Issue lösen

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

## Verzeichnisstruktur

```
ai-issue-solver/
├── README.md                    # Diese Datei
├── requirements.txt             # Python-Dependencies
├── requirements-aider.txt       # Optionale Aider-Dependencies
├── .gitignore                   # Schützt .env und Secrets
├── config/
│   └── config.example.env       # Vorlage für deine .env
├── scripts/
│   ├── analyze_repos.py         # Schritt 1: Repos analysieren
│   ├── create_issues.py         # Schritt 2: Issues erstellen
│   ├── solve_issues.py          # Schritt 3: Issues mit KI lösen
│   └── utils.py                 # Gemeinsame Hilfsfunktionen
├── templates/
│   └── issue_body.md            # Issue-Text-Vorlage
├── reports/                     # Generierte Analyse-Reports (gitignored)
│   └── .gitkeep
└── docs/
    ├── WORKFLOW.md               # Detaillierter Workflow
    ├── SETUP_AIDER.md            # Aider-Einrichtung
    └── RASPBERRY_PI.md           # Ollama auf Raspberry Pi
```

---

## Lizenz

MIT — Mach damit was du willst. Viel Spaß! 🚀
