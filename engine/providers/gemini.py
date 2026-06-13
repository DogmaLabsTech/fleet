"""Google Gemini CLI provider.

Gemini's on-disk log format is internal and has churned (per-project JSON
rewritten each turn -> in-progress JSONL migration), so this adapter is
best-effort and tolerant of more than one layout. No live status/PID file, so
liveness is inferred from transcript freshness.

Path overrides (first match wins): FLEET_GEMINI_DIR, GEMINI_DATA_DIR/.., ~/.gemini
"""

import os
from pathlib import Path


ID = "gemini"
LABEL = "Gemini CLI"


def gemini_home():
    if os.environ.get("FLEET_GEMINI_DIR"):
        return Path(os.environ["FLEET_GEMINI_DIR"])
    data = os.environ.get("GEMINI_DATA_DIR")
    if data:
        # GEMINI_DATA_DIR points at the tmp data root (default ~/.gemini/tmp)
        return Path(data).parent
    return Path.home() / ".gemini"


def tmp_dir():
    return gemini_home() / "tmp"


def detect():
    return tmp_dir().exists()


def collect(now_ms):
    # Implemented in the Gemini collect/deep chunk.
    return [], []


def find_transcript(rec):
    t = rec.get("transcript")
    return Path(t) if t else None


def deep_parse(rec, transcript):
    return None
