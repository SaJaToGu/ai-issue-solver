# Beispiele — `plan-issue-batches`-Skill

Diese Beispiele zeigen typische Aufrufe des `plan-issue-batches`-Skills.
Alle Beispielausgaben sind illustrativ; die echten Wellen hängen von
den aktuell offenen Issues im Zielrepo ab.

## Übersicht

| Beispiel | Zweck |
|----------|-------|
| [01 — Standardplan](01_standard_plan.md) | Default-Plan für `ai-issue-solver` |
| [02 — Plan mit Batch-Kommandos](02_emit_commands.md) | `--emit-commands` mit Modell `opencode` |
| [03 — Plan mit Label-Filter](03_label_filter.md) | Planung auf bestimmtes Issue-Label einschränken |
| [04 — Plan mit eigenem Basisbranch](04_custom_base_branch.md) | `--base-branch` anpassen |

## Schnellstart

```bash
# Standardplan anzeigen
bash .skills/plan-issue-batches/helpers/run_plan.sh --repo ai-issue-solver

# Plan inklusive fertiger Batch-Kommandos für OpenCode
bash .skills/plan-issue-batches/helpers/run_plan.sh \
    --repo ai-issue-solver \
    --emit-commands \
    --model opencode
```

## Verwandte Skills

- [`.agents/skills/solve-issues`](../solve-issues/examples/README.md) —
  führt die geplanten Wellen tatsächlich aus.
- [`.skills/recovery`](../recovery/SKILL.md) — Recovery bei
  abgebrochenen Solver-Runs.
- [`.skills/rework`](../rework/SKILL.md) — gezielte Nacharbeit an
  generierten PRs.
