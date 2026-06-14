---
name: model-selection
description: Use when an ai-issue-solver workflow needs an automatic, evidence-based model recommendation for a single GitHub issue. Wraps the logic in `scripts/model_selection.py` as a reusable Codex Skill that classifies the issue (language, task type, touched files, repo type), maps it to a risk/strength tier, filters by cost, and escalates after failed runs based on the run history under `reports/runs/`. Trigger on requests like "pick the right model for issue #42", "auto-select a model for this issue", "which model should I use for a Python refactor", or whenever the solver should run with `--auto-model`.
---

# Model Selection

Dieser Skill kapselt die automatische Modellauswahl aus
`scripts/model_selection.py` als wiederverwendbaren Codex-Skill. Er nimmt
ein GitHub-Issue (Text, Labels, betroffene Dateien, Repo-Typ) sowie optional
eine `run_history` und liefert eine begründete Modell-Empfehlung inklusive
Kosten-Tier, Risiko-Klasse, Kategorie und Eskalationsplan. Damit kann der
Solver künftig rein über `--auto-model` ohne `--model` und `--model-name`
auskommen, und künftige Routing-Regeln (Sprache, Issue-Typ, historische
Erfolgsraten) lassen sich an einer einzigen Stelle erweitern.

## Wann einsetzen

Verwende diesen Skill, wenn eines der folgenden Szenarien zutrifft:

- Für ein einzelnes Issue soll das beste KI-Modell klassifiziert und
  ausgewählt werden, ohne dass `--model` und `--model-name` manuell gesetzt
  werden (`auto-select a model for issue 42`).
- Ein Run ist fehlgeschlagen und das nächste Modell soll anhand des
  `run_history` automatisch eskaliert werden.
- Eine kostenbasierte Vorauswahl soll Modelle oberhalb eines
  `max_cost_tier` (`cheap`, `medium`, `expensive`) ausschließen.
- Ein manuelles Override (`MANUAL_MODEL`) soll einen konkreten Modellnamen
  durchstellen, ohne die Heuristik abzuschalten.
- Reine Diagnose: "Welche Kategorie / welches Risiko hat Issue #N in Repo X?"
  ohne Solver-Aufruf.

Nicht verwenden für die reine Solver-Ausführung (`.agents/skills/solve-issues`)
oder die Nachbearbeitung (`.skills/rework`, `.skills/recovery`,
`.skills/git-cleanup`).

## Voraussetzungen

| Komponente | Zweck | Pfad/Setup |
|------------|-------|-----------|
| Python ≥ 3.10 | Modellauswahl-Logik | `requirements.txt` |
| `scripts/model_selection.py` | Heuristik, Konstanten, API | im Repo vorhanden |
| Optional `reports/runs/` | Historie für Eskalation | wird vom Solver erzeugt |
| Optional `config/.env` | manuelle Overrides via `MANUAL_MODEL` | siehe `config/config.example.env` |

Sicherheitsregel: Niemals echte Secret-Dateien lesen oder committen
(`.env`, `.env.*`, `config/.env`, `config/.env.*`). Für Konfigurationsbeispiele
ausschließlich `config/config.example.env` oder `.env.example` verwenden.

## Eingaben

Der Skill akzeptiert diese Argumente (siehe `helpers/parse_args.py`):

| Argument | Typ | Pflicht | Bedeutung |
|----------|-----|---------|-----------|
| `--repo-type` | `str` | nein | `python`, `r`, `docs`, `mixed`, `dashboard`, `low-code` … |
| `--language` | `str` | nein | primäre Sprache, z. B. `python`, `r` (zukünftige Routing-Information) |
| `--task-type` | `str` | nein | `bug-fix`, `refactor`, `docs`, `tests`, `feature` (zukünftige Routing-Information) |
| `--issue` | `int` | nein | GitHub-Issue-Nummer, für `run_history`-Lookup |
| `--issue-text` | `str` | nein | Issue-Body oder -Titel; wird klassifiziert |
| `--labels` | `str` (Komma) | nein | Labels, an `select_model` weitergereicht |
| `--touched-files` | `str` (Komma) | nein | vom Issue implizit betroffene Dateien |
| `--max-cost-tier` | `enum` | nein | `cheap`, `medium`, `expensive` (Default: `expensive`) |
| `--max-cost` | Alias | nein | gleich wie `--max-cost-tier`, behalten für CLI-Kompatibilität |
| `--history` | `path` | nein | Pfad auf `reports/runs/.../metadata.json` mit Vorgänger-Run |
| `--manual-model` | `str` | nein | überschreibt die Auswahl (höchste Priorität) |
| `--format` | `enum` | nein | `json` (Default) oder `text` für CLI-Ausgabe |

Mindestens eine der folgenden Eingaben muss gesetzt sein, damit der Skill
eine sinnvolle Empfehlung liefern kann:

- `--issue-text`
- `--labels`
- `--touched-files`
- `--repo-type`
- `--language`
- `--task-type`
- `--manual-model`

Sonst antwortet der Skill mit Exit-Code `2` und einer Begründung im JSON.

## Standardablauf

1. **Argumente validieren** — `helpers/parse_args.py` prüft das Schema und
   akzeptiert genau einen `--issue` als `int ≥ 0`, eine nicht-leere
   Issue-Quelle und ein gültiges `--max-cost-tier`. Bei Fehler: Exit `2`
   und `ok: false` im JSON.
2. **Konstanten laden** — der Skill delegiert die Heuristik vollständig an
   `scripts/model_selection.py` (`select_model_for_issue`). Es werden
   *keine* Modellnamen, Kosten oder Eskalationsreihenfolgen im Skill
   dupliziert; `scripts/model_selection.py` bleibt die Single Source of
   Truth.
3. **Issue klassifizieren** — `classify_issue` bestimmt die Kategorie
   (`docs-only`, `tests`, `python`, `r`, `dashboard/ui`, `provider-integration`,
   `refactor`, `ci-failure`, `low-code-repo`, `general`) anhand von Text,
   Labels, Dateiendungen und `--repo-type`.
4. **Risiko schätzen** — `estimate_risk_and_strength` liefert ein
   Risiko-Level (`low`, `medium`, `high`) und das passende
   `STRENGTH_MAP`-Tier.
5. **Kosten filtern** — `filter_models_by_cost` schneidet Modelle oberhalb
   des `max_cost_tier` ab.
6. **Override und Eskalation anwenden** — `--manual-model` gewinnt vor
   jeder Heuristik. Andernfalls liest der Skill optional
   `reports/runs/<run_id>/metadata.json` und eskaliert entlang
   `MODEL_ESCALATION`, falls der letzte Run `failed` oder `no-change` war.
7. **Ergebnis formatieren** — `helpers/recommend_model.sh` ruft den
   Python-Helfer auf und gibt das Ergebnis als JSON oder als kompakten
   Textblock aus. Bei `--format text` enthält die Ausgabe das gewählte
   Modell, den Grund, das Kosten-Tier, den Fallback-Plan und die
   Risiko-/Kategorie-Tags.

Eine ausführliche Schritt-für-Schritt-Beschreibung mit Beispielausgaben
liegt unter [workflow.md](workflow.md).

## Helper Scripts

| Helper | Zweck |
|--------|-------|
| `helpers/parse_args.py` | Python-Validator für die Skill-Argumente; gibt JSON aus |
| `helpers/parse_args.sh` | Bash-Validator, schreibt `KEY=VALUE`-Paare für `eval` |
| `helpers/recommend_model.sh` | Dünner Wrapper um `select_model_for_issue`; unterstützt `--format` |
| `helpers/history_check.sh` | Listet vorhandene `reports/runs/`-Verzeichnisse für ein Issue auf |

## Beispiele

Kurze Aufrufe liegen unter
[`.agents/skills/model-selection/examples/`](examples/README.md). Häufige
Szenarien:

```bash
# Reine Empfehlung anhand von Issue-Text und Repo-Typ
bash .agents/skills/model-selection/helpers/recommend_model.sh \
    --repo-type python \
    --issue-text "Refactor the test runner to use pytest fixtures" \
    --max-cost-tier medium

# Empfehlung mit Eskalation aus dem letzten Run-Report
bash .agents/skills/model-selection/helpers/recommend_model.sh \
    --issue 42 --repo-type python --format text

# Manuelle Übersteuerung (Override gewinnt vor Heuristik)
bash .agents/skills/model-selection/helpers/recommend_model.sh \
    --issue 42 --repo-type python --manual-model claude-sonnet-4

# Diagnose: vorhandene Run-Historie prüfen
bash .agents/skills/model-selection/helpers/history_check.sh 42
```

## Integration in den Solver

`scripts/solve_issues.py` ruft `select_model_for_issue` direkt auf, wenn
`--auto-model` gesetzt ist (siehe `scripts/solve_issues.py:3072`). Der Skill
ist die wiederverwendbare Schnittstelle für neue Aufrufer (Dashboard,
Benchmark-Runner, Codex-Worker), die keine zusätzlichen Solver-Argumente
mitführen wollen.

Empfohlene CLI-Migration für neue Tools:

```bash
# Alt: solver mit explizitem Modell
python scripts/solve_issues.py --model opencode --issue 42

# Neu: solver + automatische Modellauswahl
python scripts/solve_issues.py --auto-model --issue 42
RECOMMENDED=$(bash .agents/skills/model-selection/helpers/recommend_model.sh \
    --issue 42 --repo-type python --format json | python -c "import json,sys;print(json.load(sys.stdin)['model'])")
```

## Sicherheits- und Geheimnisschutz-Regeln

Diese Regeln sind **nicht** verhandelbar und spiegeln die Regeln aus
`.agents/skills/solve-issues/SKILL.md`:

- **Repo-relative Pfade**: Verwende ausschließlich Pfade wie
  `scripts/model_selection.py`. Absolute Worktree-Pfade wie
  `/tmp/ai-solver-xyz/...` werden vom Skill weder erzeugt noch
  weitergereicht.
- **Keine Secret-Dateien lesen oder schreiben**: `.env`, `.env.*`,
  `config/.env`, `config/.env.*` werden im Skill-Pfad niemals gelesen.
  Konfigurationsbeispiele stammen aus `config/config.example.env` oder
  `.env.example`.
- **Nur lesender Zugriff auf Run-Historie**: `helpers/history_check.sh`
  liest ausschließlich JSON-Dateien aus `reports/runs/`. Schreibrechte
  bleiben beim Solver.

## Test-Workflow

Der Skill liefert einen Test-Workflow unter
[`.agents/skills/model-selection/tests/`](tests/README.md):

- `tests/test_skill_artifacts.py` — prüft, dass alle erwarteten Dateien
  vorhanden und nicht leer sind.
- `tests/test_helpers.py` — validiert `parse_args.py`, `parse_args.sh`,
  `recommend_model.sh` und `history_check.sh` in einer kontrollierten
  Umgebung.
- `tests/test_skill_workflow.py` — führt die Heuristik auf reproduzierbaren
  Eingaben aus und vergleicht die Auswahl gegen die Erwartungen aus
  `tests/test_model_selection.py`.
- `tests/run_skill_tests.sh` — Convenience-Wrapper für
  `python -m unittest discover` aus dem Skill-Verzeichnis.

Ausführen mit:

```bash
bash .agents/skills/model-selection/tests/run_skill_tests.sh
```

## Verwandte Skills

- `.agents/skills/solve-issues` — nutzt die Modellauswahl über
  `--auto-model` und ruft `scripts/model_selection.py` direkt auf.
- `.skills/rework` — kann einen Rework-Slice mit anderer Modellklasse
  anstoßen, falls ein PR verworfen wurde.
- `.skills/recovery` — nutzt `reports/runs/.../metadata.json`, die
  derselbe Skill optional als Eskalationsquelle liest.

Diese Skills ergänzen den hier beschriebenen Workflow und sollten
gemeinsam betrachtet werden, wenn der automatische Solver erweitert wird.
