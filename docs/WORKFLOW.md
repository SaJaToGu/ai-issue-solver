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
│  python scripts/solve_issues_batch.py --model codex --workers 2 │
│                                                              │
│  → Klont jedes Repo in ein Temp-Verzeichnis                  │
│  → Klont standardmäßig den GitHub-Default-Branch             │
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

# Mehrere Issues parallel mit maximal zwei Workern lösen
python scripts/solve_issues_batch.py --model codex --repo ai-issue-solver --workers 2 --base-branch develop
```

## Parallelbetrieb und Status

`solve_issues.py` löst Issues weiterhin nacheinander und bleibt damit der
einfachste Einstieg für einzelne Läufe. Für Batch-Läufe gibt es
`solve_issues_batch.py`:

- `--workers` begrenzt die Anzahl paralleler `solve_issues.py`-Prozesse.
- Jobs werden vor dem Start geplant; bereits vorhandene Branches wie
  `ai/fix-issue-10` werden übersprungen, damit keine doppelten PR-Branches
  entstehen.
- Worker-Ausgaben werden pro Job gesammelt und blockweise ausgegeben. Das hält
  parallele Läufe lesbar und bewahrt trotzdem die normale Solver-Diagnose unter
  `reports/runs/`.
- Ein fehlschlagender Job stoppt den Batch nicht. Die Zusammenfassung zählt
  erfolgreiche, fehlgeschlagene und übersprungene Jobs getrennt.

Beispiel:

```bash
python scripts/solve_issues_batch.py --model codex --workers 2
python scripts/solve_issues_batch.py --model claude --repo demo --repo tools --workers 3 --dry-run
```

Für die nächsten Ausbauschritte bleiben noch Status-Persistenz, Dashboard und
Resume-Logik offen:

Die konkreten Aufgaben dazu stehen in [NEXT_BACKLOG.md](NEXT_BACKLOG.md).
