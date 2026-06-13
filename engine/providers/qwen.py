"""Qwen Code provider.

Qwen Code (a Gemini-CLI fork) is the one non-Claude CLI that writes a per-session
runtime sidecar for external observers:
    ~/.qwen/projects/<project_id>/chats/<sessionId>.jsonl          transcript
    ~/.qwen/projects/<project_id>/chats/<sessionId>.runtime.json   {pid, work_dir, ...}
so Fleet reports TRUE liveness for Qwen (a real PID check), like Claude Code —
not the freshness guess the other non-Claude providers must use.

The transcript shares Gemini's chat-JSONL schema (see _geminish).

Path overrides (first match wins): FLEET_QWEN_DIR, QWEN_HOME, ~/.qwen
"""

import json
import os
from pathlib import Path

from .. import oscompat
from . import _geminish, base

ID = "qwen"
LABEL = "Qwen Code"

STOPPED_WINDOW_MS = 30 * 60 * 1000


def qwen_home():
    return Path(os.environ.get("FLEET_QWEN_DIR")
                or os.environ.get("QWEN_HOME")
                or (Path.home() / ".qwen"))


def projects_dir():
    return qwen_home() / "projects"


def detect():
    return projects_dir().exists()


def _read_runtime(chat):
    rt = chat.parent / (chat.stem + ".runtime.json")
    try:
        if rt.exists():
            data = json.loads(rt.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
    except (OSError, ValueError):
        pass
    return None


def _is_alive(pid):
    """True only if a process with this pid is currently running (zombies count
    as dead — see oscompat). None pid / non-int -> dead."""
    if not isinstance(pid, int):
        return False
    return oscompat.proc_create_ms(pid) is not None


def collect(now_ms):
    if not projects_dir().exists():
        return [], []
    live, stopped = [], []
    for chat in projects_dir().glob("*/chats/*.jsonl"):
        try:
            mtime_ms = int(chat.stat().st_mtime * 1000)
        except OSError:
            continue
        rt = _read_runtime(chat) or {}
        pid = rt.get("pid")
        alive = _is_alive(pid)
        if not alive and now_ms - mtime_ms > STOPPED_WINDOW_MS:
            continue  # not running and not recent
        meta = _geminish.session_meta(chat)
        s = _geminish.summarize(chat)
        cwd = rt.get("work_dir") or ""
        rec = base.make_record(
            provider="qwen",
            pid=pid if alive else None,
            session_id=meta.get("sessionId") or rt.get("session_id") or chat.stem,
            cwd=cwd,
            project=base.project_of(cwd) if cwd else chat.parent.parent.name,
            status="active" if alive else "stopped",
            kind="interactive",
            version=rt.get("qwen_version"),
            model=s["model"],
            started_at=base.iso_ms(rt.get("started_at")) or base.iso_ms(meta.get("startTime")) or mtime_ms,
            updated_at=mtime_ms,
            live=alive,
            live_inferred=False,   # Qwen exposes a real PID — this is a read fact
            transcript=str(chat),
            last_prompt=s["last_prompt"],
            activity=s["activity"],
            ctx_tokens=s["ctx_tokens"],
        )
        (live if alive else stopped).append(rec)
    return live, stopped


def find_transcript(rec):
    t = rec.get("transcript")
    return Path(t) if t else None


def deep_parse(rec, transcript):
    return _geminish.parse_full(transcript, rec,
                                rules_file="QWEN.md",
                                rules_global=qwen_home() / "QWEN.md")
