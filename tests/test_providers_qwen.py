import json
import os
import time

import pytest

from engine.providers import qwen

SID = "11111111-2222-3333-4444-555555555555"

LINES = [
    {"sessionId": SID, "projectHash": "abc", "startTime": "2026-06-13T10:00:00.000Z", "kind": "chat"},
    {"id": "1", "timestamp": "2026-06-13T10:01:00Z", "type": "user", "content": "add a test"},
    {"id": "2", "timestamp": "2026-06-13T10:02:00Z", "type": "qwen", "content": "Done.",
     "model": "qwen3-coder-plus", "tokens": 4242, "toolCalls": [
         {"id": "a", "name": "write_file", "args": {"file_path": "C:\\proj\\test_x.py"}},
     ]},
]


@pytest.fixture
def qwen_dir(tmp_path, monkeypatch):
    root = tmp_path / "qwen"
    chats = root / "projects" / "C--proj" / "chats"
    chats.mkdir(parents=True)
    f = chats / f"{SID}.jsonl"
    f.write_text("\n".join(json.dumps(x) for x in LINES), encoding="utf-8")
    monkeypatch.setenv("FLEET_QWEN_DIR", str(root))
    return f


def _runtime(chat, pid):
    rt = chat.parent / (chat.stem + ".runtime.json")
    rt.write_text(json.dumps({
        "schema_version": 1, "pid": pid, "session_id": SID,
        "work_dir": "C:\\proj", "hostname": "host",
        "started_at": "2026-06-13T10:00:00.000Z", "qwen_version": "0.18.0",
    }), encoding="utf-8")
    return rt


def test_detect(qwen_dir):
    assert qwen.detect() is True


def test_live_session_uses_real_pid_not_inferred(qwen_dir):
    # this test process is genuinely alive -> Qwen reports TRUE liveness
    _runtime(qwen_dir, os.getpid())
    live, stopped = qwen.collect(int(time.time() * 1000))
    assert len(live) == 1 and not stopped
    rec = live[0]
    assert rec["provider"] == "qwen"
    assert rec["status"] == "active" and rec["live"] is True
    assert rec["live_inferred"] is False        # the differentiator: a read PID, not a guess
    assert rec["pid"] == os.getpid()
    assert rec["cwd"] == "C:\\proj"             # from runtime.json work_dir
    assert rec["model"] == "qwen3-coder-plus"
    assert rec["last_prompt"] == "add a test"
    assert rec["version"] == "0.18.0"


def test_dead_pid_session_is_stopped_not_live(qwen_dir):
    _runtime(qwen_dir, 999999)  # never a valid live PID
    _touch_recent(qwen_dir)
    live, stopped = qwen.collect(int(time.time() * 1000))
    assert not live and len(stopped) == 1
    assert stopped[0]["status"] == "stopped" and stopped[0]["live"] is False


def test_no_runtime_recent_session_is_stopped(qwen_dir):
    _touch_recent(qwen_dir)  # no runtime.json written
    live, stopped = qwen.collect(int(time.time() * 1000))
    assert not live and len(stopped) == 1


def test_deep_parse_shares_geminish(qwen_dir):
    d = qwen.deep_parse({"provider": "qwen", "cwd": "C:\\proj"}, qwen_dir)
    assert [f["path"] for f in d["head"]["files"]["written"]] == ["C:\\proj\\test_x.py"]
    assert d["head"]["model"] == "qwen3-coder-plus"
    kinds = [e["kind"] for e in d["timeline"]]
    assert "prompt" in kinds and "writing" in kinds and "write" in kinds


def _touch_recent(path):
    t = time.time() - 60
    os.utime(path, (t, t))
