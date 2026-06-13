"""Full-transcript parser: everything the HEAD and TIMELINE tabs show."""

import json
from pathlib import Path

from .collector import _user_prompt_text

TIMELINE_CAP = 300
FILE_TOOLS = {  # tool name -> files bucket
    "Read": "read", "Write": "written", "Edit": "edited",
    "MultiEdit": "edited", "NotebookEdit": "edited",
}


def rules_for_cwd(cwd):
    """CLAUDE.md chain Claude Code actually loads: cwd up through parents, + global."""
    rules = []
    try:
        p = Path(cwd)
        for parent in [p, *p.parents]:
            c = parent / "CLAUDE.md"
            if c.exists():
                rules.append(str(c))
    except OSError:
        pass
    home = Path.home() / ".claude" / "CLAUDE.md"
    if home.exists():
        rules.append(str(home))
    return rules


def _clip(text, n=500):
    return " ".join(str(text).split())[:n]


def parse_full(path, rec):
    """One linear pass. rec needs only 'cwd'. Never raises on bad lines."""
    files = {"read": {}, "edited": {}, "written": {}, "searched": {}}
    skills, agents, mcp = [], [], []
    timeline = []
    head = {"ctx_tokens": None, "model": None, "branch": None, "warnings": []}

    def touch(bucket, key, ts):
        slot = files[bucket].setdefault(key, {"path": key, "count": 0, "last": ts})
        slot["count"] += 1
        slot["last"] = ts or slot["last"]

    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as e:
        head["warnings"].append(f"transcript unreadable: {e}")
        lines = []

    for line in lines:
        try:
            ev = json.loads(line)
            if not isinstance(ev, dict):
                continue
            ts = ev.get("timestamp") or ""
            if ev.get("gitBranch"):
                head["branch"] = ev["gitBranch"]
            etype = ev.get("type")
            msg = ev.get("message") or {}
            content = msg.get("content")

            if etype == "user":
                prompt = _user_prompt_text(ev)
                if prompt:
                    timeline.append({"ts": ts, "kind": "prompt", "text": prompt[:500]})
                if not ev.get("isMeta") and isinstance(content, list):
                    for b in content:
                        if isinstance(b, dict) and b.get("type") == "tool_result" and b.get("is_error"):
                            timeline.append({"ts": ts, "kind": "error",
                                             "text": _clip(b.get("content", ""), 200)})

            elif etype == "assistant":
                if msg.get("model") and msg["model"] != "<synthetic>":
                    head["model"] = msg["model"]
                usage = msg.get("usage") or {}
                ctx = sum(usage.get(k) or 0 for k in
                          ("cache_read_input_tokens", "cache_creation_input_tokens", "input_tokens"))
                if ctx:
                    head["ctx_tokens"] = ctx
                for b in content if isinstance(content, list) else []:
                    if not (isinstance(b, dict) and b.get("type") == "tool_use"):
                        continue
                    name, inp = b.get("name", ""), b.get("input") or {}
                    if name in FILE_TOOLS and inp.get("file_path"):
                        bucket = FILE_TOOLS[name]
                        touch(bucket, str(inp["file_path"]), ts)
                        if bucket != "read":
                            timeline.append({"ts": ts, "kind": "edit" if bucket == "edited" else "write",
                                             "text": str(inp["file_path"])})
                    elif name in ("Grep", "Glob"):
                        label = str(inp.get("pattern") or inp.get("path") or "?")
                        if inp.get("pattern") and inp.get("path"):
                            label = f"{inp['pattern']}  in {inp['path']}"
                        touch("searched", label, ts)
                    elif name == "Skill" and inp.get("skill"):
                        if inp["skill"] not in skills:
                            skills.append(inp["skill"])
                        timeline.append({"ts": ts, "kind": "skill", "text": str(inp["skill"])})
                    elif name in ("Agent", "Task"):
                        agents.append({"type": str(inp.get("subagent_type") or "general-purpose"),
                                       "desc": _clip(inp.get("description", ""), 80)})
                        timeline.append({"ts": ts, "kind": "agent",
                                         "text": f"{agents[-1]['type']}: {agents[-1]['desc']}"})
                    elif name == "ExitPlanMode":
                        timeline.append({"ts": ts, "kind": "plan", "text": "plan presented for approval"})
                    elif name.startswith("mcp__"):
                        server = name.split("__")[1] if "__" in name[5:] else name[5:]
                        if server not in mcp:
                            mcp.append(server)

            elif etype == "summary":
                timeline.append({"ts": ts, "kind": "note", "text": "context compacted"})
        except (json.JSONDecodeError, ValueError, TypeError, AttributeError):
            continue

    total = len(timeline)
    timeline = timeline[-TIMELINE_CAP:]
    if timeline and total <= TIMELINE_CAP:
        timeline.insert(0, {"ts": timeline[0]["ts"], "kind": "note", "text": "session started"})

    def bucket_list(bucket):
        return sorted(files[bucket].values(), key=lambda f: f["last"], reverse=True)

    return {
        "head": {
            **head,
            "rules": rules_for_cwd(rec.get("cwd", "")),
            "files": {k: bucket_list(k) for k in files},
            "skills": skills, "agents": agents, "mcp": mcp,
        },
        "timeline": timeline,
        "timeline_total": total,
        "files": {k: bucket_list(k) for k in files},
    }
