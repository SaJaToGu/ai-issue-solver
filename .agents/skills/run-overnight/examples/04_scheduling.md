# Beispiel 04 — Scheduling (launchd, cron, systemd)

Der `run-overnight`-Skill ist scheduling-neutral. Du kannst ihn manuell
starten oder in `launchd` (macOS), `cron` (BSD/Linux) oder `systemd`
(Linux) einplanen. `helpers/scheduling_hint.sh` gibt eine zur Umgebung
passende Vorlage aus.

## Schnellstart

```bash
bash .agents/skills/run-overnight/helpers/scheduling_hint.sh
```

Ausgabe (gekürzt):

```
=== launchd (macOS) ===
<?xml version="1.0" encoding="UTF-8"?>
...
=== cron (Linux/BSD) ===
0 2 * * * cd /Pfad/zum/Repo && /usr/bin/env bash ...
=== systemd (Linux) ===
[Unit]
Description=AI Issue Solver — Overnight Runner
...
```

Mit Optionen:

```bash
bash .agents/skills/run-overnight/helpers/scheduling_hint.sh \
    --type systemd --hour 3 --minute 15 --workers 3 --model opencode
```

## macOS — launchd

Speichere die ausgegebene `plist` unter
`~/Library/LaunchAgents/ai-issue-solver-overnight.plist` und lade sie:

```bash
launchctl load ~/Library/LaunchAgents/ai-issue-solver-overnight.plist
launchctl start ai-issue-solver-overnight   # einmal manuell anstoßen
launchctl list | grep ai-issue-solver      # Status prüfen
launchctl unload ~/Library/LaunchAgents/ai-issue-solver-overnight.plist
```

Tipps:

- `RunAtLoad: false` verhindert, dass der Job beim Boot läuft.
- `StandardOutPath` / `StandardErrorPath` zeigen auf eigene Log-Dateien,
  zusätzlich zur `summary.txt`.
- macOS wacht den Rechner **nicht** auf, wenn er schläft. Für Nachtläufe
  auf einem zugeklappten Laptop kombiniere `launchd` mit
  `pmset schedule` oder `--caffeinate` (siehe
  [05_macos_caffeinate.md](05_macos_caffeinate.md)).

## Linux/BSD — cron

Füge den ausgegebenen Eintrag mit `crontab -e` ein. Wichtig:

- `cd` in das Repo, damit `python scripts/run_overnight.py` die
  richtigen Pfade findet.
- Leite stdout/stderr in eine eigene Log-Datei um
  (`>> reports/overnight/cron.log 2>&1`), damit du Probleme siehst.

## Linux — systemd

Lege die beiden Dateien unter `/etc/systemd/system/` ab
(siehe `scheduling_hint.sh`):

```bash
sudo cp ai-issue-solver-overnight.service /etc/systemd/system/
sudo cp ai-issue-solver-overnight.timer    /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now ai-issue-solver-overnight.timer
systemctl list-timers ai-issue-solver-overnight
```

Der Service läuft als `oneshot`, der Timer startet ihn täglich um
`HH:MM:00`. `Persistent=true` sorgt dafür, dass verpasste Läufe
nachgeholt werden, wenn der Rechner zum geplanten Zeitpunkt aus war.

## Empfehlung

- Teste immer zuerst mit
  [01_smoke_test.md](01_smoke_test.md) und prüfe die `summary.txt`,
  bevor du den Job einplanst.
- Halte `rework`-/PR-Reviews in der `launchd`/cron/`systemd`-Umgebung
  aus, weil der Worker nachts unbeaufsichtigt läuft.
- Nutze `--skip-tests`, wenn dein Projekt keine schnelle Test-Suite hat
  und du den Nachtlauf nicht blockieren willst.
