"""OpenAI Codex CLI provider.

Reads ~/.codex/sessions/YYYY/MM/DD/rollout-<ts>-<uuid>.jsonl (read-only). Each
line is {timestamp, type, payload}:
  type "session_meta"  -> payload: id, cwd, cli_version, model_provider, model
  type "event_msg"     -> payload.type: task_started / user_message / agent_message
                          / task_complete / token_count (context tokens live in
                          info.total_token_usage.total_tokens)
  type "response_item" -> payload.type: message (role + input_text/output_text),
                          function_call / local_shell_call / custom_tool_call

Codex writes no live status/PID file, so liveness is inferred from how recently
the rollout file was written (base.infer_status) and marked live_inferred.

Path overrides (first match wins): FLEET_CODEX_DIR, CODEX_HOME, ~/.codex
"""

import json
import os
import re
from datetime import datetime
from pathlib import Path

from . import base

ID = "codex"
LABEL = "Codex CLI"

STOPPED_WINDOW_MS = 30 * 60 * 1000   # mirror collector's recents window
SCAN_LIMIT = 500                     # cap rollout files stat'd per collect
TIMELINE_CAP = 300

_NOISE = ("<command-", "<local-command", "Caveat:", "<task-notification", "<system-reminder")
_PATCH_FILE = re.compile(r"\*\*\* (Add|Update|Delete) File: (.+)")
_SEARCH_TOOLS = {"grep", "rg", "ag", "ripgrep", "find"}
_READ_TOOLS = {"cat", "head", "tail", "sed", "less", "bat"}


def codex_home():
    return Path(os.environ.get("FLEET_CODEX_DIR")
                or os.environ.get("CODEX_HOME")
                or (Path.home() / ".codex"))


def sessions_dir():
    return codex_home() / "sessions"


def detect():
    return sessions_dir().exists()


# ---------------------------------------------------------------- helpers

def _iso_ms(ts):
    if not isinstance(ts, str):
        return None
    try:
        return int(datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp() * 1000)
    except ValueError:
        return None


def _clean(text):
    return " ".join(str(text or "").split())


def _is_noise(text):
    return not text or text.startswith(_NOISE)


def _content_text(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(b.get("text", "") for b in content
                        if isinstance(b, dict)
                        and b.get("type") in ("input_text", "output_text", "text")
                        and b.get("text"))
    return ""


def _rollout_files():
    d = sessions_dir()
    if not d.exists():
        return []
    files = list(d.glob("**/rollout-*.jsonl"))
    files.sort(key=lambda p: p.name, reverse=True)  # filename embeds the start ts
    return files[:SCAN_LIMIT]


def _first_session_meta(path):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            ev = json.loads(f.readline() or "{}")
        if isinstance(ev, dict) and ev.get("type") == "session_meta":
            return ev.get("payload") or {}
    except (OSError, ValueError):
        pass
    return {}


def _describe_tool(payload):
    """Short label for a tool call, for the table's 'activity' line."""
    if payload.get("type") == "local_shell_call":
        action = payload.get("action") or {}
        cmd = action.get("command")
        raw = " ".join(cmd) if isinstance(cmd, list) else str(cmd or "")
        return _clean(raw)[:110]
    name = payload.get("name") or "tool"
    args = payload.get("arguments")
    raw = args if isinstance(args, str) else ""
    if _PATCH_FILE.search(raw):
        n = len(_PATCH_FILE.findall(raw))
        return f"apply_patch: {n} file{'s' if n != 1 else ''}"
    return _clean(name)[:110]


# ---------------------------------------------------------------- collect (table)

def _summarize_tail(path):
    out = {"last_prompt": None, "activity": None, "ctx_tokens": None}
    try:
        lines = base.tail_lines(path)
    except OSError:
        return out
    for line in lines:
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if not isinstance(ev, dict):
            continue
        t, p = ev.get("type"), ev.get("payload") or {}
        if t == "event_msg":
            pt = p.get("type")
            if pt == "token_count":
                tot = ((p.get("info") or {}).get("total_token_usage") or {}).get("total_tokens")
                if tot:
                    out["ctx_tokens"] = tot
            elif pt == "user_message":
                txt = _clean(p.get("message"))
                if not _is_noise(txt):
                    out["last_prompt"] = txt
            elif pt == "agent_message":
                txt = _clean(p.get("message"))
                if txt and txt != "<EXTERNAL SESSION IMPORTED>":
                    out["activity"] = ("writing: " + txt)[:110]
        elif t == "response_item":
            pt = p.get("type")
            if pt == "message":
                txt = _clean(_content_text(p.get("content")))
                if not txt:
                    continue
                if p.get("role") == "user" and not _is_noise(txt):
                    out["last_prompt"] = txt
                elif p.get("role") == "assistant":
                    out["activity"] = ("writing: " + txt)[:110]
            elif pt in ("function_call", "local_shell_call", "custom_tool_call"):
                out["activity"] = _describe_tool(p)
    return out


def collect(now_ms):
    live, stopped = [], []
    for path in _rollout_files():
        try:
            mtime_ms = int(path.stat().st_mtime * 1000)
        except OSError:
            continue
        if now_ms - mtime_ms > STOPPED_WINDOW_MS:
            continue
        meta = _first_session_meta(path)
        sid = meta.get("id") or path.stem
        cwd = meta.get("cwd") or ""
        status, alive = base.infer_status(mtime_ms, now_ms)
        summary = _summarize_tail(path)
        rec = base.make_record(
            provider="codex",
            session_id=sid,
            cwd=cwd,
            project=base.project_of(cwd),
            status=status,
            kind="interactive",
            version=meta.get("cli_version"),
            model=meta.get("model") or meta.get("model_provider"),
            started_at=_iso_ms(meta.get("timestamp")) or mtime_ms,
            updated_at=mtime_ms,
            live=alive,
            live_inferred=True,
            transcript=str(path),
            last_prompt=summary["last_prompt"],
            activity=summary["activity"],
            ctx_tokens=summary["ctx_tokens"],
        )
        (live if alive else stopped).append(rec)
    return live, stopped


def find_transcript(rec):
    t = rec.get("transcript")
    return Path(t) if t else None


# ---------------------------------------------------------------- deep (HEAD/TIMELINE)

def _touch(files, bucket, key, ts):
    slot = files[bucket].setdefault(key, {"path": key, "count": 0, "last": ts})
    slot["count"] += 1
    slot["last"] = ts or slot["last"]


def _apply_tool(payload, files, timeline, ts):
    t = payload.get("type")
    name = (payload.get("name") or "").lower()
    if t == "local_shell_call":
        action = payload.get("action") or {}
        cmd = action.get("command")
        raw = " ".join(cmd) if isinstance(cmd, list) else str(cmd or "")
    else:
        args = payload.get("arguments")
        raw = args if isinstance(args, str) else ""

    found = _PATCH_FILE.findall(raw)
    if "apply_patch" in name or found:
        for op, fpath in found:
            fpath = fpath.strip()
            bucket = "written" if op == "Add" else "edited"
            _touch(files, bucket, fpath, ts)
            timeline.append({"ts": ts, "kind": "write" if bucket == "written" else "edit",
                             "text": fpath})
        if found:
            return

    cmd = _clean(re.sub(r"^.*?-lc\s+", "", raw)).strip("\"' ")
    tok = (cmd.split() or [""])[0].lower()
    if tok in _SEARCH_TOOLS:
        _touch(files, "searched", cmd[:80], ts)
    elif tok in _READ_TOOLS:
        parts = cmd.split()
        _touch(files, "read", parts[-1] if len(parts) > 1 else cmd, ts)
    elif cmd:
        timeline.append({"ts": ts, "kind": "tool", "text": cmd[:110]})


def deep_parse(rec, transcript):
    files = {"read": {}, "edited": {}, "written": {}, "searched": {}}
    timeline = []
    head = {"ctx_tokens": None, "ctx_window": None, "model": None, "branch": None, "warnings": []}
    last_user = last_assistant = None

    try:
        lines = transcript.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as e:
        head["warnings"].append(f"transcript unreadable: {e}")
        lines = []

    def add_prompt(ts, txt):
        nonlocal last_user
        if txt and not _is_noise(txt) and txt != last_user:
            timeline.append({"ts": ts, "kind": "prompt", "text": txt[:500]})
            last_user = txt

    def add_writing(ts, txt):
        nonlocal last_assistant
        if txt and txt != "<EXTERNAL SESSION IMPORTED>" and txt != last_assistant:
            timeline.append({"ts": ts, "kind": "writing", "text": txt[:500]})
            last_assistant = txt

    for line in lines:
        try:
            ev = json.loads(line)
            if not isinstance(ev, dict):
                continue
            ts, t, p = ev.get("timestamp") or "", ev.get("type"), ev.get("payload") or {}
            if t == "session_meta":
                head["model"] = head["model"] or p.get("model") or p.get("model_provider")
            elif t == "event_msg":
                pt = p.get("type")
                if pt == "token_count":
                    info = p.get("info") or {}
                    tot = (info.get("total_token_usage") or {}).get("total_tokens")
                    if tot:
                        head["ctx_tokens"] = tot
                    if info.get("model_context_window"):
                        head["ctx_window"] = info["model_context_window"]
                elif pt == "user_message":
                    add_prompt(ts, _clean(p.get("message")))
                elif pt == "agent_message":
                    add_writing(ts, _clean(p.get("message")))
            elif t == "response_item":
                pt = p.get("type")
                if pt == "message":
                    txt = _clean(_content_text(p.get("content")))
                    if p.get("role") == "user":
                        add_prompt(ts, txt)
                    elif p.get("role") == "assistant":
                        add_writing(ts, txt)
                elif pt in ("function_call", "local_shell_call", "custom_tool_call"):
                    _apply_tool(p, files, timeline, ts)
                elif pt == "function_call_output":
                    out = p.get("output")
                    if isinstance(out, dict) and out.get("success") is False:
                        timeline.append({"ts": ts, "kind": "error",
                                         "text": _clean(out.get("content"))[:200]})
        except (json.JSONDecodeError, ValueError, TypeError, AttributeError):
            continue

    head["rules"] = base.rules_chain(rec.get("cwd", ""), "AGENTS.md", codex_home() / "AGENTS.md")
    head["files"] = {k: _bucket_list(files[k]) for k in files}
    head["skills"], head["agents"], head["mcp"] = [], [], []

    total = len(timeline)
    timeline = timeline[-TIMELINE_CAP:]
    if timeline and total <= TIMELINE_CAP:
        timeline.insert(0, {"ts": timeline[0]["ts"], "kind": "note", "text": "session started"})

    return {"head": head, "timeline": timeline, "timeline_total": total,
            "files": head["files"]}


def _bucket_list(bucket):
    return sorted(bucket.values(), key=lambda f: f["last"], reverse=True)
