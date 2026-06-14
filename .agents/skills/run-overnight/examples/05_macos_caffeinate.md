# Beispiel 05 — macOS mit `caffeinate` wach halten

Auf macOS schläft der Rechner standardmäßig nach einer Weile ohne
Benutzerinteraktion. Für einen Nachtlauf, der mehrere Stunden läuft, ist
das tödlich — der KI-Worker würde mitten im Commit einfrieren. Abhilfe
schafft `--caffeinate`, das im Hintergrund `caffeinate -dimsu -w <pid>`
startet.

## Voraussetzungen

- macOS (das `caffeinate`-Binary ist Bestandteil von macOS).
- Der Skill muss mit `--caffeinate` aufgerufen werden, sonst wird der
  Mac normal schlafen gelegt.

## Aufruf

```bash
python scripts/run_overnight.py \
    --model codex \
    --workers 2 \
    --caffeinate
```

Mit dem Skill-Wrapper:

```bash
bash .agents/skills/run-overnight/helpers/run_overnight.sh \
    --model codex \
    --workers 2 \
    --caffeinate
```

## Was passiert intern?

1. `keep_awake(args.caffeinate, log_path)` öffnet einen Kontext-Manager.
2. Beim Eintritt schreibt der Kontext-Manager `started` in
   `caffeinate.log` und startet `caffeinate -dimsu -w <pid>` mit
   `pid` = aktuelle Python-PID.
3. Der Mac bleibt wach, solange der Runner läuft.
4. Beim Verlassen sendet der Kontext-Manager `terminate` an den
   `caffeinate`-Prozess, wartet bis zu 5 Sekunden und `kill`-t ihn
   notfalls. Anschließend schreibt er `finished_at: …` ins Log.
5. Auf Nicht-macOS oder ohne `caffeinate`-Binary wird der Schritt
   übersprungen und eine Warnung ausgegeben.

## Preflight

`helpers/preflight.sh` prüft `--caffeinate` auf macOS:

```bash
bash .agents/skills/run-overnight/helpers/preflight.sh \
    --model codex --caffeinate
```

Wenn `caffeinate` fehlt, bricht der Preflight mit Exit 1 ab.

## Scheduling + caffeinate

`launchd` weckt den Mac zum geplanten Zeitpunkt auf, **wenn** der Rechner
nicht komplett ausgeschaltet ist. Mit `--caffeinate` bleibt der Mac
zusätzlich wach, solange der Runner läuft. Kombiniere die beiden
Mechanismen für zuverlässige Nachtläufe:

```xml
<key>Label</key><string>de.local.ai-issue-solver.overnight</string>
<key>ProgramArguments</key>
<array>
  <string>/bin/bash</string>
  <string>/Pfad/zum/Repo/.agents/skills/run-overnight/helpers/run_overnight.sh</string>
  <string>--model</string><string>codex</string>
  <string>--workers</string><string>2</string>
  <string>--caffeinate</string>
</array>
<key>StartCalendarInterval</key>
<dict><key>Hour</key><integer>2</integer><key>Minute</key><integer>0</integer></dict>
```

## Diagnose

```bash
tail -f reports/overnight/<session>/caffeinate.log
```

Erwartete Zeilen:

```
step: caffeinate
started_at: 2026-06-14T02:00:00
command: caffeinate -dimsu -w 12345

status: started
finished_at: 2026-06-14T05:31:12
```

Wenn die `finished_at`-Zeile fehlt, ist der Runner abgestürzt und
`caffeinate` läuft noch. Beende ihn manuell:

```bash
pgrep -fl caffeinate   # PIDs notieren
kill <pid>
```

## Hinweise

- `caffeinate -w <pid>` überwacht einen konkreten Prozess. Sobald dieser
  endet, beendet sich `caffeinate` von selbst. Trotzdem sendet der
  Kontext-Manager explizit `terminate`, damit der Log-Eintrag
  `finished_at` sofort erscheint.
- Auf Nicht-macOS ist `--caffeinate` ein No-op, gibt aber eine Warnung
  aus. Damit kannst du den Parameter in `launchd`-Plists portabel halten.
