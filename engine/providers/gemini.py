"""Google Gemini CLI provider.

Reads ~/.gemini/tmp/<project>/chats/session-*.jsonl (read-only). The <project>
dir name is a friendly label; ~/.gemini/projects.json maps it back to the real
cwd. Gemini writes no live status/PID file, so liveness is inferred from
transcript freshness (live_inferred=True). The chat JSONL schema is shared with
Qwen Code — see _geminish.

Path overrides (first match wins): FLEET_GEMINI_DIR, GEMINI_DATA_DIR/.., ~/.gemini
"""

import json
import os
from pathlib import Path

from . import _geminish, base

ID = "gemini"
LABEL = "Gemini CLI"

STOPPED_WINDOW_MS = 30 * 60 * 1000


def gemini_home():
    if os.environ.get("FLEET_GEMINI_DIR"):
        return Path(os.environ["FLEET_GEMINI_DIR"])
    data = os.environ.get("GEMINI_DATA_DIR")
    if data:
        return Path(data).parent  # GEMINI_DATA_DIR is the tmp root (default ~/.gemini/tmp)
    return Path.home() / ".gemini"


def tmp_dir():
    return gemini_home() / "tmp"


def detect():
    return tmp_dir().exists()


def _cwd_by_project():
    """{project-label: cwd} inverted from ~/.gemini/projects.json ({cwd: label})."""
    try:
        data = json.loads((gemini_home() / "projects.json").read_text(encoding="utf-8"))
        return {label: cwd for cwd, label in (data.get("projects") or {}).items()}
    except (OSError, ValueError):
        return {}


def collect(now_ms):
    if not tmp_dir().exists():
        return [], []
    cwd_map = _cwd_by_project()
    live, stopped = [], []
    for chat in tmp_dir().glob("*/chats/session-*.jsonl"):
        try:
            mtime_ms = int(chat.stat().st_mtime * 1000)
        except OSError:
            continue
        if now_ms - mtime_ms > STOPPED_WINDOW_MS:
            continue
        project = chat.parent.parent.name
        cwd = cwd_map.get(project, "")
        meta = _geminish.session_meta(chat)
        status, alive = base.infer_status(mtime_ms, now_ms)
        s = _geminish.summarize(chat)
        rec = base.make_record(
            provider="gemini",
            session_id=meta.get("sessionId") or chat.stem,
            cwd=cwd,
            project=project or base.project_of(cwd),
            status=status,
            kind="interactive",
            model=s["model"],
            started_at=base.iso_ms(meta.get("startTime")) or mtime_ms,
            updated_at=mtime_ms,
            live=alive,
            live_inferred=True,
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
                                rules_file="GEMINI.md",
                                rules_global=gemini_home() / "GEMINI.md")
