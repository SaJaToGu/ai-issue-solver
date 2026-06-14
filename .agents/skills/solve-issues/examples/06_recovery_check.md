# Beispiel 06 — Recovery-Check vor dem Solver-Start

Bevor ein `python scripts/solve_issues.py`-Run gestartet wird, kannst du
prüfen, ob es für eine Issue-Nummer bereits Branches oder PRs gibt. Das
verhindert doppelte Arbeit.

## Aufruf

```bash
bash .agents/skills/solve-issues/helpers/recovery_check.sh \
    "$GITHUB_USER" BedBoxDrawerRole 3
```

## Was wird ausgegeben?

- Standard-Branch (`ai/fix-issue-3`) — vorhanden oder fehlt.
- Liste aller Branches, die mit `ai/fix-issue-3` oder `ai/fix-issue-3-...`
  beginnen.
- Pro Branch: ein Eintrag pro PR mit Status
  - **OFFEN** — Solver überspringt diesen Branch.
  - **GEMERGED** — Branch ist obsolet, `.skills/git-cleanup` empfohlen.
  - **GESCHLOSSEN (unmerged)** — `.skills/rework` empfohlen.

## Anwendungsfälle

- Vor `--continue-run`: gibt es überhaupt einen wiederverwendbaren Branch?
- Nach einem Crash: ist der Branch aus dem letzten Run noch im
  akzeptablen Zustand?
- Vor dem Anlegen eines neuen Backlog-Issues: gibt es historische
  Branches, die das Issue schon halb gelöst haben?
