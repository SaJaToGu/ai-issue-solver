# 📋 Detaillierter Workflow

## Branch-Modell

Dieses Projekt nutzt ein einfaches `develop`-basiertes Branch-Modell:

- `main` bleibt stabil und enthält nur geprüfte, releasefähige Änderungen.
- `develop` sammelt die laufende Arbeit und ist der Zielbranch für Pull Requests.
- Feature- und Fix-Branches werden pro GitHub Issue erstellt und benannt, sodass
  der Bezug zum Issue sichtbar bleibt, zum Beispiel `ai/fix-issue-10`.
- Pull Requests werden von Feature-Branches zurück nach `develop` geöffnet.
- Nach Review und erfolgreicher Prüfung wird in `develop` gemergt. Änderungen aus
  `develop` gelangen erst nach einer bewussten Stabilisierung oder Release-Vorbereitung
  nach `main`.

Für den AI Issue Solver ist `develop` der Standard-Zielbranch:

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
│  python scripts/create_issues.py --report reports/analysis.json            │
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
│  → Klont standardmäßig den Zielbranch develop                │
│  → Erstellt Issue-Branch: ai/fix-issue-{nummer}              │
│  → Ruft Codex oder aider mit dem Issue-Text auf              │
│  → Der KI-Worker ändert Dateien                              │
│  → Commit + Push + PR zurück nach develop erstellen          │
│  → Issue schließen mit Kommentar                             │
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

## Vollständiges Beispiel-Kommando

```bash
# Alles auf einmal (Morpheus-Methode):
python scripts/analyze_repos.py --user SaJaToGu && \
python scripts/create_issues.py --report reports/analysis.json && \
python scripts/solve_issues.py --model codex
```

## Nützliche Flags

```bash
# Nur bestimmte Priorität analysieren
python scripts/create_issues.py --priority high

# Nur ein Repo bearbeiten
python scripts/solve_issues.py --model codex --repo BedBoxDrawerRole
python scripts/solve_issues.py --model ollama --repo BedBoxDrawerRole

# Einzelnes Issue lösen
python scripts/solve_issues.py --model claude --repo dustycase --issue 1

# Alles erst simulieren
python scripts/analyze_repos.py --user SaJaToGu
python scripts/create_issues.py --dry-run
python scripts/solve_issues.py --model codex --dry-run
```
