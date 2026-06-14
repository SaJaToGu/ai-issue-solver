#!/usr/bin/env bash
# Hilfs-Script: gibt eine zur Umgebung passende Scheduling-Vorlage aus
# (launchd, cron, systemd-timer). Damit lässt sich der run-overnight-Skill
# in bestehende Automation einbinden, ohne dass du das Rad neu erfinden
# musst.
#
# Verwendung:
#   bash helpers/scheduling_hint.sh
#   bash helpers/scheduling_hint.sh --hour 2 --minute 30
#   bash helpers/scheduling_hint.sh --type systemd --hour 3
#
# Optionen:
#   --type launchd|cron|systemd|all   Welche Vorlage(n) ausgegeben werden (Standard: all)
#   --hour H                          Stunde für StartCalendarInterval / cron (Standard: 2)
#   --minute M                        Minute (Standard: 0)
#   --repo-path P                     Pfad zum Repo (Standard: aktuelles Verzeichnis)
#   --label NAME                      Label/Identifier für den Job (Standard: ai-issue-solver-overnight)
#   --model MODEL                     Modell für die launchd/systemd-Vorlage (Standard: codex)
#   --workers N                       Worker für die Vorlage (Standard: 2)

set -euo pipefail

TYPE="all"
HOUR="2"
MINUTE="0"
REPO_PATH="$(pwd)"
LABEL="ai-issue-solver-overnight"
MODEL="codex"
WORKERS="2"

while [ $# -gt 0 ]; do
  case "$1" in
    --type)
      TYPE="${2:-all}"
      shift 2
      ;;
    --hour)
      HOUR="${2:-2}"
      shift 2
      ;;
    --minute)
      MINUTE="${2:-0}"
      shift 2
      ;;
    --repo-path)
      REPO_PATH="${2:-$(pwd)}"
      shift 2
      ;;
    --label)
      LABEL="${2:-ai-issue-solver-overnight}"
      shift 2
      ;;
    --model)
      MODEL="${2:-codex}"
      shift 2
      ;;
    --workers)
      WORKERS="${2:-2}"
      shift 2
      ;;
    -h|--help)
      cat <<USAGE
Verwendung: scheduling_hint.sh [--type launchd|cron|systemd|all] [--hour H] [--minute M]
                              [--repo-path P] [--label NAME] [--model M] [--workers N]
USAGE
      exit 0
      ;;
    *)
      echo "Unbekanntes Argument: $1" >&2
      exit 2
      ;;
  esac
done

case "$TYPE" in
  launchd|cron|systemd|all) ;;
  *)
    echo "Ungültiger --type: $TYPE (erwartet: launchd|cron|systemd|all)" >&2
    exit 2
    ;;
esac

if ! echo "$HOUR" | grep -Eq '^[0-9]+$' || [ "$HOUR" -lt 0 ] || [ "$HOUR" -gt 23 ]; then
  echo "--hour muss zwischen 0 und 23 liegen" >&2
  exit 2
fi
if ! echo "$MINUTE" | grep -Eq '^[0-9]+$' || [ "$MINUTE" -lt 0 ] || [ "$MINUTE" -gt 59 ]; then
  echo "--minute muss zwischen 0 und 59 liegen" >&2
  exit 2
fi

print_launchd() {
  cat <<PLIST
# launchd plist — speichern unter ~/Library/LaunchAgents/${LABEL}.plist
# Danach: launchctl load ~/Library/LaunchAgents/${LABEL}.plist
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>de.local.${LABEL}</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>${REPO_PATH}/.agents/skills/run-overnight/helpers/run_overnight.sh</string>
    <string>--model</string><string>${MODEL}</string>
    <string>--workers</string><string>${WORKERS}</string>
  </array>
  <key>StartCalendarInterval</key>
  <dict>
    <key>Hour</key><integer>${HOUR}</integer>
    <key>Minute</key><integer>${MINUTE}</integer>
  </dict>
  <key>StandardOutPath</key><string>${REPO_PATH}/reports/overnight/${LABEL}.out.log</string>
  <key>StandardErrorPath</key><string>${REPO_PATH}/reports/overnight/${LABEL}.err.log</string>
  <key>RunAtLoad</key><false/>
</dict>
</plist>
PLIST
}

print_cron() {
  cat <<CRON
# crontab-Eintrag (crontab -e)
${MINUTE} ${HOUR} * * * cd ${REPO_PATH} && /usr/bin/env bash .agents/skills/run-overnight/helpers/run_overnight.sh --model ${MODEL} --workers ${WORKERS} >> reports/overnight/${LABEL}.cron.log 2>&1
CRON
}

print_systemd() {
  cat <<SYSTEMD
# /etc/systemd/system/${LABEL}.service
[Unit]
Description=AI Issue Solver — Overnight Runner
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
WorkingDirectory=${REPO_PATH}
ExecStart=/usr/bin/env bash ${REPO_PATH}/.agents/skills/run-overnight/helpers/run_overnight.sh --model ${MODEL} --workers ${WORKERS}
StandardOutput=append:${REPO_PATH}/reports/overnight/${LABEL}.out.log
StandardError=append:${REPO_PATH}/reports/overnight/${LABEL}.err.log

# /etc/systemd/system/${LABEL}.timer
[Unit]
Description=AI Issue Solver — Overnight Timer

[Timer]
OnCalendar=*-*-* ${HOUR}:${MINUTE}:00
Persistent=true
Unit=${LABEL}.service

[Install]
WantedBy=timers.target
# Aktivieren: systemctl enable --now ${LABEL}.timer
SYSTEMD
}

case "$TYPE" in
  launchd)
    print_launchd
    ;;
  cron)
    print_cron
    ;;
  systemd)
    print_systemd
    ;;
  all)
    echo "=== launchd (macOS) ==="
    print_launchd
    echo
    echo "=== cron (Linux/BSD) ==="
    print_cron
    echo
    echo "=== systemd (Linux) ==="
    print_systemd
    ;;
esac
