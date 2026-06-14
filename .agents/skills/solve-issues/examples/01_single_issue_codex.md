# Beispiel 01 — Einzelnes Issue mit Codex CLI

Löst Issue #3 in `BedBoxDrawerRole` mit dem Codex CLI.

## Voraussetzungen

- `codex`-Binary im PATH (Codex Desktop oder `codex-cli`).
- `GITHUB_TOKEN` und `GITHUB_USER` in `config/.env`.
- Issues sind in `BedBoxDrawerRole` aktiviert.
- Issue #3 ist offen.

## Aufruf

```bash
python scripts/solve_issues.py \
    --model codex \
    --repo BedBoxDrawerRole \
    --issue 3 \
    --verbosity normal
```

Mit dem Skill-Wrapper:

```bash
bash .agents/skills/solve-issues/helpers/run_solve.sh \
    --model codex \
    --repo BedBoxDrawerRole \
    --issue 3
```

## Erwarteter Verlauf

1. **Preflight** — `GITHUB_TOKEN` und `GITHUB_USER` werden geprüft;
   Repo und Issue #3 werden geladen.
2. **Congestion-Check** — Abbruch, wenn bereits zu viele offene PRs da sind.
3. **Branch-Planung** — Default-Branch ist `ai/fix-issue-3`. Falls ein
   Branch mit PR existiert, wird `skip_existing_pr` ausgegeben.
4. **Klonen** — `BedBoxDrawerRole` wird nach
   `$OPENCODE_CACHE_DIR/tmp/ai-solver-XXXX/BedBoxDrawerRole` geklont.
5. **Worker** — Codex läuft mit `--sandbox workspace-write` und
   `--cd <repo>`. Output wird gefiltert.
6. **Validation** — `validate_worker_changes` prüft Schreibrechte und
   Python-Syntax.
7. **Commit/Push** — `fix: Löse Issue #3 — <Titel>`.
8. **PR** — `[AI] Fix: <Titel>` gegen den GitHub-Default-Branch.

## Diagnose

```bash
python scripts/solve_issues.py --diagnostic
```

Dieser Aufruf ist nur für `--model opencode` vorgesehen; für Codex
reicht ein simpler Aufruf mit `--dry-run` zur Plan-Anzeige:

```bash
python scripts/solve_issues.py \
    --model codex \
    --repo BedBoxDrawerRole \
    --issue 3 \
    --dry-run
```
