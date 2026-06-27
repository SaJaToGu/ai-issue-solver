#!/usr/bin/env python3
"""OpenCode state diagnostic — for the §63/§65 App-State-Conflict.

Prints a clear report of:
- which `opencode` binaries are reachable on PATH / well-known paths
  (and their versions)
- the running `opencode serve` process (if any): pid, binary path,
  version
- which `.app` bundle in /Applications/ owns the launchd respawn
  (by matching the running binary path against bundle resources)
- the configured `OPENCODE_BIN` env-var (if set) and where it points

Usage:
  python scripts/opencode_state_diagnostic.py
  python scripts/opencode_state_diagnostic.py --json

Exit codes:
  0 — diagnostic ran (state may or may not be a conflict; see output)
  1 — diagnostic itself errored (e.g. `opencode` not on PATH)
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


VERSION_RE = re.compile(r"\b(\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.\-]+)*)\b")


def _run(cmd: list[str], timeout: int = 10) -> tuple[int, str, str]:
    """Run a subprocess, return (returncode, stdout, stderr)."""
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return p.returncode, p.stdout, p.stderr
    except FileNotFoundError:
        return 127, "", f"command not found: {cmd[0]}"
    except subprocess.TimeoutExpired:
        return 124, "", f"timeout after {timeout}s: {' '.join(cmd)}"


def _opencode_version(binary: Path) -> str:
    rc, out, _ = _run([str(binary), "--version"])
    if rc != 0:
        return f"<unavailable (rc={rc})>"
    m = VERSION_RE.search(out)
    return m.group(1) if m else out.strip().splitlines()[0] if out.strip() else "<no-output>"


def _find_opencode_binaries() -> list[dict[str, str]]:
    """Locate all opencode binaries reachable on PATH or in well-known dirs."""
    seen: set[str] = set()
    found: list[dict[str, str]] = []

    # PATH-relative
    path_binary = shutil.which("opencode")
    if path_binary:
        seen.add(path_binary)
        p = Path(path_binary)
        found.append(
            {
                "source": "PATH",
                "path": str(p),
                "version": _opencode_version(p),
            }
        )

    # ~/.opencode/bin/opencode (the developer's local install)
    user_bin = Path.home() / ".opencode" / "bin" / "opencode"
    if user_bin.exists() and str(user_bin) not in seen:
        seen.add(str(user_bin))
        found.append(
            {
                "source": "user-install",
                "path": str(user_bin),
                "version": _opencode_version(user_bin),
            }
        )

    # /Applications/*.app/Contents/Resources/.../opencode (app-bundled)
    apps_dir = Path("/Applications")
    if apps_dir.is_dir():
        for app in apps_dir.glob("*.app"):
            for cand in app.glob("Contents/Resources/**/opencode"):
                if cand.is_file() and str(cand) not in seen:
                    seen.add(str(cand))
                    found.append(
                        {
                            "source": f"app-bundle:{app.stem}",
                            "path": str(cand),
                            "version": _opencode_version(cand),
                        }
                    )

    return found


def _running_opencode_serve() -> dict[str, Any] | None:
    """Find the running opencode-serve process, its binary, and its version."""
    rc, out, _ = _run(["pgrep", "-af", "opencode serve"])
    if rc != 0 or not out.strip():
        return None
    # First matching line is enough — there should be exactly one serve.
    line = out.strip().splitlines()[0]
    # Format: <pid> <command...>
    parts = line.split(None, 1)
    if len(parts) < 2:
        return None
    pid = int(parts[0])
    cmd = parts[1]

    # Resolve binary from /proc/<pid>/exe (Linux) or lsof -d txt (mac)
    binary_path: str | None = None
    rc, out2, _ = _run(["lsof", "-a", "-p", str(pid), "-d", "txt"])
    if rc == 0 and out2.strip():
        for ll in out2.strip().splitlines()[1:]:
            if "opencode" in ll and "DEL" not in ll:
                # lsof output line: "command  pid user  fd type device  size/offset  node  name"
                parts = ll.split()
                if len(parts) >= 9:
                    binary_path = parts[-1]
                    break

    version = "<unknown>"
    if binary_path:
        version = _opencode_version(Path(binary_path))

    return {
        "pid": pid,
        "command": cmd,
        "binary_path": binary_path,
        "version": version,
    }


def _app_owner_for_binary(binary_path: str | None) -> str | None:
    """Find the .app bundle that contains the given binary path."""
    if not binary_path:
        return None
    # Split on '/' manually so leading '/' is preserved on join.
    parts = binary_path.split("/")
    for i, part in enumerate(parts):
        if part.endswith(".app"):
            return "/".join(parts[: i + 1])
    return None


def _opencode_bin_env() -> str | None:
    """Resolve $OPENCODE_BIN (if set) to an absolute path."""
    raw = os.environ.get("OPENCODE_BIN")
    if not raw:
        return None
    p = Path(raw).expanduser()
    if not p.is_absolute():
        p = (Path.cwd() / p).resolve()
    return str(p) if p.exists() else f"{p} (does not exist)"


def _build_report() -> dict[str, Any]:
    return {
        "binaries_found": _find_opencode_binaries(),
        "running_serve": _running_opencode_serve(),
        "opencode_bin_env": _opencode_bin_env(),
    }


def _format_text(report: dict[str, Any]) -> str:
    out: list[str] = []
    out.append("=" * 60)
    out.append("OpenCode state diagnostic (§63 / §65)")
    out.append("=" * 60)

    binaries = report["binaries_found"]
    out.append("")
    out.append(f"Binaries found: {len(binaries)}")
    for b in binaries:
        out.append(f"  [{b['source']}] {b['path']}")
        out.append(f"      version: {b['version']}")

    serve = report["running_serve"]
    out.append("")
    if serve is None:
        out.append("Running opencode-serve: <none>")
    else:
        out.append(f"Running opencode-serve:")
        out.append(f"  pid:         {serve['pid']}")
        out.append(f"  binary:      {serve['binary_path'] or '<unresolved>'}")
        out.append(f"  version:     {serve['version']}")
        app_owner = _app_owner_for_binary(serve["binary_path"])
        if app_owner:
            out.append(f"  app-owner:   {app_owner} (this app's launchd respawns the serve)")

    out.append("")
    out.append(f"$OPENCODE_BIN: {report['opencode_bin_env'] or '<unset>'}")

    # Verdict
    out.append("")
    out.append("-" * 60)
    if not binaries:
        verdict = "INCONCLUSIVE: no opencode binary found on PATH or in well-known dirs"
    elif len(binaries) == 1 and (serve is None or serve["binary_path"] in binaries[0]["path"]):
        verdict = "OK: single binary, serve matches CLI (or no serve running)"
    elif serve and any(b["path"] == serve["binary_path"] for b in binaries) is False:
        serve_version = serve["version"]
        path_versions = [b["version"] for b in binaries]
        if serve_version not in path_versions:
            app_owner = _app_owner_for_binary(serve["binary_path"]) or "<unknown>"
            verdict = (
                f"CONFLICT: serve is {serve_version} ({serve['binary_path']}), "
                f"CLI is {path_versions}. App launchd respawns the old serve "
                f"(from {app_owner}). "
                f"Workaround: --allow-opencode-state-conflict (diagnostic only). "
                f"See docs/OPENCODE_APP_STATE.md for resolution options A/B/C."
            )
        else:
            verdict = "OK: serve binary version matches a discovered CLI version"
    else:
        verdict = "OK"
    out.append(f"Verdict: {verdict}")
    out.append("-" * 60)
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Print a clear report of the local OpenCode App-State "
        "(binaries, running serve, launchd owner). See docs/OPENCODE_APP_STATE.md.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON instead of the human-readable report",
    )
    args = parser.parse_args(argv)

    try:
        report = _build_report()
    except Exception as exc:
        print(f"Diagnostic errored: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        print(_format_text(report))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
