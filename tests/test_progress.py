import json
from pathlib import Path
from engine import progress


def _write(repo, milestones):
    d = Path(repo) / ".fleet"
    d.mkdir(parents=True, exist_ok=True)
    (d / "progress.json").write_text(json.dumps({"schema": "fleet-progress/1", "milestones": milestones}))


def test_no_manifest_is_empty(tmp_path):
    r = progress.progress_for(tmp_path, "x")
    assert r["percent"] == 0 and r["source"] == "none" and r["milestones"] == []


def test_done_with_passing_verify_is_verified(tmp_path):
    (tmp_path / "ok.txt").write_text("x")
    _write(tmp_path, [{"name": "A", "weight": 1, "status": "done",
                       "provenance": "c1", "verify": {"type": "file", "path": "ok.txt"}}])
    r = progress.progress_for(tmp_path, "x")
    assert r["milestones"][0]["confidence"] == "verified"
    assert r["split"]["verified"] == 100 and r["percent"] == 100


def test_done_with_failing_verify_is_contradicted(tmp_path):
    _write(tmp_path, [{"name": "A", "weight": 1, "status": "done",
                       "provenance": "c1", "verify": {"type": "file", "path": "missing.txt"}}])
    r = progress.progress_for(tmp_path, "x")
    assert r["milestones"][0]["confidence"] == "contradicted"
    assert r["flags"]["contradicted"] == 1


def test_done_with_provenance_only_is_attested(tmp_path):
    _write(tmp_path, [{"name": "A", "weight": 1, "status": "done", "provenance": "PR #9"}])
    r = progress.progress_for(tmp_path, "x")
    assert r["milestones"][0]["confidence"] == "attested"
    assert r["split"]["attested"] == 100


def test_done_with_nothing_is_uncited(tmp_path):
    _write(tmp_path, [{"name": "A", "weight": 1, "status": "done"}])
    r = progress.progress_for(tmp_path, "x")
    assert r["milestones"][0]["confidence"] == "uncited"
    assert r["flags"]["uncited"] == 1


def test_in_progress_counts_half(tmp_path):
    _write(tmp_path, [{"name": "A", "weight": 1, "status": "done", "provenance": "c"},
                      {"name": "B", "weight": 1, "status": "in-progress"}])
    r = progress.progress_for(tmp_path, "x")
    assert r["percent"] == 75  # 100*(1 + 0.5)/2
