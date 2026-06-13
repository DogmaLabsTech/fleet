import json
from pathlib import Path

import engine.collector as collector


def test_cwd_to_slug_known_mappings():
    assert collector.cwd_to_slug(r"C:\projects\my-vault") == "C--projects-my-vault"
    assert collector.cwd_to_slug(r"C:\projects\notes_os") == "C--projects-notes-os"
    assert collector.cwd_to_slug(r"C:\Users\alice\.claude") == "C--Users-alice--claude"


def test_parse_tail_extracts_fields():
    lines = [
        json.dumps({"type": "ai-title", "aiTitle": "My Session", "timestamp": "2026-06-11T01:00:00Z"}),
        json.dumps({"type": "user", "message": {"role": "user", "content": "do the thing"},
                    "gitBranch": "main", "timestamp": "2026-06-11T01:00:01Z"}),
        json.dumps({"type": "assistant", "timestamp": "2026-06-11T01:00:02Z", "message": {
            "role": "assistant", "model": "claude-fable-5",
            "usage": {"input_tokens": 5, "cache_read_input_tokens": 1000, "cache_creation_input_tokens": 10},
            "content": [{"type": "tool_use", "name": "Bash", "input": {"command": "ls", "description": "List files"}}]}}),
        json.dumps({"type": "assistant", "timestamp": "2026-06-11T01:00:03Z", "message": {
            "role": "assistant", "model": "<synthetic>", "content": [{"type": "text", "text": "API Error"}]}}),
    ]
    info = collector.parse_tail(lines)
    assert info["title"] == "My Session"
    assert info["last_prompt"] == "do the thing"
    assert info["activity"] == "writing: API Error"
    assert info["model"] == "claude-fable-5"
    assert info["branch"] == "main"
    assert info["ctx_tokens"] == 1015


def test_parse_tail_ignores_tool_results_and_meta():
    lines = [
        json.dumps({"type": "user", "message": {"role": "user", "content": "real prompt"}}),
        json.dumps({"type": "user", "message": {"role": "user",
                    "content": [{"type": "tool_result", "content": "big output"}]}}),
        json.dumps({"type": "user", "isMeta": True, "message": {"role": "user", "content": "meta noise"}}),
    ]
    assert collector.parse_tail(lines)["last_prompt"] == "real prompt"


def test_pid_match_lenient_accepts_unreadable(monkeypatch):
    monkeypatch.setattr(collector, "proc_creation_unix_ms", lambda pid: -1)
    assert collector.pid_matches_session(1234, 0, strict=False) is True
    assert collector.pid_matches_session(1234, 0) is False  # strict default refuses


def test_pid_match_dead_refused_in_both_modes(monkeypatch):
    monkeypatch.setattr(collector, "proc_creation_unix_ms", lambda pid: None)
    assert collector.pid_matches_session(1234, 0, strict=False) is False
    assert collector.pid_matches_session(1234, 0) is False


def test_collect_against_fixture_claude_dir(fixture_claude_dir):
    data = collector.collect()
    assert data["counts"]["live"] == 0  # fixture session PID is dead
    # dead-but-recent session lands in stopped_recent
    assert len(data["stopped_recent"]) == 1
