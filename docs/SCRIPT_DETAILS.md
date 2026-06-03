# 📝 Script-Details

Dieses Dokument enthält detaillierte Informationen zu den einzelnen Scripts des AI Issue Solvers.

---

## `analyze_repos.py`

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

## `create_issues.py`

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

## `solve_issues.py`

Löst offene Issues automatisch mit KI + Codex, Mistral Vibe, OpenCode oder aider.

```bash
python scripts/solve_issues.py --model codex --repo BedBoxDrawerRole
python scripts/solve_issues.py --model opencode --model-name mistral/mistral-small-2603 --repo BedBoxDrawerRole
python scripts/solve_issues.py --model mistral-vibe --repo BedBoxDrawerRole
python scripts/solve_issues.py --model claude --repo BedBoxDrawerRole
python scripts/solve_issues.py --model mistral --repo BedBoxDrawerRole
python scripts/solve_issues.py --model mistral --model-name magistral-small-2509
python scripts/solve_issues.py --model ollama --model-name llama3
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

## `solve_issues_batch.py`

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

## `run_overnight.py`

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

## `github_summary.py`

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

## `post_merge_cleanup.py`

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

## `status_dashboard.py`

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
ghalten und ersetzt keine GitHub-Ansicht: Sie beantwortet nur, ob noch Review,
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