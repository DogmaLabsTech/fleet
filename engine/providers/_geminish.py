"""Shared transcript parsing for Gemini CLI and its fork, Qwen Code.

Both write per-session JSONL chat logs with the same record shape:
  line 0           {sessionId, projectHash, startTime, lastUpdated, kind}   (meta)
  type "user"      {content: str}                  a prompt (content is a string)
  type "user"      {content: [{functionResponse}]} a tool result (skipped)
  type "gemini"/   {content, toolCalls:[{name,args,result}], model, tokens}  assistant turn
       "qwen"
  {"$set": ...}    state update (skipped)

Tool calls map to Fleet's file buckets: read_file -> read, write_file -> written,
replace -> edited, run_shell_command/grep/glob -> searched, activate_skill -> skills.
"""

import json

from . import base

TIMELINE_CAP = 300
_NOISE = ("<command-", "<local-command", "Caveat:", "<task-notification", "<system-reminder")

_READ = {"read_file", "read_many_files"}
_WRITE = {"write_file"}
_EDIT = {"replace", "edit"}
_SEARCH = {"search_file_content", "grep", "glob", "list_directory", "ripgrep"}
_SHELL = "run_shell_command"
_SKILL = "activate_skill"
_SH_SEARCH = {"grep", "rg", "ag", "find"}
_SH_READ = {"cat", "head", "tail", "sed", "less", "bat"}


def session_meta(path):
    """First-line meta record {sessionId, startTime, lastUpdated, ...}, or {}."""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            o = json.loads(f.readline() or "{}")
        if isinstance(o, dict) and o.get("sessionId"):
            return o
    except (OSError, ValueError):
        pass
    return {}


def _clean(text):
    return " ".join(str(text or "").split())


def _is_noise(text):
    return not text or text.startswith(_NOISE)


def _is_assistant(t):
    return t not in (None, "user", "$set", "")


def _tool_path(args):
    if not isinstance(args, dict):
        return None
    for k in ("absolute_path", "file_path", "path", "filename"):
        if args.get(k):
            return str(args[k])
    return None


def _tool_calls(msg):
    """(name, args) pairs from a message's toolCalls array and/or functionCall blocks."""
    calls, seen = [], set()
    for tc in msg.get("toolCalls") or []:
        if isinstance(tc, dict) and tc.get("name"):
            key = (tc["name"], json.dumps(tc.get("args"), sort_keys=True, default=str))
            if key not in seen:
                seen.add(key)
                calls.append((tc["name"], tc.get("args")))
    content = msg.get("content")
    if isinstance(content, list):
        for b in content:
            if isinstance(b, dict) and isinstance(b.get("functionCall"), dict):
                fc = b["functionCall"]
                key = (fc.get("name"), json.dumps(fc.get("args"), sort_keys=True, default=str))
                if fc.get("name") and key not in seen:
                    seen.add(key)
                    calls.append((fc.get("name"), fc.get("args")))
    return calls


def _touch(files, bucket, key, ts):
    slot = files[bucket].setdefault(key, {"path": key, "count": 0, "last": ts})
    slot["count"] += 1
    slot["last"] = ts or slot["last"]


def _apply_tool(name, args, files, timeline, skills, ts):
    name = (name or "").lower()
    if name in _READ:
        p = _tool_path(args)
        if p:
            _touch(files, "read", p, ts)
    elif name in _WRITE:
        p = _tool_path(args)
        if p:
            _touch(files, "written", p, ts)
            timeline.append({"ts": ts, "kind": "write", "text": p})
    elif name in _EDIT:
        p = _tool_path(args)
        if p:
            _touch(files, "edited", p, ts)
            timeline.append({"ts": ts, "kind": "edit", "text": p})
    elif name in _SEARCH:
        a = args if isinstance(args, dict) else {}
        label = str(a.get("pattern") or a.get("query") or _tool_path(args) or name)
        _touch(files, "searched", label[:80], ts)
    elif name == _SHELL:
        cmd = _clean((args or {}).get("command") if isinstance(args, dict) else args)
        tok = (cmd.split() or [""])[0].lower()
        if tok in _SH_SEARCH:
            _touch(files, "searched", cmd[:80], ts)
        elif tok in _SH_READ:
            parts = cmd.split()
            _touch(files, "read", parts[-1] if len(parts) > 1 else cmd, ts)
        elif cmd:
            timeline.append({"ts": ts, "kind": "tool", "text": cmd[:110]})
    elif name == _SKILL:
        s = (args or {}).get("name") if isinstance(args, dict) else None
        if s and s not in skills:
            skills.append(s)
        timeline.append({"ts": ts, "kind": "skill", "text": str(s)})
    elif name:
        timeline.append({"ts": ts, "kind": "tool", "text": name})


def _bucket_list(bucket):
    return sorted(bucket.values(), key=lambda f: f["last"], reverse=True)


def summarize(path):
    """Table fields (last_prompt, activity, model, ctx_tokens) from a tail read."""
    out = {"last_prompt": None, "activity": None, "model": None, "ctx_tokens": None}
    try:
        lines = base.tail_lines(path)
    except OSError:
        return out
    for line in lines:
        try:
            o = json.loads(line)
        except ValueError:
            continue
        if not isinstance(o, dict):
            continue
        t = o.get("type")
        if t == "user":
            txt = _clean(o.get("content")) if isinstance(o.get("content"), str) else ""
            if not _is_noise(txt):
                out["last_prompt"] = txt
        elif _is_assistant(t):
            if o.get("model"):
                out["model"] = o["model"]
            if isinstance(o.get("tokens"), int):
                out["ctx_tokens"] = o["tokens"]
            txt = _clean(o.get("content")) if isinstance(o.get("content"), str) else ""
            if txt:
                out["activity"] = ("writing: " + txt)[:110]
            else:
                calls = _tool_calls(o)
                if calls:
                    out["activity"] = str(calls[-1][0])[:110]
    return out


def parse_full(path, rec, rules_file="GEMINI.md", rules_global=None):
    files = {"read": {}, "edited": {}, "written": {}, "searched": {}}
    timeline, skills = [], []
    head = {"ctx_tokens": None, "ctx_window": None, "model": None, "branch": None, "warnings": []}
    last_user = last_assistant = None

    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as e:
        head["warnings"].append(f"transcript unreadable: {e}")
        lines = []

    for line in lines:
        try:
            o = json.loads(line)
            if not isinstance(o, dict):
                continue
            ts = o.get("timestamp") or ""
            t = o.get("type")
            if t == "user":
                if isinstance(o.get("content"), str):
                    txt = _clean(o["content"])
                    if txt and not _is_noise(txt) and txt != last_user:
                        timeline.append({"ts": ts, "kind": "prompt", "text": txt[:500]})
                        last_user = txt
            elif _is_assistant(t):
                if o.get("model"):
                    head["model"] = o["model"]
                if isinstance(o.get("tokens"), int):
                    head["ctx_tokens"] = o["tokens"]
                if isinstance(o.get("content"), str):
                    txt = _clean(o["content"])
                    if txt and txt != last_assistant:
                        timeline.append({"ts": ts, "kind": "writing", "text": txt[:500]})
                        last_assistant = txt
                for name, args in _tool_calls(o):
                    _apply_tool(name, args, files, timeline, skills, ts)
        except (json.JSONDecodeError, ValueError, TypeError, AttributeError):
            continue

    head["rules"] = base.rules_chain(rec.get("cwd", ""), rules_file, rules_global)
    head["files"] = {k: _bucket_list(files[k]) for k in files}
    head["skills"], head["agents"], head["mcp"] = skills, [], []

    total = len(timeline)
    timeline = timeline[-TIMELINE_CAP:]
    if timeline and total <= TIMELINE_CAP:
        timeline.insert(0, {"ts": timeline[0]["ts"], "kind": "note", "text": "session started"})

    return {"head": head, "timeline": timeline, "timeline_total": total,
            "files": head["files"]}
