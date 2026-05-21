#!/usr/bin/env python3
"""serve_dashboard.py - Dashboard generieren und mit Shutdown-Button ausliefern."""

from __future__ import annotations

import argparse
from functools import partial
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import sys
import threading

sys.path.insert(0, str(Path(__file__).parent))
from status_dashboard import DEFAULT_OUTPUT, DEFAULT_RUNS_DIR, read_runs, write_dashboard  # noqa: E402
from utils import load_env, print_banner, print_step  # noqa: E402


class DashboardRequestHandler(SimpleHTTPRequestHandler):
    dashboard_config = None

    def refresh_dashboard(self) -> None:
        if self.dashboard_config is None:
            return
        runs = read_runs(self.dashboard_config["runs_dir"])
        write_dashboard(
            runs,
            self.dashboard_config["output_path"],
            owner=self.dashboard_config["owner"],
            allow_shutdown=True,
            refresh_seconds=self.dashboard_config["refresh_seconds"],
        )

    def do_GET(self) -> None:  # noqa: N802 - stdlib hook
        if self.dashboard_config and self.path.split("?", 1)[0] in {"/", f"/{self.dashboard_config['output_path'].name}"}:
            self.refresh_dashboard()
        super().do_GET()

    def do_POST(self) -> None:  # noqa: N802 - stdlib hook
        if self.path != "/__shutdown__":
            self.send_error(404)
            return

        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write("Dashboard server shutting down.\n".encode("utf-8"))
        threading.Thread(target=self.server.shutdown, daemon=True).start()

    def log_message(self, format: str, *args) -> None:
        print(f"   {self.address_string()} - {format % args}")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generiert und serviert das lokale Status-Dashboard mit Beenden-Knopf"
    )
    parser.add_argument("--runs-dir", default=str(DEFAULT_RUNS_DIR), help="Run-Report-Verzeichnis")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="Zielpfad fuer die HTML-Datei")
    parser.add_argument("--owner", help="GitHub Owner fuer Issue- und Branch-Links")
    parser.add_argument("--host", default="0.0.0.0", help="Host/IP fuer den Server")
    parser.add_argument("--port", type=int, default=8765, help="Port fuer den Server")
    parser.add_argument(
        "--refresh-seconds",
        type=int,
        default=10,
        help="Browser-Auto-Refresh in Sekunden; 0 deaktiviert ihn",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    config = load_env()
    owner = args.owner or config.get("GITHUB_USER")
    runs_dir = Path(args.runs_dir)
    output_path = Path(args.output)

    print_banner("STATUS-DASHBOARD SERVIEREN")
    print_step(1, f"Generiere Dashboard aus {runs_dir}")
    refresh_seconds = args.refresh_seconds if args.refresh_seconds > 0 else None
    runs = read_runs(runs_dir)
    write_dashboard(
        runs,
        output_path,
        owner=owner,
        allow_shutdown=True,
        refresh_seconds=refresh_seconds,
    )
    print(f"   Dashboard: {output_path}")

    serve_dir = output_path.parent.resolve()
    DashboardRequestHandler.dashboard_config = {
        "runs_dir": runs_dir,
        "output_path": output_path,
        "owner": owner,
        "refresh_seconds": refresh_seconds,
    }
    handler = partial(DashboardRequestHandler, directory=str(serve_dir))
    server = ThreadingHTTPServer((args.host, args.port), handler)
    url_host = "localhost" if args.host in {"0.0.0.0", "::"} else args.host
    print_step(2, "Server gestartet")
    print(f"   URL lokal: http://{url_host}:{args.port}/{output_path.name}")
    if refresh_seconds:
        print(f"   Auto-refresh: {refresh_seconds}s")
    else:
        print("   Auto-refresh: aus")
    print("   Beenden: Button im Dashboard oder Ctrl+C im Terminal")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n   Server per Ctrl+C beendet")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
