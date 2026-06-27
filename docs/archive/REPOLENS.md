# RepoLens: Sicherheits- und Qualitätsanalyse in isolierter Umgebung

## Was ist RepoLens?

RepoLens ist ein **statisches Analysewerkzeug**, das Repository-Strukturen, Konfigurationen und Code auf:
- **Sicherheitslücken** (z. B. veraltete Abhängigkeiten, unsichere Konfigurationen)
- **Performance-Probleme** (z. B. ineffiziente Skripte, große Binärdateien im Repo)
- **Code-Qualität** (z. B. fehlende Tests, veraltete Patterns)
- **Typen und Schweregrade** (klassifiziert Befunde nach `critical`, `high`, `medium`, `low`)

analysiert. Es handelt sich um ein **internes Skript** dieses Projekts, das als Docker-Container ausgeführt wird, um eine sichere Sandbox-Umgebung zu gewährleisten.

---

## Warum Docker-Isolation?

### 1. Netzwerk-Trennung (`--network none`)
- **Kein Internetzugang**: Verhindert, dass RepoLens versehentlich Daten an externe Server sendet oder Abhängigkeiten nachlädt.
- **Lokale Analyse**: Alle Prüfungen erfolgen ausschließlich mit den im Container verfügbaren Tools.

### 2. Berechtigungsmodell
- **Read-Only-Projektmount**: Das zu analysierende Repository wird als `/project` **schreibgeschützt** eingebunden (`:ro`).
- **Separater Report-Ordner**: Ergebnisse werden in einen **dedizierten Ordner** (`/reports`) geschrieben, der explizit als schreibbar gemountet ist.
- **Keine GitHub-Tokens**: `.env`-Dateien oder Schreibberechtigungen werden **nicht** in den Container durchgereicht.

### 3. Prinzip der minimalen Rechte
- **Kein Zugriff auf Host-System**: Der Container sieht nur das gemountete Projekt und den Report-Ordner.
- **Keine persistente Speicherung**: Der Container wird nach dem Lauf entfernt (`--rm`).
- **Ressourcenbegrenzung**: Optional können CPU (`--cpus`) und Speicher (`--memory`) limitiert werden.

---

## Sicherheitsmodell

### Was RepoLens **darf**:
- Dateien im gemounteten Projekt **lesen** (z. B. `src/`, `package.json`, `Dockerfile`).
- Analyseergebnisse in `/reports` **schreiben** (JSON/Markdown-Dateien).
- Lokale Tools wie `grep`, `shellcheck` oder `bandit` ausführen.

### Was RepoLens **nicht darf**:
- **Netzwerkzugriff**: Keine HTTP-Anfragen, API-Calls oder Updates.
- **Schreibzugriff auf das Projekt**: Keine Änderungen an Quellcode oder Konfigurationen.
- **Zugriff auf Secrets**: Keine `.env`-Dateien, SSH-Keys oder GitHub-Tokens.
- **Persistente Änderungen**: Der Container und alle temporären Daten werden nach dem Lauf gelöscht.

---

## Quickstart: Repo analysieren

### 1. Analyse starten
```bash
scripts/run_repolens_docker.sh --project-dir /pfad/zum/repo --domain security
```

- `--project-dir`: Pfad zum zu analysierenden Repository (Standard: aktuelles Verzeichnis).
- `--domain`: Analyse-Fokus (`security`, `performance`, `quality`).
- `--report-dir`: Zielordner für Berichte (Standard: `PROJECT/reports/repolens`).

### 2. Report lesen
Die Ergebnisse liegen als strukturierte Dateien im Report-Ordner:
```
reports/repolens/
├── findings.json      # Maschinenlesbare Befunde
├── summary.md         # Zusammenfassung für Menschen
└── details/           # Detaillierte Analysen pro Kategorie
```

### 3. Befunde als Issues importieren
```bash
scripts/import_repolens_results.py --report-dir reports/repolens
```

---

## Typische Befunde und Schweregrade

| Typ               | Beispiel                                  | Schweregrad  | Empfehlung                          |
|-------------------|------------------------------------------|--------------|--------------------------------------|
| **Sicherheit**    | Hardcodierte API-Keys in `config.js`     | critical     | Keys in `.env` auslagern             |
| **Performance**   | 500 MB `node_modules` im Repo            | high         | `.gitignore` anpassen                |
| **Qualität**      | Fehlende Type-Hints in Python            | medium       | `mypy` integrieren                  |
| **Wartung**      | Veraltete `requirements.txt` (CVE-2021-) | low          | `pip list --outdated` prüfen        |

---

## Warum diese Architektur?

1. **Trennung der Verantwortlichkeiten**:
   - Der **Analyse-Agent** (RepoLens im Container) hat **keine Schreibrechte**.
   - Der **Deployment-Agent** (Host-Skripte wie `import_repolens_results.py`) entscheidet, welche Befunde als Issues importiert werden.

2. **Wiederholbare Umgebung**:
   - Gleiche Container-Version → gleiche Analyseergebnisse.
   - Keine Abhängigkeit von Host-Tools oder -Versionen.

3. **Sicherheit durch Design**:
   - Selbst bei einem Kompromittieren des Containers: **kein Netzwerk + keine Secrets = keine Angriffsfläche**.

---

## Häufige Fragen

### Ist RepoLens ein externes Tool?
Nein. Es handelt sich um ein **internes Skript** (`repolens.sh` im Docker-Image), das speziell für dieses Projekt entwickelt wurde. Der Quellcode liegt im [Docker-Image](https://github.com/SaJaToGu/repolens-docker) (privates Repo).

### Warum nicht direkt auf dem Host ausführen?
- **Sicherheit**: Docker garantiert, dass RepoLens **keine unbeabsichtigten Änderungen** am System oder Netzwerkverbindungen durchführt.
- **Saubere Umgebung**: Keine Konflikte mit Host-Tools oder -Versionen.
- **Wartbarkeit**: Die Container-Version kann unabhängig vom Host aktualisiert werden.

### Wie werden False Positives vermieden?
- **Manueller Import**: Befunde werden erst nach Prüfung durch `import_repolens_results.py` zu Issues.
- **Schweregrad-Filter**: Standardmäßig werden nur `critical`/`high` importiert (konfigurierbar).

---

## Beispiel: Sicherheitsanalyse

```bash
# 1. Analyse mit Fokus auf Sicherheit (kein Netzwerk, 2 CPUs)
scripts/run_repolens_docker.sh \
  --project-dir ~/projects/mein-repo \
  --domain security \
  --network none \
  --cpus 2

# 2. Ergebnisse prüfen
cat reports/repolens/summary.md

# 3. Nur kritische Befunde importieren
scripts/import_repolens_results.py \
  --report-dir reports/repolens \
  --min-severity critical
```

---

## Weiterführende Links
- [Workflow-Dokumentation](WORKFLOW.md) (Integration in den Morpheus-Workflow)
- [Test-Suite](tests/test_run_repolens_docker.py) (Sicherheitschecks des Docker-Wrappers)