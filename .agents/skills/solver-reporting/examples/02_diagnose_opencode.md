# Beispiel 02 — OpenCode-Runtime-Diagnose

Filtert bekannte OpenCode-Runtime-Probleme aus einem Worker-Output und
gibt sie als Klartext aus. Deckt SQLite/WAL-Fehler und Edit-Loops ab.

## Voraussetzungen

- Worker-Output unter `reports/runs/<run_id>/worker-output.log` oder ein
  beliebiger Text-Snapshot.

## Aufruf

```bash
# Direkter Helper
python .agents/skills/solver-reporting/helpers/diagnose_opencode.py \
    --worker-output reports/runs/20260614-153038-myrepo-issue-3/worker-output.log
```

## Erkannte Befunde

### 1. SQLite/WAL-Fehler

Wenn der Worker-Output Zeilen wie

```
PRAGMA wal_checkpoint(PASSIVE)
journal_mode = WAL
```

enthält, gibt der Helper folgende Empfehlung aus:

```
OpenCode SQLite/WAL-Fehler erkannt.
Recovery: OpenCode-Prozesse beenden und nur opencode.db-wal/opencode.db-shm entfernen.
Nicht auth.json oder opencode.db löschen.
```

### 2. Edit-Loop

Wenn `Edit <file> failed` mindestens dreimal im Output vorkommt
(`OPENCODE_EDIT_FAILURE_REPEAT_THRESHOLD = 3`), meldet der Helper:

```
OpenCode Edit-Loop-Risiko erkannt: N fehlgeschlagene Edit-Versuche (<Datei1>, <Datei2>, ...).
```

Bis zu fünf Dateinamen werden in der Meldung aufgeführt.

## Beispielausgabe

```text
=== OpenCode-Runtime-Diagnose ===
Worker-Output: reports/runs/20260614-153038-myrepo-issue-3/worker-output.log
WAL-Fehler:        erkannt
Edit-Loop:         erkannt
Edit-Failures:     5 (README.md, scripts/foo.py, scripts/bar.py)
Befund:            OpenCode SQLite/WAL-Fehler erkannt.
                   Recovery: OpenCode-Prozesse beenden und nur opencode.db-wal/opencode.db-shm entfernen.
                   Nicht auth.json oder opencode.db löschen.
                   OpenCode Edit-Loop-Risiko erkannt: 5 fehlgeschlagene Edit-Versuche (README.md, scripts/foo.py, ...).
Exit-Code:         0 = keine Befunde, 2 = Befunde vorhanden
```

## Wann ist die Diagnose sinnvoll?

- Nach einem OpenCode-Run mit `worker_exit_code != 0`.
- Vor einem `.agents/skills/rework`-Schritt, um zu prüfen, ob das Problem beim
  Worker oder in der Pipeline lag.
- Bei wiederholt fehlschlagenden Edit-Versuchen in einer Datei.
