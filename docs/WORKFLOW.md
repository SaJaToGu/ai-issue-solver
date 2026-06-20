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
          │
          ▼
┌─────────────────┐
│ 4. rework /      │  ← Bei roter CI, zu großem PR oder Review-Bedenken
│    merge         │    gezielt nacharbeiten oder mergen
└─────────────────┘
```

---

## Branch-Modell

- `main` bleibt stabil, `develop` sammelt laufende Änderungen.
- Feature-Branches referenzieren GitHub Issues (z.B. `ai/fix-issue-10`).
- `solve_issues.py` nutzt standardmäßig den GitHub-Default-Branch des Ziel-Repositories.
- Für `develop`-Modelle: `--base-branch develop` setzen.

### Default-Branch-Preflight für Solver-Läufe

Bevor ein Validierungs- oder Night-Mode-Lauf gestartet wird, sollte der
Default-Branch des Ziel-Repos verifiziert werden. Zeigt GitHub auf den
falschen Branch, klont der Solver unter Umständen eine Branch-Version
ohne die beabsichtigten Änderungen. Es genügt, einen der folgenden
Operator-Checks auszuführen:

- `git remote show origin` (lokaler Clone) – prüft `HEAD branch`.
- `gh repo view <repo> --json defaultBranchRef --jq .defaultBranchRef.name` (GitHub CLI).

Alternativ `--base-branch` explizit an `run_overnight.py`, `solve_issues.py`
oder `solve_issues_batch.py` übergeben, damit der Solver unabhängig vom
Remote-Default arbeitet.

---

## Scripts im Detail

Die Modellauswahl folgt der gemeinsamen, englischsprachigen Policy in
[MODEL_OVERRIDE_POLICY.md](MODEL_OVERRIDE_POLICY.md): Kommandozeilen-Overrides
gelten nur fuer den einzelnen Lauf; Defaults bleiben in Rollen- oder
Provider-Konfiguration.

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

**Repository-Profil (GitHub-first, lokaler Fallback):**
Sobald der Clone erfolgreich war, ruft `solve_issues.py` `build_repo_profile()`
aus `scripts/repo_profile.py` auf. GitHub liefert Sprache, Topics, Workflows
sowie offene PRs/Issues; ein lokaler Marker-Scan (`DESCRIPTION`, `renv.lock`,
`pyproject.toml`, `package.json`, …) dient als Fallback, falls GitHub nicht
erreichbar ist oder das Repo offline bearbeitet wird. Das Ergebnis landet
unter `repo_profile` in `metadata.json` und als `repo_profile:`-Block in
`summary.txt`. Secret-Pfade (`.env`, `auth.json`, `secrets/*`) werden
gefiltert, bevor sie auf die Festplande geschrieben werden.

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

### `rework_workflow.py`
Erstellt strukturierte Rework-Kontexte, wenn ein generierter PR nicht direkt
gemergt werden sollte. Das gilt nicht nur für rote CI, sondern auch für grüne,
aber zu große oder riskante PRs.

**Typische Auslöser:**
- CI oder lokale Tests sind rot
- PR ist grün, aber zu groß, zu breit oder nicht reviewbar genug
- Worker wurde unterbrochen, hat aber verwertbare Änderungen erzeugt
- User-Review fordert eine konkrete Korrektur
- Ein alter PR soll durch einen engeren Ansatz ersetzt werden

**Beispiele:**
```bash
python scripts/rework_workflow.py --from-note "PR #288 is CI green but too large for #223" --dry-run
python scripts/rework_workflow.py --from-pr 288 --rework-reason risky_pr_rework --dry-run
python scripts/rework_workflow.py --from-run reports/runs/<run-id> --dry-run
```

**Same-Branch-Rework:**
Wenn ein PR grundsätzlich brauchbar ist, aber einen kleinen Nacharbeitsbedarf
hat, kann ein Modell auf demselben PR-Branch weiterlaufen. Der Prompt sollte
dann den PR, Branch, konkreten Fehler, erlaubte Dateien, Tests und Out-of-Scope
Punkte nennen. Vorher:

```bash
git status --short --branch
gh pr view <pr> --json number,title,state,mergeable,headRefName,changedFiles,additions,deletions,url
gh pr checks <pr>
```

**Merge-Guard:**
Ein PR wird nicht allein wegen grüner Checks gemergt. Wenn Diff-Größe, Scope,
Risko oder unterbrochene Worker-Ausgabe unklar sind, erst Rework klassifizieren
und den nächsten Slice explizit machen.

---

### `review_pr.py`
Führt eine AI-gestützte PR-Prüfung mit einer der Reviewer-Rollen aus:
`code`, `architecture` oder `documentation`.

**Flags:**
- `--pr`: Pull-Request-Nummer
- `--role`: Reviewer-Rolle (`code`, `architecture`, `documentation`)
- `--dry-run`: Prompt, Modell und Diff laden, aber kein Modell aufrufen
- `--model-override`: Modell nur für diesen Review-Lauf überschreiben, ohne
  `config/role_routing.yaml` zu ändern

**Beispiele:**
```bash
python scripts/review_pr.py --pr 368 --role code --dry-run
python scripts/review_pr.py --pr 368 --role code --model-override minimax/minimax-m3
```

`--model-override` ist für kostenbewusste Standard-Reviews gedacht: Die
Rollen-Konfiguration bleibt stabil, aber ein einzelner Lauf kann ein günstigeres
oder frisch getestetes OpenRouter-Modell verwenden.

---

### `post_merge_cleanup.py`
Räumt nach gemergten AI-Pull-Requests auf.

**Automatische Aktionen (mit `--apply`):**
- Gemergte AI-PRs zusammenfassen
- Offene Issues schließen (bei Closing-Keywords oder Branch-Referenz)
- Gemergte AI-Branches löschen
- Stale Branches melden
- Optional abgeschlossene Einträge aus `docs/BACKLOG/open.md` entfernen

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

### OpenCode WAL/SQLite-State

Vor echten OpenCode-Worker-Läufen prüft der Solver den globalen OpenCode-State.
Wenn ein laufender `opencode serve`-Prozess nicht zur aktuellen CLI-Version oder
zum aktuellen Executable passt, bricht `solve_issues.py` ab. `solve_issues_batch.py`
und `run_overnight.py` prüfen denselben Zustand früh, bevor Jobs gestartet werden.

Diagnose:

```bash
python scripts/solve_issues.py --model opencode --diagnostic
```

Recovery bei blockiertem Versions-/State-Mix:

1. Laufende OpenCode- oder MiniMax-Code-Prozesse beenden.
2. Die Diagnose erneut ausführen.
3. Nur wenn kein OpenCode-Prozess mehr läuft, verbliebene `opencode.db-wal`
   und `opencode.db-shm` entfernen.
4. Nicht löschen: `auth.json`, `account.json` oder `opencode.db`.

Ein bewusstes Überstimmen ist möglich, aber nicht empfohlen:

```bash
python scripts/solve_issues.py --model opencode --allow-opencode-state-conflict
```

> ⚠️ **Hinweise:**
> - Night-Mode-Läufe sollten immer auf den `develop`-Branch zielen, um Stabilität in `main` zu gewährleisten.
> - Vermeide breite `--open-issue`-Sweeps während der Kalibrierung. Nutze stattdessen explizite `--issue`-Flags.
> - Die Dokumentation ist rein informativ und enthält keine Secrets.

---

## Benchmark-Modus (`benchmark_issues.py`)

`benchmark_issues.py` vergleicht mehrere OpenCode-Modelle auf einer einzelnen, sicheren Issue. Es startet pro Modell einen Solverlauf mit `--skip-pr`, schreibt die Ergebnisse als JSON nach `benchmarks/` und erzeugt bewusst keinen Pull Request.

### Aktuelle Funktionsweise

- Der Benchmark ruft `scripts/solve_issues.py` mit `--model opencode`, `--model-name <modell>`, `--skip-pr` und einem eindeutigen `--branch-suffix` auf.
- Ohne `--models` werden die freien OpenCode-Modelle aus `FREE_OPENCODE_MODELS` verwendet.
- Jeder Modelllauf bekommt einen eigenen Branch-Suffix wie `bench/<timestamp>/<model-slug>`, damit parallele oder wiederholte Läufe nicht kollidieren.
- Wenn ein Run-Report gefunden wird, übernimmt die Benchmark-Ausgabe das strukturierte `run_outcome` aus `metadata.json`.

### Bekannte Grenzen

- Der Benchmark wählt noch keinen Gewinner automatisch aus.
- Er promotet kein Ergebnis automatisch in einen PR.
- Alte Benchmark-Branches und gespeicherte Benchmark-JSONs werden noch nicht automatisch bereinigt.
- Ein erfolgreicher `--skip-pr`-Lauf bedeutet nur: Branch/Änderungen sind für Review verfügbar. Merge-Entscheidung und PR-Erstellung bleiben manuell.

### Recovery-Signale

Die wichtigsten `run_outcome`-Felder helfen, Modellqualität und Pipeline-Probleme zu trennen:

| Signal | Bedeutung | Nächster Schritt |
|---|---|---|
| `delivery_status: pushed_without_pr` + `failure_class: success` | Modell hat Änderungen geliefert; PR wurde absichtlich übersprungen | Branch prüfen und bei Bedarf PR erstellen |
| `delivery_status: push_failed` + `recovery_status: preserved_worktree` | Änderungen existieren, aber Push/Delivery ist fehlgeschlagen | Preserved Worktree prüfen und Recovery-Hinweise nutzen |
| `has_changes: false` + `failure_class: noop` | Modell hat keine Änderung geliefert | Anderes Modell oder präzisere Issue-Beschreibung erwägen |
| `failure_class: model_failure` | Worker ist ohne verwertbare Änderung fehlgeschlagen | Sauber neu starten oder anderes Modell testen |
| `failure_class: pipeline_failure` | Solver-/GitHub-/Delivery-Problem, nicht zwingend Modellversagen | Run-Report, `RECOVERY.md` und Worktree prüfen |

Preserved Worktrees liegen unter `reports/preserved-worktrees/`. Sie enthalten eine `RECOVERY.md` mit konkreten Befehlen für Inspektion, Push oder manuelle PR-Erstellung.

### Sparsamer Einsatz

- Standardmäßig nur ein kleines, ungefährliches Issue benchmarken.
- Für normale Arbeit ein Modell verwenden; alle freien OpenCode-Modelle nur gelegentlich, zum Beispiel bei jedem zehnten Dokumentationslauf.
- Für einen engen Vergleich `--models` mit konkreten OpenCode-Modellnamen verwenden.

Beispiele:

```bash
# Alle freien OpenCode-Modelle
python scripts/benchmark_issues.py --issue 184

# Nur zwei ausgewählte OpenCode-Modelle
python scripts/benchmark_issues.py --issue 184 --models opencode/deepseek-v4-flash-free,opencode/mimo-v2.5-free

# Planung ohne Änderungen
python scripts/benchmark_issues.py --issue 184 --dry-run
```
