"""engine.collector — data-collection layer for fleet.

Reads Claude Code's on-disk state (read-only):
  ~/.claude/sessions/*.json                   live session state
  ~/.claude/projects/<slug>/<sessionId>.jsonl session transcript
  ~/.claude/history.jsonl                     prompt fallback

All path roots are env-overridable for testing:
  FLEET_CLAUDE_DIR — overrides ~/.claude (default)
"""

import json
import os
import re
import time
from datetime import datetime
from pathlib import Path

from . import oscompat
from .providers import base

# ---------------------------------------------------------------- constants

TAIL_BYTES = 262_144          # single tool_result lines can exceed 64 KB
HISTORY_TAIL_BYTES = 65_536   # history lines can embed huge pastedContents
STOPPED_WINDOW_MS = 30 * 60 * 1000
PID_MATCH_TOLERANCE_MS = 60_000

_STATUS_ORDER = {"busy": 0, "waiting": 1, "idle": 3}  # unknown statuses → 2


# ---------------------------------------------------------------- env-overridable paths

def claude_dir() -> Path:
    return Path(os.environ.get("FLEET_CLAUDE_DIR", str(Path.home() / ".claude")))


def sessions_dir() -> Path:
    return claude_dir() / "sessions"


def projects_dir() -> Path:
    return claude_dir() / "projects"


def history_file() -> Path:
    return claude_dir() / "history.jsonl"


# ---------------------------------------------------------------- repo / slug mapping

_REPO_MARKERS = (".git", "CLAUDE.md", ".fleet")


def repo_root_for(cwd):
    """The repo a session in `cwd` belongs to: nearest ancestor with a marker
    (.git / CLAUDE.md / .fleet), else `cwd` itself. Fail-soft: returns the input
    string on any path error."""
    try:
        here = Path(cwd)
        for d in (here, *here.parents):
            if any((d / m).exists() for m in _REPO_MARKERS):
                return str(d)
    except (OSError, ValueError):
        pass
    return str(cwd)


def slug_for(repo_root):
    """Folder basename → kebab slug. Splits camelCase ("MyApp"→"my-app")
    and non-alnum ("Some_Project"→"some-project")."""
    name = re.split(r"[\\/]", str(repo_root).rstrip("\\/"))[-1]
    name = re.sub(r"(?<=[a-z])(?=[A-Z])", "-", name)  # camelCase boundary
    return re.sub(r"[^A-Za-z0-9]+", "-", name).strip("-").lower()


# ---------------------------------------------------------------- process layer

def proc_creation_unix_ms(pid):
    """Process creation time in unix ms (None=dead, -1=alive-unreadable).
    Delegates to the cross-platform backend; callers and semantics unchanged."""
    return oscompat.proc_create_ms(pid)


def pid_matches_session(pid, started_at_ms, strict=True):
    """Alive AND created within 60s of the session's startedAt (PID-reuse guard).

    strict=True (default/kill): unverifiable identity is refused — never kill
    what we cannot positively identify.
    strict=False (display): an alive-but-unreadable process (access denied, -1)
    counts as a match so elevated sessions stay in the list.

    The session file's own procStart is local-time .NET ticks — DST-fragile,
    deliberately not used here.
    """
    creation = proc_creation_unix_ms(pid)
    if creation is None:
        return False
    if creation == -1:
        return not strict
    return abs(creation - (started_at_ms or 0)) < PID_MATCH_TOLERANCE_MS


# ---------------------------------------------------------------- transcript layer

def cwd_to_slug(cwd):
    return re.sub(r"[^A-Za-z0-9]", "-", cwd or "")


def find_transcript(cwd, session_id):
    direct = projects_dir() / cwd_to_slug(cwd) / f"{session_id}.jsonl"
    if direct.exists():
        return direct
    # slug transform is lossy/case-varied; the sessionId glob is authoritative
    return next(projects_dir().glob(f"*/{session_id}.jsonl"), None)


def tail_lines(path, n_bytes=TAIL_BYTES):
    with open(path, "rb") as f:
        f.seek(0, 2)
        size = f.tell()
        offset = max(0, size - n_bytes)
        f.seek(offset)
        data = f.read()
    lines = data.decode("utf-8", "replace").splitlines()
    if offset > 0 and lines:
        lines = lines[1:]  # drop the partial first line
    return lines


def _user_prompt_text(ev):
    if ev.get("isMeta"):
        return None
    content = (ev.get("message") or {}).get("content")
    if isinstance(content, str):
        text = content
    elif isinstance(content, list):
        if any(isinstance(b, dict) and b.get("type") == "tool_result" for b in content):
            return None
        text = " ".join(b.get("text", "") for b in content
                        if isinstance(b, dict) and b.get("type") == "text")
    else:
        return None
    text = " ".join(text.split())
    if not text or text.startswith(("<command-", "<local-command", "Caveat:")):
        return None
    return text


def _tool_detail(name, tool_input):
    if not isinstance(tool_input, dict):
        return ""
    if name in ("Bash", "PowerShell") and tool_input.get("description"):
        return str(tool_input["description"])
    for key in ("description", "file_path", "pattern", "command", "url",
                "skill", "prompt", "query", "question"):
        if tool_input.get(key):
            return " ".join(str(tool_input[key]).split())
    return ""


def parse_tail(lines):
    """One chronological pass over transcript tail; last writer wins."""
    info = {"title": None, "last_prompt": None, "activity": None,
            "model": None, "branch": None, "last_ts": None, "ctx_tokens": None}
    slug_title = None
    for line in lines:
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if not isinstance(ev, dict):
            continue
        if ev.get("gitBranch"):
            info["branch"] = ev["gitBranch"]
        if ev.get("slug"):
            slug_title = str(ev["slug"]).replace("-", " ")
        if isinstance(ev.get("timestamp"), str):
            info["last_ts"] = ev["timestamp"]
        etype = ev.get("type")
        if etype == "ai-title" and ev.get("aiTitle"):
            info["title"] = ev["aiTitle"]
        elif etype == "last-prompt" and ev.get("lastPrompt"):
            info["last_prompt"] = " ".join(str(ev["lastPrompt"]).split())
        elif etype == "user":
            prompt = _user_prompt_text(ev)
            if prompt:
                info["last_prompt"] = prompt
        elif etype == "assistant":
            msg = ev.get("message") or {}
            if msg.get("model") and msg["model"] != "<synthetic>":
                info["model"] = msg["model"]
            usage = msg.get("usage") or {}
            ctx = sum(usage.get(k) or 0 for k in
                      ("cache_read_input_tokens", "cache_creation_input_tokens", "input_tokens"))
            if ctx:
                info["ctx_tokens"] = ctx
            content = msg.get("content")
            if isinstance(content, list) and content and isinstance(content[-1], dict):
                block = content[-1]
                if block.get("type") == "tool_use":
                    name = block.get("name", "?")
                    detail = _tool_detail(name, block.get("input"))
                    info["activity"] = (name + (": " + detail if detail else ""))[:110]
                elif block.get("type") == "text" and block.get("text", "").strip():
                    info["activity"] = "writing: " + " ".join(block["text"].split())[:90]
    if not info["title"]:
        info["title"] = slug_title
    return info


def history_prompt_fallback(session_id):
    try:
        lines = tail_lines(history_file(), HISTORY_TAIL_BYTES)
    except OSError:
        return None
    for line in reversed(lines):
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if isinstance(ev, dict) and ev.get("sessionId") == session_id and ev.get("display"):
            return " ".join(str(ev["display"]).split())
    return None


# ---------------------------------------------------------------- collector

def _read_session_file(path):
    for attempt in range(2):
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            if attempt == 0:
                time.sleep(0.05)  # mid-write lock; one retry
    return None


def collect_claude(now_ms):
    """Gather Claude Code sessions as normalized records (live_list, stopped).

    The shared sort/count/age step lives in collect(), which runs it across every
    provider — so this returns lists, not the final envelope.
    """
    live, stopped = {}, []
    for path in sorted(sessions_dir().glob("*.json")):
        try:
            data = _read_session_file(path)
            if not isinstance(data, dict) or "sessionId" not in data:
                continue
            sid = data["sessionId"]
            status = data.get("status") or "unknown"
            started = data.get("startedAt") or 0
            updated = data.get("updatedAt") or started
            alive = status != "stopped" and pid_matches_session(data.get("pid"), started, strict=False)
            cwd = data.get("cwd") or ""
            rec = base.make_record(
                provider="claude",
                pid=data.get("pid"),
                session_id=sid,
                cwd=cwd,
                project=re.split(r"[\\/]", cwd.rstrip("\\/"))[-1] or "?",
                status=status if alive else "stopped",
                waiting_for=data.get("waitingFor"),
                kind=data.get("kind") or "interactive",
                name=data.get("name"),
                version=data.get("version"),
                started_at=started,
                updated_at=updated,
                live=alive,
            )
            if alive:
                prev = live.get(sid)
                if prev is None or updated > prev["updated_at"]:
                    live[sid] = rec
            elif now_ms - updated <= STOPPED_WINDOW_MS:
                stopped.append(rec)
        except Exception:
            continue  # one weird session file must never kill the table

    live_list = list(live.values())
    for rec in live_list:
        try:
            transcript = find_transcript(rec["cwd"], rec["session_id"])
            if transcript:
                rec["transcript"] = str(transcript)
                info = parse_tail(tail_lines(transcript))
                for key in ("title", "last_prompt", "activity", "model", "branch", "ctx_tokens"):
                    if info.get(key):
                        rec[key] = info[key]
                if info.get("last_ts"):
                    try:
                        ts_ms = int(datetime.fromisoformat(info["last_ts"]).timestamp() * 1000)
                        rec["updated_at"] = max(rec["updated_at"], ts_ms)
                    except ValueError:
                        pass
        except Exception:
            pass
        if not rec["last_prompt"]:
            try:
                rec["last_prompt"] = history_prompt_fallback(rec["session_id"])
            except Exception:
                pass
    return live_list, stopped


def collect():
    """Merge live + recently-stopped sessions across every enabled provider into
    the dashboard envelope (counts/sessions/stopped_recent)."""
    now_ms = int(time.time() * 1000)
    from .providers import enabled_providers
    live, stopped = [], []
    for prov in enabled_providers():
        try:
            prov_live, prov_stopped = prov.collect(now_ms)
            live.extend(prov_live)
            stopped.extend(prov_stopped)
        except Exception:
            continue  # one broken provider must never kill the table

    sessions = sorted(live, key=lambda r: (
        0 if r["kind"] == "interactive" else 1,
        _STATUS_ORDER.get(r["status"], 2),
        now_ms - r["updated_at"],
    ))
    for rec in sessions + stopped:
        rec["age_s"] = max(0, (now_ms - rec["updated_at"]) // 1000)
    interactive = [r for r in sessions if r["kind"] == "interactive"]
    return {
        "generated_at": now_ms,
        "counts": {
            "live": len(sessions),
            "busy": sum(1 for r in interactive if r["status"] == "busy"),
            "waiting": sum(1 for r in interactive if r["status"] == "waiting"),
            "idle": sum(1 for r in interactive if r["status"] == "idle"),
            "background": len(sessions) - len(interactive),
        },
        "sessions": sessions,
        "stopped_recent": sorted(stopped, key=lambda r: r["age_s"]),
    }
