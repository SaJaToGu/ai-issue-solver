"""OpenCode CLI discovery, auth checks, and shared state diagnostics."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import shutil
import subprocess
import sys

from scripts.utils import print_err, print_warn


def find_opencode_executable(repo_path: str | None = None) -> str | None:
    """Find the OpenCode CLI in common local install locations or PATH."""
    candidates = []

    if sys.executable:
        candidates.append(Path(sys.executable).with_name("opencode"))

    if repo_path:
        repo_root = Path(repo_path)
        candidates.extend([
            repo_root / ".venv" / "bin" / "opencode",
            repo_root / "venv" / "bin" / "opencode",
        ])

    candidates.append(Path.home() / ".local" / "bin" / "opencode")
    candidates.append(Path.home() / ".local" / "share" / "opencode" / "opencode")
    candidates.append(Path.home() / ".opencode" / "bin" / "opencode")

    for candidate in candidates:
        if candidate.exists() and os.access(candidate, os.X_OK):
            return str(candidate)

    return shutil.which("opencode")


def check_opencode_auth(opencode_exe: str) -> bool:
    """Return True when `opencode auth list` reports at least one credential."""
    try:
        result = subprocess.run(
            [opencode_exe, "auth", "list"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        stderr_lower = result.stderr.lower() if result.stderr else ""
        stdout_lower = result.stdout.lower() if result.stdout else ""
        combined = stderr_lower + stdout_lower

        if result.returncode == 0 and "credentials" in combined and "0 credentials" not in combined:
            return True

        print_warn("OpenCode ist nicht authentifiziert!")
        print("   → Anmelden mit: opencode auth login")
        print("   → Oder Provider-Token via OPENCODE_API_KEY setzen")
        return False
    except FileNotFoundError:
        print_warn("OpenCode Auth-Check fehlgeschlagen: executable nicht gefunden")
        return False
    except subprocess.TimeoutExpired:
        print_warn("OpenCode Auth-Check hat nicht innerhalb von 15s geantwortet")
        return False
    except OSError as exc:
        print_warn(f"OpenCode Auth-Check fehlgeschlagen: {exc}")
        return False


@dataclass
class OpenCodeServeProcess:
    pid: str
    command: str
    executable: str | None = None
    version: str | None = None


@dataclass
class OpenCodeStatePreflight:
    opencode_exe: str
    cli_version: str | None
    db_path: Path | None
    wal_files: list[Path]
    serve_processes: list[OpenCodeServeProcess]

    @property
    def mismatched_serve_processes(self) -> list[OpenCodeServeProcess]:
        return [
            proc for proc in self.serve_processes
            if (proc.version and self.cli_version and proc.version != self.cli_version)
            or (proc.executable and Path(proc.executable) != Path(self.opencode_exe))
        ]

    @property
    def has_blocking_state_conflict(self) -> bool:
        return bool(self.mismatched_serve_processes)


def _format_version(value: str | None) -> str:
    return value or "unknown"


def _extract_opencode_serve_executable(command: str) -> str | None:
    """Best-effort extraction of the executable path from an `opencode serve` line."""
    marker = " serve"
    if marker not in command:
        return None
    executable = command.split(marker, 1)[0].strip()
    return executable or None


def _looks_like_opencode_executable(executable: str | None) -> bool:
    if not executable:
        return False
    return Path(executable).name in {"opencode", "opencode.exe"}


def _opencode_version_for_executable(executable: str) -> str | None:
    try:
        result = subprocess.run(
            [executable, "--version"],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return (result.stdout or result.stderr).strip() or None


def _find_opencode_serve_processes() -> list[OpenCodeServeProcess]:
    """Find running `opencode serve` processes without requiring platform-specific tools."""
    try:
        result = subprocess.run(
            ["ps", "-ef"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    if result.returncode != 0:
        return []

    processes: list[OpenCodeServeProcess] = []
    for line in result.stdout.splitlines():
        if "opencode serve" not in line:
            continue
        columns = line.split(None, 7)
        if len(columns) < 8:
            continue
        pid = columns[1]
        command = columns[7]
        executable = _extract_opencode_serve_executable(command)
        if not _looks_like_opencode_executable(executable):
            continue
        version = _opencode_version_for_executable(executable) if executable else None
        processes.append(
            OpenCodeServeProcess(
                pid=pid,
                command=command,
                executable=executable,
                version=version,
            )
        )
    return processes


def _opencode_wal_files_for_db(db_path: Path | None) -> list[Path]:
    if db_path is None:
        return []
    return [
        path for path in (Path(f"{db_path}-wal"), Path(f"{db_path}-shm"))
        if path.exists()
    ]


def _find_opencode_db_path() -> Path | None:
    try:
        from workers.opencode_session_reader import find_opencode_db_path
    except ImportError:
        return None
    return find_opencode_db_path()


def _read_opencode_cli_version(opencode_exe: str) -> str | None:
    try:
        version_result = subprocess.run(
            [opencode_exe, "--version"],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if version_result.returncode != 0:
        return None
    return (version_result.stdout or version_result.stderr).strip() or None


def _collect_opencode_state_preflight(
    opencode_exe: str,
    cli_version: str | None,
) -> OpenCodeStatePreflight:
    db_path = _find_opencode_db_path()
    return OpenCodeStatePreflight(
        opencode_exe=opencode_exe,
        cli_version=cli_version,
        db_path=db_path,
        wal_files=_opencode_wal_files_for_db(db_path),
        serve_processes=_find_opencode_serve_processes(),
    )


def _print_opencode_state_preflight_result(preflight: OpenCodeStatePreflight) -> None:
    """Print global OpenCode state hints that often explain WAL/SQLite failures."""
    print()
    print("  State/SQLite:")
    if preflight.db_path is None:
        print("    opencode.db: nicht gefunden")
    else:
        print(f"    opencode.db: {preflight.db_path}")
        if preflight.wal_files:
            print_warn("OpenCode WAL-Dateien sind vorhanden")
            for path in preflight.wal_files:
                print(f"    WAL: {path}")
            print("    Recovery-Hinweis: OpenCode-Prozesse beenden, dann nur opencode.db-wal/opencode.db-shm entfernen.")
            print("    Nicht löschen: auth.json, account.json oder opencode.db.")

    if not preflight.serve_processes:
        print("    opencode serve: kein laufender Prozess gefunden")
        return

    print_warn("Laufende opencode-serve-Prozesse gefunden")
    for proc in preflight.serve_processes:
        version_suffix = f", version={proc.version}" if proc.version else ""
        executable_suffix = f", exe={proc.executable}" if proc.executable else ""
        print(f"    pid={proc.pid}{version_suffix}{executable_suffix}")

    if preflight.mismatched_serve_processes:
        print_err("OpenCode Versions-/Executable-Konflikt erkannt.")
        print(f"    CLI:   version={_format_version(preflight.cli_version)}, exe={preflight.opencode_exe}")
        for proc in preflight.mismatched_serve_processes:
            print(
                "    Serve: "
                f"pid={proc.pid}, version={_format_version(proc.version)}, "
                f"exe={proc.executable or 'unknown'}"
            )
        print_warn(
            "Root Cause: CLI und laufender Server nutzen nicht dieselbe "
            "OpenCode-Version oder nicht dasselbe Executable. WAL/SHM-Dateien "
            "sind dabei nur ein Symptom bzw. ein nachgelagerter Recovery-Schritt."
        )


def _print_opencode_state_preflight(opencode_exe: str, cli_version: str | None) -> None:
    _print_opencode_state_preflight_result(
        _collect_opencode_state_preflight(opencode_exe, cli_version)
    )


def _print_opencode_state_conflict_recovery() -> None:
    print("   Recovery:")
    print("   1. MiniMax Code/OpenCode App schließen oder OpenCode-Versionen angleichen.")
    print("   2. Danach erneut ausführen: python scripts/solve_issues.py --model opencode --diagnostic")
    print("   3. Erst wenn kein OpenCode/MiniMax-Prozess mehr läuft: opencode.db-wal und opencode.db-shm entfernen.")
    print("   4. WAL/SHM nicht als Root Cause behandeln; sie sind nur ein SQLite-Recovery-Artefakt.")
    print("   5. Nicht löschen: auth.json, account.json oder opencode.db.")
    print("   Override nur bewusst: --allow-opencode-state-conflict")


def check_opencode_state_guard(
    opencode_exe: str,
    *,
    allow_conflict: bool = False,
    print_state: bool = True,
) -> bool:
    """Return False when OpenCode global state is unsafe for a real worker run."""
    cli_version = _read_opencode_cli_version(opencode_exe)
    preflight = _collect_opencode_state_preflight(opencode_exe, cli_version)
    if print_state:
        _print_opencode_state_preflight_result(preflight)

    if not preflight.has_blocking_state_conflict:
        return True

    if allow_conflict:
        print_warn(
            "OpenCode State-Konflikt erkannt, aber per "
            "--allow-opencode-state-conflict ueberstimmt."
        )
        return True

    print_err(
        "OpenCode Worker-Start blockiert: laufender opencode-serve-Prozess "
        "passt nicht zur aktuellen CLI-Version oder zum aktuellen Executable. "
        "Das ist ein Versions-/Executable-Konflikt, kein reines WAL-Problem."
    )
    _print_opencode_state_conflict_recovery()
    return False
