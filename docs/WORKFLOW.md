# 📋 Detaillierter Workflow

## Branch-Modell

Dieses Projekt kann ein einfaches `develop`-basiertes Branch-Modell nutzen:

- `main` bleibt stabil und enthält nur geprüfte, releasefähige Änderungen.
- `develop` sammelt die laufende Arbeit und kann der Zielbranch für Pull Requests sein.
- Feature- und Fix-Branches werden pro GitHub Issue erstellt und benannt, sodass
  der Bezug zum Issue sichtbar bleibt, zum Beispiel `ai/fix-issue-10`.
- Pull Requests werden von Feature-Branches zurück zum gewählten Zielbranch geöffnet.
- Nach Review und erfolgreicher Prüfung wird in `develop` gemergt. Änderungen aus
  `develop` gelangen erst nach einer bewussten Stabilisierung oder Release-Vorbereitung
  nach `main`.

Für den AI Issue Solver ist ohne weitere Angabe der GitHub-Default-Branch des
Ziel-Repositories der Zielbranch. In vielen Repos ist das `main`; für ein
`develop`-basiertes Modell wird der Zielbranch explizit gesetzt:

```bash
python scripts/solve_issues.py --model codex --base-branch develop
```

Soll ein anderes Ziel verwendet werden, kann es explizit über `--base-branch`
gesetzt werden.

## Der vollständige Ablauf

```
┌──────────────────────────────────────────────────────────────┐
│  VORBEREITUNG (einmalig)                                      │
│                                                              │
│  1. pip install -r requirements.txt                          │
│  2. cp config/config.example.env config/.env                 │
│  3. .env befüllen (GitHub PAT + KI-API-Keys)                 │
└──────────────────────────────────────────────────────────────┘
                          │
                          ▼
┌──────────────────────────────────────────────────────────────┐
│  SCHRITT 1: ANALYSE                                          │
│                                                              │
│  python scripts/analyze_repos.py --user SaJaToGu            │
│                                                              │
│  → Scannt alle Repos per GitHub API                          │
│  → Prüft: README, Lizenz, .gitignore, CI, Topics, ...        │
│  → Speichert Report: reports/analysis.json                   │
└──────────────────────────────────────────────────────────────┘
                          │
                          ▼
┌──────────────────────────────────────────────────────────────┐
│  SCHRITT 2: ISSUES ERSTELLEN                                 │
│                                                              │
│  python scripts/create_issues.py --report reports/analysis.json --dry-run  │
│  python scripts/create_issues.py --report reports/analysis.json --confirm-create │
│                                                              │
│  → Erstellt strukturierte GitHub Issues                      │
│  → Mit Labels, Priorität und Beschreibung                    │
│  → Vermeidet doppelte Issues                                 │
└──────────────────────────────────────────────────────────────┘
                          │
                          ▼
┌──────────────────────────────────────────────────────────────┐
│  SCHRITT 3: ISSUES LÖSEN                                     │
│                                                              │
│  python scripts/solve_issues.py --model codex                │
│                                                              │
│  → Klont jedes Repo in ein Temp-Verzeichnis                  │
│  → Klont standardmäßig den GitHub-Default-Branch             │
│  → Prüft vorhandene Issue-Branches und PRs                   │
│  → Erstellt Issue-Branch: ai/fix-issue-{nummer}              │
│  → Ruft Codex oder aider mit dem Issue-Text auf              │
│  → Der KI-Worker ändert Dateien                              │
│  → Commit + Push + PR zurück zum Zielbranch erstellen        │
│  → Issue optional mit --close-issues schließen               │
└──────────────────────────────────────────────────────────────┘
                          │
                          ▼
┌──────────────────────────────────────────────────────────────┐
│  REVIEW (manuell)                                            │
│                                                              │
│  → PR auf GitHub öffnen                                      │
│  → Änderungen reviewen                                       │
│  → Mergen oder Feedback geben                                │
└──────────────────────────────────────────────────────────────┘
```

## Wiederaufnahme nach abgebrochenen Läufen

Vor einem Worker-Lauf und auch im Dry-Run prüft `solve_issues.py`, ob Branches
mit dem Präfix `ai/fix-issue-{nummer}` bereits auf GitHub existieren und ob Pull
Requests von diesen Branches vorhanden sind:

- Branch fehlt: Das Script startet normal mit `ai/fix-issue-{nummer}`.
- Branch existiert ohne PR: Der Branch wird ausgecheckt. Enthält er bereits
  Änderungen gegen den Zielbranch, erstellt das Script direkt den fehlenden PR;
  andernfalls läuft der Worker auf diesem Branch weiter.
- Offener PR existiert: Das Script meldet den PR und bearbeitet das Issue nicht
  erneut.
- Gemergter PR existiert: Das Script meldet den gemergten PR und überspringt das
  Issue.
- Geschlossener, nicht gemergter PR existiert: Im interaktiven Terminal fragt
  das Script nach, ob ein neuer Run gestartet oder das Issue übersprungen werden
  soll. In nicht-interaktiven Läufen wird automatisch ein neuer Branch mit
  Zeitstempel verwendet.

## Sicherer Start

```bash
# 1. Repos analysieren
python scripts/analyze_repos.py --user SaJaToGu --output reports/analysis.json

# 2. Erst prüfen, welche Issues entstehen würden
python scripts/create_issues.py --report reports/analysis.json --dry-run

# 3. Danach bewusst echte Issues erstellen
python scripts/create_issues.py --report reports/analysis.json --confirm-create

# 4. Erst einen einzelnen KI-Lauf simulieren
python scripts/solve_issues.py --model codex --repo ai-issue-solver --issue 1 --base-branch develop --dry-run

# 5. Danach einen einzelnen KI-Lauf ausführen
python scripts/solve_issues.py --model codex --repo ai-issue-solver --issue 1 --base-branch develop
```

## Nützliche Flags

```bash
# Nur bestimmte Priorität aus einem Report als Issues vorbereiten
python scripts/create_issues.py --report reports/analysis.json --priority high --dry-run

# Nur ein Repo bearbeiten
python scripts/solve_issues.py --model codex --repo BedBoxDrawerRole --base-branch develop
python scripts/solve_issues.py --model ollama --repo BedBoxDrawerRole --base-branch develop

# Einzelnes Issue lösen
python scripts/solve_issues.py --model claude --repo dustycase --issue 1 --base-branch develop

# Alles erst simulieren
python scripts/analyze_repos.py --user SaJaToGu --output reports/analysis.json
python scripts/create_issues.py --report reports/analysis.json --dry-run
python scripts/solve_issues.py --model codex --base-branch develop --dry-run
```

## Parallelbetrieb und Status

Für größere Backlogs kann `solve_issues_batch.py` mehrere Issues parallel
bearbeiten, ohne unbegrenzt Worker zu starten. Jeder Job läuft als eigener
`solve_issues.py`-Prozess und nutzt dadurch dieselbe Branch-Recovery,
Run-Report-Erstellung und PR-Logik wie ein einzelner Solver-Lauf.

```bash
python scripts/solve_issues_batch.py --model codex --workers 2
python scripts/solve_issues_batch.py --model claude --repo BedBoxDrawerRole --workers 3
python scripts/solve_issues_batch.py --model codex --repo ai-issue-solver --issue 23 --issue 24 --dry-run
```

Der Batch-Runner dedupliziert identische `(Repo, Issue)`-Jobs vor dem Start,
damit innerhalb eines Laufs nicht zwei Worker denselben Issue-Branch bearbeiten.
Worker-Ausgaben werden pro Job gesammelt und erst nach Abschluss dieses Jobs
gedruckt. Wenn ein Worker fehlschlägt, laufen die übrigen Jobs weiter; am Ende
meldet das Script erfolgreiche und fehlgeschlagene Jobs separat.
Wenn Codex ein Nachrichtenlimit mit Reset-Zeit meldet, wird der betroffene Job
als verzögert erfasst und nicht sofort erneut verbrannt. Mit
`--requeue-rate-limited` schläft der Batch-Runner erst dann bis zur Reset-Zeit,
wenn keine anderen Jobs mehr verfügbar sind, und legt den verzögerten Job danach
wieder in die Queue.

Die Run-Reports unter `reports/runs/` können anschließend mit dem lokalen
Dashboard ausgewertet werden:

```bash
python scripts/status_dashboard.py
```
