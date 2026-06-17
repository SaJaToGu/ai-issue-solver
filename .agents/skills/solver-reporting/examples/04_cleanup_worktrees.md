# Beispiel 04 — Preserved Worktrees aufräumen

Löscht abgelaufene Preserved Worktrees unter
`reports/preserved-worktrees/`. Standard-Retention ist 14 Tage
(`PRESERVED_WORKTREE_RETENTION_DAYS`).

## Voraussetzungen

- Verzeichnis `reports/preserved-worktrees/` (kann leer sein, dann
  passiert nichts).
- Bash-Shell.

## Aufruf

```bash
# Dry-Run (Standard) — zeigt nur, was gelöscht würde
bash .agents/skills/solver-reporting/helpers/cleanup_worktrees.sh

# Andere Retention
bash .agents/skills/solver-reporting/helpers/cleanup_worktrees.sh \
    --retention-days 30

# Wirklich löschen
bash .agents/skills/solver-reporting/helpers/cleanup_worktrees.sh \
    --apply
```

## Erwartete Ausgabe

```text
=== solver-reporting: cleanup_worktrees ===
Root:           reports/preserved-worktrees
Retention:      14 Tage
Dry-Run:        ja
Aktuelle Zeit:  2026-06-14 16:00:00
Cutoff:         2026-05-31 16:00:00

Kandidaten (älter als 14 Tage):
  reports/preserved-worktrees/20260515-110038-myrepo-issue-12/myrepo
  reports/preserved-worktrees/20260520-142211-myrepo-issue-13/myrepo

→ Dry-Run: keine Aktion. Mit --apply wirklich löschen.
```

## Sicherheit

- Der Helper bricht ab, wenn der Root-Pfad außerhalb von
  `reports/preserved-worktrees` liegt.
- Verzeichnisse werden **nur** über `shutil.rmtree` gelöscht, niemals
  mit `rm -rf`.
- Vor `--apply` sollte der Dry-Run-output mit der
  [`.agents/skills/recovery`](../SKILL.md)-Empfehlung abgeglichen werden.

## Alternative: Über den Solver-Script

```bash
# Entspricht dem Helper mit Default-Retention
python scripts/solve_issues.py --cleanup-preserved-worktrees \
    --retention-days 14 --apply
```

Der Skill-Wrapper ist die read-only-Variante, der Solver-Script bietet
zusätzlich `--apply` als zentralen Code-Pfad.
