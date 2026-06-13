"""OpenAI Codex CLI provider.

Reads ~/.codex/sessions/YYYY/MM/DD/rollout-<ts>-<uuid>.jsonl (read-only).
Codex writes no live status/PID file, so liveness is inferred from transcript
freshness (see base.infer_status).

Path overrides (first match wins): FLEET_CODEX_DIR, CODEX_HOME, ~/.codex
"""

import os
from pathlib import Path


ID = "codex"
LABEL = "Codex CLI"


def codex_home():
    return Path(os.environ.get("FLEET_CODEX_DIR")
                or os.environ.get("CODEX_HOME")
                or (Path.home() / ".codex"))


def sessions_dir():
    return codex_home() / "sessions"


def detect():
    return sessions_dir().exists()


def collect(now_ms):
    # Implemented in the Codex collect/deep chunk.
    return [], []


def find_transcript(rec):
    t = rec.get("transcript")
    return Path(t) if t else None


def deep_parse(rec, transcript):
    return None
