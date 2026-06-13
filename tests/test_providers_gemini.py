import json
import os
import time

import pytest

from engine.providers import gemini

SID = "75cc8c6c-bfb9-4fd2-9f87-968d98cece77"

LINES = [
    {"sessionId": SID, "projectHash": "abc", "startTime": "2026-05-27T21:24:25.169Z",
     "lastUpdated": "2026-05-27T21:30:00.000Z", "kind": "chat"},
    {"id": "1", "timestamp": "2026-05-27T21:25:00Z", "type": "user", "content": "refactor the parser"},
    {"id": "2", "timestamp": "2026-05-27T21:26:00Z", "type": "gemini", "content": "Editing now.",
     "model": "gemini-2.5-pro", "tokens": 12345, "toolCalls": [
         {"id": "a", "name": "read_file", "args": {"absolute_path": "C:\\proj\\src\\parser.py"}},
         {"id": "b", "name": "write_file", "args": {"file_path": "C:\\proj\\src\\new.py"}},
         {"id": "c", "name": "replace", "args": {"file_path": "C:\\proj\\src\\parser.py"}},
         {"id": "d", "name": "run_shell_command", "args": {"command": "grep -rn TODO src/"}},
         {"id": "e", "name": "activate_skill", "args": {"name": "onboarding-guide"}},
     ]},
    {"$set": {"lastUpdated": "2026-05-27T21:30:00Z"}},  # state line must be skipped
]


@pytest.fixture
def gemini_dir(tmp_path, monkeypatch):
    root = tmp_path / "gemini"
    chats = root / "tmp" / "myproj" / "chats"
    chats.mkdir(parents=True)
    f = chats / f"session-2026-05-27T21-24-{SID[:8]}.jsonl"
    f.write_text("\n".join(json.dumps(x) for x in LINES), encoding="utf-8")
    (root / "projects.json").write_text(
        json.dumps({"projects": {"c:\\proj": "myproj"}}), encoding="utf-8")
    monkeypatch.setenv("FLEET_GEMINI_DIR", str(root))
    return f


def _touch(path, age_s):
    t = time.time() - age_s
    os.utime(path, (t, t))


def test_detect(gemini_dir):
    assert gemini.detect() is True


def test_collect_maps_cwd_from_projects_json(gemini_dir):
    _touch(gemini_dir, 30)
    live, stopped = gemini.collect(int(time.time() * 1000))
    assert len(live) == 1 and not stopped
    rec = live[0]
    assert rec["provider"] == "gemini"
    assert rec["session_id"] == SID
    assert rec["project"] == "myproj"
    assert rec["cwd"] == "c:\\proj"          # recovered from projects.json
    assert rec["model"] == "gemini-2.5-pro"
    assert rec["last_prompt"] == "refactor the parser"
    assert rec["ctx_tokens"] == 12345
    assert rec["status"] == "active" and rec["live"] is True
    assert rec["live_inferred"] is True       # no PID file -> inferred


def test_collect_stale_is_stopped(gemini_dir):
    _touch(gemini_dir, 10 * 60)
    live, stopped = gemini.collect(int(time.time() * 1000))
    assert not live and len(stopped) == 1 and stopped[0]["status"] == "stopped"


def test_deep_files_buckets_and_skills(gemini_dir):
    rec = {"provider": "gemini", "cwd": "c:\\proj"}
    d = gemini.deep_parse(rec, gemini_dir)
    head = d["head"]
    assert [f["path"] for f in head["files"]["read"]] == ["C:\\proj\\src\\parser.py"]
    assert [f["path"] for f in head["files"]["written"]] == ["C:\\proj\\src\\new.py"]
    assert [f["path"] for f in head["files"]["edited"]] == ["C:\\proj\\src\\parser.py"]
    assert head["files"]["searched"] and "TODO" in head["files"]["searched"][0]["path"]
    assert head["skills"] == ["onboarding-guide"]
    assert head["model"] == "gemini-2.5-pro"
    assert head["ctx_tokens"] == 12345


def test_deep_timeline_kinds(gemini_dir):
    d = gemini.deep_parse({"provider": "gemini", "cwd": "c:\\proj"}, gemini_dir)
    kinds = [e["kind"] for e in d["timeline"]]
    assert kinds[0] == "note"
    assert "prompt" in kinds and "writing" in kinds
    assert "write" in kinds and "edit" in kinds and "skill" in kinds
