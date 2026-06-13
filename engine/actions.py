"""Full-control actions. Kill re-validates PID identity at action time.
The only actions are a non-destructive open (file/folder/Obsidian page, handed
off to the OS) and ending a session (confirm-gated, PID-reuse guarded)."""

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

from . import collector, oscompat, vault


def _launch(target):
    """Separated for testability - tests monkeypatch oscompat.open_in_os."""
    oscompat.open_in_os(target)


def kill_session(pid, started_at_ms):
    creation = collector.proc_creation_unix_ms(pid)
    if creation == -1:
        return {"ok": False, "message": f"pid {pid} identity unverifiable (access denied) - "
                                        "refused; run fleet with more privilege to manage it"}
    if not collector.pid_matches_session(pid, started_at_ms):
        return {"ok": False, "message": f"pid {pid} not alive or identity mismatch - refused"}
    try:
        if sys.platform == "win32":
            graceful = subprocess.run(["taskkill", "/PID", str(pid)], capture_output=True, timeout=10)
            if graceful.returncode == 0 and _wait_gone(pid, 3):
                return {"ok": True, "message": f"session pid {pid} ended"}
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True, timeout=10)
            if _wait_gone(pid, 1):
                return {"ok": True, "message": f"session pid {pid} force-ended (tree)"}
            return {"ok": False, "message": f"pid {pid} survived taskkill /F"}
        # POSIX: SIGTERM, grace, then SIGKILL. os.kill(pid, 0) is a safe liveness
        # probe off-Windows (the Windows hazard where it terminates the target does not apply).
        os.kill(pid, signal.SIGTERM)
        if _wait_gone(pid, 3):
            return {"ok": True, "message": f"session pid {pid} ended"}
        os.kill(pid, signal.SIGKILL)
        if _wait_gone(pid, 1):
            return {"ok": True, "message": f"session pid {pid} force-killed"}
        return {"ok": False, "message": f"pid {pid} survived SIGKILL"}
    except (OSError, ValueError) as e:
        return {"ok": False, "message": f"kill failed: {e}"}


def _wait_gone(pid, seconds):
    deadline = time.time() + seconds
    while time.time() < deadline:
        if collector.proc_creation_unix_ms(pid) is None:
            return True
        time.sleep(0.1)
    return False


def open_obsidian(rel):
    uri = vault.obsidian_uri(rel)
    label = f"opened {rel} in Obsidian" if rel else "opened vault in Obsidian"
    try:
        _launch(uri)
        return {"ok": True, "message": label}
    except OSError:
        try:
            subprocess.Popen(["obsidian", uri], stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, shell=False)
            return {"ok": True, "message": label + " (cli fallback)"}
        except OSError as e:
            return {"ok": False, "message": f"obsidian launch failed: {e}"}


def open_path(path):
    p = Path(path)
    if not p.exists():
        return {"ok": False, "message": f"path not found: {path}"}
    try:
        _launch(str(p))
        return {"ok": True, "message": f"opened {p.name}"}
    except OSError as e:
        return {"ok": False, "message": f"open failed: {e}"}


def dispatch(payload, server=None):
    if not isinstance(payload, dict):
        return {"ok": False, "message": "payload must be a json object"}
    action = payload.get("action")
    if action == "kill":
        try:
            return kill_session(int(payload["pid"]), int(payload["started_at"]))
        except (KeyError, TypeError, ValueError):
            return {"ok": False, "message": "kill needs integer pid and started_at"}
    if action == "open-obsidian":
        return open_obsidian(str(payload.get("rel") or ""))
    if action in ("open-file", "open-folder"):
        return open_path(str(payload.get("path") or ""))
    if action == "stop-server":
        if server is None:
            return {"ok": False, "message": "stop-server unavailable here"}
        import threading
        threading.Thread(target=server.shutdown, daemon=True).start()
        return {"ok": True, "message": "server stopping"}
    return {"ok": False, "message": f"unknown action: {action}"}
