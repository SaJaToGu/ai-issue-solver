# Workflow, Batch-Verarbeitung & Dashboard

Dieser Guide erklärt den detaillierten Workflow des AI Issue Solvers, die Batch-Verarbeitung, das Dashboard und weitere Features wie Night Mode.

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
│    .py           │    Prüft: README, Lizenz, .gitignore, CI, Tests, Topics, Staleness
└────────┬────────┘
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

- `main` bleibt stabil, `develop` sammelt laufende Änderungen.
- Feature-Branches referenzieren GitHub Issues (z.B. `ai/fix-issue-10`).
- `solve_issues.py` nutzt standardmäßig den GitHub-Default-Branch des Ziel-Repositories.
- Für `develop`-Modelle: `--base-branch develop` setzen.

---

## Scripts im Detail

### `solve_issues.py`
Löst offene Issues automatisch mit KI + Codex, Mistral Vibe, OpenCode oder aider.

**Flags:**
- `--model`: `codex`, `mistral-vibe`, `opencode`, `claude`, `openai`, `mistral`, `ollama`
- `--model-name`: Spezifisches Modell (z.B. `mistral/magistral-medium-latest`
  oder `mistral/mistral-large-latest`)
- `--dry-run`: Zeigt Plan ohne Änderungen
- `--issue`: Nur ein bestimmtes Issue lösen

**Beispiele:**
```bash
python scripts/solve_issues.py --model codex --repo BedBoxDrawerRole
python scripts/solve_issues.py --model claude --repo BedBoxDrawerRole
python scripts/solve_issues.py --model ollama --model-name llama3
```

---

### `solve_issues_batch.py`
Löst mehrere Issues parallel mit begrenzter Worker-Zahl.

**Flags:**
- `--workers`: Maximale parallele Worker (Standard: `2`)
- `--issue`: Kann mehrfach angegeben werden
- `--requeue-rate-limited`: Codex-Jobs nach Rate-Limit erneut einplanen
- `--fallback-model`: Fallback-Modell bei Rate-Limits

**Beispiele:**
```bash
python scripts/solve_issues_batch.py --model codex --workers 2
python scripts/solve_issues_batch.py --model claude --repo BedBoxDrawerRole --workers 3
```

---

### `run_overnight.py`
Startet einen unbeaufsichtigten Batch-Lauf mit Preflight und Abschlussbericht.

**Flags:**
- `--workers`: Maximale parallele Worker (Standard: `2`)
- `--base-branch`: Branch für Pull und Solver-Basis (Standard: `main`)
- `--skip-pull` / `--skip-tests`: Preflight-Schritte überspringen

**Beispiel:**
```bash
python scripts/run_overnight.py --model codex --base-branch develop --workers 2
```

---

### `status_dashboard.py`
Erzeugt ein lokales HTML-Dashboard aus Run-Reports.

**Features:**
- Gruppiert wartende, laufende, erfolgreiche und fehlgeschlagene Jobs
- Verlinkt GitHub Issues, Branches und Pull Requests
- Optional GitHub-API-Anreicherung für PR-/Issue-Status

**Beispiele:**
```bash
python scripts/status_dashboard.py
python scripts/status_dashboard.py --github-enrich
python scripts/serve_dashboard.py --port 8765 --refresh-seconds 10
```

**Flags:**
- `--github-enrich`: PR-/Merge-/Issue-Lifecycle per GitHub API anreichern
- `--cleanup-stale`: Alte Reports als Cleanup-Kandidaten anzeigen
- `--health-timeout-minutes`: Timeout für Unhealthy-Jobs (Standard: `60`)

---

### `post_merge_cleanup.py`
Räumt nach gemergten AI-Pull-Requests auf.

**Automatische Aktionen (mit `--apply`):**
- Gemergte AI-PRs zusammenfassen
- Offene Issues schließen (bei Closing-Keywords oder Branch-Referenz)
- Gemergte AI-Branches löschen
- Stale Branches melden

**Beispiel:**
```bash
python scripts/post_merge_cleanup.py --repo ai-issue-solver --apply
```

---

## Night Mode & Automatisierung

- **Preflight:** `run_overnight.py` zieht zuerst den Basis-Branch (`git pull --ff-only`) und führt Tests aus.
- **Batch-Lauf:** Startet `solve_issues_batch.py` mit Worker-Limit.
- **Abschluss:** Regeneriert das lokale Status-Dashboard.
- **Logs:** Alle Schritte werden unter `reports/overnight/<timestamp>/` protokolliert.

### OpenCode mit Mistral im Night Mode

**Exakter Befehl für unbeaufsichtigte Läufe mit Medium:**
```bash
python scripts/run_overnight.py --model opencode --model-name mistral/magistral-medium-latest --base-branch develop --workers 1
```

**Stärkeres Modell für Review-sensible Issues:**
```bash
python scripts/run_overnight.py --model opencode --model-name mistral/mistral-large-latest --base-branch develop --workers 1
```

**Smoke-Test (direkt prüfen, ob der Workflow funktioniert):**
```bash
python scripts/solve_issues.py --model opencode --model-name mistral/mistral-large-latest --repo <repo-name> --issue <issue-number> --dry-run
```

> ⚠️ **Hinweis:** Night-Mode-Läufe sollten immer auf den `develop`-Branch zielen, um Stabilität in `main` zu gewährleisten. Die Dokumentation ist rein informativ und enthält keine Secrets.
