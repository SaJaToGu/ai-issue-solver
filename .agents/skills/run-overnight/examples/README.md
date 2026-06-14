# Beispiele für den run-overnight-Skill

Dieses Verzeichnis enthält reproduzierbare Aufrufe für die häufigsten
Szenarien rund um unbeaufsichtigte Nachtläufe. Alle Beispiele gehen davon
aus, dass du im Projekt-Root bist und `config/.env` gemäß
`config/config.example.env` befüllt ist.

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
| [01_smoke_test.md](01_smoke_test.md) | Preflight + leere Session ohne Worker |
| [02_standard_run.md](02_standard_run.md) | Standard-Nachtlauf mit Codex und 2 Workern |
| [03_single_issue.md](03_single_issue.md) | Einzelnes Issue über Nacht bearbeiten |
| [04_scheduling.md](04_scheduling.md) | Scheduling-Vorlagen (launchd, cron, systemd) |
| [05_macos_caffeinate.md](05_macos_caffeinate.md) | macOS mit `caffeinate` wach halten |
| [06_dashboard_review.md](06_dashboard_review.md) | Dashboard und Session-Summary prüfen |

## Generelles Muster

Jeder Aufruf folgt diesem Muster:

```bash
python scripts/run_overnight.py --model <MODEL> [--model-name <NAME>] \
                                [--repo <REPO>] [--issue <NUMBER>] \
                                [--workers N] [--caffeinate] \
                                [--skip-pull] [--skip-tests] \
                                [--skip-congestion-check] \
                                [--verbosity normal]
```

Die Helper `helpers/run_overnight.sh` und `helpers/parse_args.sh` kapseln
diese Aufrufe und prüfen die Argumente vorab. `helpers/preflight.sh` führt
einen vollständigen Preflight aus, ohne den KI-Worker zu starten.
`helpers/summary_check.sh` liest eine fertige Session-Summary und meldet
Erfolg oder Fehlschlag inklusive Issue-Outcomes.
