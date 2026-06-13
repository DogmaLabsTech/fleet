import json
import os

import psutil

from engine import collector, roster


def _pins(tmp_path, monkeypatch, mapping):
    pins = tmp_path / "projects.json"
    pins.write_text(json.dumps(mapping), encoding="utf-8")
    monkeypatch.setenv("FLEET_PROJECTS_JSON", str(pins))
    return pins


def _empty_claude(tmp_path, monkeypatch):
    """A claude dir with no sessions, wired via FLEET_CLAUDE_DIR."""
    claude = tmp_path / "claude"
    (claude / "sessions").mkdir(parents=True)
    (claude / "history.jsonl").write_text("", encoding="utf-8")
    monkeypatch.setenv("FLEET_CLAUDE_DIR", str(claude))
    return claude


def _live_session(claude, cwd, session_id="live-1"):
    """Write a session file the collector will treat as live: this process's PID,
    startedAt pinned to this process's real creation time (within the PID-match
    tolerance)."""
    created_ms = int(psutil.Process(os.getpid()).create_time() * 1000)
    (claude / "sessions" / f"{session_id}.json").write_text(json.dumps({
        "pid": os.getpid(), "sessionId": session_id, "cwd": cwd,
        "status": "busy", "kind": "interactive",
        "startedAt": created_ms, "updatedAt": created_ms,
    }), encoding="utf-8")


def test_no_sessions_no_pins_is_empty(tmp_path, monkeypatch):
    _empty_claude(tmp_path, monkeypatch)
    monkeypatch.setenv("FLEET_PROJECTS_JSON", str(tmp_path / "absent.json"))
    out = roster.roll_up()
    assert out["projects"] == []
    assert "generated_at" in out


def test_pins_become_projects(tmp_path, monkeypatch):
    _empty_claude(tmp_path, monkeypatch)
    repo = tmp_path / "Some_Repo"
    repo.mkdir()
    _pins(tmp_path, monkeypatch, {"some-repo": str(repo)})
    out = roster.roll_up()
    slugs = [p["slug"] for p in out["projects"]]
    assert "some-repo" in slugs
    p = next(p for p in out["projects"] if p["slug"] == "some-repo")
    assert p["repo_root"] == str(repo)


def test_session_cwd_unioned_in(tmp_path, monkeypatch):
    claude = _empty_claude(tmp_path, monkeypatch)
    repo = tmp_path / "MyApp"
    (repo / ".git").mkdir(parents=True)  # marker so repo_root_for resolves to repo
    _live_session(claude, str(repo))
    _pins(tmp_path, monkeypatch, {})
    out = roster.roll_up()
    expected = collector.slug_for(str(repo))  # "my-app"
    slugs = [p["slug"] for p in out["projects"]]
    assert expected in slugs


def test_roll_up_shape_has_no_internal_keys(tmp_path, monkeypatch):
    claude = _empty_claude(tmp_path, monkeypatch)
    repo = tmp_path / "MyApp"
    (repo / ".git").mkdir(parents=True)
    _live_session(claude, str(repo))
    _pins(tmp_path, monkeypatch, {})
    out = roster.roll_up()
    assert out["projects"], "expected the live session to yield a project"
    p = out["projects"][0]
    assert set(p.keys()) == {"slug", "title", "repo_root", "progress", "team"}
    assert set(p["progress"].keys()) == {"percent", "source", "split", "flags"}
    assert set(p["team"].keys()) == {"sessions", "busy", "waiting"}
    for banned in ("has_agent", "relay", "relay_active", "crew_batch", "active_goal",
                   "visual", "components", "goal"):
        assert banned not in p
        assert banned not in p["team"]


def test_team_counts_busy(tmp_path, monkeypatch):
    claude = _empty_claude(tmp_path, monkeypatch)
    repo = tmp_path / "MyApp"
    (repo / ".git").mkdir(parents=True)
    _live_session(claude, str(repo))
    _pins(tmp_path, monkeypatch, {})
    out = roster.roll_up()
    p = next(p for p in out["projects"] if p["slug"] == "my-app")
    assert p["team"]["sessions"] == 1
    assert p["team"]["busy"] == 1
    assert p["team"]["waiting"] == 0


def test_project_detail_unknown_is_none(tmp_path, monkeypatch):
    _empty_claude(tmp_path, monkeypatch)
    _pins(tmp_path, monkeypatch, {})
    assert roster.project_detail("definitely-not-a-real-slug") is None


def test_project_detail_carries_progress_and_team(tmp_path, monkeypatch):
    claude = _empty_claude(tmp_path, monkeypatch)
    repo = tmp_path / "MyApp"
    (repo / ".git").mkdir(parents=True)
    _live_session(claude, str(repo))
    _pins(tmp_path, monkeypatch, {})
    detail = roster.project_detail("my-app")
    assert detail is not None
    assert detail["slug"] == "my-app"
    assert "progress" in detail
    assert isinstance(detail["team"]["sessions"], list)
    for banned in ("has_agent", "visual", "actions", "relay_active", "crew_batch", "active_goal"):
        assert banned not in detail
        assert banned not in detail["team"]
