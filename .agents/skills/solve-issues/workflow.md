# Solve-Issues — Workflow-Dokumentation

Diese Dokumentation beschreibt den vollständigen Workflow, den der
`solve-issues`-Skill ausführt. Sie ergänzt die kompakte Beschreibung in
`SKILL.md` und dient als Referenz beim Debugging, beim Schreiben eigener
Helper oder beim Audit einzelner Solver-Runs.

## 1. Aufrufvarianten

Der Skill akzeptiert alle Argumente, die `python scripts/solve_issues.py`
versteht. Die wichtigsten Optionen sind in `SKILL.md` (`## Auswahl des
Workers`) zusammengefasst; die vollständige Liste liefert:

```bash
python scripts/solve_issues.py --help
```

Drei typische Aufrufmuster:

1. **Diagnose** — `--dry-run` ohne Worker-Start. Nützlich, um vor dem
   eigentlichen Lauf zu sehen, welcher Branch gewählt würde und welche
   PR-Basis verwendet wird.
2. **Einzellauf** — `--repo <name> --issue <nummer>`. Der häufigste Fall.
3. **Batch / Run-Overnight** — ohne `--repo`/`--issue` werden alle
   erreichbaren Repos durchlaufen. Empfohlen nur in
   `scripts/solve_issues_batch.py` oder `scripts/run_overnight.py`.

## 2. Phasenmodell

Jeder Run durchläuft sieben klar getrennte Phasen. Der Phase-String wird in
`reports/runs/<run_id>/health.json` festgehalten, damit das Dashboard und
der `.agents/skills/recovery`-Skill den Status einordnen können.

| Phase | Bedeutung | Exit-Strategie |
|-------|-----------|----------------|
| `preflight` | GitHub-Config und Worker-Verfügbarkeit prüfen | Bei Fehler sofortiger Abbruch, kein Run-Report |
| `congestion` | Workflow-Congestion prüfen | Bei `recommended_action != "continue"` Abbruch |
| `clone` | Repo klonen, Branch anlegen | Bei Fehler: `clone_failed` im Report |
| `worker_running` | KI-Worker läuft | Bei Codex-Rate-Limit optional `rate_limit_deferred` |
| `validating` | `validate_worker_changes` läuft | Bei Syntaxfehler: `validation_failed` |
| `committing` | `commit_and_push` läuft | Bei Fehler: `push_failed`, optional `preserved_worktree` |
| `creating_pr` | `create_issue_pull_request` läuft | Bei Fehler: `pr_failed` |

`create_run_report` initialisiert den Report mit `status="started"`,
`write_run_health` aktualisiert die laufende Phase, und am Ende schreibt
`write_run_report` den finalen Status.

## 3. Verzweigungen

Der Skill trifft an mehreren Stellen Entscheidungen, die Recovery und
Reviewer später nachvollziehen können:

- **Branch-Wahl** — `plan_branch_recovery` klassifiziert in
  `skip_existing_pr`, `skip_merged_pr`, `reuse_branch`,
  `skip_closed_pr` und `new`. Der Plan wird im Run-Report unter `note`
  abgelegt.
- **Modell-Auswahl** — entweder explizit (`--model`) oder via
  `--auto-model` + `model_selection.select_model_for_issue`. Bei
  `--auto-model` muss `--issue` gesetzt sein.
- **Ensemble** — `--ensemble N` führt `N` Modelle parallel aus und wählt
  das Ergebnis mit dem höchsten Score (siehe `evaluate_results`). Score
  setzt sich zusammen aus: `has_changes` (3), `returncode == 0` (2),
  `should_continue` (1) und begrenzt durch `changed_files` (max 5).
- **Side-Effect-Filter** — `meaningful_changed_paths_for_worker`
  entfernt `.aider*`, `.DS_Store` und leere `.gitignore`/`LICENSE`-Stubs,
  bevor der Assessment-Score berechnet wird.

## 4. Run-Artefakte

Ein erfolgreicher oder fehlgeschlagener Run hinterlässt immer diese
Dateien unter `reports/runs/<run_id>/`:

| Datei | Inhalt |
|-------|--------|
| `summary.txt` | Kompakte Zusammenfassung für `.agents/skills/recovery` und das Dashboard |
| `metadata.json` | Repo, Issue, Branch, Provider, Modell-Name, Zeitstempel |
| `worker-output.log` | Vollständiger Worker-Output (kann mehrere MB groß sein) |
| `health.json` | Phasenstatus, Worker-PID, letzter Aktivitätszeitpunkt |
| `resource-diagnostics.json` | Lock- und Branch-Konflikt-Diagnostik |
| `vibe.log.snippet.txt` | (Nur `mistral-vibe`) Snippet aus `.vibe/logs/vibe.log` |

Bei Fehlern mit erhaltenswerten Änderungen wird zusätzlich ein
`preserved_worktree` unter `reports/preserved-worktrees/...` angelegt
(`should_preserve_worktree` + `preserve_worker_worktree`).

## 5. Beobachtbarkeit

Der Skill setzt mehrere Hooks ein, damit Runs auch im Hintergrund gut
sichtbar bleiben:

- **Run-Health** — `write_run_health` aktualisiert `health.json` mit
  Phase, Worker-PID und Zeitstempel. Das Dashboard liest diese Datei.
- **Resource-Diagnostics** — `write_resource_diagnostics_to_report`
  schreibt Lock- und Branch-Konflikt-Informationen. Damit kann der
  `.agents/skills/recovery`-Skill nach einem Absturz entscheiden, ob ein
  Resume möglich ist.
- **OpenCode-Session-Metriken** — Bei `--model opencode` werden
  `cost_usd`, Token-Zähler und `budget_exceeded` aus der Session
  extrahiert und im Run-Report abgelegt.
- **Vibe-Log-Snippet** — Bei `--model mistral-vibe` wird das Ende der
  `.vibe/logs/vibe.log` als Snippet angehängt.

## 6. Fehlerklassifikation

`SKILL.md` (`## Sicherheits- und Geheimnisschutz-Regeln`) und
`reports/runs/.../summary.txt` verwenden konsistente Status-Strings, die
das Dashboard und der `.agents/skills/recovery`-Skill auswerten:

| Status | Bedeutung | Empfohlene Aktion |
|--------|-----------|-------------------|
| `pr_created` | PR erfolgreich erstellt | Review |
| `pr_created_with_warning` | Vibe-Turn-Limit erreicht, PR trotzdem offen | Manueller Review-Fokus auf Vollständigkeit |
| `pr_created_from_existing_branch` | `--continue-run`, vorhandene Änderungen genutzt | Direkter Review |
| `pr_skipped` | `--skip-pr` (Benchmark-Modus) | Diff selbst inspizieren |
| `pr_failed` | PR-API-Aufruf fehlgeschlagen | `.agents/skills/recovery` |
| `push_failed` | Commit/Push fehlgeschlagen | `.agents/skills/recovery` (meist Pipeline-Problem) |
| `clone_failed` | Klonen fehlgeschlagen | Base-Branch prüfen, Token prüfen |
| `branch_create_failed` | Branch konnte nicht angelegt werden | Recovery-Plan erneut starten |
| `checkout_failed` | `checkout_existing_remote_branch` fehlgeschlagen | `.agents/skills/recovery` |
| `validation_failed` | Syntax/Schreibrechte/Konfliktmarker | Meist Modell- oder Sandbox-Problem |
| `no_changes` | Worker ohne Änderungen beendet | Prompt prüfen, ggf. `.agents/skills/rework` |
| `nonzero_with_changes` | Worker-Fehler, aber Änderungen da | Diff manuell prüfen |
| `nonzero_without_changes` | Worker-Fehler ohne Änderungen | `.agents/skills/rework` |
| `rate_limit_deferred` | Codex-Rate-Limit erreicht | Bei Batch: erneut einplanen |
| `lock_failed` | Issue-Lock konnte nicht erworben werden | Später erneut versuchen |
| `branch_conflict` | Anderer Run arbeitet am gleichen Branch | Auf Konflikt-Run warten |
| `started` | Initialer Zustand, kein Worker-Output | Wahrscheinlich Abbruch — `.agents/skills/recovery` |
| `skip_existing_pr` | Branch hatte bereits offenen PR | Manuell prüfen |
| `skip_merged_pr` | PR war bereits gemergt | Branch ggf. mit `.agents/skills/git-cleanup` löschen |
| `skip_closed_pr` | PR war geschlossen, ungemergt | `.agents/skills/rework` empfohlen |

## 7. Aufräumen

Nach einem Merge des PRs kommen diese Schritte:

1. `.agents/skills/rework` — falls Reviewer Anmerkungen haben.
2. `.agents/skills/recovery` — falls Artefakte aufgeräumt werden müssen.
3. `.agents/skills/git-cleanup` — gemergte AI-Branches sicher löschen.
4. `python scripts/post_merge_cleanup.py` — Bulk-Cleanup vieler Repos.

## 8. Erweiterung

Wenn ein neuer Provider angebunden werden soll:

1. Adapter in `workers/<name>_adapter.py` anlegen (siehe
   `workers/base.py` für die Schnittstelle).
2. Eintrag in `MODEL_CONFIGS` (`scripts/solve_issues.py`) ergänzen.
3. Factory `get_worker_adapter` erweitern.
4. Optional Helper im Skill anpassen (`helpers/run_solve.sh`,
   `helpers/parse_args.py`).
5. Tests im `tests/`-Verzeichnis des Repos ergänzen.
6. Diese Doku in `## Auswahl des Workers` aktualisieren.

## 9. Sandbox-Härtung (Issue #217)

Seit Issue #217 gibt es drei schmale, diagnostische Helfer in
`scripts/solve_issues.py`. Sie ersetzen **keinen** bestehenden
Workflow-Schritt, sondern ergänzen die Fehlerauswertung:

- `run_codex_environment_preflight(config)` / `print_codex_environment_preflight(...)` —
  prüft den GitHub-Zugang über `gh api user` *und* Python-`requests`
  parallel und druckt das Ergebnis kompakt. Beide Pfade werden
  unabhängig ausgewertet, damit ein Sandbox-DNS-Block nicht den
  anderen Pfad mit-abbricht.
- `classify_sandbox_failure(text)` — erkennt DNS/Netzwerk-Fehler
  (`kind = "network"`) und `.git/`-Schreibrechte-Fehler
  (`kind = "git_write"`). Alles andere liefert `kind = "unknown"`.
  Jeder Treffer enthält einen konkreten `hint` mit
  Eskalations-Empfehlung (z. B. `--sandbox danger-full-access` oder
  `rm -f .git/index.lock`).
- `recommend_escalation_prefix(command)` — gibt für genau vier
  dokumentierte Befehle (`git pull --ff-only`, `git switch`,
  `gh pr checks`, `gh run view`) eine schmale Empfehlung zurück.
  Andere Befehle liefern `None`, damit keine breite Allowlist
  entsteht.

Details und Anwendungsbeispiele liegen unter
[examples/08_sandbox_escalation.md](examples/08_sandbox_escalation.md).
Die Test-Suite
`tests/test_solve_issues_sandbox_hardening.py` deckt alle drei
Helfer ab.
