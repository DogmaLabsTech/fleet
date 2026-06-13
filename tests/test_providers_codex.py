import json
import os
import time
from pathlib import Path

import pytest

from engine.providers import codex


def _rollout(lines):
    return "\n".join(json.dumps(x) for x in lines)


SESSION_ID = "019eadc6-cc6b-7230-a79e-45c7f6303449"

LINES = [
    {"timestamp": "2026-06-09T19:05:53.469Z", "type": "session_meta",
     "payload": {"id": SESSION_ID, "timestamp": "2026-06-09T19:05:53.469Z",
                 "cwd": "C:\\projects\\widget", "cli_version": "0.137.0", "model": "gpt-5-codex",
                 "model_provider": "openai"}},
    {"timestamp": "2026-06-09T19:06:00Z", "type": "event_msg",
     "payload": {"type": "user_message", "message": "refactor the parser"}},
    # response_item carries the same user prompt — must dedupe to one timeline entry
    {"timestamp": "2026-06-09T19:06:00Z", "type": "response_item",
     "payload": {"type": "message", "role": "user",
                 "content": [{"type": "input_text", "text": "refactor the parser"}]}},
    {"timestamp": "2026-06-09T19:06:05Z", "type": "response_item",
     "payload": {"type": "message", "role": "assistant",
                 "content": [{"type": "output_text", "text": "On it — editing now."}]}},
    {"timestamp": "2026-06-09T19:06:07Z", "type": "response_item",
     "payload": {"type": "function_call", "name": "apply_patch",
                 "arguments": "*** Begin Patch\n*** Update File: src/parser.py\n@@\n-old\n+new\n"
                              "*** Add File: src/new_mod.py\n+hello\n*** End Patch"}},
    {"timestamp": "2026-06-09T19:06:09Z", "type": "response_item",
     "payload": {"type": "local_shell_call", "action": {"command": ["grep", "-rn", "TODO", "src/"]}}},
    {"timestamp": "2026-06-09T19:06:11Z", "type": "response_item",
     "payload": {"type": "local_shell_call", "action": {"command": ["cat", "src/parser.py"]}}},
    {"timestamp": "2026-06-09T19:06:12Z", "type": "event_msg",
     "payload": {"type": "token_count",
                 "info": {"total_token_usage": {"total_tokens": 18445}, "model_context_window": 272000}}},
]


@pytest.fixture
def codex_dir(tmp_path, monkeypatch):
    """Synthetic ~/.codex with one fresh rollout session."""
    root = tmp_path / "codex"
    day = root / "sessions" / "2026" / "06" / "09"
    day.mkdir(parents=True)
    f = day / f"rollout-2026-06-09T15-05-53-{SESSION_ID}.jsonl"
    f.write_text(_rollout(LINES), encoding="utf-8")
    monkeypatch.setenv("FLEET_CODEX_DIR", str(root))
    return f


def _touch(path, age_s):
    t = time.time() - age_s
    os.utime(path, (t, t))


def test_detect(codex_dir):
    assert codex.detect() is True


def test_collect_fresh_session_is_inferred_active(codex_dir):
    _touch(codex_dir, 30)  # written 30s ago
    now = int(time.time() * 1000)
    live, stopped = codex.collect(now)
    assert len(live) == 1 and not stopped
    rec = live[0]
    assert rec["provider"] == "codex"
    assert rec["session_id"] == SESSION_ID
    assert rec["status"] == "active" and rec["live"] is True
    assert rec["live_inferred"] is True            # honesty: not a read status
    assert rec["project"] == "widget"
    assert rec["model"] == "gpt-5-codex"
    assert rec["last_prompt"] == "refactor the parser"
    assert rec["ctx_tokens"] == 18445
    assert rec["transcript"] == str(codex_dir)


def test_collect_stale_session_is_stopped(codex_dir):
    _touch(codex_dir, 10 * 60)  # 10 min ago: past active window, within recents
    now = int(time.time() * 1000)
    live, stopped = codex.collect(now)
    assert not live and len(stopped) == 1
    assert stopped[0]["status"] == "stopped"


def test_collect_ancient_session_dropped(codex_dir):
    _touch(codex_dir, 60 * 60)  # 1h ago: past the recents window entirely
    now = int(time.time() * 1000)
    live, stopped = codex.collect(now)
    assert not live and not stopped


def test_deep_timeline_dedupes_and_orders(codex_dir):
    rec = {"provider": "codex", "cwd": "C:\\projects\\widget"}
    d = codex.deep_parse(rec, codex_dir)
    tl = d["timeline"]
    assert tl[0]["kind"] == "note" and tl[0]["text"] == "session started"
    prompts = [e for e in tl if e["kind"] == "prompt"]
    assert len(prompts) == 1 and prompts[0]["text"] == "refactor the parser"  # deduped
    assert any(e["kind"] == "writing" for e in tl)
    assert any(e["kind"] == "edit" and e["text"] == "src/parser.py" for e in tl)
    assert any(e["kind"] == "write" and e["text"] == "src/new_mod.py" for e in tl)


def test_deep_files_buckets_from_patch_and_shell(codex_dir):
    rec = {"provider": "codex", "cwd": "C:\\projects\\widget"}
    head = codex.deep_parse(rec, codex_dir)["head"]
    assert [f["path"] for f in head["files"]["edited"]] == ["src/parser.py"]
    assert [f["path"] for f in head["files"]["written"]] == ["src/new_mod.py"]
    assert [f["path"] for f in head["files"]["read"]] == ["src/parser.py"]   # from `cat`
    assert head["files"]["searched"] and "TODO" in head["files"]["searched"][0]["path"]
    assert head["ctx_tokens"] == 18445
    assert head["ctx_window"] == 272000
    assert head["model"] == "gpt-5-codex"


def test_deep_missing_transcript_warns():
    rec = {"provider": "codex", "cwd": "C:\\nope"}
    d = codex.deep_parse(rec, Path("C:\\nope\\does-not-exist.jsonl"))
    assert d["timeline"] == []
    assert any("unreadable" in w for w in d["head"]["warnings"])


def test_malformed_lines_never_raise(tmp_path):
    bad = tmp_path / "rollout-x.jsonl"
    bad.write_text('{"type":"session_meta"\nnot json\n{"weird": []}\n', encoding="utf-8")
    d = codex.deep_parse({"cwd": "C:\\nope"}, bad)
    assert d["timeline"] == [] and d["head"]["files"]["read"] == []
