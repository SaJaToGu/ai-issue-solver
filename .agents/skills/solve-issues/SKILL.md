---
name: solve-issues
description: Use when a user wants to solve one or more GitHub issues in a repository with an AI worker (Codex, OpenCode, Mistral Vibe, OpenRouter, or aider-based providers like Claude, OpenAI, Mistral, Ollama). Wraps the python scripts/solve_issues.py pipeline into a single Codex Skill that handles preflight checks, model selection, branch planning, recovery, worker execution, change validation, commit/push, and PR creation. Trigger on requests like "solve issue #42", "run the AI solver on my repo", "let Codex fix this issue", or any reference to the ai-issue-solver workflow step 3.
---

# Solve Issues

Dieser Skill kapselt den kompletten Issue-Lösungs-Workflow aus
`scripts/solve_issues.py` (Morpheus-Methode, Schritt 3) als wiederverwendbaren
Codex-Skill. Er übernimmt die Vorauswahl des KI-Workers, Preflight-Checks,
Branch-Planung, Recovery bei vorhandenen Branches/PRs, die eigentliche
Worker-Ausführung, Validierung der Änderungen sowie Commit, Push und
Pull-Request-Erstellung.

## Wann einsetzen

Verwende diesen Skill, wenn eines der folgenden Szenarien zutrifft:

- Ein einzelnes offenes Issue soll automatisch von einer KI bearbeitet werden
  (z. B. `solve issue 42 in BedBoxDrawerRole with codex`).
- Mehrere Issues eines Repos sollen der Reihe nach gelöst werden.
- Ein vorhandener Branch ohne offenen PR soll wiederverwendet werden
  (`--continue-run`).
- Ein Ensemble aus mehreren Modellen soll parallel laufen und das beste
  Ergebnis ausgewählt werden (`--ensemble`).
- Eine `--dry-run`-Diagnose zur Branch- und PR-Planung ist gewünscht.

Nicht verwenden für reine Analyse (`analyze_repos.py`), Issue-Erstellung
(`create_issues.py`) oder Rework eines bestehenden PRs
(`rework_workflow.py` / `.agents/skills/rework`).

## Voraussetzungen

Bevor der Skill läuft, müssen diese Voraussetzungen erfüllt sein:

| Komponente | Zweck | Pfad/Setup |
|------------|-------|-----------|
| Python ≥ 3.10 | Solver-Scripts | `requirements.txt` |
| `requests` | GitHub-API-Calls | `pip install -r requirements.txt` |
| `aider` | Aider-Worker (Claude/OpenAI/Mistral/Ollama/OpenRouter) | `pip install -r requirements-aider.txt` |
| `git` | Klonen, Branch, Commit, Push | PATH |
| GitHub PAT | `GITHUB_TOKEN` + `GITHUB_USER` in `config/.env` | siehe `config/config.example.env` |
| Optional `codex`, `opencode`, `vibe` | CLI-Worker | siehe `docs/SETUP_AIDER.md` |

Sicherheitsregel: Niemals echte Secret-Dateien lesen oder committen
(`.env`, `.env.*`, `config/.env`, `config/.env.*`). Für Konfigurationsbeispiele
ausschließlich `config/config.example.env` oder `.env.example` verwenden.

## Helper Scripts

Der Skill integriert sich in die bestehenden Helfer im Projekt:

| Helper | Zweck |
|--------|-------|
| `scripts/utils.py` | `load_env`, `require_github_config`, `require_config_value`, `print_banner`, `print_step` |
| `scripts/solver_repository.py` | `clone_repo`, `create_branch`, `commit_and_push`, `git_status_porcelain` |
| `scripts/solver_reporting.py` | `create_run_report`, `write_run_report`, `preserve_worker_worktree` |
| `scripts/solver_run_resources.py` | `create_run_resources`, `ResourceLock`, Lock- und Branch-Konflikterkennung |
| `scripts/workflow_congestion.py` | Congestion-Analyse, `issue_has_open_pr`, `analyze_workflow_congestion` |
| `workers/*.py` | Provider-Adapter (`codex`, `opencode`, `mistral-vibe`, `aider`, `openrouter_direct`) |

Zusätzlich enthält der Skill eigene, dünnere Helfer unter
`.agents/skills/solve-issues/`:

- `helpers/run_solve.sh` — kapselt die häufigsten `python scripts/solve_issues.py`-Aufrufe.
- `helpers/preflight.sh` — prüft Config, Worker-Verfügbarkeit und Repo-Erreichbarkeit ohne Worker-Start.
- `helpers/recovery_check.sh` — inspiziert vorhandene Branches und PRs zu einer Issue-Nummer.
- `helpers/parse_args.py` — kleine Python-Hilfe zum Validieren der Skill-Argumente.

## Standardablauf

1. **Argumente prüfen** — mindestens `--model` und (für Einzel-Runs) `--repo`
   plus `--issue` müssen gesetzt sein.
2. **Config laden** — `load_env` aus `scripts/utils.py`; ohne `GITHUB_TOKEN`
   und `GITHUB_USER` abbrechen.
3. **Preflight** — Repo erreichbar? Issues aktiviert? Token hat `repo`-Scope?
   Issue offen (falls `--issue`)? Worker-Binary verfügbar?
4. **Congestion-Check** — `check_and_warn_on_congestion` aus
   `scripts/workflow_congestion.py`; bei `recommended_action != "continue"`
   ohne `--skip-congestion-check` abbrechen.
5. **Branch-Planung** — `plan_branch_recovery` wählt einen vorhandenen Branch
   ohne offenen PR, einen neuen Branch oder Skip bei vorhandenem PR.
6. **Klonen & Branch** — Repo in `$OPENCODE_CACHE_DIR/tmp/ai-solver-*/<repo>`
   klonen, Branch anlegen oder auschecken.
7. **Prompt bauen** — `AIDER_PROMPT_TEMPLATE` aus `scripts/solve_issues.py`
   mit `number`, `title` und `body` füllen. Für OpenCode zusätzlich
   `build_opencode_prompt` (relativiert Pfade, schützt Secrets).
8. **Worker-Adapter wählen** — `get_worker_adapter(model)` liefert den
   passenden Adapter aus `workers/`. Umgebung wird via `adapter.build_env`
   vorbereitet (Provider-Keys, Cache-Isolation).
9. **Worker ausführen** — `adapter.run` mit `verbosity`, optionalen
   Budget-Limits (`--max-run-cost-usd`, `--max-run-input-tokens`, …) und
   Run-Report. Live-Ausgabe wird gefiltert über `should_surface_worker_line`.
10. **Assessment** — `assess_worker_result` bewertet Returncode und
    `git_status_porcelain` (changed / no_changes / nonzero_with_changes /
    nonzero_without_changes).
11. **Validierung** — `validate_worker_changes` prüft Schreibrechte,
    Konfliktmarker und Python-Syntax (`py_compile`) für geänderte `.py`-Dateien.
12. **Commit & Push** — `commit_and_push` mit deterministischer Message
    `fix: Löse Issue #N — <Titel>`.
13. **PR erstellen** — `create_issue_pull_request` erstellt den PR über die
    GitHub-API, hängt Modell-Metadaten an und schließt optional das Issue.
14. **Aufräumen** — temporärer Klon wird entfernt; Run-Report bleibt unter
    `reports/runs/<run_id>/`; bei Fehlern ggf. `preserve_worker_worktree`.

### Sandbox-Härtung (Issue #217)

Seit Issue #217 gibt es drei schmale, diagnostische Helfer in
`scripts/solve_issues.py`:

- `run_codex_environment_preflight` / `print_codex_environment_preflight` —
  prüft den GitHub-Zugang über `gh api user` *und* Python-`requests`
  parallel.
- `classify_sandbox_failure(text)` — klassifiziert DNS/Netzwerk- und
  `.git/`-Schreibrechte-Fehler und liefert eine konkrete
  Eskalations-Empfehlung.
- `recommend_escalation_prefix(command)` — schmale Empfehlungen für
  genau vier Befehle (`git pull --ff-only`, `git switch`,
  `gh pr checks`, `gh run view`).

Diese Helfer ersetzen **keinen** Workflow-Schritt. Details und
Anwendung in
[examples/08_sandbox_escalation.md](examples/08_sandbox_escalation.md).

Eine ausführliche Schritt-für-Schritt-Beschreibung mit Beispielausgaben liegt
unter [docs/SOLVE_ISSUES_WORKFLOW.md](docs/SOLVE_ISSUES_WORKFLOW.md).

## Auswahl des Workers

| Modell | Provider | Wann sinnvoll |
|--------|----------|---------------|
| `codex` | Codex CLI | Schneller, lokaler Codex-Zugang, Default-Sandbox `workspace-write` |
| `opencode` | OpenCode CLI | Freie Modelle (`opencode/deepseek-v4-flash-free`, `opencode/mimo-v2.5-free`, `opencode/minimax-m3-free`, `opencode/nemotron-3-ultra-free`) oder kostenpflichtige Provider via OpenCode-Auth |
| `claude`, `openai`, `mistral` | aider | Klassische Provider mit API-Key, jeweils eigener `--model-name` |
| `ollama` | aider + Ollama | Lokale Modelle (Raspberry Pi, Offline) |
| `openrouter` | aider | OpenRouter-Router mit `OPENROUTER_API_KEY` |
| `openrouter_direct` | OpenRouter-API direkt | Patch-basierte Ausgabe, eigene Code-Pfade |
| `mistral-vibe` | Mistral Vibe CLI | Wenn Vibe-CLI installiert und Turn-Limit akzeptabel |

Details zu `--model`, `--model-name` und API-Keys siehe
`config/config.example.env` und `docs/SETUP_AIDER.md`.

## Beispiele

Minimale Beispiele liegen unter
[`.agents/skills/solve-issues/examples/`](examples/README.md). Häufige
Aufrufe:

```bash
# Einzelnes Issue mit Codex
python scripts/solve_issues.py --model codex --repo BedBoxDrawerRole --issue 3

# Kostenlose OpenCode-Modellfamilie
python scripts/solve_issues.py --model opencode --model-name opencode/deepseek-v4-flash-free --issue 3

# Dry-Run zur PR-Planung
python scripts/solve_issues.py --model claude --repo BedBoxDrawerRole --issue 3 --dry-run

# Bestehenden Branch weiterbearbeiten
python scripts/solve_issues.py --model opencode --issue 3 --continue-run

# Ensemble mit drei Modellen
python scripts/solve_issues.py --model opencode --issue 3 --ensemble 3 --skip-pr
```

Der Skill-Wrapper `helpers/run_solve.sh` nimmt dieselben Argumente und
normalisiert den Aufruf:

```bash
bash .agents/skills/solve-issues/helpers/run_solve.sh \
    --model opencode --model-name opencode/deepseek-v4-flash-free --issue 3
```

## Sicherheits- und Geheimnisschutz-Regeln

Diese Regeln werden vom OpenCode-Prompt, vom Codex-Adapter und vom
`build_opencode_prompt` durchgesetzt und sind **nicht** verhandelbar:

- **Repo-relative Pfade**: Verwende ausschließlich Pfade wie
  `scripts/datei.py`. Absolute Worktree-Pfade wie `/tmp/ai-solver-xyz/...`
  werden im Prompt entfernt oder durch Platzhalter ersetzt.
- **Keine Secret-Dateien lesen oder schreiben**: `.env`, `.env.*`,
  `config/.env`, `config/.env.*` werden im Worker-Prompt niemals
  weitergereicht. Konfigurationsbeispiele stammen aus
  `config/config.example.env` oder `.env.example`.
- **Keine ungewollten Side-Effects**: `.aider*`, `.aider/**`, `.DS_Store`
  und leere `.gitignore`/`LICENSE`-Stub-Dateien werden vom Assessment
  herausgefiltert.
- **Keine Commits/Pushes durch den Worker**: Der Worker schreibt nur
  Dateien. `commit_and_push` und die PR-Erstellung laufen zentral in
  `scripts/solve_issues.py`.

## Test-Workflow

Der Skill liefert einen Test-Workflow unter
[`.agents/skills/solve-issues/tests/`](tests/README.md):

- `tests/test_skill_artifacts.py` — prüft, dass alle erwarteten Dateien
  vorhanden und nicht leer sind.
- `tests/test_helpers.py` — validiert `helpers/parse_args.py`,
  `helpers/preflight.sh` und `helpers/recovery_check.sh` in einer
  temporären Umgebung.
- `tests/test_skill_workflow.py` — führt einen End-to-End-Dry-Run auf
  einem Sandbox-Repo aus und prüft Run-Report-Artefakte.
- `tests/run_skill_tests.sh` — Convenience-Wrapper für
  `python -m unittest discover` aus dem Skill-Verzeichnis.

Ausführen mit:

```bash
bash .agents/skills/solve-issues/tests/run_skill_tests.sh
```

## Verwandte Skills

- `.agents/skills/git-cleanup` — Branch- und PR-Bereinigung nach Merge.
- `.agents/skills/recovery` — Recovery bei abgebrochenen Solver-Runs.
- `.agents/skills/rework` — Gezielte Nacharbeit an generierten PRs.

Diese Skills ergänzen den hier beschriebenen Workflow und sollten nach
jedem Solver-Run in Betracht gezogen werden.
