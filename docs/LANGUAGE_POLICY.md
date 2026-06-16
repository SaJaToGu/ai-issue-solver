# 🌍 Sprachrichtlinie

Dieses Dokument legt fest, welche Sprache fuer Dokumentation, Issues, Tests und
KI-Worker-Inhalte in diesem Repository verwendet wird.

Kurzfassung: **Deutsch zuerst fuer Nutzer, Englisch fuer technische Inhalte, die
von Tools, KI-Workern oder internationalen Standards profitieren.** English
notes are used only where they make the policy easier for AI workers or external
contributors to apply.

---

## Grundsatz

AI Issue Solver richtet sich primaer an deutschsprachige Nutzer. Deshalb bleiben
README, Setup-Anleitungen, Workflow-Dokumentation, Dashboard-Texte und
CLI-Ausgaben deutsch.

Technische Inhalte duerfen Englisch sein, wenn sie direkt von KI-Workern,
GitHub-Issues, Tests, Code oder externen Tooling-Konventionen verarbeitet
werden. Das vermeidet holprige Uebersetzungen und verbessert die
Kompatibilitaet mit Codex, OpenCode, Mistral, aider und aehnlichen Werkzeugen.

---

## Deutsch

Folgende Inhalte sollen auf Deutsch geschrieben werden:

- `README.md`
- `docs/WORKFLOW.md`
- `docs/SETUP_AIDER.md`
- `docs/RASPBERRY_PI.md`
- Setup-, Installations- und Konfigurationsanleitungen
- CLI-Ausgaben, Fehlermeldungen und Statusmeldungen fuer Nutzer
- Dashboard-Labels und andere sichtbare UI-Texte
- Projektstatus und Bedienhinweise

Kurze englische Fachbegriffe sind okay, wenn sie ueblich sind, zum Beispiel
`dry-run`, `worker`, `branch`, `pull request` oder Modellnamen.

---

## Englisch

Folgende Inhalte duerfen Englisch bleiben oder neu auf Englisch verfasst werden:

- `docs/BACKLOG.md` (historisch) und `docs/BACKLOG/open.md` (aktiv)
- GitHub-Issue-Bodies, Acceptance Criteria und technische Aufgabenlisten
- Test-Dateinamen, Testnamen und Assertions
- Code-Kommentare, wenn sie technische Details erklaeren
- Prompts, Worker-Anweisungen und modellnahe Kontexttexte
- Generierte Worker-Zusammenfassungen
- Externe API- oder Tool-Begriffe, bei denen Englisch die stabilere Bezeichnung ist

English summary: user-facing docs stay German; AI-facing and code-facing content
may stay English.

---

## Entscheidungshilfe

| Inhaltstyp | Sprache | Beispiel |
| --- | --- | --- |
| Nutzeranleitung | Deutsch | README, Setup-Anleitung |
| Workflow-Dokumentation | Deutsch | `docs/WORKFLOW.md` |
| CLI- und Dashboard-Texte | Deutsch | Status, Fehler, Buttons |
| GitHub-Issues fuer Worker | Englisch | Issue-Bodies, Acceptance Criteria |
| Backlog und Roadmap | Englisch | `docs/BACKLOG.md`, `docs/BACKLOG/open.md` |
| Tests | Englisch | Testnamen, Assertions |
| Code-Kommentare | Englisch | technische Implementierungsnotizen |

Wenn ein Dokument gemischt ist, entscheidet die Hauptzielgruppe:

- Nutzer lesen es direkt: Deutsch als Hauptsprache, englische Begriffe nur knapp.
- KI-Worker oder Entwickler-Tools verarbeiten es: Englisch ist erlaubt; eine
  kurze deutsche Einordnung kann helfen.
- Bestehende Dateien: Sprache nicht ohne Grund wechseln. Kleine Korrekturen
  sollen den bestehenden Stil respektieren.

---

## Beispiele

### Nutzerorientiert

```markdown
## GitHub PAT erstellen

Ein Personal Access Token (PAT) ist dein API-Schluessel fuer GitHub.

Scopes: `repo`, `read:user`, `workflow`
```

### Workerorientiert

```markdown
## Acceptance Criteria

- Validate missing `GITHUB_TOKEN` before creating issues.
- Keep dry-run mode as the default.
```

---

## Haeufige Fragen

### Warum nicht alles auf Deutsch?

KI-Tools und viele technische Oekosysteme arbeiten mit englischen Begriffen,
Prompts und Fehlermeldungen stabiler. Fuer Worker-nahe Inhalte ist Englisch oft
praeziser und weniger missverstaendlich.

### Warum nicht alles auf Englisch?

Die Bedienung dieses Projekts soll fuer deutschsprachige Entwickler angenehm
bleiben. Nutzerzugewandte Dokumentation in Deutsch senkt Reibung und passt zum
aktuellen Projektstil.

### Was tun bei Unsicherheit?

Orientiere dich am Leser: Mensch im lokalen Workflow bedeutet meist Deutsch;
Worker, Test, API oder Issue-Template bedeutet oft Englisch. Bei bestehenden
Dateien ist Konsistenz wichtiger als eine perfekte Sprachgrenze.

---

## Changelog

- **2026-05-22:** Sprachrichtlinie eingefuehrt (Issue #70).
- **2026-05-27:** Richtlinie auf Deutsch-first verdichtet, Linkhinweise und
  Platzhalterdatum bereinigt (Issue #82).
