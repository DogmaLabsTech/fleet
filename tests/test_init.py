import json
from pathlib import Path

import fleet
from engine import progress, roster


def test_init_writes_valid_template(tmp_path):
    fleet.init_repo(str(tmp_path))
    target = tmp_path / ".fleet" / "progress.json"
    assert target.is_file()
    data = json.loads(target.read_text(encoding="utf-8"))
    assert data["schema"] == "fleet-progress/1"
    assert isinstance(data["milestones"], list) and data["milestones"]


def test_template_is_readable_by_progress(tmp_path):
    fleet.init_repo(str(tmp_path))
    r = progress.progress_for(str(tmp_path), "x")
    assert r["source"] == "manifest"
    assert isinstance(r["percent"], int) and 0 <= r["percent"] <= 100
    assert {"verified", "attested", "in_progress"} <= set(r["split"])


def test_init_does_not_clobber_existing(tmp_path, capsys):
    d = tmp_path / ".fleet"
    d.mkdir()
    (d / "progress.json").write_text('{"keep": "me"}', encoding="utf-8")
    fleet.init_repo(str(tmp_path))
    out = capsys.readouterr().out
    assert "already exists" in out
    assert json.loads((d / "progress.json").read_text(encoding="utf-8")) == {"keep": "me"}


def test_main_init_command(tmp_path, monkeypatch):
    monkeypatch.setattr("sys.argv", ["fleet.py", "init", "--repo", str(tmp_path)])
    fleet.main()
    assert (tmp_path / ".fleet" / "progress.json").is_file()


def test_main_projects_add(tmp_path, monkeypatch, capsys):
    repo = tmp_path / "MyApp"
    repo.mkdir()
    pins = tmp_path / "projects.json"
    monkeypatch.setenv("FLEET_PROJECTS_JSON", str(pins))
    monkeypatch.setattr("sys.argv", ["fleet.py", "projects", "add", str(repo)])
    fleet.main()
    out = capsys.readouterr().out
    assert "my-app" in out
    saved = json.loads(pins.read_text(encoding="utf-8"))
    assert saved["my-app"] == str(repo.resolve())
