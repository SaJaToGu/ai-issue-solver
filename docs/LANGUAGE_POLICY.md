# 🌍 Sprachrichtlinie / Language Policy

Dieses Dokument definiert die Sprachkonventionen für die Dokumentation in diesem Repository.
This document defines the language conventions for documentation in this repository.

---

## 📋 Richtlinie / Policy

### ✅ Deutsch (German) — Benutzerzuwendung / User-Facing

Die folgenden Inhalte **sollen auf Deutsch** verfasst werden:
The following content **should be written in German**:

- `README.md` — Hauptdokumentation für Nutzer
- `docs/WORKFLOW.md` — Workflow-Beschreibungen
- `docs/SETUP_AIDER.md` — Setup-Anleitungen
- `docs/RASPBERRY_PI.md` — Hardware-spezifische Anleitungen
- CLI-Ausgaben und Fehlermeldungen
- Dashboard-Labels und Benutzeroberflächen
- Setup-Instruktionen und Konfigurationshilfen

**Begründung:** Dieses Projekt richtet sich primär an deutschsprachige Nutzer. Benutzerzugewandte Dokumentation soll in der Zielsprache verfasst sein.
**Rationale:** This project primarily targets German-speaking users. User-facing documentation should be written in the target language.

---

### ✅ Englisch (English) — Technisch & KI-Kompatibel / Technical & AI-Compatible

Die folgenden Inhalte **dürfen auf Englisch** bleiben oder verfasst werden:
The following content **may remain or be written in English**:

- `docs/BACKLOG.md` — Projekt-Backlog (dient als Vorlage für GitHub Issues)
- `docs/NEXT_BACKLOG.md` — Geplante Weiterentwicklungen
- GitHub Issue-Bodies (für KI-Worker)
- PR Acceptance Criteria
- Test-Dateinamen und Test-Beschreibungen
- Interne Implementierungsnotizen
- Generierte Worker-Zusammenfassungen
- Modell-spezifische Anweisungen und Prompts
- Code-Kommentare (wenn sie technische Details erklären)

**Begründung:** Technische Inhalte, die von KI-Tools verarbeitet werden oder internationale Standards verwenden, profitieren von englischer Sprache. Dies verbessert die Kompatibilität mit AI-Workern und internationaler Dokumentation.
**Rationale:** Technical content processed by AI tools or using international standards benefits from English language. This improves compatibility with AI workers and international documentation.

---

## 🎯 Ziele / Goals

1. **Konsistenz:** Klare Trennung zwischen benutzerzugewandten und technischen Inhalten
   **Consistency:** Clear separation between user-facing and technical content
2. **Pragmatismus:** Keine große Übersetzungsaktion bestehender Inhalte
   **Pragmatism:** No large-scale translation of existing content
3. **KI-Unterstützung:** Englisch für Inhalte, die von KI-Tools optimal verarbeitet werden
   **AI Support:** English for content best processed by AI tools
4. **Benutzerfreundlichkeit:** Deutsch für alle nutzerrelevanten Anleitungen
   **User-Friendliness:** German for all user-relevant instructions

---

## 📝 Anleitung für neue Dokumentation / Guidelines for New Documentation

| Inhaltstyp / Content Type | Empfohlene Sprache / Recommended Language | Beispiel / Example |
|--------------------------|------------------------------------------|-------------------|
| Benutzeranleitung / User Guide | **Deutsch** / **German** | README, Setup-Anleitung |
| API-Dokumentation / API Docs | **Deutsch** / **German** | Skript-Beschreibungen |
| Workflow-Beschreibung / Workflow Docs | **Deutsch** / **German** | docs/WORKFLOW.md |
| GitHub Issues (für KI) / GitHub Issues (for AI) | **Englisch** / **English** | Issue-Bodies, Acceptance Criteria |
| Backlog & Roadmap / Backlog & Roadmap | **Englisch** / **English** | docs/BACKLOG.md, NEXT_BACKLOG.md |
| Tests / Tests | **Englisch** / **English** | Test-Dateinamen, Assertions |
| Code-Kommentare / Code Comments | **Englisch** / **English** | Technische Erklärungen |
| CLI-Nachrichten / CLI Messages | **Deutsch** / **German** | Nutzer-Feedback |

---

## 🔄 Gemischte Inhalte / Mixed Content

Wenn Inhalte sowohl Benutzer- als auch technische Aspekte abdecken, gilt:
When content covers both user-facing and technical aspects:

- **Primär nutzerzuwandt:** Hauptinhalt auf Deutsch, technische Details in Klammern auf Englisch
  **Primarily user-facing:** Main content in German, technical details in parentheses in English
- **Primär technisch:** Hauptinhalt auf Englisch, kurze deutsche Zusammenfassung möglich
  **Primarily technical:** Main content in English, brief German summary optional

**Beispiel für gemischte Inhalte:**
```markdown
## GitHub PAT erstellen

Ein Personal Access Token (PAT) ist dein API-Schlüssel für GitHub.

### Schritt-für-Schritt:
1. Gehe zu: GitHub → Settings → Developer settings → Personal access tokens → Tokens (classic)
2. Scopes: `repo`, `read:user`, `workflow` (full repository access, read user info, workflow)
```

---

## ❓ Häufige Fragen / FAQ

### Warum nicht alles auf Deutsch?
Why not everything in German?

> KI-Tools wie Codex, Claude und andere LLM-basierte Systeme arbeiten mit englischer Dokumentation und Code-Kommentaren am zuverlässigsten. Technische Begriffe haben oft keine etablierten deutschen Übersetzungen, und englische Prompts führen zu besseren Ergebnissen.
> AI tools like Codex, Claude, and other LLM-based systems work most reliably with English documentation and code comments. Technical terms often lack established German translations, and English prompts yield better results.

### Warum nicht alles auf Englisch?
Why not everything in English?

> Dieses Projekt richtet sich primär an deutschsprachige Entwickler. Benutzerzugewandte Dokumentation in der Muttersprache verbessert die Verständlichkeit und Akzeptanz.
> This project primarily targets German-speaking developers. User-facing documentation in the native language improves comprehension and acceptance.

### Was tun bei Unsicherheit?
What to do when unsure?

> Bei neuen Dateien: Orientiert euch am Inhaltstyp (siehe Tabelle oben). Bei bestehenden Dateien: Behaltet die bestehende Sprache bei und fügt ggf. eine Übersetzung hinzu, wenn der Inhalt wichtig ist.
> For new files: Refer to the content type (see table above). For existing files: Keep the existing language and optionally add a translation if the content is important.

---

## 📌 Changelog

- **2025-XX-XX:** Sprachrichtlinie eingeführt (Issue #70)
  Language policy introduced (Issue #70)
