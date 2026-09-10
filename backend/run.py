#!/usr/bin/env python3
"""RouteMind AI launcher.

    python run.py                 # start the control room (auto-detects stack)
    python run.py --port 9000     # different port
    python run.py --offline       # skip live feeds, use bundled snapshot
    python run.py --stdlib        # force the zero-dependency server
    python run.py --selftest      # verify every endpoint, then exit

Works on a clean Python 3.9+ install with no pip packages at all. If FastAPI
and uvicorn happen to be installed, it uses them instead and exposes /docs.
"""

from __future__ import annotations

import argparse
import os
import sys
import webbrowser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from app import config  # noqa: E402

SCHEME = "http" + "://"

BANNER = r"""
  ____             _       __  __ _           _
 |  _ \ ___  _   _| |_ ___|  \/  (_)_ __   __| |
 | |_) / _ \| | | | __/ _ \ |\/| | | '_ \ / _` |
 |  _ < (_) | |_| | ||  __/ |  | | | | | | (_| |
 |_| \_\___/ \__,_|\__\___|_|  |_|_|_| |_|\__,_|  AI

  Risk-aware logistics control room - North East India
"""


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Run the RouteMind AI control room.")
    p.add_argument("--host", default=config.HOST, help="bind address (default 127.0.0.1)")
    p.add_argument("--port", type=int, default=config.PORT, help="port (default 8000)")
    p.add_argument("--offline", action="store_true",
                   help="do not call live APIs; use the bundled snapshot")
    p.add_argument("--stdlib", action="store_true",
                   help="force the standard-library server even if FastAPI is installed")
    p.add_argument("--no-browser", action="store_true", help="do not open a browser")
    p.add_argument("--selftest", action="store_true",
                   help="exercise every endpoint and exit with a report")
    return p.parse_args()


def check_python() -> None:
    if sys.version_info < (3, 9):
        sys.exit("Python 3.9+ required, found " + sys.version.split()[0])


def warm_up() -> None:
    """Load road geometry and run the first live assessment before serving."""
    from app.store import STORE

    print("  Loading road network and live conditions...")
    STORE.bootstrap()

    provenance = STORE.provenance.get("overall", "unknown")
    corridors = len(STORE.corridor_state)
    incidents = len(STORE.all_incidents(include_resolved=False))
    geometry = STORE.geometry_provenance

    print("  Corridors assessed : " + str(corridors))
    print("  Active incidents   : " + str(incidents))
    print("  Road geometry      : " + str(geometry))
    print("  Live data          : " + str(provenance))

    if provenance in ("offline-snapshot", "unavailable") or geometry == "fallback-geometry":
        print("\n  NOTE: live feeds unreachable, running on cached/bundled data.")
        print("        The UI labels every value with its data source.")
    print()


def run_selftest(host: str, port: int) -> int:
    """Start the server, hit every endpoint, report results."""
    import json
    import threading
    import urllib.error
    import urllib.request

    from app import api
    from app.server import create_server

    server = create_server(host, 0)
    actual_port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    base = SCHEME + host + ":" + str(actual_port)

    checks = [("GET", ep.split()[1]) for ep in api.ENDPOINTS if ep.startswith("GET")]
    checks += [
        ("POST", "/api/simulation/start"),
        ("GET", "/api/simulation"),
        ("POST", "/api/simulation/accept"),
        ("POST", "/api/simulation/reset"),
        ("POST", "/api/alerts/acknowledge-all"),
        ("POST", "/api/routes/plan"),
    ]

    passed, failed = 0, []
    for method, path in checks:
        if "{" in path:
            if "/corridors/" in path or "/risk/" in path:
                path = path.replace("{id}", "NH306-SCL-AJL").replace(
                    "{corridor_id}", "NH306-SCL-AJL")
            else:
                path = path.replace("{id}", "TR-104")

        req = urllib.request.Request(base + path, method=method)
        # /api/audit is admin-only by design, so ask for it as an admin.
        if path.startswith("/api/audit"):
            req.add_header("X-RouteMind-Role", "admin")
        if method == "POST":
            payload = b"{}"
            if path == "/api/routes/plan":
                payload = b'{"vehicle_id": "TR-104"}'
            req.data = payload
            req.add_header("Content-Type", "application/json")

        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                passed += 1
                print("  ok   {:4} {:38} {} bytes".format(
                    method, path, len(json.dumps(data))))
        except urllib.error.HTTPError as exc:
            failed.append((method, path, "HTTP " + str(exc.code)))
        except Exception as exc:
            failed.append((method, path, str(exc)))

    # The static frontend must be reachable from the same origin.
    try:
        with urllib.request.urlopen(base + "/", timeout=30) as resp:
            html = resp.read().decode("utf-8", "ignore")
            if "RouteMind" in html:
                passed += 1
                print("  ok   GET  /                                      "
                      + str(len(html)) + " bytes (index.html)")
            else:
                failed.append(("GET", "/", "index.html did not render"))
    except Exception as exc:
        failed.append(("GET", "/", str(exc)))

    server.shutdown()
    server.server_close()

    print("\n  " + str(passed) + " passed, " + str(len(failed)) + " failed")
    for method, path, reason in failed:
        print("  FAIL " + method + " " + path + ": " + reason)
    return 0 if not failed else 1


def main() -> int:
    check_python()
    args = parse_args()

    if args.offline:
        config.OFFLINE = True
        os.environ["ROUTEMIND_OFFLINE"] = "1"

    print(BANNER)
    if config.OFFLINE:
        print("  Mode: OFFLINE (live feeds disabled)\n")

    warm_up()

    if args.selftest:
        return run_selftest(args.host, args.port)

    url = SCHEME + args.host + ":" + str(args.port)

    if not args.stdlib:
        try:
            import uvicorn  # noqa: F401
            from app.fastapi_app import create_app

            print("  Server (FastAPI + uvicorn) on " + url)
            print("  API docs: " + url + "/docs")
            print("  Press Ctrl+C to stop.\n")
            if not args.no_browser:
                _open_later(url)
            uvicorn.run(create_app(), host=args.host, port=args.port, log_level="warning")
            return 0
        except ImportError:
            print("  FastAPI/uvicorn not installed - using the built-in server instead.")
            print("  (Optional: pip install -r requirements.txt)\n")

    from app.server import serve

    if not args.no_browser:
        _open_later(url)
    serve(args.host, args.port)
    return 0


def _open_later(url: str) -> None:
    import threading

    def go() -> None:
        try:
            webbrowser.open(url)
        except Exception:
            pass

    threading.Timer(1.2, go).start()


if __name__ == "__main__":
    sys.exit(main())
