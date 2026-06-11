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
- Optional abgeschlossene Einträge aus `docs/NEXT_BACKLOG.md` entfernen

**Beispiel:**
```bash
python scripts/post_merge_cleanup.py --repo ai-issue-solver --apply
python scripts/post_merge_cleanup.py --repo ai-issue-solver --apply --cleanup-backlog
```

---

## Night Mode & Automatisierung

- **Preflight:** `run_overnight.py` zieht zuerst den Basis-Branch (`git pull --ff-only`) und führt Tests aus.
- **Batch-Lauf:** Startet `solve_issues_batch.py` mit Worker-Limit.
- **Abschluss:** Regeneriert das lokale Status-Dashboard.
- **Logs:** Alle Schritte werden unter `reports/overnight/<timestamp>/` protokolliert.

### Auswahl sicherer Issues für Night Mode

Night-Mode-Läufe sind **unbeaufsichtigt** und sollten daher nur für **risikoarme Issues** verwendet werden:

- **Dokumentation:** README, Workflow-Dokus, Kommentare, Typo-Fixes
- **Isolierte Workflows:** Kleine, abgegrenzte Code-Änderungen (z. B. einzelne Funktionen, Tests)
- **Vermeiden:** Issues mit Auswirkungen auf:
  - **Credentials** (`.env`, `config/config.example.env`, Provider-Auth)
  - **Multi-Repo-Zugriffe** (gleichzeitige Änderungen in mehreren Repositories)
  - **Kritische Logik** (Authentifizierung, Datenbank-Schemata, CI/CD-Pipelines)

### Empfohlene Night-Mode-Einstellungen

**Worker-Limit für erste Läufe:**
```bash
python scripts/run_overnight.py --model opencode --model-name mistral/magistral-medium-latest --base-branch develop --workers 1
```

**Explizite Issue-Auswahl (empfohlen für Kalibrierung):**
```bash
python scripts/run_overnight.py --model opencode --model-name mistral/mistral-large-latest --base-branch develop --workers 1 --issue 123 --issue 456
```

**Stärkeres Modell für Review-sensible Issues:**
```bash
python scripts/run_overnight.py --model opencode --model-name mistral/mistral-large-latest --base-branch develop --workers 1
```

**Smoke-Test (direkt prüfen, ob der Workflow funktioniert):**
```bash
python scripts/solve_issues.py --model opencode --model-name mistral/mistral-large-latest --repo <repo-name> --issue <issue-number> --dry-run
```

> ⚠️ **Hinweise:**
> - Night-Mode-Läufe sollten immer auf den `develop`-Branch zielen, um Stabilität in `main` zu gewährleisten.
> - Vermeide breite `--open-issue`-Sweeps während der Kalibrierung. Nutze stattdessen explizite `--issue`-Flags.
> - Die Dokumentation ist rein informativ und enthält keine Secrets.

---

## Benchmark-Modus & Einschränkungen

### `benchmark_issues.py`

Das Skript `scripts/benchmark_issues.py` führt mehrere Model-Kandidaten gegen dieselbe Issue aus, ohne Pull Requests zu erzeugen. Es dient dem Vergleich verschiedener Provider und Modellversionen.

**Verhalten:**
- Ruft `solve_issues.py` für jedes Modell mit `--skip-pr` auf, sodass Commits erstellt aber keine PRs geöffnet werden.
- Jeder Lauf erhält einen eindeutigen Branch-Suffix (`bench/<timestamp>/<model-slug>`) über `--branch-suffix`, um Branch-Kollisionen zwischen Modellen zu vermeiden.
- Ergebnisse werden als JSON-Datei (`benchmark_results_<timestamp>.json`) abgelegt.

**Aktuelle Einschränkungen:**
- **Keine automatische Gewinnerauswahl:** Es existiert noch keine Logik, die aus den Benchmark-Ergebnissen den besten Kandidaten ermittelt und automatisch einen PR erstellt.
- **Keine PR-Promotion:** Ein erfolgreicher Modell-Lauf führt nicht automatisch zu einem PR. Dies muss manuell oder per Skript aus dem gepushten Branch nachgeholt werden.
- **Kein Ensemble-Modus:** Parallele Modell-Läufe werden sequenziell ausgeführt; es gibt kein paralleles Dispatch-System für Benchmark-Sweeps.

### Auswertung von Run-Reports und Worktrees

Nach einem Benchmark-Lauf liegen Run-Reports unter `reports/runs/<timestamp>-<repo>-<issue>/` und ggf. gesicherte Worktrees unter `reports/preserved-worktrees/`. Um zwischen Modellfehler und Pipeline-Fehler zu unterscheiden, sollten folgende Felder im `metadata.json` des Run-Reports ausgewertet werden:

| Feld | Bedeutung | Fehler-Diagnose |
|------|-----------|-----------------|
| `status` | Run-Endstatus (`pr_skipped`, `no_changes`, `worker_failed`, `push_failed`, `validation_failed`, `branch_create_failed`) | `worker_failed` → Modell-Problem; `push_failed` → Pipeline-Problem |
| `worker_exit_code` | Exit-Code des KI-Workers | `!= 0` deutet auf Worker-Absturz hin |
| `preserved_worktree` | Pfad zum gesicherten Worktree für Recovery | Gesetzt bei teilweisem Erfolg (Änderungen vorhanden, aber PR fehlgeschlagen) |
| `provider_scorecard_run_status` | Normalisierter Run-Status aus der Provider-Scorecard | Identisch zu `status`, aber für Dashboard-Abfragen aufbereitet |
| `provider_scorecard_duration_seconds` | Laufzeit des Workers | Ungewöhnlich kurze Laufzeit → Worker frühzeitig abgebrochen |
| `model_selection.reason` | Grund der Modellauswahl | Hilft bei der Einordnung von Fallback-Entscheidungen |
| `resource_diagnostics` | Locking-/Branch-Konflikte | Nicht-leer → parallele Run-Kollision, kein Modellfehler |

**Orientierung:**
- **Modellfehler:** `worker_exit_code != 0`, kurze Laufzeit, `status` endet auf `_failed` ohne `preserved_worktree`.
- **Pipeline-Fehler:** `push_failed`, `branch_create_failed`, `branch_conflict` — hier liegt ein Infrastruktur-Problem vor.
- **Teilerfolg:** `pr_skipped` oder `validation_failed` mit gesetztem `preserved_worktree` — Änderungen existieren, können manuell inspiziert werden.

**Wiederherstellung aus preserved Worktrees:**
```bash
# Worktree inspizieren
ls reports/preserved-worktrees/<timestamp>-<repo>-<issue>/

# Branch aus dem Worktree pushen (falls nicht bereits geschehen)
cd reports/preserved-worktrees/<timestamp>-<repo>-<issue>/repo
git push origin <branch-name>

# Bereinigung alter Worktrees
python scripts/solve_issues.py --cleanup-preserved-worktrees --retention-days 14
```

### Sparsamer Einsatz von Benchmark-Läufen

Benchmark-Läufe verbrauchen Tokens und Provider-Kontingent. Folgende Empfehlungen helfen, Ressourcen zu schonen:

- **Nicht breitflächig einsetzen:** Führe Benchmarks nur auf einer kleinen, repräsentativen Issue aus, nicht auf allen offenen Issues.
- **Modelle gezielt auswählen:** Teste nicht alle verfügbaren Modelle, sondern nur die relevanten Kandidaten (z. B. zwei pro Provider).
- **Limit setzen:** Nutze `--issues` statt offener Sweeps, und vermeide `run_overnight.py` für Benchmark-Sweeps.
- **Ergebnisse wiederverwenden:** Analysiere vorhandene Run-Reports aus `reports/runs/`, bevor neue Benchmark-Läufe gestartet werden.
- **Dashboard konsultieren:** `status_dashboard.py` gruppiert Runs nach Status und zeigt gesicherte Worktrees an, sodass vorhandene Ergebnisse sichtbar sind, bevor neue Läufe anstoßen werden.
