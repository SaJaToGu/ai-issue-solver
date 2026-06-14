# Beispiel 08 — Sandbox-Härtung & Eskalations-Empfehlungen

Dieses Beispiel dokumentiert die **schmale** Härtungs-Erweiterung aus
Issue **#217**. Sie ergänzt den bestehenden Codex-Sandbox-Workflow um
drei kleine, diagnostisch orientierte Helfer:

1. **Codex-Environment-Preflight** — prüft den GitHub-Zugang über
   `gh api user` *und* Python-`requests`, **parallel**.
2. **Sandbox-Fehlerklassifizierung** — erkennt DNS/Netzwerk- und
   `.git/`-Schreibrechte-Fehler in Worker-Outputs und liefert eine
   konkrete Eskalations-Empfehlung.
3. **Schmale Eskalations-Prefix-Empfehlung** — für vier bekannte
   Befehle (`git pull --ff-only`, `git switch`, `gh pr checks`,
   `gh run view`). Alles andere bleibt absichtlich *ohne*
   Empfehlung.

Wichtig: Diese Helfer greifen **nicht** in den Solver-Hauptloop ein.
Sie sind diagnostische Begleiter; der Standard-Workflow bleibt
unverändert.

## Wann einsetzen?

- Direkt nach dem Klonen in der Codex-Sandbox, wenn Worker-Fehler
  ohne klare Ursache auftreten.
- Wenn `git pull`, `git switch` oder `gh pr checks` mit unklarem
  Permission-Error abbrechen.
- In CI, um DNS/Netzwerk-Blockaden der Sandbox früh zu erkennen.

## Aufruf

### 1) Programmatisch (innerhalb des Solver-Prozesses)

```python
from solve_issues import (
    run_codex_environment_preflight,
    print_codex_environment_preflight,
    classify_sandbox_failure,
    format_escalation_recommendation,
    recommend_escalation_prefix,
)

# Preflight — gh + requests werden unabhängig geprüft.
preflight = run_codex_environment_preflight(config)
print_codex_environment_preflight(preflight, user=config.get("GITHUB_USER"))

# Klassifizierung — z. B. nach einem fehlgeschlagenen Worker-Run.
diagnosis = classify_sandbox_failure(worker_output_tail)
print(format_escalation_recommendation(diagnosis))

# Schmale Empfehlung für bekannte Befehle
prefix = recommend_escalation_prefix("git pull --ff-only")
```

### 2) Per Helper-Skript (in CI oder Diagnose-Runs)

```bash
# Codex-Environment-Preflight aus dem Solve-Issues-Skill aufrufen
bash .agents/skills/solve-issues/helpers/preflight.sh --model codex
```

## Was wird klassifiziert?

### DNS / Netzwerk (`kind = "network"`)

| Erkanntes Muster (Beispiel)                       | Empfehlung |
|---------------------------------------------------|------------|
| `Could not resolve host: api.github.com`         | `--sandbox danger-full-access` oder ausserhalb der Sandbox |
| `Temporary failure in name resolution`           | dto. |
| `Failed to connect to …: Connection refused`     | dto. |
| `getaddrinfo failed`                              | dto. |
| `ssl3_get_record: wrong version number`           | dto. |
| `TLS connect error: hostname mismatch`            | dto. |

Die volle Pattern-Liste liegt in
`SANDBOX_NETWORK_ERROR_PATTERNS` in
[`scripts/solve_issues.py`](../../../scripts/solve_issues.py).

### `.git/`-Schreibrechte (`kind = "git_write"`)

| Erkanntes Muster (Beispiel)                                          | Empfehlung |
|----------------------------------------------------------------------|------------|
| `error: unable to write FETCH_HEAD`                                 | `--sandbox danger-full-access` |
| `fatal: Unable to create .git/index.lock: File exists`              | `rm -f .git/index.lock` oder `--sandbox danger-full-access` |
| `Permission denied while writing .git/HEAD`                         | `--sandbox danger-full-access` oder Mounts prüfen |
| `Read-only file system when writing to .git/config`                 | Repo-Klon in ein beschreibbares Verzeichnis |
| `Operation not permitted` (im .git/-Pfad)                           | `--sandbox danger-full-access` |

## Schmale Eskalations-Empfehlungen

Diese Befehle erhalten **bewusst nur** eine task-spezifische
Empfehlung — `recommend_escalation_prefix` liefert `None` für alles
andere:

| Befehl                                  | Empfehlung |
|-----------------------------------------|------------|
| `git pull --ff-only`                    | `git pull --ff-only` |
| `git switch <branch>`                   | `git switch` |
| `gh pr checks <nr>`                     | `gh pr checks` |
| `gh run view <id>`                      | `gh run view` |

Nicht-empfohlene Befehle (z. B. `git pull --rebase`, `git checkout`,
`kubectl apply`, `docker run`) liefern absichtlich `None`, damit sich
keine breite Allowlist ansammelt.

## Was ist *nicht* Teil dieser Härtung?

- Keine Änderung am Solver-Hauptloop. Normale Solver-Runs laufen
  unverändert weiter.
- Keine breite Command-Approval-Verwaltung.
- Keine Änderung am Dashboard-Prozess-Status.
- Keine Schema-Änderung an Run-Reports.

## Tests

Die Härtung wird durch eine eigene Test-Suite abgedeckt:

- [`tests/test_solve_issues_sandbox_hardening.py`](../../../tests/test_solve_issues_sandbox_hardening.py)

Sie prüft:

- DNS/Netzwerk-Klassifizierung (mehrere Patterns).
- `.git/`-Schreibrechte-Klassifizierung (FETCH_HEAD, index.lock,
  Permission denied, Read-only, Operation not permitted).
- Unbekannte Texte → `kind = "unknown"`.
- Schmale Eskalations-Empfehlungen (nur die vier dokumentierten
  Befehle).
- Codex-Environment-Preflight (gh + requests) — beide Pfade
  unabhängig auswertbar, Mock-fähig.

Ausführen:

```bash
python3 -m unittest tests.test_solve_issues_sandbox_hardening -v
```

## Sicherheits- und Geheimnisschutz

Diese Erweiterung liest oder schreibt **keine** Secret-Dateien:

- `config/.env`, `config/.env.*`, `.env`, `.env.*` werden nicht
  angefasst.
- Der Preflight nutzt ausschließlich den konfigurierten
  `GITHUB_TOKEN`; Werte werden nicht in den Empfehlungen angezeigt.
- Für Konfigurationsbeispiele siehe
  [`config/config.example.env`](../../../config/config.example.env).
