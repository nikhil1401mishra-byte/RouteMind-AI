"""Standard-library HTTP server.

Runs with zero pip installs -- important for a demo machine with no internet.
Serves both the JSON API and the static frontend from one origin, so there are
no CORS problems and only one command to remember.
"""

from __future__ import annotations

import json
import mimetypes
import posixpath
import sys
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import api, config

mimetypes.add_type("application/javascript", ".js")
mimetypes.add_type("application/json", ".json")
mimetypes.add_type("image/svg+xml", ".svg")

SCHEME = "http" + "://"
START_LOCK = threading.Lock()


class RouteMindHandler(BaseHTTPRequestHandler):
    server_version = "RouteMind/1.0"
    protocol_version = "HTTP/1.1"

    # ------------------------------------------------------------- plumbing
    def _send_json(self, status: int, payload) -> None:
        body = json.dumps(payload, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_bytes(self, status: int, body: bytes, content_type: str,
                    cache: str = "no-cache") -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", cache)
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self) -> dict:
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        try:
            parsed = json.loads(raw.decode("utf-8"))
            return parsed if isinstance(parsed, dict) else {"value": parsed}
        except (ValueError, UnicodeDecodeError):
            return {}

    # ---------------------------------------------------------------- verbs
    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        if path.startswith("/api"):
            query = {k: v[0] for k, v in urllib.parse.parse_qs(parsed.query).items()}
            try:
                status, payload = api.handle("GET", path, query, {},
                                             dict(self.headers.items()))
            except Exception as exc:  # keep the demo alive on unexpected errors
                self.log_error("API error on %s: %s", path, exc)
                status, payload = 500, {"error": str(exc)}
            self._send_json(status, payload)
            return

        self._serve_static(path)

    def do_POST(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        if not path.startswith("/api"):
            self._send_json(404, {"error": "Not found"})
            return

        query = {k: v[0] for k, v in urllib.parse.parse_qs(parsed.query).items()}
        body = self._read_body()
        try:
            status, payload = api.handle("POST", path, query, body,
                                         dict(self.headers.items()))
        except Exception as exc:
            self.log_error("API error on %s: %s", path, exc)
            status, payload = 500, {"error": str(exc)}
        self._send_json(status, payload)

    # --------------------------------------------------------------- static
    def _serve_static(self, path: str) -> None:
        root = config.FRONTEND_DIR

        if path in ("", "/"):
            target = root / "index.html"
        else:
            clean = posixpath.normpath(urllib.parse.unquote(path)).lstrip("/")
            target = (root / clean).resolve()
            try:
                target.relative_to(root.resolve())
            except ValueError:
                self._send_json(403, {"error": "Forbidden"})
                return
            if target.is_dir():
                target = target / "index.html"

        if not target.exists() or not target.is_file():
            fallback = root / "index.html"
            if fallback.exists():
                target = fallback
            else:
                self._send_json(404, {"error": "Not found: " + path})
                return

        content_type = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        if content_type.startswith("text/") or content_type in (
                "application/javascript", "application/json", "image/svg+xml"):
            content_type += "; charset=utf-8"

        try:
            body = target.read_bytes()
        except OSError as exc:
            self._send_json(500, {"error": str(exc)})
            return

        self._send_bytes(200, body, content_type)

    # -------------------------------------------------------------- logging
    def log_message(self, fmt: str, *args) -> None:
        # Keep API calls visible but skip static-asset noise.
        if "/api" in (self.path or ""):
            sys.stderr.write("  " + (fmt % args) + "\n")


def create_server(host: str = None, port: int = None) -> ThreadingHTTPServer:
    host = host or config.HOST
    port = port if port is not None else config.PORT
    server = ThreadingHTTPServer((host, port), RouteMindHandler)
    server.daemon_threads = True
    return server


def serve(host: str = None, port: int = None) -> None:
    server = create_server(host, port)
    bound_host = str(server.server_address[0])
    bound_port = str(server.server_address[1])
    print("  Server (stdlib http.server) listening on " + SCHEME + bound_host + ":" + bound_port)
    print("  Press Ctrl+C to stop.\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  Shutting down.")
    finally:
        server.server_close()
