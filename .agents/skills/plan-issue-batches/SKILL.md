---
name: plan-issue-batches
description: Use when a user wants to convert a set of open GitHub issues into a conflict-aware execution plan, batch waves, or scheduled solver runs in ai-issue-solver. Wraps scripts/plan_issue_batches.py into a single Codex Skill that handles argument parsing, prioritization, conflict-aware grouping into waves, optional batch-command emission for a chosen model, and integration with the solve-issues skill. Trigger on requests like "plan the next solver waves", "schedule issue batches", "group issues by file conflicts", or any reference to the ai-issue-solver batch planning step before a worker run.
---

# Plan Issue Batches

Dieser Skill kapselt `scripts/plan_issue_batches.py` (Morpheus-Methode,
Planungs-Schritt vor Schritt 3) als wiederverwendbaren Codex-Skill. Er
übernimmt das Laden der offenen Issues aus der GitHub-API, das Bestimmen
der berührten Dateien pro Issue (explizit per `Touches:`-Hinweis oder
implizit per Stichwort), das Bilden konfliktfreier Wellen und — auf Wunsch —
das Erzeugen fertiger `solve_issues_batch.py`-Aufrufe pro Welle.

## Wann einsetzen

Verwende diesen Skill, wenn eines der folgenden Szenarien zutrifft:

- Vor einem Solver-Lauf soll sichtbar werden, welche offenen Issues in
  welcher Reihenfolge und Wellen-Zusammensetzung bearbeitet werden können.
- Mehrere Issues sollen in konfliktarme Batches sortiert werden, damit
  parallele Worker sich nicht gegenseitig die gleichen Dateien überschreiben.
- Es sollen fertige `solve_issues_batch.py`-Kommandos für ein gewähltes
  Modell (`codex`, `opencode`, `claude`, …) erzeugt werden.
- Eine Trockenübung (`--dry-run` / Plan ohne Worker-Start) ist gewünscht,
  um Priorisierung, Konflikte und Aufteilung vorab zu prüfen.

Nicht verwenden für reine Analyse (`analyze_repos.py`), Issue-Erstellung
(`create_issues.py`), das eigentliche Lösen (`solve_issues.py` /
`.agents/skills/solve-issues`) oder Rework eines bestehenden PRs
(`.agents/skills/rework`).

## Voraussetzungen

Bevor der Skill läuft, müssen diese Voraussetzungen erfüllt sein:

| Komponente | Zweck | Pfad/Setup |
|------------|-------|-----------|
| Python ≥ 3.10 | Planungs-Script | `requirements.txt` |
| `requests` | GitHub-API-Calls | `pip install -r requirements.txt` |
| GitHub PAT | `GITHUB_TOKEN` + `GITHUB_USER` in `config/.env` | siehe `config/config.example.env` |
| Offene Issues | Planbare Issues im Zielrepo | GitHub-Repo mit aktivierten Issues |

Sicherheitsregel: Niemals echte Secret-Dateien lesen oder committen
(`.env`, `.env.*`, `config/.env`, `config/.env.*`). Für Konfigurationsbeispiele
ausschließlich `config/config.example.env` oder `.env.example` verwenden.

## Unterstützte Argumente

Der Skill leitet alle Argumente an `python scripts/plan_issue_batches.py`
weiter. Die wichtigsten Optionen sind:

| Argument | Default | Zweck |
|----------|---------|-------|
| `--repo` | `ai-issue-solver` | GitHub-Repository ohne Owner |
| `--label` | leer | Optionales Issue-Label als Filter |
| `--model` | `codex` | Modellname für die erzeugten Batch-Kommandos |
| `--base-branch` | `develop` | Basisbranch für erzeugte Batch-Kommandos |
| `--emit-commands` | aus | Pro Welle ein `solve_issues_batch.py`-Kommando ausgeben |

Die vollständige Liste liefert:

```bash
python scripts/plan_issue_batches.py --help
```

## Priorisierung

Die Priorisierung erfolgt in zwei Stufen:

1. **Issue-Reihenfolge** — Issues werden intern nach `(repo, number)`
   sortiert, damit die Planung deterministisch und reproduzierbar ist.
2. **Wave-Platzierung** — Pro Issue wird die erste passende Welle
   gesucht. Eine Welle ist passend, wenn es **keinen** Konflikt zwischen
   den `touches` des Issues und den `touches` der Welle gibt. Konflikte
   werden mit `touches_conflict` aus `scripts/plan_issue_batches.py`
   erkannt (Datei- oder Verzeichnis-Überschneidung).

Konflikterkennung pro Welle:

- zwei identische Pfade → Konflikt
- ein Pfad liegt unter einem Verzeichnis-Pfad der anderen Welle → Konflikt
- Pfad-Gleichheit nach Bereinigung von Slashes und leeren Einträgen

Wellen werden zusätzlich mit einer Begründung (`separation_reason`)
ausgegeben, damit die Trennung für Reviewer nachvollziehbar bleibt.

## Gruppierung (Wave-Bildung)

Die Gruppierung folgt dem **Greedy-First-Fit**-Verfahren aus
`plan_waves(issues)`:

1. Iteriere Issues in deterministischer Reihenfolge.
2. Pro Issue: durchlaufe bestehende Wellen und nimm die erste Welle
   auf, deren `touches` nicht mit dem Issue kollidieren.
3. Aktualisiere die Welle um die neuen `touches`.
4. Wenn keine bestehende Welle passt: lege eine neue Welle mit nur
   diesem Issue an.

Heuristik für `touches`:

- `Touches:`-Hinweis im Issue-Body (Backticks oder Komma/Semikolon-getrennt)
- Stichwort-Erkennung über `KEYWORD_TOUCHES` in `plan_issue_batches.py`
  (z. B. `dashboard` → `scripts/status_dashboard.py` + Tests)
- Fallback: `README.md` + `scripts/`, wenn weder explizite noch
  implizite Touches erkannt werden

## Ausführungsplanung (Execution Plan)

Mit `--emit-commands` erzeugt der Skill pro Welle einen fertigen
`solve_issues_batch.py`-Aufruf:

```bash
python scripts/solve_issues_batch.py \
    --model <model> \
    --repo <repo> \
    --base-branch <base> \
    --issue <N1> --issue <N2> ... \
    --workers <anzahl>
```

`--workers` wird automatisch auf die Anzahl der Issues der Welle gesetzt,
sodass jede Welle vollständig parallel innerhalb der Worker-Limits
laufen kann. Die ausgegebenen Kommandos sind so gestaltet, dass sie
ohne weitere Nachbearbeitung in einer Shell ausgeführt werden können
(`shlex.quote` schützt Pfade und Argumente).

## Standardablauf

1. **Argumente prüfen** — mindestens `--repo` (Default `ai-issue-solver`)
   wird erwartet. `--model` und `--base-branch` haben sinnvolle Defaults.
2. **Config laden** — `load_env` aus `scripts/utils.py`; ohne
   `GITHUB_TOKEN` und `GITHUB_USER` bricht der Skill mit Exit-Code 1 ab.
3. **Issues laden** — `GitHubClient.get_open_issues` aus
   `scripts/solve_issues.py`; PRs werden herausgefiltert.
4. **Touches bestimmen** — pro Issue: explizit per `Touches:`-Hinweis,
   sonst per Stichwort, sonst Fallback `README.md` + `scripts/`.
5. **Wellen planen** — `plan_waves` baut die konfliktarme Wellenliste.
6. **Plan rendern** — `render_plan` erzeugt Wellen, Begründungen,
   Touches und optionale Batch-Kommandos.
7. **Ausgabe** — Wellenliste wird auf stdout ausgegeben; `--emit-commands`
   ergänzt pro Welle das passende Batch-Kommando.

## Helper Scripts

Der Skill integriert sich in die bestehenden Helfer im Projekt:

| Helper | Zweck |
|--------|-------|
| `scripts/utils.py` | `load_env`, `require_config_value`, `print_banner`, `print_step` |
| `scripts/solve_issues.py` | `GitHubClient`, `MODEL_CONFIGS` (für Modell-Validierung) |
| `scripts/plan_issue_batches.py` | Planungs-Logik (`plan_waves`, `render_plan`, …) |

Zusätzlich enthält der Skill eigene, dünnere Helfer unter
`.agents/skills/plan-issue-batches/`:

- `helpers/run_plan.sh` — kapselt die häufigsten
  `python scripts/plan_issue_batches.py`-Aufrufe.
- `helpers/parse_args.py` — kleine Python-Hilfe zum Validieren der
  Skill-Argumente.

## Beispiele

Minimale Beispiele liegen unter
[`.agents/skills/plan-issue-batches/examples/`](examples/README.md). Häufige
Aufrufe:

```bash
# Standardplan für das Default-Repo
python scripts/plan_issue_batches.py --repo ai-issue-solver

# Plan inklusive fertiger Batch-Kommandos für OpenCode
python scripts/plan_issue_batches.py \
    --repo ai-issue-solver \
    --emit-commands \
    --model opencode

# Plan nur für Issues mit bestimmtem Label
python scripts/plan_issue_batches.py \
    --repo ai-issue-solver \
    --label agent/planner

# Plan gegen einen anderen Basisbranch
python scripts/plan_issue_batches.py \
    --repo ai-issue-solver \
    --emit-commands \
    --model codex \
    --base-branch main
```

Der Skill-Wrapper `helpers/run_plan.sh` nimmt dieselben Argumente und
normalisiert den Aufruf:

```bash
bash .agents/skills/plan-issue-batches/helpers/run_plan.sh \
    --repo ai-issue-solver \
    --emit-commands \
    --model opencode
```

## Sicherheits- und Geheimnisschutz-Regeln

Diese Regeln werden vom Planungs-Script bereits eingehalten und sind
**nicht** verhandelbar:

- **Repo-relative Pfade**: Pfade in Wellen und Batch-Kommandos sind
  immer repo-relativ (z. B. `scripts/datei.py`). Absolute Worktree-Pfade
  werden vom Planungs-Script nicht erzeugt.
- **Keine Secret-Dateien lesen oder schreiben**: `GITHUB_TOKEN` und
  `GITHUB_USER` werden ausschließlich aus `config/.env` gelesen und
  niemals in den Plan oder die erzeugten Batch-Kommandos geschrieben.
- **Keine Worker-Seiteneffekte**: Der Planungs-Skill startet selbst
  keine KI-Worker. Er erzeugt lediglich Pläne und optionale
  Batch-Kommandos, die der Nutzer oder ein nachgelagerter Run ausführt.

## Test-Workflow

Der Skill liefert einen Test-Workflow unter
[`.agents/skills/plan-issue-batches/tests/`](tests/README.md):

- `tests/test_skill_artifacts.py` — prüft, dass alle erwarteten
  Dateien vorhanden und nicht leer sind.
- `tests/test_helpers.py` — validiert `helpers/parse_args.py` und
  `helpers/run_plan.sh` in einer temporären Umgebung.
- `tests/test_skill_workflow.py` — führt einen End-to-End-Dry-Run auf
  synthetischen Issues aus und prüft die Plan-Ausgabe.
- `tests/run_skill_tests.sh` — Convenience-Wrapper für
  `python -m unittest discover` aus dem Skill-Verzeichnis.

Ausführen mit:

```bash
bash .agents/skills/plan-issue-batches/tests/run_skill_tests.sh
```

Die bestehenden Planungs-Tests in `tests/test_plan_issue_batches.py`
bleiben unverändert aktiv und sichern die Kernlogik von
`scripts/plan_issue_batches.py` weiterhin ab.

## Verwandte Skills

- `.agents/skills/solve-issues` — eigentliches Lösen der geplanten
  Issues mit KI-Workern.
- `.agents/skills/rework` — gezielte Nacharbeit an generierten PRs.
- `.agents/skills/recovery` — Recovery bei abgebrochenen Solver-Runs.
- `.agents/skills/git-cleanup` — Branch- und PR-Bereinigung nach Merge.

Diese Skills ergänzen den hier beschriebenen Planungs-Workflow: der
`plan-issue-batches`-Skill entscheidet, **was** in welcher Welle gelöst
wird; der `solve-issues`-Skill führt die Wellen anschließend aus.
