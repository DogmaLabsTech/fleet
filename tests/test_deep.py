import json
from pathlib import Path

from engine import deep

FIXTURE = Path(__file__).parent / "fixtures" / "transcript.jsonl"


def parse():
    return deep.parse_full(FIXTURE, {"cwd": "C:\\projects\\my-vault"})


def test_head_files_buckets():
    head = parse()["head"]
    reads = [f["path"] for f in head["files"]["read"]]
    assert "C:\\projects\\my-vault\\wiki\\shared\\Quality Bar.md" in reads
    edits = [f["path"] for f in head["files"]["edited"]]
    assert "C:\\projects\\my-vault\\wiki\\projects\\Kitchen Compass.md" in edits
    writes = [f["path"] for f in head["files"]["written"]]
    assert "C:\\projects\\tool\\out.txt" in writes
    assert head["files"]["searched"][0]["path"].startswith("widget")


def test_head_skills_agents_mcp_ctx():
    head = parse()["head"]
    assert head["skills"] == ["superpowers:brainstorming"]
    assert head["agents"] == [{"type": "Explore", "desc": "Map the data dir"}]
    assert head["mcp"] == ["alpaca"]
    assert head["ctx_tokens"] == 120052  # latest usage: 120000+50+2
    assert head["model"] == "claude-fable-5"
    assert head["branch"] == "main"


def test_timeline_order_and_kinds():
    tl = parse()["timeline"]
    kinds = [e["kind"] for e in tl]
    assert kinds[0] == "note" and tl[0]["text"] == "session started"
    assert kinds[1] == "prompt"
    assert "edit" in kinds and "write" in kinds and "agent" in kinds
    assert "skill" in kinds and "error" in kinds
    # the summary noise line becomes a compaction note
    assert any(e["kind"] == "note" and e["text"] == "context compacted" for e in tl)
    # chronological (oldest first)
    assert tl == sorted(tl, key=lambda e: e["ts"])
    err = next(e for e in tl if e["kind"] == "error")
    assert "connection refused" in err["text"]
    assert not any("<command-name>" in e["text"] for e in tl if e["kind"] == "prompt")


def test_files_dedupe_and_count():
    files = parse()["files"]
    qb = next(f for f in files["read"] if "Quality Bar" in f["path"])
    assert qb["count"] == 1


def test_rules_for_cwd(tmp_path):
    (tmp_path / "CLAUDE.md").write_text("x", encoding="utf-8")
    sub = tmp_path / "proj"
    sub.mkdir()
    (sub / "CLAUDE.md").write_text("y", encoding="utf-8")
    rules = deep.rules_for_cwd(str(sub))
    assert str(sub / "CLAUDE.md") in rules and str(tmp_path / "CLAUDE.md") in rules


def test_malformed_lines_never_raise(tmp_path):
    bad = tmp_path / "bad.jsonl"
    bad.write_text('{"type":"user"\nnot json at all\n{"weird": []}\n', encoding="utf-8")
    out = deep.parse_full(bad, {"cwd": "C:\\nope"})
    assert out["head"]["files"]["read"] == []
    assert out["timeline"] == []


def test_timeline_cap(tmp_path):
    big = tmp_path / "big.jsonl"
    lines = [json.dumps({"type": "user", "timestamp": f"2026-06-11T10:{i // 60:02d}:{i % 60:02d}Z",
                         "message": {"role": "user", "content": f"prompt {i}"}})
             for i in range(400)]
    big.write_text("\n".join(lines), encoding="utf-8")
    out = deep.parse_full(big, {"cwd": "C:\\nope"})
    assert out["timeline_total"] == 400
    assert len(out["timeline"]) == 300
    assert out["timeline"][0]["text"] == "prompt 100"  # capped: no session-started note
    assert not any(e["text"] == "session started" for e in out["timeline"])
