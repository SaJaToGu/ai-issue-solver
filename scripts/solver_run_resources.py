#!/usr/bin/env python3
"""solver_run_resources.py — Per-Run-Ressourcenmodell und Locking für parallele Solver-Jobs.

Dieses Modul definiert ein explizites Ressourcenmodell für jeden Solver-Run
und stellt Locking-Mechanismen bereit, um Kollisionen bei parallelen Jobs
(z. B. im Benchmark-Betrieb) zu verhindern.

Ressourcen-Eigentumsregeln:
- Jeder Run besitzt exklusiv: checkout_path, temp_path, report_path
- Branch-Namen und PR-Erstellung sind für dasselbe Issue konfliktbehaftet
  und werden durch explizites Locking abgesichert
- Provider-Auth- und Cache-Verzeichnisse dürfen geteilt werden (read-only
  bzw. append-only), aber nicht überschrieben

Locking-Modell:
- Lock-Dateien liegen unter reports/locks/<issue-key>.lock
- Stale Locks (älter als LOCK_STALE_SECONDS) werden automatisch übernommen
- Lock-Metadaten enthalten run_id, pid, branch_name, started_at — keine Secrets
- Fehlgeschlagene Lock-Akquisitionen und Stale-Lock-Cleanup werden in
  RunResourceDiagnostics festgehalten und erscheinen im Run-Report
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Iterator
import contextlib

from utils import print_warn


# ─────────────────────────────────────────────────────────────
# Konstanten
# ─────────────────────────────────────────────────────────────

LOCKS_ROOT = Path("reports") / "locks"

# Lock gilt als veraltet nach dieser Zeit (in Sekunden)
LOCK_STALE_SECONDS = 60 * 60 * 2  # 2 Stunden

# Maximale Wartezeit beim Versuch, einen Lock zu erwerben (in Sekunden)
LOCK_ACQUIRE_TIMEOUT_SECONDS = 30

# Warteintervall zwischen Lock-Akquisitionsversuchen (in Sekunden)
LOCK_POLL_INTERVAL_SECONDS = 0.5


# ─────────────────────────────────────────────────────────────
# Datenmodelle
# ─────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class RunResources:
    """Beschreibt alle exklusiven und geteilten Ressourcen eines Solver-Runs.

    Attribute:
        run_id:        Eindeutige Kennung für diesen Run (z. B. Zeitstempel + Repo + Issue).
        repo:          Repository-Name (ohne Owner-Prefix).
        issue_number:  Nummer des zu lösenden Issues.
        branch_name:   Geplanter Branch-Name für diesen Run.
        provider:      Provider/Modell-Kennung (z. B. "opencode/mistral-large").
        checkout_path: Exklusiver Checkout-Pfad (temporäres Verzeichnis).
        temp_path:     Exklusives temporäres Verzeichnis.
        report_path:   Exklusiver Bericht-Pfad.
        base_branch:   Basis-Branch (nur lesend genutzt, daher geteilt).
        cleanup_on_exit: Ob das checkout-/temp-Verzeichnis bei Abschluss gelöscht wird.
        comparison_id: Optionale Benchmark-Gruppen-ID für same-issue-Vergleiche.
    """
    run_id: str
    repo: str
    issue_number: int
    branch_name: str
    provider: str
    checkout_path: Path
    temp_path: Path
    report_path: Path
    base_branch: str
    cleanup_on_exit: bool = True
    comparison_id: str | None = None

    @property
    def issue_key(self) -> str:
        """Stabiler Schlüssel für Issue-Locking: repo + issue_number."""
        return f"{self.repo}-issue-{self.issue_number}"

    @property
    def branch_lock_key(self) -> str:
        """Schlüssel für Branch-Level-Locking: verhindert doppelte Branch-Erstellung."""
        return f"{self.repo}-branch-{self.branch_name}"

    def to_report_dict(self) -> dict:
        """Gibt ein Berichts-kompatibles Dict zurück — ohne Secrets."""
        return {
            "run_id": self.run_id,
            "repo": self.repo,
            "issue_number": self.issue_number,
            "branch_name": self.branch_name,
            "provider": self.provider,
            "checkout_path": str(self.checkout_path),
            "report_path": str(self.report_path),
            "base_branch": self.base_branch,
            "cleanup_on_exit": self.cleanup_on_exit,
            "comparison_id": self.comparison_id or "",
        }


@dataclass
class RunResourceDiagnostics:
    """Protokolliert Lock-Ereignisse und Ressourcen-Konflikte für Run-Reports."""
    acquired_locks: list[str] = field(default_factory=list)
    stale_locks_cleaned: list[str] = field(default_factory=list)
    lock_conflicts: list[str] = field(default_factory=list)
    lock_acquire_failures: list[str] = field(default_factory=list)
    branch_conflict_detected: bool = False
    branch_conflict_message: str = ""

    @property
    def has_findings(self) -> bool:
        return bool(
            self.stale_locks_cleaned
            or self.lock_conflicts
            or self.lock_acquire_failures
            or self.branch_conflict_detected
        )

    def to_report_dict(self) -> dict:
        return {
            "acquired_locks": self.acquired_locks,
            "stale_locks_cleaned": self.stale_locks_cleaned,
            "lock_conflicts": self.lock_conflicts,
            "lock_acquire_failures": self.lock_acquire_failures,
            "branch_conflict_detected": self.branch_conflict_detected,
            "branch_conflict_message": self.branch_conflict_message,
        }

    def to_summary_lines(self) -> list[str]:
        lines = []
        if self.stale_locks_cleaned:
            lines.append(
                f"Stale Locks bereinigt: {', '.join(self.stale_locks_cleaned)}"
            )
        if self.lock_conflicts:
            for msg in self.lock_conflicts:
                lines.append(f"Lock-Konflikt: {msg}")
        if self.lock_acquire_failures:
            for msg in self.lock_acquire_failures:
                lines.append(f"Lock-Fehler: {msg}")
        if self.branch_conflict_detected:
            lines.append(f"Branch-Konflikt: {self.branch_conflict_message}")
        return lines


# ─────────────────────────────────────────────────────────────
# Lock-Datei-Verwaltung
# ─────────────────────────────────────────────────────────────

@dataclass
class LockMetadata:
    """Metadaten einer Lock-Datei — enthält keine Secrets."""
    run_id: str
    pid: int
    branch_name: str
    repo: str
    issue_number: int
    started_at: str  # ISO-Format
    provider: str


def _lock_path(key: str, locks_root: Path = LOCKS_ROOT) -> Path:
    """Gibt den Pfad einer Lock-Datei für den gegebenen Schlüssel zurück."""
    # Ungültige Zeichen in Dateinamen ersetzen
    safe_key = key.replace("/", "-").replace("\\", "-").replace(":", "-")
    return locks_root / f"{safe_key}.lock"


def _read_lock(lock_file: Path) -> LockMetadata | None:
    """Liest eine Lock-Datei und gibt die Metadaten zurück oder None."""
    try:
        data = json.loads(lock_file.read_text(encoding="utf-8"))
        return LockMetadata(
            run_id=data.get("run_id", ""),
            pid=int(data.get("pid", 0)),
            branch_name=data.get("branch_name", ""),
            repo=data.get("repo", ""),
            issue_number=int(data.get("issue_number", 0)),
            started_at=data.get("started_at", ""),
            provider=data.get("provider", ""),
        )
    except (OSError, json.JSONDecodeError, ValueError, TypeError):
        return None


def _write_lock(lock_file: Path, resources: RunResources) -> bool:
    """Schreibt eine Lock-Datei atomar mit exklusivem Erstellen (O_CREAT|O_EXCL).

    Gibt True zurück, wenn wir exklusiv die Datei erstellt haben. Gibt False zurück,
    wenn die Datei bereits existiert (ein anderer Prozess/Thread war schneller).
    """
    lock_file.parent.mkdir(parents=True, exist_ok=True)
    metadata = {
        "run_id": resources.run_id,
        "pid": os.getpid(),
        "branch_name": resources.branch_name,
        "repo": resources.repo,
        "issue_number": resources.issue_number,
        "started_at": datetime.now().isoformat(timespec="seconds"),
        "provider": resources.provider,
    }
    content = json.dumps(metadata, indent=2, ensure_ascii=False) + "\n"
    try:
        # O_CREAT | O_EXCL: schlägt fehl, wenn die Datei bereits existiert
        fd = os.open(str(lock_file), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
        try:
            os.write(fd, content.encode("utf-8"))
        finally:
            os.close(fd)
        return True
    except FileExistsError:
        # Datei existiert bereits — ein anderer Prozess/Thread war schneller
        return False
    except OSError as exc:
        print_warn(f"Lock-Datei konnte nicht geschrieben werden: {lock_file.name}: {exc}")
        return False


def _remove_lock(lock_file: Path) -> bool:
    """Entfernt eine Lock-Datei. Gibt True zurück, wenn erfolgreich."""
    try:
        lock_file.unlink()
        return True
    except FileNotFoundError:
        return True  # Bereits gelöscht — kein Problem
    except OSError as exc:
        print_warn(f"Lock-Datei konnte nicht entfernt werden: {lock_file.name}: {exc}")
        return False


def _is_stale_lock(lock_file: Path, stale_seconds: float = LOCK_STALE_SECONDS,
                   now_fn=time.time) -> bool:
    """Prüft ob eine Lock-Datei älter als stale_seconds ist."""
    try:
        mtime = lock_file.stat().st_mtime
        return (now_fn() - mtime) > stale_seconds
    except OSError:
        return False


def _is_owning_process_alive(pid: int) -> bool:
    """Prüft ob der Prozess mit der gegebenen PID noch läuft."""
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        # Prozess existiert, aber gehört einem anderen Benutzer
        return True
    except OSError:
        return False


# ─────────────────────────────────────────────────────────────
# Lock-Akquisition und -Freigabe
# ─────────────────────────────────────────────────────────────

class ResourceLock:
    """Kontext-Manager für einen exklusiven Ressourcen-Lock.

    Erwirbt beim Eintritt eine Lock-Datei und gibt sie beim Austritt frei.
    Stale Locks werden automatisch übernommen, wenn der haltende Prozess
    nicht mehr lebt oder die Lock-Datei zu alt ist.

    Beispiel::

        lock = ResourceLock(key="my-repo-issue-42", resources=run_resources)
        with lock.acquire(diagnostics):
            # kritischer Abschnitt
    """

    def __init__(
        self,
        key: str,
        resources: RunResources,
        locks_root: Path = LOCKS_ROOT,
        stale_seconds: float = LOCK_STALE_SECONDS,
        timeout_seconds: float = LOCK_ACQUIRE_TIMEOUT_SECONDS,
        poll_interval: float = LOCK_POLL_INTERVAL_SECONDS,
        now_fn=time.time,
        sleep_fn=time.sleep,
    ) -> None:
        self.key = key
        self.resources = resources
        self.lock_file = _lock_path(key, locks_root)
        self.stale_seconds = stale_seconds
        self.timeout_seconds = timeout_seconds
        self.poll_interval = poll_interval
        self.now_fn = now_fn
        self.sleep_fn = sleep_fn
        self._held = False

    def _try_acquire(self, diagnostics: RunResourceDiagnostics) -> bool:
        """Einzelner Akquisitionsversuch. Gibt True zurück, wenn der Lock erworben wurde."""
        if not self.lock_file.exists():
            # Lock-Datei existiert nicht: versuche zu schreiben
            if _write_lock(self.lock_file, self.resources):
                # Doppelcheck: Stellt sicher, dass wir wirklich den Lock haben
                meta = _read_lock(self.lock_file)
                if meta and meta.run_id == self.resources.run_id:
                    return True
            return False

        # Lock-Datei existiert: prüfen ob veraltet oder Prozess beendet
        meta = _read_lock(self.lock_file)
        if meta is None:
            # Korrumpierte Lock-Datei: übernehmen
            diagnostics.stale_locks_cleaned.append(
                f"{self.key} (korrumpiert)"
            )
            _remove_lock(self.lock_file)
            return _write_lock(self.lock_file, self.resources)

        # Eigener Run: Lock gehört uns bereits
        if meta.run_id == self.resources.run_id:
            return True

        # Prüfe ob der haltende Prozess noch läuft
        if not _is_owning_process_alive(meta.pid):
            diagnostics.stale_locks_cleaned.append(
                f"{self.key} (Prozess {meta.pid} nicht mehr aktiv, run_id={meta.run_id})"
            )
            _remove_lock(self.lock_file)
            return _write_lock(self.lock_file, self.resources)

        # Prüfe ob der Lock zu alt ist
        if _is_stale_lock(self.lock_file, self.stale_seconds, self.now_fn):
            diagnostics.stale_locks_cleaned.append(
                f"{self.key} (veraltet, run_id={meta.run_id}, pid={meta.pid})"
            )
            _remove_lock(self.lock_file)
            return _write_lock(self.lock_file, self.resources)

        # Lock wird aktiv von einem anderen Run gehalten
        conflict_msg = (
            f"{self.key}: gehalten von run_id={meta.run_id}, "
            f"pid={meta.pid}, branch={meta.branch_name}"
        )
        diagnostics.lock_conflicts.append(conflict_msg)
        return False

    @contextlib.contextmanager
    def acquire(self, diagnostics: RunResourceDiagnostics) -> Iterator[bool]:
        """Kontext-Manager: erwirbt den Lock und gibt ihn beim Verlassen frei.

        Yields:
            True wenn der Lock erworben wurde, False wenn Timeout.
        """
        deadline = self.now_fn() + self.timeout_seconds
        acquired = False

        while self.now_fn() <= deadline:
            if self._try_acquire(diagnostics):
                acquired = True
                self._held = True
                diagnostics.acquired_locks.append(self.key)
                break
            self.sleep_fn(self.poll_interval)

        if not acquired:
            diagnostics.lock_acquire_failures.append(
                f"Timeout nach {self.timeout_seconds:.0f}s: {self.key}"
            )

        try:
            yield acquired
        finally:
            if acquired and self._held:
                # Nur freigeben, wenn wir den Lock noch besitzen
                meta = _read_lock(self.lock_file)
                if meta and meta.run_id == self.resources.run_id:
                    _remove_lock(self.lock_file)
                self._held = False


# ─────────────────────────────────────────────────────────────
# Branch-Konflikt-Erkennung
# ─────────────────────────────────────────────────────────────

def detect_branch_name_conflict(
    branch_name: str,
    repo: str,
    issue_number: int,
    locks_root: Path = LOCKS_ROOT,
    own_run_id: str = "",
) -> str | None:
    """Erkennt ob ein Branch-Name bereits von einem anderen laufenden Run beansprucht wird.

    Durchsucht alle aktiven Lock-Dateien nach dem gleichen Branch-Namen.

    Returns:
        Fehlermeldung wenn Konflikt gefunden, sonst None.
    """
    if not locks_root.exists():
        return None
    for lock_file in locks_root.glob("*.lock"):
        meta = _read_lock(lock_file)
        if not meta:
            continue
        if meta.run_id == own_run_id:
            continue
        if meta.branch_name != branch_name:
            continue
        if not _is_owning_process_alive(meta.pid):
            continue
        return (
            f"Branch '{branch_name}' wird bereits von run_id={meta.run_id}, "
            f"pid={meta.pid} verwendet"
        )
    return None


# ─────────────────────────────────────────────────────────────
# Ressourcen-Erstellung
# ─────────────────────────────────────────────────────────────

def make_run_id(
    repo: str,
    issue_number: int,
    provider: str = "",
    comparison_id: str = "",
    now_fn=datetime.now,
) -> str:
    """Erzeugt eine eindeutige Run-ID aus Zeitstempel, Repo, Issue und Provider.

    Die Run-ID enthält keine Secrets und ist sicher für Logs und Lock-Dateien.
    """
    from solver_reporting import safe_run_repo_name
    timestamp = now_fn().strftime("%Y%m%d-%H%M%S-%f")
    safe_repo = safe_run_repo_name(repo)
    parts = [timestamp, safe_repo, f"issue-{issue_number}"]
    if provider:
        # Provider-String normalisieren (z. B. "opencode/mistral-large" -> "opencode-mistral-large")
        safe_provider = provider.replace("/", "-").replace(":", "-")[:32]
        parts.append(safe_provider)
    if comparison_id:
        safe_cmp = comparison_id.replace("/", "-").replace(":", "-")[:16]
        parts.append(f"cmp-{safe_cmp}")
    return "-".join(parts)


def create_run_resources(
    repo: str,
    issue_number: int,
    branch_name: str,
    provider: str,
    base_branch: str,
    temp_base: Path,
    report_path: Path,
    cleanup_on_exit: bool = True,
    comparison_id: str | None = None,
    run_id: str | None = None,
    now_fn=datetime.now,
) -> RunResources:
    """Erzeugt ein RunResources-Objekt mit vollständigem Ressourcenpfad.

    Args:
        repo:           Repository-Name.
        issue_number:   Issue-Nummer.
        branch_name:    Geplanter Branch-Name.
        provider:       Provider/Modell-Kennung (keine Secrets).
        base_branch:    Basis-Branch.
        temp_base:      Basis-Verzeichnis für temporäre Checkouts.
        report_path:    Exklusiver Report-Pfad (bereits erstellt vom Caller).
        cleanup_on_exit: Ob das temporäre Verzeichnis am Ende gelöscht wird.
        comparison_id:  Optionale Benchmark-Gruppen-ID.
        run_id:         Optionale Run-ID; wird automatisch generiert wenn None.
        now_fn:         Zeitfunktion (für Tests überschreibbar).

    Returns:
        RunResources mit exklusiven Pfaden für diesen Run.
    """
    effective_run_id = run_id or make_run_id(
        repo, issue_number, provider, comparison_id or "", now_fn
    )
    # Exklusives Temp-Verzeichnis mit Run-ID-Prefix
    temp_path = temp_base / effective_run_id
    checkout_path = temp_path / repo

    return RunResources(
        run_id=effective_run_id,
        repo=repo,
        issue_number=issue_number,
        branch_name=branch_name,
        provider=provider,
        checkout_path=checkout_path,
        temp_path=temp_path,
        report_path=report_path,
        base_branch=base_branch,
        cleanup_on_exit=cleanup_on_exit,
        comparison_id=comparison_id,
    )


# ─────────────────────────────────────────────────────────────
# Stale-Lock-Cleanup
# ─────────────────────────────────────────────────────────────

def cleanup_stale_locks(
    locks_root: Path = LOCKS_ROOT,
    stale_seconds: float = LOCK_STALE_SECONDS,
    dry_run: bool = True,
    now_fn=time.time,
) -> list[Path]:
    """Bereinigt veraltete Lock-Dateien.

    Args:
        locks_root:     Verzeichnis mit Lock-Dateien.
        stale_seconds:  Locks älter als diese Sekunden gelten als veraltet.
        dry_run:        Wenn True, wird nur gelistet, nicht gelöscht.
        now_fn:         Zeitfunktion für Tests.

    Returns:
        Liste der veralteten (gelöschten oder zu löschenden) Lock-Pfade.
    """
    if not locks_root.exists():
        return []

    stale_locks: list[Path] = []
    for lock_file in sorted(locks_root.glob("*.lock")):
        # Prüfe ob Prozess noch läuft
        meta = _read_lock(lock_file)
        if meta and _is_owning_process_alive(meta.pid):
            # Prozess ist noch aktiv: nicht als stale behandeln
            continue
        if _is_stale_lock(lock_file, stale_seconds, now_fn):
            stale_locks.append(lock_file)
            if not dry_run:
                _remove_lock(lock_file)

    return stale_locks


# ─────────────────────────────────────────────────────────────
# Report-Integration
# ─────────────────────────────────────────────────────────────

def write_resource_diagnostics_to_report(
    report_path: Path,
    resources: RunResources,
    diagnostics: RunResourceDiagnostics,
) -> None:
    """Schreibt Ressourcen-Diagnosen als resource-diagnostics.json in den Run-Report.

    Die Datei enthält keine Secrets — nur Lock-Schlüssel, PIDs und Branch-Namen.
    """
    payload = {
        "run_id": resources.run_id,
        "resources": resources.to_report_dict(),
        "diagnostics": diagnostics.to_report_dict(),
    }
    try:
        (report_path / "resource-diagnostics.json").write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    except OSError as exc:
        print_warn(f"Ressourcen-Diagnosen konnten nicht geschrieben werden: {exc}")


def format_resource_diagnostics_summary_lines(
    diagnostics: RunResourceDiagnostics,
) -> list[str]:
    """Formatiert Ressourcen-Diagnosen als lesbare Zusammenfassungszeilen."""
    lines = diagnostics.to_summary_lines()
    if not lines:
        return []
    return ["resource_diagnostics:"] + [f"  {line}" for line in lines]
