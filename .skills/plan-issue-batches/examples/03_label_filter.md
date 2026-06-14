# Beispiel 03 — Plan mit Label-Filter

Schränkt die Planung auf Issues mit einem bestimmten Label ein.
Nützlich, um nur thematisch zusammenhängende Issues (z. B.
`agent/planner`, `theme/workflow`, `priority/1`) in einer Welle zu
bündeln.

## Voraussetzungen

- `GITHUB_TOKEN` und `GITHUB_USER` in `config/.env`.
- Offene Issues mit dem gewünschten Label im Zielrepo.

## Aufruf

```bash
python scripts/plan_issue_batches.py \
    --repo ai-issue-solver \
    --label agent/planner
```

Mit dem Skill-Wrapper:

```bash
bash .skills/plan-issue-batches/helpers/run_plan.sh \
    --repo ai-issue-solver \
    --label agent/planner
```

## Erwarteter Verlauf

1. **Config laden** — `GITHUB_TOKEN` und `GITHUB_USER` werden geprüft.
2. **Issues laden** — nur Issues mit dem Label `agent/planner` werden
   über `GitHubClient.get_open_issues(repo, label="agent/planner")`
   geholt.
3. **Wellen planen** und **Plan rendern** wie in
   [01 — Standardplan](01_standard_plan.md).

## Beispielausgabe

```text
Welle 1:
  #34 - Implement agent/planner — idea-to-issue shaping pipeline
    Touches: scripts/planner_agent.py, docs/NEXT_BACKLOG.md

  #22 - Research backlog shaping frameworks before turning ideas into issues
    Touches: docs/, README.md
    Grund: getrennt von Welle 1: keine Ueberschneidung in frueheren Wellen
```

## Kombination mit `--emit-commands`

```bash
python scripts/plan_issue_batches.py \
    --repo ai-issue-solver \
    --label agent/planner \
    --emit-commands \
    --model codex
```

Erzeugt zusätzlich pro Welle ein fertiges
`solve_issues_batch.py`-Kommando, das nur die gefilterten Issues
umfasst.

## Diagnose

- `gh issue list --label agent/planner --state open --json number,title`
  zeigt, welche Issues tatsächlich das Label tragen.
- Label-Namen sind case-sensitive: `--label Agent/Planner` liefert ein
  anderes Ergebnis als `--label agent/planner`.
