"""engine.providers.base — shared scaffolding for session providers.

Fleet supports more than one terminal AI coding agent. Each is a *provider*: a
module that reads its tool's own on-disk state (read-only) and returns sessions
in one common shape so the merger, the table, and the dashboard treat them all
identically.

A provider module exposes:
    ID                    : str    short id ("claude", "codex", ...)
    LABEL                 : str    display name ("Claude Code")
    detect()              -> bool                       is the tool present on disk?
    collect(now_ms)       -> (live: list, stopped: list)  normalized records
    find_transcript(rec)  -> Path | None                transcript path for a record
    deep_parse(rec, path) -> dict | None                {head, timeline, timeline_total, files}

Records all come from make_record() so every key the UI reads is always present.

Liveness honesty: only providers that persist a live status/PID file (Claude
Code, Qwen Code) can report true running/waiting/idle. The rest expose only an
after-the-fact transcript, so their liveness is *inferred* from how recently the
transcript was written — marked live_inferred=True and never dressed up as the
precise busy/waiting state we cannot actually know.
"""

import re

# A status-file-less provider counts a session as inferred-active if its
# transcript was written within this window; older-but-recent ones fall through
# to "stopped" (mirroring collector.STOPPED_WINDOW_MS for the table's recents).
ACTIVE_WINDOW_MS = 5 * 60 * 1000

# Every record carries these keys with these defaults; providers override what
# they can supply and leave the rest. Keeps the table/UI free of key checks.
_DEFAULTS = {
    "provider": "?",
    "pid": None,
    "session_id": "",
    "cwd": "",
    "project": "?",
    "status": "idle",
    "waiting_for": None,
    "kind": "interactive",
    "name": None,
    "version": None,
    "started_at": 0,
    "updated_at": 0,
    "live": False,
    "live_inferred": False,   # True => status is a freshness guess, not a read fact
    "transcript": None,       # str path, when the provider knows it at collect time
    "title": None,
    "last_prompt": None,
    "activity": None,
    "model": None,
    "branch": None,
    "ctx_tokens": None,
}


def make_record(**fields):
    """A session record with every key defaulted; pass overrides as kwargs."""
    rec = dict(_DEFAULTS)
    rec.update(fields)
    return rec


def project_of(cwd):
    """Folder basename of a working dir, OS-agnostic ('' -> '?')."""
    return re.split(r"[\\/]", (cwd or "").rstrip("\\/"))[-1] or "?"


def iso_ms(ts):
    """ISO-8601 timestamp -> unix ms, or None."""
    from datetime import datetime
    if not isinstance(ts, str):
        return None
    try:
        return int(datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp() * 1000)
    except ValueError:
        return None


def infer_status(updated_ms, now_ms):
    """(status, live) for a provider with no status file, from transcript freshness."""
    if now_ms - updated_ms <= ACTIVE_WINDOW_MS:
        return "active", True
    return "stopped", False


def rules_chain(cwd, filename, global_path=None):
    """Rule files in scope for a session: `filename` from cwd up through its
    parents, then an optional global path. Each provider passes its own rules
    filename (CLAUDE.md / AGENTS.md / GEMINI.md / QWEN.md)."""
    from pathlib import Path
    rules = []
    try:
        p = Path(cwd)
        for parent in [p, *p.parents]:
            c = parent / filename
            if c.exists():
                rules.append(str(c))
    except (OSError, ValueError):
        pass
    if global_path is not None:
        gp = Path(global_path)
        if gp.exists():
            rules.append(str(gp))
    return rules


def tail_lines(path, n_bytes=262_144):
    """Last ~n_bytes of a file as decoded lines, dropping the partial first line.
    Mirrors collector.tail_lines so providers don't reach back into Claude code."""
    with open(path, "rb") as f:
        f.seek(0, 2)
        size = f.tell()
        offset = max(0, size - n_bytes)
        f.seek(offset)
        data = f.read()
    lines = data.decode("utf-8", "replace").splitlines()
    if offset > 0 and lines:
        lines = lines[1:]
    return lines
