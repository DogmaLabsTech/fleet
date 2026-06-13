"""Full-control actions. Kill re-validates PID identity at action time.
Spawn actions validate the slug + roster membership and resolve repo_root
server-side before launching (the request body never supplies a path)."""

import os
import re
import subprocess
import time
from pathlib import Path

from . import collector, roster, spawn, vault

SLUG_RE = re.compile(r"^[a-z0-9-]{1,40}$")


def _launch(target):
    """Separated for testability - tests monkeypatch this."""
    os.startfile(target)  # noqa: S606 - deliberate local launcher


def kill_session(pid, started_at_ms):
    creation = collector.proc_creation_unix_ms(pid)
    if creation == -1:
        return {"ok": False, "message": f"pid {pid} identity unverifiable (access denied) - "
                                        "refused; run fleet elevated to manage this session"}
    if not collector.pid_matches_session(pid, started_at_ms):
        return {"ok": False, "message": f"pid {pid} not alive or identity mismatch - refused"}
    try:
        graceful = subprocess.run(["taskkill", "/PID", str(pid)],
                                  capture_output=True, timeout=10)
        if graceful.returncode == 0:
            deadline = time.time() + 3
            while time.time() < deadline:
                if collector.proc_creation_unix_ms(pid) is None:
                    return {"ok": True, "message": f"session pid {pid} ended"}
                time.sleep(0.25)
        # console processes refuse graceful termination - escalate, taking the tree
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)],
                       capture_output=True, timeout=10)
        deadline = time.time() + 1
        while time.time() < deadline:
            if collector.proc_creation_unix_ms(pid) is None:
                return {"ok": True, "message": f"session pid {pid} force-ended (tree)"}
            time.sleep(0.1)
        return {"ok": False, "message": f"pid {pid} survived taskkill /F"}
    except (OSError, subprocess.SubprocessError) as e:
        return {"ok": False, "message": f"kill failed: {e}"}


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


def _gated_spawn(payload, kind):
    """Server-side gate for every spawn: regex-validate the slug, require roster
    membership, resolve repo_root from the roster (NOT the body), and for agent
    dispatch require the repo to actually have a dedicated agent."""
    slug = str(payload.get("slug") or "")
    if not SLUG_RE.match(slug):
        return {"ok": False, "message": "invalid slug"}
    entry = roster.resolve(slug)
    if entry is None:
        return {"ok": False, "message": f"unknown project: {slug}"}
    repo_root = entry.get("repo_root")  # authoritative; payload['repo_root'] is ignored
    if not repo_root or not Path(repo_root).exists():
        return {"ok": False, "message": f"no repo on disk for {slug}"}
    if kind == "agent" and not entry.get("has_agent"):
        return {"ok": False, "message": f"{slug} has no dedicated agent"}
    return spawn.launch(kind, slug, repo_root)


def dispatch(payload, server=None):
    if not isinstance(payload, dict):
        return {"ok": False, "message": "payload must be a json object"}
    action = payload.get("action")
    if action == "spawn-visual-sweep":
        return _gated_spawn(payload, "visual-sweep")
    if action == "spawn-agent":
        return _gated_spawn(payload, "agent")
    if action == "spawn-relay":
        return _gated_spawn(payload, "relay")
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
