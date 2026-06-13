import json
import shutil
import time
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def fixture_claude_dir(tmp_path, monkeypatch):
    """Synthetic ~/.claude with one dead-PID session + its transcript."""
    claude = tmp_path / "claude"
    sessions = claude / "sessions"
    proj = claude / "projects" / "C--projects-my-vault"
    sessions.mkdir(parents=True)
    proj.mkdir(parents=True)
    now_ms = int(time.time() * 1000)
    (sessions / "999999.json").write_text(json.dumps({
        "pid": 999999,  # 999999 is not a multiple of 4, so it can never be a valid Windows PID; OpenProcess fails with error 87, never error 5
        "sessionId": "fix-1", "cwd": "C:\\projects\\my-vault",
        "status": "busy", "kind": "interactive", "version": "2.1.174",
        "startedAt": now_ms - 60_000, "updatedAt": now_ms - 5_000,
    }), encoding="utf-8")
    # Generate a transcript using the tmp vault path so /vault route resolves pages
    # on any OS. The fixture stores JSON-escaped Windows paths; rewrite the vault
    # root to the tmp vault and normalise separators to '/' (pathlib resolves
    # forward slashes on Windows too). test_deep.py uses the static fixture directly
    # and is unaffected.
    native = (tmp_path / "my-vault").as_posix()
    static = (FIXTURES / "transcript.jsonl").read_text(encoding="utf-8")
    dynamic = static.replace("C:\\\\projects\\\\my-vault", native).replace("\\\\", "/")
    (proj / "fix-1.jsonl").write_text(dynamic, encoding="utf-8")
    (claude / "history.jsonl").write_text("", encoding="utf-8")
    monkeypatch.setenv("FLEET_CLAUDE_DIR", str(claude))
    return claude


@pytest.fixture
def fixture_vault(tmp_path, monkeypatch):
    """Synthetic Obsidian vault + registry json."""
    vault = tmp_path / "my-vault"
    wiki = vault / "wiki" / "shared"
    wiki.mkdir(parents=True)
    (wiki / "Quality Bar.md").write_text(
        "Links to [[Project Atlas]] and [[Missing Page]].", encoding="utf-8")
    proj_dir = vault / "wiki" / "projects"
    proj_dir.mkdir(parents=True)
    (proj_dir / "Project Atlas.md").write_text(
        "See [[Quality Bar]].", encoding="utf-8")
    registry = tmp_path / "obsidian.json"
    registry.write_text(json.dumps({
        "vaults": {"abc123def456": {"path": str(vault), "ts": 0}, "zzz999decoy": {"path": "C:\\somewhere\\else", "ts": 0}}
    }), encoding="utf-8")
    monkeypatch.setenv("FLEET_VAULT_DIR", str(vault))
    monkeypatch.setenv("FLEET_OBSIDIAN_JSON", str(registry))
    return vault
