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
- [Nächste Ausbaustufe](#nächste-ausbaustufe)
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
prüft Repo-Metadaten und Dateistruktur auf fehlende Projekt-Basics,
Wartungssignale und Best-Practice-Auffälligkeiten.

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
│    .py           │    Prüft: README, Lizenz, .gitignore,
└────────┬────────┘    CI, Tests, Topics, Staleness
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

Die Projektarbeit kann über `develop` laufen: `main` bleibt stabil, `develop`
sammelt laufende Änderungen, und Feature-Branches referenzieren GitHub Issues,
zum Beispiel `ai/fix-issue-10`. `solve_issues.py` nutzt ohne explizite Vorgabe
den GitHub-Default-Branch des Ziel-Repositories. Wer ein `develop`-Modell nutzt,
setzt `--base-branch develop`.

Details stehen in [docs/WORKFLOW.md](docs/WORKFLOW.md#branch-modell).

---

## Scripts im Detail

### `analyze_repos.py`
Analysiert alle Repos eines GitHub-Users und erstellt einen JSON-Report.

```bash
python scripts/analyze_repos.py --user SaJaToGu --output reports/analysis.json
```

**Prüft auf:**
- Fehlende oder sehr kurze README-Datei (`< 200` Bytes)
- Fehlende LICENSE-Datei (`LICENSE`, `LICENSE.md` oder `LICENSE.txt`)
- Fehlende `.gitignore`
- Fehlende GitHub-Actions-Workflows bei erkannten Code-Projekten
- Leeres GitHub-About-Feld (`description`)
- Fehlende GitHub Topics/Tags
- Seit über 2 Jahren oder über 4 Jahren nicht aktualisierte Repos
- Code-Projekte ohne erkennbare Testdateien oder Testverzeichnisse
- Riskante generierte Dateien im Repo, z.B. `dist/`, `build/`, `*.pyc`, `*.zip`
- Forks ohne eigene README-Anpassung oder Beschreibung

Die Analyse ist bewusst heuristisch: Sie wertet GitHub-Metadaten und den
Repository-Tree aus. Sie führt aktuell keine Dependency-Audits, Secret-Scans,
statische Codequalitätsanalyse oder Kommentar-Vollständigkeitsprüfung aus.

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

Das Script verdichtet die Worker-Ausgabe live auf Status-, Planungs-, Warn- und
Ergebniszeilen. Detailausgaben wie lange Diffs oder Kommando-Logs werden im
Terminal ausgeblendet und nur einmal am Ende gezählt; der vollständige Rohoutput
landet weiterhin unter `reports/runs/` in der Worker-Diagnose. Nach dem Lauf
zeigt das Script eine kompakte Git-Übersicht mit geänderten Dateien,
Einfügungen/Löschungen, Diff-Stat und kurzer Diff-Vorschau. Ein erfolgreicher
Worker-Lauf ohne Dateiänderungen wird
als No-op behandelt und erzeugt keinen Commit. Falls Codex mit einem
Nicht-Null-Exitcode beendet, aber Änderungen im Arbeitsbaum liegen, prüft das
Script diese Änderungen weiter und zeigt die letzten Worker-Zeilen als Diagnose.
Wenn Codex das Nachrichtenlimit meldet und eine Reset-Zeit ausgibt, pausiert
`solve_issues.py` bis zu diesem Zeitpunkt und versucht dasselbe Issue danach
erneut, statt die restlichen Issues sofort als Fehler zu zählen.

Vor jedem Worker-Lauf und auch im Dry-Run prüft das Script vorhandene
Issue-Branches mit dem Präfix `ai/fix-issue-{nummer}` und zugehörige Pull
Requests. Einen vorhandenen
Branch ohne PR nutzt es weiter; enthält er bereits Änderungen gegen den
Zielbranch, erstellt das Script direkt den fehlenden PR. So kann ein
abgebrochener Lauf nach Push oder vor der PR-Erstellung fortgesetzt werden.
Gibt es bereits einen offenen oder
gemergten PR, wird das Issue nicht erneut bearbeitet und der gefundene PR
ausgegeben. Bei einem geschlossenen, nicht gemergten PR startet das Script in
nicht-interaktiven Läufen automatisch mit einem neuen Branch; im Terminal kann
man stattdessen bewusst überspringen.

Im Aider-Modus begrenzt das Script den Kontext auf den geklonten Arbeitsbaum und
übergibt plausible Datei-Ziele aus Issue-Titel und Beschreibung als
Dateiargumente. Pfade werden vorab gegen das Repo validiert, damit keine
externen oder ungültigen Pfade an aider durchgereicht werden.

**Flags:**
- `--model` — `codex`, `claude`, `openai`, oder `ollama`
- `--model-name` — spezifisches Modell, z.B. für Codex oder Ollama
- `--dry-run` — zeigt Plan ohne Änderungen
- `--issue` — nur ein bestimmtes Issue lösen

---

## Nächste Ausbaustufe

Die erste Workflow-Runde ist abgeschlossen: Analyse, Backlog-Issues,
KI-Bearbeitung, PR-Erstellung, CI und Tests laufen. Als nächstes soll der
Morpheus-Style Workflow komfortabler werden:

- mehrere Issues parallel mit begrenzter Worker-Zahl lösen
- laufende Jobs, PRs und Fehler in einer lokalen Übersicht anzeigen
- Worker-Logs und Ergebnisse unter `reports/runs/` nachvollziehbar speichern
- offene PRs und Issues nach einem Lauf automatisch zusammenfassen

Der geplante Backlog dafür liegt in [docs/NEXT_BACKLOG.md](docs/NEXT_BACKLOG.md).

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
├── .github/
│   ├── settings.yml             # Repo-Beschreibung und Topics als Referenz
│   └── workflows/
│       └── ci.yml               # GitHub-Actions-Smoke- und Testlauf
├── README.md                    # Diese Datei
├── requirements.txt             # Python-Dependencies
├── requirements-aider.txt       # Optionale Aider-Dependencies
├── .gitignore                   # Schützt .env und Secrets
├── config/
│   └── config.example.env       # Vorlage für deine .env
├── scripts/
│   ├── analyze_repos.py         # Schritt 1: Repos analysieren
│   ├── create_issues.py         # Schritt 2: Issues erstellen
│   ├── create_backlog_issues.py # Backlog-Issues aus Markdown erstellen
│   ├── solve_issues.py          # Schritt 3: Issues mit KI lösen
│   └── utils.py                 # Gemeinsame Hilfsfunktionen
├── templates/
│   └── issue_body               # Issue-Text-Vorlage
├── reports/                     # Generierte Analyse-Reports (gitignored)
│   └── .gitkeep
├── docs/
│   ├── BACKLOG.md               # Erster Projekt-Backlog
│   ├── NEXT_BACKLOG.md          # Nächste Ausbaustufe
│   ├── WORKFLOW.md              # Detaillierter Workflow
│   ├── SETUP_AIDER.md           # Aider-Einrichtung
│   └── RASPBERRY_PI.md          # Ollama auf Raspberry Pi
└── tests/
    ├── test_analyze_repos.py    # Analyzer-Tests
    └── test_solve_issues.py     # Solver- und Worker-Tests
```

---

## Lizenz

MIT — Mach damit was du willst. Viel Spaß! 🚀
