"""Claude Code provider — the reference implementation.

The Claude-specific gathering and transcript parsing still live in
engine.collector / engine.deep (battle-tested, directly unit-covered); this
module is the thin provider face over them so the merger can treat Claude like
any other provider.
"""

from .. import collector, deep

ID = "claude"
LABEL = "Claude Code"


def detect():
    return collector.sessions_dir().exists()


def collect(now_ms):
    return collector.collect_claude(now_ms)


def find_transcript(rec):
    return collector.find_transcript(rec.get("cwd", ""), rec["session_id"])


def deep_parse(rec, transcript):
    return deep.parse_full(transcript, rec)
