"""Qwen Code provider.

Qwen Code (a Gemini-CLI fork) is the one non-Claude CLI that writes a per-session
runtime sidecar for external observers:
    ~/.qwen/projects/<project_id>/chats/<sessionId>.jsonl          transcript
    ~/.qwen/projects/<project_id>/chats/<sessionId>.runtime.json   {pid, work_dir, ...}
so Fleet can report TRUE liveness (PID check) for Qwen, like Claude Code.

Path overrides (first match wins): FLEET_QWEN_DIR, QWEN_HOME, ~/.qwen
"""

import os
from pathlib import Path


ID = "qwen"
LABEL = "Qwen Code"


def qwen_home():
    return Path(os.environ.get("FLEET_QWEN_DIR")
                or os.environ.get("QWEN_HOME")
                or (Path.home() / ".qwen"))


def projects_dir():
    return qwen_home() / "projects"


def detect():
    return projects_dir().exists()


def collect(now_ms):
    # Implemented in the Qwen collect/deep chunk.
    return [], []


def find_transcript(rec):
    t = rec.get("transcript")
    return Path(t) if t else None


def deep_parse(rec, transcript):
    return None
