# 🤖 AI Issue Solver (AIS) — Morpheus-Style Workflow

> Automatisches Analysieren, Erstellen und Lösen von GitHub Issues mit KI-Unterstützung
> Inspiriert von [TheMorpheus407](https://www.youtube.com/user/TheMorpheus407) / [the-morpheus.de](https://www.the-morpheus.de)

---

## 📋 Inhaltsverzeichnis

- [Was macht dieses Repo?](#was-macht-dieses-repo)
- [Repository-Metadaten](#repository-metadaten)
- [Sprachrichtlinie](#sprachrichtlinie)
- [Voraussetzungen](#voraussetzungen)
- [Quickstart](#quickstart)
- [Dokumentation](#dokumentation)
- [Verzeichnisstruktur](#verzeichnisstruktur)
- [Wartungshinweis](#wartungshinweis)

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
und erstellt einen Branch + Commit. Dieser Schritt ist außerdem als
wiederverwendbarer Codex-Skill unter
[`.agents/skills/solve-issues/`](.agents/skills/solve-issues/SKILL.md) verfügbar.

**Modellauswahl:** Welches KI-Modell ein Issue bekommt, entscheidet
[`scripts/model_selection.py`](scripts/model_selection.py) anhand von
Kategorie, Risiko, Kostenlimit und Run-Historie. Die gleiche Heuristik
ist als wiederverwendbarer Codex-Skill unter
[`.agents/skills/model-selection/`](.agents/skills/model-selection/SKILL.md)
verfügbar und kann vom Solver über `--auto-model` oder von eigenen
Tools über `helpers/recommend_model.sh` aufgerufen werden.

**Sicherheit:** Um Fehler zu vermeiden, führen partielle Patch-Anwendungen
oder Fehler bei Reject-Artefakten zu einem sofortigen Abbruch (Hard-Stop)
und erstellen keine Pull Requests.

**OpenCode Free Models (dynamisch):** Die Liste der freien OpenCode-Modelle
wird nicht mehr statisch im Code gepflegt. Stattdessen lädt
[`scripts/model_catalog.py`](scripts/model_catalog.py) den Live-Stand von
`~/.opencode/bin/opencode models` (mit Cache und statischem Fallback),
klassifiziert Kandidaten anhand von `-free`-Suffix und expliziten
Allow-Listen wie `opencode/big-pickle`, und meldet veraltete bzw.
nicht mehr verfügbare Slugs als `missing` oder `stale`. Die Solver-Hilfen
`--verify-opencode`, `--list-opencode-free-models` und das Reviewer-Prompt
verwenden denselben Mechanismus.

**Recently-Removed-Patterns-Guard:** Damit der Solver nicht versehentlich
ein Pattern re-introduziert, das in einem kürzlich gemergten PR explizit
entfernt wurde, liest der Solve-Prompt die Maintainer-Tabelle in
[`docs/AGENTS.md`](docs/AGENTS.md) (Abschnitt „Recently Removed Patterns").
Aktuelle Einträge sind z.B. die statische `free_models`-Liste (entfernt
in PR #439, ersetzt durch dynamische Discovery) und der Hart-Cost-Cap
`$20/$20` (ersetzt durch `$15/$50` plus abgestufte Budget-Ratio-Warnungen
in PR #437). Der Guard ist **soft**: er weist den Solver an, das Pattern
im PR-Body zu erklären, falls er es für notwendig hält, statt es
stillschweigend wieder einzubauen. Maintainer pflegen die Tabelle in
jedem PR, der absichtlich ein Pattern entfernt.

**Run-Reports auswerten:** Die von Schritt 3 erzeugten Run-Reports,
Provider-Scorecards und OpenCode-Diagnosen werden durch
[`.agents/skills/solver-reporting/`](.agents/skills/solver-reporting/SKILL.md)
aggregiert, gefiltert und aufgeräumt (Preserved Worktrees, Heartbeat,
Run-Outcome-Verteilung).

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

## Quickstart

### 1. Repo klonen

```bash
git clone https://github.com/SaJaToGu/ai-issue-solver.git
cd ai-issue-solver
```

### 2. Python-Abhängigkeiten installieren

```bash
pip install -r requirements.txt
```

Für KI-Modelle (Claude, OpenAI, Ollama, etc.):

```bash
pip install -r requirements-aider.txt
```

### 3. GitHub PAT einrichten

```bash
cp config/config.example.env config/.env
# .env mit deinen Werten befüllen (NIEMALS committen!)
```

### 4. Erstes Issue lösen

```bash
python scripts/solve_issues.py --model openrouter --repo <dein-repo> --issue <issue-number>
```

---

## Dokumentation

- **[Provider Setup](docs/SETUP_AIDER.md):** Einrichtung von KI-Modellen (Claude, OpenAI, Ollama, etc.)
- **[Workflow & Batch](docs/WORKFLOW.md):** Detaillierter Workflow, Batch-Verarbeitung, Dashboard, Night Mode
- **[Model Override Policy](docs/MODEL_OVERRIDE_POLICY.md):** Regeln fuer Modell-Defaults und per-run Overrides
- **[Repository Profile Provider](docs/REPO_PROFILE_PROVIDER.md):** GitHub-first Repo-Profil mit lokalem Fallback (Issue #213)

---

## Wartungshinweis

Um die README schlank zu halten, werden detaillierte Anleitungen in der [Dokumentation](#dokumentation) gepflegt.

- **Provider-Setup** → [docs/SETUP_AIDER.md](docs/SETUP_AIDER.md)
- **Workflow & Batch** → [docs/WORKFLOW.md](docs/WORKFLOW.md)
- **Repo-Profile-Provider** → [docs/REPO_PROFILE_PROVIDER.md](docs/REPO_PROFILE_PROVIDER.md)

Neue Abschnitte bitte nur hier einfügen, wenn sie für den **Quickstart** relevant sind. Alle anderen Inhalte gehören in die Dokumentation.

---

## Nächste Ausbaustufe

Die erste Workflow-Runde ist abgeschlossen: Analyse, Backlog-Issues,
KI-Bearbeitung, PR-Erstellung, CI und Tests laufen. Als nächstes soll der
Morpheus-Style Workflow komfortabler werden:

- mehrere Issues parallel mit begrenzter Worker-Zahl lösen (teilweise implementiert)
- laufende Jobs, PRs und Fehler in einer lokalen Übersicht anzeigen (Dashboard)
- offene PRs und Issues nach einem Lauf automatisch zusammenfassen
- gemergte AI-PRs nach dem Review sicher bereinigen (post_merge_cleanup.py)

Die verbleibenden Backlog-Items befinden sich in [docs/BACKLOG/open.md](docs/BACKLOG/open.md).

---



---

## Verzeichnisstruktur

```
ai-issue-solver/
├── .github/
│   ├── settings.yml             # Repo-Beschreibung und Topics als Referenz
│   └── workflows/
│       └── ci.yml               # GitHub-Actions-Smoke- und Testlauf
├── .agents/
│   └── skills/
│       ├── git-cleanup/         # Branch- und PR-Bereinigung nach Merge
│       ├── model-selection/     # Codex-Skill für die automatische Modellauswahl
│       ├── plan-issue-batches/  # Konfliktarme Issue-Wellen planen
│       ├── recovery/            # Recovery bei abgebrochenen Solver-Runs
│       ├── rework/              # Gezielte Nacharbeit an generierten PRs
│       ├── run-overnight/       # Unbeaufsichtigter Batch-Betrieb
│       ├── solve-issues/        # Codex-Skill für Schritt 3 (solve_issues.py)
│       └── solver-reporting/    # Codex-Skill für Run-Reports, Metriken & Provider-Scorecards
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
│   ├── github_summary.py        # GitHub-Issues, PRs und Actions-Runs anzeigen
│   ├── plan_issue_batches.py    # Konfliktarme Issue-Wellen planen
│   ├── post_merge_cleanup.py    # Gemergte AI-PRs und Branches bereinigen
│   ├── status_dashboard.py      # Lokales HTML-Dashboard aus Run-Reports
│   ├── serve_dashboard.py       # Dashboard lokal mit Beenden-Knopf servieren
│   ├── solve_issues.py          # Schritt 3: einzelnes Issue mit KI lösen
│   ├── solve_issues_batch.py    # Mehrere Issues parallel begrenzt lösen
│   ├── run_overnight.py         # Unbeaufsichtigter Batch mit Preflight und Logs
│   ├── model_selection.py       # Automatische Modellauswahl (Heuristik)
│   └── utils.py                 # Gemeinsame Hilfsfunktionen
├── templates/
│   └── issue_body               # Issue-Text-Vorlage
├── reports/                     # Generierte Analyse-Reports (gitignored)
│   └── .gitkeep
├── docs/
│   ├── BACKLOG.md               # Erster Projekt-Backlog
│   ├── docs/BACKLOG/open.md          # Nächste Ausbaustufe
│   ├── WORKFLOW.md              # Detaillierter Workflow
│   ├── SETUP_AIDER.md           # Aider-Einrichtung
│   ├── RASPBERRY_PI.md          # Ollama auf Raspberry Pi
│   ├── REPO_PROFILE_PROVIDER.md # GitHub-first Repo-Profil mit lokalem Fallback
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
