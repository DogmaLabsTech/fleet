"""HTTP layer. Binds 127.0.0.1 only. One server behind fleet dash / fleet app."""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import actions, collector, deep, roster, vault

UI_DIR = Path(__file__).resolve().parent / "ui"
CONTENT_TYPES = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
                 ".css": "text/css; charset=utf-8", ".ico": "image/x-icon",
                 ".png": "image/png", ".svg": "image/svg+xml", ".woff2": "font/woff2"}
MAX_BODY = 1_048_576
_deep_cache = {}

_EMPTY_DETAIL = {"head": {"warnings": ["transcript not found"], "files": {"read": [], "edited": [], "written": [], "searched": []},
                          "rules": [], "skills": [], "agents": [], "mcp": [],
                          "ctx_tokens": None, "model": None, "branch": None},
                 "timeline": [], "timeline_total": 0,
                 "files": {"read": [], "edited": [], "written": [], "searched": []}}

PROJECTS_TTL = 3.0
_projects_cache = {"ts": 0.0, "data": None}


def _projects_roll_up():
    import time
    now = time.time()
    if _projects_cache["data"] is None or now - _projects_cache["ts"] > PROJECTS_TTL:
        _projects_cache["data"] = roster.roll_up()
        _projects_cache["ts"] = now
    return _projects_cache["data"]


def _find_record(sid):
    data = collector.collect()
    for rec in data["sessions"] + data["stopped_recent"]:
        if rec["session_id"] == sid:
            return rec
    return None


def deep_for(sid):
    """(record, deep-parse) for a session id, cached on transcript identity."""
    rec = _find_record(sid)
    if rec is None:
        return None, None
    transcript = collector.find_transcript(rec["cwd"], sid)
    if transcript is None:
        return rec, _EMPTY_DETAIL
    try:
        st = transcript.stat()
        key = (str(transcript), st.st_mtime_ns, st.st_size)
        cached = _deep_cache.get(sid)
        if cached is None or cached["key"] != key:
            _deep_cache[sid] = {"key": key, "data": deep.parse_full(transcript, rec), "graph": None}
        return rec, _deep_cache[sid]["data"]
    except OSError:
        return rec, _EMPTY_DETAIL


def graph_for(sid):
    """(record, vault graph), graph cached under the same transcript key as the deep parse."""
    rec, data = deep_for(sid)
    if rec is None:
        return None, None
    slot = _deep_cache.get(sid)
    if slot is None or slot["data"] is not data:
        graph = vault.build_graph(data["files"])  # transcript-missing fallback: not cached
        graph["vault_dir"] = str(vault.vault_dir())
        return rec, graph
    if slot["graph"] is None:
        graph = vault.build_graph(slot["data"]["files"])
        graph["vault_dir"] = str(vault.vault_dir())
        slot["graph"] = graph
    return rec, slot["graph"]


class FleetServer(ThreadingHTTPServer):
    # HTTPServer defaults allow_reuse_address=1; on Windows SO_REUSEADDR lets a
    # second server bind the SAME port silently (no error), so "already running"
    # detection via WinError 10048 only works with reuse disabled.
    allow_reuse_address = False


class Handler(BaseHTTPRequestHandler):
    def _send(self, body, ctype="application/json", code=200):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code=200):
        self._send(json.dumps(obj).encode("utf-8"), code=code)

    def do_GET(self):
        if not self._host_allowed():
            return self._json({"error": "forbidden host"}, 403)
        path = self.path.split("?")[0]
        if path == "/":
            path = "/index.html"
        if path == "/data":
            data = collector.collect()
            live_sids = {s["session_id"] for s in data["sessions"] + data["stopped_recent"]}
            for sid in list(_deep_cache):
                if sid not in live_sids:
                    _deep_cache.pop(sid, None)
            return self._json(data)
        if path.startswith("/session/"):
            rec, d = deep_for(path[len("/session/"):])
            if rec is None:
                return self._json({"error": "unknown session"}, 404)
            return self._json({"session": rec, "head": d["head"],
                               "timeline": d["timeline"], "timeline_total": d["timeline_total"]})
        if path.startswith("/vault/"):
            rec, graph = graph_for(path[len("/vault/"):])
            if rec is None:
                return self._json({"error": "unknown session"}, 404)
            return self._json(graph)
        if path == "/projects":
            return self._json(_projects_roll_up())
        if path.startswith("/project/"):
            detail = roster.project_detail(path[len("/project/"):])
            return self._json(detail) if detail else self._json({"error": "unknown project"}, 404)
        static = (UI_DIR / path.lstrip("/")).resolve()
        if static.is_file() and static.is_relative_to(UI_DIR.resolve()):
            return self._send(static.read_bytes(),
                              CONTENT_TYPES.get(static.suffix.lower(), "application/octet-stream"))
        self.send_error(404)

    def do_POST(self):
        if not self._host_allowed():
            return self._json({"error": "forbidden host"}, 403)
        # Check body size before draining; RST on abuse is acceptable.
        try:
            length = max(0, int(self.headers.get("Content-Length", 0)))
        except (ValueError, TypeError):
            length = 0
        if length > MAX_BODY:
            return self._json({"ok": False, "message": "body too large"}, 413)
        # Drain the body first so TCP doesn't RST before we send the response.
        try:
            raw = self.rfile.read(length) if length else b""
        except OSError:
            raw = b""
        if self.path.split("?")[0] != "/action":
            return self.send_error(404)
        if not self._post_allowed():
            return self._json({"ok": False, "message": "forbidden"}, 403)
        try:
            payload = json.loads(raw or b"{}")
        except (ValueError, TypeError):
            return self._json({"ok": False, "message": "bad json"}, 400)
        self._json(actions.dispatch(payload, server=self.server))

    def _post_allowed(self):
        """CSRF guard: a browser page on another origin can fire no-preflight POSTs
        at 127.0.0.1. Require the JSON content type (forces preflight cross-origin,
        and we never answer preflights) and reject foreign Origin headers outright."""
        ctype = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        if ctype != "application/json":
            return False
        origin = self.headers.get("Origin")
        if origin is None:
            return True  # non-browser client (curl, tests, pywebview same-origin)
        port = self.server.server_address[1]
        return origin in (f"http://127.0.0.1:{port}", f"http://localhost:{port}")

    def _host_allowed(self):
        """DNS-rebinding guard: reject requests with a foreign Host header."""
        host = (self.headers.get("Host") or "").strip().lower()
        port = self.server.server_address[1]
        return host in (
            f"127.0.0.1:{port}", f"localhost:{port}",
            "127.0.0.1", "localhost",
        )

    def log_message(self, *args):
        pass


def make_server(port):
    return FleetServer(("127.0.0.1", port), Handler)


def serve(port):
    try:
        srv = make_server(port)
    except OSError as e:
        import errno
        if getattr(e, "winerror", None) == 10048 or e.errno == errno.EADDRINUSE:
            print(f"fleet server already running on port {port}")
            return
        raise
    print(f"fleet -> http://127.0.0.1:{srv.server_address[1]}")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
