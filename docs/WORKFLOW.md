# 📋 Detaillierter Workflow

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
│  → Erstellt Branch: ai/fix-issue-{nummer}                    │
│  → Ruft Codex oder aider mit dem Issue-Text auf              │
│  → Der KI-Worker ändert Dateien                              │
│  → Commit + Push + PR erstellen                              │
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
