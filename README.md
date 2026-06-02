# 🤖 AI Issue Solver — Morpheus-Style Workflow

> Automatisches Analysieren, Erstellen und Lösen von GitHub Issues mit KI-Unterstützung  
> Inspiriert von [TheMorpheus407](https://www.youtube.com/user/TheMorpheus407) / [the-morpheus.de](https://www.the-morpheus.de)

---

## 📋 Inhaltsverzeichnis

- [Was macht dieses Repo?](#was-macht-dieses-repo)
- [Repository-Metadaten](#repository-metadaten)
- [Sprachrichtlinie](#sprachrichtlinie)
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

**Status-Überblick:** `github_summary.py` zeigt offene Issues, offene PRs,
zuletzt gemergte PRs und fehlgeschlagene GitHub-Actions-Runs kompakt über die
GitHub API. Die GitHub CLI wird dafür nicht benötigt.

**Post-Merge Cleanup:** `post_merge_cleanup.py` fasst gemergte AI-PRs zusammen,
schließt sicher referenzierte Issues, löscht gemergte AI-Branches und meldet
alles, was manuell geprüft werden sollte. Ohne `--apply` läuft es als Dry-Run.

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

## Sprachrichtlinie

Dieses Projekt verwendet eine klare Sprachtrennung:

- **🇩🇪 Deutsch** für nutzerzugewandte Dokumentation: README, Workflow-Beschreibungen, Setup-Anleitungen, CLI-Ausgaben
- **🇬🇧 Englisch** für technische Inhalte: Backlog, Issue-Bodies, Tests, Code-Kommentare, KI-Prompts

Detaillierte Richtlinien finden sich in [docs/LANGUAGE_POLICY.md](docs/LANGUAGE_POLICY.md).

**Begründung:** Benutzerdokumentation bleibt in der Zielsprache (Deutsch), während technische Inhalte für bessere KI-Tool-Kompatibilität auf Englisch bleiben dürfen.

---

## Voraussetzungen

| Tool | Version | Zweck |
|------|---------|-------|
| Python | ≥ 3.10 | Haupt-Scriptsprache |
| `gh` CLI | optional | Manuelle GitHub-Diagnose außerhalb der Scripts |
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
python scripts/solve_issues.py --model codex       # Codex CLI
python scripts/solve_issues.py --model opencode    # OpenCode CLI
python scripts/solve_issues.py --model openrouter  # OpenRouter (aider)
python scripts/solve_issues.py --model mistral-vibe # Mistral Vibe CLI
python scripts/solve_issues.py --model claude      # Anthropic Claude
python scripts/solve_issues.py --model openai      # OpenAI GPT-4
python scripts/solve_issues.py --model ollama      # Lokales Modell
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
python scripts/import_repolens_results.py --report-dir reports/repolens --repo ai-issue-solver
python scripts/import_repolens_results.py --report-dir reports/repolens --repo ai-issue-solver --apply --confirm-create
```

**Flags:**
- `--dry-run` — zeigt Issues mit Titel, Labels und Body an ohne sie zu erstellen
- `--confirm-create` — erforderlich, bevor echte GitHub-Issues erstellt werden
- `--repo` — nur für ein bestimmtes Repo
- `--priority high` — nur High-Priority Issues

`create_backlog_issues.py` liest [docs/BACKLOG.md](docs/BACKLOG.md) und erstellt
daraus die initialen Projekt-Issues. Ohne `--apply --confirm-create` läuft es
als Dry-Run.

`import_repolens_results.py` liest lokale RepoLens-Markdown-Reports rekursiv aus
`--report-dir`, erkennt Findings aus Severity-Headings oder Listenpunkten und
bereitet daraus GitHub-Issues mit Labels wie `repolens`, `security`,
`performance` und `severity:high` vor. Standard ist eine Vorschau; echte Issues
werden nur mit `--apply --confirm-create` erstellt. Importierte Issues erhalten
einen stabilen Marker im Body, damit offene RepoLens-Issues nicht doppelt
angelegt werden.

RepoLens-Audits sollten getrennt vom Solver laufen. Der Solver braucht
GitHub-Write-Zugriff fuer Branches und PRs; RepoLens bekommt diesen Zugriff
nicht automatisch. Fuer lokale Audits gibt es einen Docker-Wrapper mit
read-only Projektmount und separatem Report-Mount:

```bash
scripts/run_repolens_docker.sh \
  --project-dir /path/to/repo \
  --report-dir /path/to/repo/reports/repolens \
  --domain security \
  --network none \
  --cpus 2 \
  --memory 4g
```

Der Wrapper mountet das Projekt als `/project:ro` und schreibt Reports nach
`/reports`. Er reicht keine `.env`, kein `GITHUB_TOKEN` und keine GitHub-Write-
Credentials in den Container. Falls ein RepoLens-Agent Provider-Zugriff braucht,
wird Netzwerk bewusst ueber `--network bridge` oder ein anderes Docker-Netzwerk
aktiviert; fuer lokale Analysen bleibt `--network none` die sichere Vorgabe.

---

### `solve_issues.py`
Löst offene Issues automatisch mit KI + Codex, Mistral Vibe, OpenCode oder aider.

```bash
python scripts/solve_issues.py --model codex --repo BedBoxDrawerRole
python scripts/solve_issues.py --model opencode --model-name mistral/mistral-small-2603 --repo BedBoxDrawerRole
python scripts/solve_issues.py --model mistral-vibe --repo BedBoxDrawerRole
python scripts/solve_issues.py --model claude --repo BedBoxDrawerRole
python scripts/solve_issues.py --model mistral --repo BedBoxDrawerRole
python scripts/solve_issues.py --model mistral --model-name magistral-small-2509
python scripts/solve_issues.py --model ollama --model-name llama3
python scripts/solve_issues_batch.py --model codex --repo BedBoxDrawerRole --workers 2
python scripts/run_overnight.py --model codex --base-branch develop --workers 2
```

Das Script verdichtet die Worker-Ausgabe live auf Status-, Planungs-, Warn- und
Ergebniszeilen. Detailausgaben wie lange Diffs oder Kommando-Logs werden im
Terminal ausgeblendet und nur einmal am Ende gezählt; der vollständige Rohoutput
landet weiterhin unter `reports/runs/` im Run-Report. Für jeden echten
Issue-Lauf legt das Script dort ein zeitgestempeltes Verzeichnis an. Die
`summary.txt` enthält ausgewähltes Repository, Issue-Nummer, Branch, Modell,
Worker-Exitcode, PR-URL falls vorhanden sowie einen kurzen Output-Tail; der
vollständige Worker-Output liegt zusätzlich in `worker-output.log`. Nach dem
Lauf zeigt das Script eine kompakte Git-Übersicht mit geänderten Dateien,
Einfügungen/Löschungen, Diff-Stat und kurzer Diff-Vorschau. Ein erfolgreicher
Worker-Lauf ohne Dateiänderungen wird
als No-op behandelt und erzeugt keinen Commit. Falls Codex mit einem
Nicht-Null-Exitcode beendet, aber Änderungen im Arbeitsbaum liegen, prüft das
Script diese Änderungen weiter und zeigt die letzten Worker-Zeilen als Diagnose.
Wenn Codex das Nachrichtenlimit meldet und eine Reset-Zeit ausgibt, pausiert
`solve_issues.py` bis zu diesem Zeitpunkt und versucht dasselbe Issue danach
erneut, statt die restlichen Issues sofort als Fehler zu zählen.

Scheitert ein Lauf erst nach nutzbaren Änderungen, etwa bei `push_failed`,
`pr_failed`, `pr_failed_from_existing_branch` oder einem abbrechenden
Worker-Status mit wiederherstellbaren Änderungen, verschiebt das Script den
temporären Klon nach `reports/preserved-worktrees/`. Das gilt auch für
`rate_limit_deferred`, wenn Codex wegen eines nicht fortsetzbaren Rate-Limits
abbricht und bereits Änderungen vorliegen. Die `summary.txt` und
`metadata.json` des Run-Reports enthalten dann `preserved_worktree`, einen
Cleanup-Befehl und kurze Recovery-Kommandos. Vor dem Sichern wird die
Git-Remote-URL auf die öffentliche GitHub-URL zurückgesetzt, damit kein Token
im erhaltenen Worktree liegen bleibt.

Manuelle Wiederherstellung aus einem gesicherten Worktree:

```bash
cd reports/preserved-worktrees/<run>/<repo>
git status --short
git diff --stat origin/main...HEAD
git push origin HEAD:<branch>
```

Danach kann der PR manuell erstellt oder `solve_issues.py` erneut gestartet
werden, damit die Branch-Recovery-Logik den vorhandenen Branch weiterverwendet.
Alte gesicherte Worktrees lassen sich mit einer 14-Tage-Retention aufräumen:

```bash
python scripts/solve_issues.py --cleanup-preserved-worktrees --dry-run
python scripts/solve_issues.py --cleanup-preserved-worktrees
python scripts/solve_issues.py --cleanup-preserved-worktrees --retention-days 30
```

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
- `--model` — `codex`, `mistral-vibe`, `opencode`, `claude`, `openai`, `mistral` oder `ollama`
- `--model-name` — spezifisches Modell, z.B. für Codex, Mistral oder Ollama
- `--dry-run` — zeigt Plan ohne Änderungen
- `--issue` — nur ein bestimmtes Issue lösen
- `--defer-codex-rate-limit` — bei Codex-Limits nicht im Einzel-Solver
  schlafen; für Batch-Läufe gedacht

---

### `solve_issues_batch.py`
Löst mehrere Issues parallel, aber mit begrenzter Worker-Zahl. Der Batch-Runner
ermittelt die offenen Issues, dedupliziert identische `(Repo, Issue)`-Jobs und
startet pro Job einen isolierten `solve_issues.py`-Prozess. Ein fehlschlagender
Worker stoppt den Batch nicht; die übrigen Jobs laufen weiter. Die Ausgabe wird
pro Job gesammelt und erst nach Abschluss dieses Jobs gedruckt, damit parallele
Worker-Logs lesbar bleiben.
Vor dem Start der Worker schreibt der Batch-Runner leichte Queue-Reports unter
`reports/runs/`. Das Status-Dashboard zeigt dadurch auch wartende Jobs mit Repo,
Issue, Modell, geplantem Base-Branch und Queue-Zeitpunkt. Sobald ein Worker den
Job übernimmt, nutzt der Einzel-Solver denselben Report-Pfad und ersetzt den
Queue-Status durch den normalen Run-Report.
Meldet ein Codex-Worker ein Nachrichtenlimit mit Reset-Zeit, markiert der
Batch-Runner den betroffenen Job als verzögert und startet ihn nicht sofort
erneut. Mit `--requeue-rate-limited` wird der Job nach der Reset-Zeit wieder in
die Queue gelegt; bis dahin laufen andere verfügbare Jobs weiter.
Der Batch-Runner überwacht außerdem laufende Worker-Prozesse: Bleibt die
Worker-Ausgabe länger als das Health-Timeout aus, kann er nur warnen,
den Prozess stoppen oder den Job neu einplanen. Codex-Rate-Limit-Wartezeiten
mit zukünftiger Reset-Zeit werden dabei nicht als unhealthy behandelt.

```bash
python scripts/solve_issues_batch.py --model codex --workers 2
python scripts/solve_issues_batch.py --model claude --repo BedBoxDrawerRole --workers 3
python scripts/solve_issues_batch.py --model codex --repo ai-issue-solver --issue 23 --issue 24 --dry-run
python scripts/solve_issues_batch.py --model codex --workers 2 --requeue-rate-limited
python scripts/solve_issues_batch.py --model codex --workers 2 --fallback-model mistral --fallback-model-name magistral-medium-2509
python scripts/solve_issues_batch.py --model codex --workers 2 --unhealthy-action retry
python scripts/plan_issue_batches.py --repo ai-issue-solver --emit-commands --model codex
```

**Flags:**
- `--workers` — maximale parallele Worker, Standard: `2`
- `--issue` — kann mehrfach angegeben werden
- `--requeue-rate-limited` — Codex-Jobs nach erkanntem Reset erneut einplanen
- `--rate-limit-retries` — maximale Requeue-Versuche pro rate-limitiertem Job,
  Standard: `1`
- `--fallback-model` / `--fallback-model-name` — expliziter Provider-Fallback
  nur bei erkanntem Codex-Rate-Limit; normale Fehler wechseln den Provider nicht
- `--worker-health-timeout-minutes` — Minuten ohne Worker-Ausgabe bis zur
  Health-Warnung, Standard: `60`
- `--unhealthy-action` — Verhalten bei unhealthy Worker: `warn`, `stop` oder
  `retry`, Standard: `warn`
- `--unhealthy-retries` — maximale Retry-Versuche für unhealthy Jobs bei
  `--unhealthy-action retry`, Standard: `1`
- alle relevanten Solver-Flags wie `--model`, `--model-name`, `--repo`,
  `--label`, `--base-branch`, `--dry-run` und `--close-issues`

`plan_issue_batches.py` plant offene Issues lokal in konfliktarme Wellen, ohne
Worker zu starten. Es schaetzt erwartete Datei-Ueberschneidungen aus Titel,
Body, Labels und optionalen `Touches:`-Zeilen im Issue-Body. Mit
`--emit-commands` gibt es passende `solve_issues_batch.py`-Kommandos pro Welle
aus.

---

### `run_overnight.py`
Startet einen längeren unbeaufsichtigten Lauf mit Preflight und Abschlussbericht.
Der Wrapper zieht zuerst den Basis-Branch per `git pull --ff-only`, führt die
Tests aus, startet danach `solve_issues_batch.py` mit Worker-Limit und
regeneriert am Ende das lokale Status-Dashboard. Jeder Schritt schreibt ein
eigenes Log unter `reports/overnight/<timestamp>/`; die finale `summary.txt`
verlinkt Pull-, Test-, Batch- und Dashboard-Log für die Kontrolle am nächsten
Morgen.

```bash
python scripts/run_overnight.py --model codex --base-branch develop --workers 2
python scripts/run_overnight.py --model claude --repo BedBoxDrawerRole --workers 3
python scripts/run_overnight.py --model codex --issue 23 --issue 24 --dry-run --skip-pull
python scripts/run_overnight.py --model codex --workers 2 --fallback-model mistral --fallback-model-name magistral-medium-2509
```

Wenn Pull oder Tests fehlschlagen, startet der Batch nicht. Das Dashboard und die
finale Summary werden trotzdem geschrieben, damit der Abbruchgrund sichtbar
bleibt.

**Flags:**
- `--workers` — maximale parallele Batch-Worker, Standard: `2`
- `--base-branch` — Branch für Pull und Solver-Basis, Standard: `main`
- `--test-command` — Preflight-Testbefehl, Standard:
  `python -m unittest discover -s tests`
- `--skip-pull` / `--skip-tests` — einzelne Preflight-Schritte bewusst auslassen
- `--log-root` — Zielverzeichnis für Overnight-Logs, Standard:
  `reports/overnight`
- `--fallback-model` / `--fallback-model-name` — an den Batch-Runner
  weitergereichter Fallback fuer erkannte Codex-Rate-Limits
- alle relevanten Batch-Flags wie `--model`, `--model-name`, `--repo`,
  `--issue`, `--label`, `--dry-run`, `--close-issues` und Dashboard-Optionen

---

### `github_summary.py`
Zeigt eine kompakte Review- und Statusübersicht über die GitHub API.

```bash
python scripts/github_summary.py
python scripts/github_summary.py --repo ai-issue-solver
python scripts/github_summary.py --limit 3 --merged-days 7 --run-days 7
```

**Enthält pro Repository:**
- offene Issues
- offene Pull Requests
- zuletzt gemergte Pull Requests
- fehlgeschlagene GitHub-Actions-Runs im gewählten Zeitraum

**Flags:**
- `--repo` — nur ein bestimmtes Repo anzeigen
- `--limit` — maximale Einträge pro Abschnitt, Standard: `5`
- `--merged-days` — Zeitraum für gemergte Pull Requests, Standard: `14`
- `--run-days` — Zeitraum für fehlgeschlagene Runs, Standard: `14`

---

### `post_merge_cleanup.py`
Räumt nach gemergten AI-Pull-Requests auf. Das Script nutzt dieselbe GitHub
API-Konfiguration wie die übrigen GitHub-Befehle und läuft standardmäßig als
Dry-Run, damit geplante Änderungen zuerst geprüft werden können.

```bash
python scripts/post_merge_cleanup.py
python scripts/post_merge_cleanup.py --repo ai-issue-solver
python scripts/post_merge_cleanup.py --repo ai-issue-solver --apply
```

**Automatisch geplant bzw. mit `--apply` ausgeführt:**
- gemergte AI-PRs aus dem gewählten Zeitraum zusammenfassen
- offene Issues schließen, wenn sie per Closing-Keyword oder Branch
  `ai/fix-issue-{nummer}` eindeutig referenziert sind
- gemergte AI-Branches im Owner-Repo löschen, sofern kein offener PR mehr daran hängt
- stale, bereits gemergte AI-Branches auch außerhalb des PR-Zeitfensters löschen
- stale AI-Branches ohne sichere Merge-Zuordnung als Review-Hinweis melden

**Flags:**
- `--repo` — nur ein bestimmtes Repo bereinigen
- `--merged-days` — Zeitraum für gemergte PRs, Standard: `30`
- `--stale-days` — Alter für stale AI-Branches, Standard: `30`
- `--branch-prefix` — AI-Branch-Präfix, Standard: `ai/`
- `--apply` — echte GitHub-Änderungen ausführen
- `--dry-run` — nur anzeigen; ist ohne `--apply` bereits Standard

---

### `status_dashboard.py`
Erzeugt ein lokales HTML-Dashboard aus den Run-Reports unter `reports/runs/`.
Die Übersicht gruppiert wartende, laufende, unhealthy, erfolgreiche,
fehlgeschlagene, archivierte und No-op-Jobs und verlinkt GitHub Issues,
Branches und Pull Requests, wenn genug Metadaten vorliegen.

```bash
python scripts/status_dashboard.py
python scripts/status_dashboard.py --owner SaJaToGu
python scripts/status_dashboard.py --runs-dir reports/runs --output reports/status-dashboard.html
python scripts/status_dashboard.py --github-enrich
python scripts/status_dashboard.py --health-timeout-minutes 90
python scripts/status_dashboard.py --cleanup-stale
python scripts/status_dashboard.py --cleanup-stale --mark archived --older-than-days 14 --apply
python scripts/serve_dashboard.py --port 8765 --refresh-seconds 10 --github-enrich
```

Ohne `--owner` nutzt das Script `GITHUB_USER` aus `config/.env` oder leitet den
Owner aus vorhandenen PR-URLs ab. Die erzeugte Datei liegt standardmäßig unter
`reports/status-dashboard.html` und kann direkt im Browser geöffnet werden.
`serve_dashboard.py` erzeugt das Dashboard ebenfalls, serviert es lokal und zeigt
einen Beenden-Knopf im Dashboard an und regeneriert die HTML-Datei bei jedem
Aufruf. Mit `--refresh-seconds` lädt der Browser die Seite automatisch neu. Der
einfache `python -m http.server` kann Dateien ausliefern, aber nicht per
Browser-Button beendet werden.

Erfolgreiche Solver-Runs zeigen eine kompakte Lifecycle-Spalte. Offline bleibt
das Dashboard bei lokalen Report-Daten wie `PR created`. Mit `--github-enrich`
nutzt es optional `GITHUB_TOKEN` und `GITHUB_USER`, liest PR-, Merge- und
Issue-Status aus der GitHub API und zeigt zum Beispiel `PR open`,
`Merged to develop`, `In main` oder `Issue closed`. Die Anreicherung ist klein
gehalten und ersetzt keine GitHub-Ansicht: Sie beantwortet nur, ob noch Review,
Merge oder Issue-Cleanup offen ist. Ergebnisse werden standardmäßig in
`reports/status-dashboard.github-cache.json` gecacht; wenn GitHub nicht
erreichbar ist oder Credentials fehlen, wird weiterhin das lokale Dashboard
generiert.

Während `solve_issues.py` läuft, schreibt es neben `summary.txt` eine
`health.json` mit letzter sinnvoller Worker-Ausgabe, Report-Update-Zeit und
Output-Tail. Das Dashboard markiert `started`-Runs nach dem Health-Timeout als
`Unhealthy` und zeigt Output-Tail, Report-Link und Recovery-Hinweise an. Das
Timeout ist per `--health-timeout-minutes` oder
`AI_SOLVER_HEALTH_TIMEOUT_MINUTES` konfigurierbar. Bekannte Codex-Wartezeiten
mit zukünftiger Reset-Zeit bleiben `Running`, um falsche Alarme zu vermeiden.

Mit `--cleanup-stale` zeigt das Script zuerst eine Dry-run-Vorschau fuer alte
unvollstaendige Reports (`queued`, `running`, `unhealthy` oder `unknown`). Erst `--apply`
schreibt in die betroffenen `summary.txt`-Dateien. Standardmaessig werden nur Runs mit
parsbarem Zeitstempel beruecksichtigt, die aelter als 7 Tage sind; dadurch
bleiben aktuelle aktive Laeufe geschuetzt. Archivierte Reports zaehlt das
Dashboard separat und nicht mehr als unbekannte historische Arbeit.

**Flags:**
- `--runs-dir` — Verzeichnis mit Run-Reports, Standard: `reports/runs`
- `--output` — Zielpfad der HTML-Datei, Standard: `reports/status-dashboard.html`
- `--owner` — GitHub Owner für Issue- und Branch-Links
- `--github-enrich` — erfolgreiche Runs per GitHub API um PR-/Merge-/Issue-Lifecycle anreichern, falls Credentials verfügbar sind
- `--github-cache` — Cache-Datei für Lifecycle-Daten, Standard: `reports/status-dashboard.github-cache.json`
- `--github-cache-ttl-seconds` — Cache-TTL in Sekunden, Standard: `600`; `-1` nutzt den Cache ohne Ablauf
- `--health-timeout-minutes` — Running-Runs nach so vielen Minuten ohne
  Aktivität als `Unhealthy` markieren, Standard: `60`
- `--cleanup-stale` — alte `queued`/`running`/`unhealthy`/`unknown` Reports als Cleanup-Kandidaten anzeigen
- `--mark` — Zielstatus fuer Cleanup: `archived`, `failed`, `noop` oder `successful`
- `--older-than-days` — Mindestalter fuer Cleanup-Kandidaten, Standard: `7`
- `--include-undated` — auch Reports ohne parsbaren Zeitstempel aufnehmen
- `--apply` — Cleanup wirklich schreiben; ohne diese Option bleibt es beim Dry-run
- `serve_dashboard.py --port` — lokaler Port für den Dashboard-Server, Standard: `8765`
- `serve_dashboard.py --refresh-seconds` — Browser-Auto-Refresh, Standard: `10`, `0` deaktiviert ihn
- `serve_dashboard.py --github-enrich` — nutzt dieselbe optionale Lifecycle-Anreicherung beim Servieren

---

## Nächste Ausbaustufe

Die erste Workflow-Runde ist abgeschlossen: Analyse, Backlog-Issues,
KI-Bearbeitung, PR-Erstellung, CI und Tests laufen. Als nächstes soll der
Morpheus-Style Workflow komfortabler werden:

- mehrere Issues parallel mit begrenzter Worker-Zahl lösen
- laufende Jobs, PRs und Fehler in einer lokalen Übersicht anzeigen
- offene PRs und Issues nach einem Lauf automatisch zusammenfassen
- gemergte AI-PRs nach dem Review sicher bereinigen

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
│   ├── import_repolens_results.py # RepoLens-Reports als Issues importieren
│   ├── github_summary.py        # GitHub-Issues, PRs und Actions-Runs anzeigen
│   ├── plan_issue_batches.py    # Konfliktarme Issue-Wellen planen
│   ├── post_merge_cleanup.py    # Gemergte AI-PRs und Branches bereinigen
│   ├── run_repolens_docker.sh   # RepoLens in Docker-Sandbox ausfuehren
│   ├── status_dashboard.py      # Lokales HTML-Dashboard aus Run-Reports
│   ├── serve_dashboard.py       # Dashboard lokal mit Beenden-Knopf servieren
│   ├── solve_issues.py          # Schritt 3: einzelnes Issue mit KI lösen
│   ├── solve_issues_batch.py    # Mehrere Issues parallel begrenzt lösen
│   ├── run_overnight.py         # Unbeaufsichtigter Batch mit Preflight und Logs
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
│   ├── RASPBERRY_PI.md          # Ollama auf Raspberry Pi
│   └── LANGUAGE_POLICY.md        # Sprachrichtlinie / Language Policy
└── tests/
    ├── test_analyze_repos.py    # Analyzer-Tests
    ├── test_github_summary.py   # GitHub-Übersichts-Tests
    ├── test_post_merge_cleanup.py # Post-Merge-Cleanup-Tests
    ├── test_status_dashboard.py # Dashboard-Tests
    ├── test_solve_issues_batch.py # Batch-Runner-Tests
    └── test_solve_issues.py     # Solver- und Worker-Tests
```

---

## Lizenz

MIT — Mach damit was du willst. Viel Spaß! 🚀
