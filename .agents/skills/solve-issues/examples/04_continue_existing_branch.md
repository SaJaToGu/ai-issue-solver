# Beispiel 04 — Bestehenden Branch weiterbearbeiten

Wenn ein Solver-Run unterbrochen wurde, der Branch aber bereits
Änderungen gegen die Basis hat, kann der Skill mit `--continue-run`
den vorhandenen Branch wiederverwenden und den KI-Worker gezielt auf
den offenen Lücken ansetzen.

## Voraussetzungen

- Branch `ai/fix-issue-3` existiert remote.
- Der Branch enthält Commits, die noch nicht gemergt sind.
- Kein offener PR dazu.

## Aufruf

```bash
python scripts/solve_issues.py \
    --model opencode \
    --issue 3 \
    --continue-run
```

## Verhalten

1. `plan_branch_recovery` erkennt den vorhandenen Branch und plant
   `reuse_branch`.
2. `checkout_existing_remote_branch` checkt den Branch lokal aus.
3. `branch_has_changes_against_base` prüft, ob es Commits oder Working-
   Tree-Änderungen gegen den Base-Branch gibt.
4. **Ohne** `--continue-run` würde der Skill jetzt einen PR für die
   bereits vorhandenen Änderungen erstellen (`pr_created_from_existing_branch`).
5. **Mit** `--continue-run` läuft der Worker auf dem Branch weiter und
   kann bestehende Änderungen erweitern.

## Verwandt: Recovery-Skill

Wenn unklar ist, ob der Branch wiederverwendet werden kann, hilft der
`.agents/skills/recovery`-Skill weiter — er klassifiziert vorhandene
Run-Report-Artefakte in `resume` / `push-pr` / `retry-clean` /
`manual-review` / `delete`.

## Diagnose-Helfer

```bash
bash .agents/skills/solve-issues/helpers/recovery_check.sh \
    "$GITHUB_USER" BedBoxDrawerRole 3
```
