# OpenCode App-State-Conflict — Diagnose und Optionen

> **Status (2026-06-26):** §63 ist **geparked** (echte App-seitige
> Resolution erfordert User-seitige Aktion außerhalb dieses Repos).
> §65 (diese Diagnose + Doku) ist **active** — siehe Backlog
> `docs/BACKLOG/open.md` §65.

## Was ist der Konflikt?

Auf einer Maschine mit **beidem**:

- `~/.opencode/bin/opencode` (oder eine andere User-Installation
  der OpenCode CLI), und
- einer App, die eine eigene `opencode`-Binary mitbringt
  (z.B. MiniMax Code.app, Claude Desktop, …)

…kann die OpenCode-Solver-Pipeline den Solver-Worker nicht
starten, weil der laufende `opencode serve` (vom App-Launchd
respawnt) eine **andere Version** benutzt als die CLI, die der
Solver gerade aufrufen würde. Konkretes Symptom:

```
❌ OpenCode Versions-/Executable-Konflikt erkannt.
CLI:   version=1.15.13, exe=/Users/<user>/.opencode/bin/opencode
Serve: pid=<pid>, version=1.14.28, exe=/Applications/MiniMax Code.app/.../opencode
❌ OpenCode Worker-Start blockiert
```

Auf Guidos Mac am 2026-06-26 war genau das der Stand.

## Warum passiert das?

`opencode serve` läuft als Hintergrund-Service. macOS-Apps mit
einem Helper-Process nutzen typischerweise einen **LaunchAgent**
(`~/Library/LaunchAgents/...`) oder ein **app-internal launchd
bundle** (`/Applications/<App>.app/Contents/.../LaunchAgents/`),
der den Serve neu startet, sobald er fehlt. Wenn der App-launchd
Pfad eine **ältere** opencode-Binary mitbringt als die CLI, die
du selbst installiert hast, dann gewinnt nach jedem `kill` die
App-Variante.

Der Solver-Diagnose zeigt dir **welche App** den Serve respawnt
und **welche Binary** sie nutzt:

```bash
python scripts/opencode_state_diagnostic.py
```

Output (Beispiel, echter Lauf vom 2026-06-26):

```
Binaries found: 2
  [PATH] /Users/Guido/.opencode/bin/opencode
      version: 1.15.13
  [app-bundle:MiniMax Code] /Applications/MiniMax Code.app/.../opencode
      version: 1.14.28

Running opencode-serve: <none>

$OPENCODE_BIN: /Applications/MiniMax Code.app/.../opencode

Verdict: OK    (kein Serve-Prozess gerade; Konflikt ist latent)
```

## Drei Resolution-Optionen

In Reihenfolge der User-Kontrolle (von "App-Upstream reparieren"
bis "Projekt-seitig unabhängig machen"):

### Option A — App-Bundle aktualisieren

Der App-Hersteller (z.B. MiniMax) bringt eine neue Version heraus,
die die aktuelle OpenCode-Binary bündelt. Update über den
üblichen App-Mechanismus (Mac App Store, Sparkle, manueller
Download).

**Vorteil:** kein Repo-/Code-Touch nötig. App + CLI werden
automatisch synchron gehalten.

**Nachteil:** liegt außerhalb unserer Kontrolle. Bis das App-
Update ausgerollt ist, sind OpenCode Free-Models (z.B.
`opencode/big-pickle`, `opencode/deepseek-v4-flash-free`) auf
dieser Maschine nicht testbar.

### Option B — App-bundled Binary umbenennen oder entfernen

Wenn der App-Hersteller kein Update liefert, kann der Operator
das app-bundled `opencode` lokal **umbenennen** (z.B.
`opencode.disabled`), sodass der App-launchd die Binary nicht
mehr findet und der User-CLI gewinnt. Alternativ das App-Bundle
komplett aus `/Applications/` entfernen, wenn es nicht aktiv
gebraucht wird.

**Vorteil:** ohne App-Hersteller-Update lösbar.

**Nachteil:** kann die App-Funktionalität beeinträchtigen (wenn
die App selbst auf ihre gebündelte opencode-Binary angewiesen
ist). Vorher Doku der App prüfen.

### Option C — Projekt-seitig immer konfigurierte `OPENCODE_BIN` nutzen

Im Projekt selbst: der OpenCode-Adapter in
`scripts/solve_issues.py` ruft immer `Path(os.environ["OPENCODE_BIN"])` auf,
statt auf `PATH` zu vertrauen. Damit ist die Solver-Pipeline
immun gegen jede App-launchd-Respawn.

**Vorteil:** unabhängig vom App-Verhalten, deterministisch
reproduzierbar.

**Nachteil:** erfordert Code-Änderung im Projekt (bisher nicht
gemacht — wäre eine zukünftige §63-Folge, falls Option C
gewählt wird).

## Workaround `--allow-opencode-state-conflict`

Der Solver hat ein Override-Flag `--allow-opencode-state-conflict`
für **Diagnose-Zwecke**. Es umgeht den Versions-Check und startet
den Worker trotzdem — aber:

- Es repariert **nicht** den Versions-Konflikt; die Worker-
  Session läuft mit der App-bundled Binary, nicht mit der CLI.
- **Niemals** als Produktionspfad benutzen. Diagnose only.
- Ergebnisse aus `--allow-opencode-state-conflict`-Runs sind
  möglicherweise nicht repräsentativ für die User-Installation.

## Empfehlung für 0.9.0

Aufgrund des Smoke-Benchmarks vom 2026-06-26
(`reports/benchmarks/smoke-free-models-2026-06-26.json`):

- **Strategische Issues** mit `--model openrouter_direct
  --model-name openai/gpt-4o` lösen. Funktioniert reproduzierbar,
  ist unabhängig vom App-State.
- **OpenCode Free-Models** sind **experimentell / supervised**
  und erst sinnvoll testbar, wenn Option A oder Option B umgesetzt
  ist. Bis dahin: gpt-4o.
- **Diagnose** mit `python scripts/opencode_state_diagnostic.py`
  gehört in jeden Pre-Merge-Check eines OpenCode-relevanten PRs.

## Siehe auch

- Backlog `docs/BACKLOG/open.md` §63 (geparkt) und §65 (active).
- README "Free-Models" Abschnitt (experimental / supervised Status).
