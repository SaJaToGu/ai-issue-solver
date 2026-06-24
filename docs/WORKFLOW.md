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
┌──────────────────────┐
│ 2b. SPLIT PLANNING   │  ← NEU: Aufteilungsschritt vor breiten
│    split_planning.py  │    Solver-Läufen. Analysiert, ob ein
└────────┬─────────────┘    Issue broad ist und erzeugt enge
          │                 Child-Issues mit Wellen-Reihenfolge
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

**Wichtig:** Vor jedem breiten Solver-Lauf MUSS der `split_planning.py`-Schritt
durchlaufen werden. Ein Issue gilt als **broad**, wenn es:
- mehrere unabhaengige Bereiche (`scripts/`, `tests/`, `docs/`) betrifft
- mehr als 5 Bullet-Items oder ToDos enthaelt
- mehr als 2 Markdown-Sektionen hat
- Schluesselwoerter wie "mehrere", "verschiedene" oder "sowohl ... als auch" enthaelt
- ein `enhancement`-, `epic`- oder `feature`-Label traegt

Ein broad Issue darf NICHT direkt an Minimax Code oder einen anderen Worker
uebergeben werden. Es muss vorher in enge, konfliktarme Child-Issues aufgeteilt
werden.

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

### `split_planning.py`
Analysiert ein Parent-Issue auf Breite und erzeugt einen strukturierten
Aufteilungsplan mit Child-Issues, Ausführungswellen und Modell-Empfehlung.

**Flags:**
- `--issue`: Parent-Issue-Nummer (Pflicht)
- `--repo`: GitHub-Repository (Default: `ai-issue-solver`)
- `--dry-run`: Nur anzeigen, nichts ändern
- `--emit-command`: Worker- und `gh issue create`-Kommandos ausgeben
- `--emit-comment`: Split-Plan als Issue-Kommentar posten

**Beispiele:**
```bash
python scripts/split_planning.py --issue 387
python scripts/split_planning.py --issue 387 --emit-command
python scripts/split_planning.py --issue 387 --emit-comment
```

**Ausgabe:**
- `BROAD ISSUE erkannt`: Der Plan enthaelt Child-Issues, Wellen-Reihenfolge
  und Konfliktanalyse. Der Solver darf NUR Child-Issues erhalten.
- `Issue ist NICHT broad`: Kein Split noetig; direkte Übergabe an den Solver.

**Regel:** Ein broad Issue darf NIEMALS direkt an `solve_issues.py` oder
`minimax-code` uebergeben werden. Der `split_planning.py`-Schritt MUSS
vor jedem breiten Solver-Lauf durchlaufen werden.

---

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

> **Welchen Rework-Pfad soll ich nehmen?** Für eine Übersicht
> `--rework` / `--retry` / `--rework-pr` / `--compare-models` vs.
> `rework_workflow.py` siehe die [Decision Matrix](#which-rework-path-do-i-want-decision-matrix-48--412)
> weiter unten.

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

### Rework offener Solver-PRs

Standardmäßig überspringt der Solver Issues, deren Issue-Branch bereits einen
offenen PR hat. Für gezielte Nacharbeit an genau diesem offenen PR kann der Run
bewusst auf demselben Branch fortgesetzt werden:

```bash
python scripts/solve_issues.py --model opencode --repo <repo-name> --issue <issue-number> --rework
```

### Which rework path do I want? (Decision Matrix, §48 / #412)

There are now four rework-adjacent entry points. Use the matrix below to
pick the right one. Each invocation appends one JSON line to
`reports/usage/rework-flags.jsonl` so usage can be analysed after one
release cycle.

| Situation                                                    | Use                                  |
| ------------------------------------------------------------ | ------------------------------------ |
| PR has review feedback (request-changes verdict), I want the solver to read the review threads and push follow-up commits on the same PR branch | `--rework-pr <N>` (PR-keyed, added in #404 / PR #405) |
| Issue-branch already has an open PR and I want to keep working on it (continue the solver run on the same branch, not PR-feedback driven) | `--rework` (Issue-keyed)             |
| Open PR exists and I want to force a fresh solver run anyway (e.g. flaky CI, want to retry the original issue scope) | `--retry`                            |
| Compare multiple models on the same issue in one shot         | `--compare-models` (requires `--retry`) |
| The PR is too large / risky / needs decomposition into sub-issues before any rework | `scripts/rework_workflow.py` (sub-issue planning only) |

**Cheat rule of thumb:**

- *"There is review feedback on PR #N"* → `--rework-pr <N>`
- *"There is an open PR for issue #M and I want to push more commits to its branch"* → `--rework`
- *"There is an open PR but I want to start over / compare models"* → `--retry` (or `--retry --compare-models`)
- *"The PR is too big or risky, decompose it first"* → `rework_workflow.py`

Der Modus wird verweigert, wenn mehrere offene PR-Branches gefunden werden oder
der PR-Head/Base-Branch nicht eindeutig zum geplanten Issue-Branch passt.

### PR-keyed Rework via Review Feedback (`--rework-pr`)

Wenn ein PR Review-Feedback erhalten hat (Verdict "request changes" mit
konkreten Blockern und/oder Suggestions), übernimmt `--rework-pr <N>` das
bisherige Mavis-as-dev-Refactor: Es liest die offenen Review-Threads, holt
den aktuellen PR-Diff, baut einen fokussierten Prompt (PR-Kontext +
Review-Feedback + Base-Branch-Info), spawnt einen Worker auf demselben
PR-Branch und pusht Follow-up-Commits. CI läuft automatisch erneut, der
Reviewer wird via PR-Comment re-notified.

Im Gegensatz zu `--rework` (Issue-keyed, setzt einen Solver-Run auf dem
Issue-Branch fort) ist `--rework-pr` PR-keyed: keine neue Branch-Anlage,
kein Kampf mit `skip_existing_pr`, fokussierter auf Review-Feedback statt
auf den ursprünglichen Issue-Scope.

```bash
python scripts/solve_issues.py --rework-pr <N>
python scripts/solve_issues.py --rework-pr <N> --dry-run    # nur Prompt anzeigen
python scripts/solve_issues.py --rework-pr <N> --model opencode/deepseek-v4-flash-free
```

**Ablauf:**

1. Unresolved review threads via GitHub client holen
2. PR-Diff (current tip vs base) fetchen
3. Fokussierten Prompt konstruieren (billiger als Volllauf — Issue-Scope
   muss nicht re-derived werden)
4. Worker auf demselben Branch spawnen, Follow-up-Commits pushen
5. Run-Report unter `reports/runs/pr-{N}-rework-{ts}/`

**Out of scope** (von #404 explizit ausgeschlossen):

- Auto-Merge nach erfolgreichem Rework — Menschen approven weiterhin
- Cross-PR-Rework (ein Rework → mehrere abhängige PRs)
- Webhook-getriebenes automatisches Rework auf Review-Event
  (braucht einen Server; deferred)
- LLM-basierte Decomposition von "oversized + rework" → Split-Pfad
  (orthogonal zum Backward-Split-Loop aus #402)

**Wann nutzen:**

- Review-Verdict "request changes" + konkrete Fixes
- Worker hat was Brauchbares produziert, aber Reviewer hat
  Line-Cap / Naming / Test-Coverage angemerkt
- NICHT für: neue Features, breite Refactors, scope-creep — dafür
  ist ein neuer Issue besser

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

---

## Shared Orchestration Modules

The solver pipeline is built on a shared orchestration layer that eliminates
duplicate code across entry points. The following modules serve as the single
source of truth:

### `scripts/solver_commands.py`

Command construction for all solver entry points (`solve_issues.py`,
`solve_issues_batch.py`, `run_overnight.py`, `benchmark_issues.py`).
Key functions:

- `build_single_solver_command()` — flags for one `solve_issues.py` invocation
- `build_batch_command()` — flags for `solve_issues_batch.py`
- `build_dashboard_command()` — flags for `status_dashboard.py`
- `add_solver_core_flags()` / `add_budget_flags()` / `add_fallback_flags()` /
  `add_health_flags()` — reusable flag groups

Callers import from `solver_commands` directly. Previously duplicated wrappers
in `run_overnight.py` were removed (see [#383](https://github.com/ai-issue-solver/ai-issue-solver/issues/383)).

### `scripts/solver_reporting.py`

Run reporting, diagnostics, health classification, and outcome normalization.
Key functions:

- `parse_summary_file()` — key/value parser for `summary.txt` (shared by
  `status_dashboard.py`, `solver_supervisor.py`, `watchdog.py`)
- `classify_run_status()` — raw status → dashboard category (replaces
  per-script `classify_status` duplicates)
- `read_normalized_run_outcome()` — unified read-side view of a run report
- `build_run_outcome()` — structured outcome schema for benchmarking
- `parse_datetime_value()` / `parse_created_at()` / `latest_datetime()` —
  shared datetime parsing
- `write_run_report()` / `create_run_report()` — report persistence
- `detect_opencode_runtime_diagnostics()` — WAL/Edit-loop detection
- `classify_worker_health()` — health classification for monitoring

### `scripts/solver_repository.py`

Git repository operations: `clone_repo()`, `create_branch()`,
`commit_and_push()`, `git_status_porcelain()`, `branch_has_changes_against_base()`.

### `scripts/solver_run_resources.py`

Resource tracking and locking: `RunResources`, `ResourceLock`,
`create_run_resources()`, `cleanup_stale_locks()`.

### `workers/execution.py`

Worker subprocess management: `run_worker_subprocess()`,
`classify_worker_outcome()`, `WorkerHealthConfig`.

---

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



## Validierung gemergter PRs (Manuelle Änderungen & Solver-Runs)

Nach jedem Merge — egal ob aus Mavis-as-dev (manuell) oder aus einem
Solver-Run — kann der aktuelle Stand der PRs in einer Liste mit
`validation_run check-prs` geprüft werden. Das ist der schnellste Weg
zu sehen, ob alle relevanten PRs gemerged sind und CI grün ist.

```bash
set -a && . config/.env && set +a
export GITHUB_OWNER=$GITHUB_USER
export GITHUB_REPO=ai-issue-solver

# Explizit: PR-Nummern prüfen
python scripts/validation_run.py check-prs --numbers 416 417 419

# Ohne Argumente: scannt offene Issues (bis --max N) und prüft deren PRs
python scripts/validation_run.py check-prs --max 20
```

Output:

```
Checking PRs for up to 3 numbers...
  #416 [MERGED] CI:GREEN  [AI] Fix: Consolidate solver orchestration across
  #417 [MERGED] CI:RED     [AI] Fix: Retire legacy orchestration helpers
  #419 [MERGED] CI:GREEN  [AI] Fix: Forward --max-run-cost-usd
```

**Was das Script tut:**

- Sucht pro Nummer zuerst als PR (per `get_pull_request` —
  funktioniert auch für gemergte PRs deren `ai/fix-issue-N`-Branch
  durch `--delete-branch` schon gelöscht ist).
- Fallback: PR per Branch-Name `ai/fix-issue-N` (legacy-Pfad für
  offene PRs deren Branch noch existiert).
- Fragt den CI-Status auf der **PR-Head-SHA** ab (nicht auf dem
  Merge-Commit — der ist neu und hat oft noch keine Checks).
- Kombiniert Legacy-Commit-Statuses und Check-Runs; `GREEN` nur wenn
  beide grün bzw. fehlend sind.

**Deprecation-Hinweis:** Das frühere `--issues` wird weiter akzeptiert
(deprecated alias für `--numbers`). Bei `--issues <N>` schaut das
Script nach dem Branch `ai/fix-issue-N` und scheitert für gemergte
PRs — das war der ursprüngliche Bug, den dieser Workflow-Step fixt.


## Issue/PR/Commit Netzwerk (build_graph.py)

`scripts/build_graph.py` baut einen Graph aus Issue↔PR↔Commit-Relations
über die GitHub API und lokale Run-Reports. Datenquellen:

- **GitHub API** (via `gh api`) — gemergte PRs mit verlinkten Issues,
  LOC-Daten (`additions`/`deletions`/`changed_files`), Merge-Commit SHA,
  Branch-Referenz, Labels und Autor. Die Issue↔PR-Verknüpfung erfolgt
  über ``Closes #N`` / ``Fixes #N`` / ``Resolves #N`` im PR-Body.
- `docs/BACKLOG/open.md` — aktive §-Items, parst §-Nummer + Title +
  optional `Parent: #N`-Referenz (für `parent_of`-Edges)
- `reports/runs/*/summary.txt` + `metadata.json` — Solver-Run-Metadaten
  (PR-URL, Model, Cost wo vorhanden)

Output als JSON (default) oder DOT (Graphviz). Node-Typen: `issue`,
`pr`, `commit`. Edge-Typen: `closes` (issue→pr), `merged_into`
(pr→commit), `parent_of` (issue→issue).

```bash
# Default: JSON nach stdout
python scripts/build_graph.py

# Graphviz DOT für Visualisierung
python scripts/build_graph.py --format dot > /tmp/issue-network.dot
dot -Tsvg /tmp/issue-network.dot > /tmp/issue-network.svg

# Nur PRs ab einem bestimmten Datum
python scripts/build_graph.py --since 2026-06-01

# In Datei schreiben
python scripts/build_graph.py --output /tmp/graph.json
```

### Annotations

Cost (USD) stammt aus den lokalen Run-Reports, LOC (`additions`/
`deletions`/`changed_files`) aus der GitHub PR API, Model aus den
Run-Reports. Per `--color-by <dimension>` werden die Knoten eingefärbt:

| Dimension | Was es zeigt | Farbschema |
|---|---|---|
| `model` | Welche Modelle für welche Issue-Typen | Discrete map (opencode=grün, codex=blau, etc.) |
| `cost` | Teure vs günstige PRs | Grün (günstig) → Rot (teuer) |
| `loc` | Große vs kleine Refactors | Grün (klein) → Rot (groß) |
| `time` | Velocity-Trend | Aktuell binär (gemerkt vs nicht) — TODO: gradient |
| `difficulty` | narrow / medium / broad / unsolved | Heuristik aus LOC + Cost + Run-State |

### Beispiel-Output (gekürzt)

```json
{
  "nodes": [
    {"id": "issue-357", "type": "issue", "title": "Consolidate solver orchestration", "state": "done", "loc_add": 384, "loc_del": -205, "files": 9},
    {"id": "pr-416", "type": "pr", "title": "PR #416", "head_sha": "f17783f", "color": "#22c55e", "model": "opencode"},
    {"id": "commit-f17783f", "type": "commit", "title": "f17783f3"}
  ],
  "edges": [
    {"from": "issue-357", "to": "pr-416", "type": "closes"},
    {"from": "pr-416", "to": "commit-f17783f", "type": "merged_into"}
  ]
}
```

### Einschränkungen

- Cost-Daten hängen davon ab ob der Run-Report `estimated_cost`
  schreibt (derzeit nicht alle Runs tun das — Memory-noted: 'User-Cost-Cap
  nicht enforced'). Wenn leer, fehlt die Cost-Annotation stillschweigend.
- Der Parent-Of-Edge wird nur erkannt wenn `Parent: #N` explizit im
  Issue-Body steht (wenige Issues haben das aktuell).
- Die GitHub-API-Daten sind immer wohlgeformt — LOC wird aus den PR-
  Feldern `additions`/`deletions`/`changed_files` bezogen, nicht aus
  Textparsing.
- `gh` muss installiert und authentifiziert sein (`gh auth login`).
  Fehlt `gh`, gibt das Script eine Warnung aus und erzeugt einen
  leeren Graph (ohne abzustürzen).

### Future Work (später, nicht in dieser Version)

- **Dashboard-Tab** in `status_dashboard.py` als Renderer für die
  JSON-Datei (heute CLI-only — Status-Dashboard hat 3280 Zeilen,
  Refactor wäre eigenes Stück Arbeit).
- **Native App View** — JSON ist bereits app-friendly, sobald die
  App das Format liest.
- **Actions Workflow Logs** — Cost/Model/Runtime-Daten könnten
  künftig direkt aus den Workflow-Logs statt aus lokalen Run-Reports
  bezogen werden (`gh run view <id> --log`).
