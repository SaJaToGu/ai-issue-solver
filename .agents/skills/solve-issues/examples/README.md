# Beispiele für den solve-issues-Skill

Dieses Verzeichnis enthält reproduzierbare Aufrufe für die häufigsten
Szenarien. Alle Beispiele gehen davon aus, dass du im Projekt-Root bist
und `config/.env` gemäß `config/config.example.env` befüllt ist.

## Voraussetzungen

```bash
# Python-Abhängigkeiten
pip install -r requirements.txt
pip install -r requirements-aider.txt   # nur falls du aider-Worker nutzt

# Config anlegen (Secrets bleiben in config/.env, nicht committen!)
cp config/config.example.env config/.env
# → jetzt GITHUB_TOKEN, GITHUB_USER und Provider-Keys eintragen
```

## Beispiele

| Datei | Szenario |
|-------|----------|
| [01_single_issue_codex.md](01_single_issue_codex.md) | Einzelnes Issue mit Codex CLI |
| [02_single_issue_opencode.md](02_single_issue_opencode.md) | Einzelnes Issue mit kostenlosem OpenCode-Modell |
| [03_dry_run.md](03_dry_run.md) | Dry-Run zur PR-Planung |
| [04_continue_existing_branch.md](04_continue_existing_branch.md) | Bestehenden Branch weiterbearbeiten |
| [05_ensemble.md](05_ensemble.md) | Drei Modelle parallel, beste Lösung gewinnt |
| [06_recovery_check.md](06_recovery_check.md) | Vorhandene Branches und PRs prüfen |
| [07_preflight.md](07_preflight.md) | Preflight ohne Solver-Start |
| [08_sandbox_escalation.md](08_sandbox_escalation.md) | Sandbox-Härtung: Fehlerklassifizierung & schmale Eskalations-Empfehlungen (Issue #217) |

## Generelles Muster

Jeder Aufruf folgt diesem Muster:

```bash
python scripts/solve_issues.py --model <MODEL> [--model-name <NAME>] \
                               [--repo <REPO>] [--issue <NUMBER>] \
                               [--dry-run] [--verbosity normal]
```

Die Helper `helpers/run_solve.sh` und `helpers/parse_args.sh` kapseln
diese Aufrufe und prüfen die Argumente vorab.
