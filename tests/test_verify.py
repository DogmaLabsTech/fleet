import json
from engine import verify


def test_file_exists_true(tmp_path):
    (tmp_path / "cov.lcov").write_text("x")
    assert verify.check({"type": "file", "path": "cov.lcov"}, tmp_path) is True


def test_file_missing_false(tmp_path):
    assert verify.check({"type": "file", "path": "nope.lcov"}, tmp_path) is False


def test_glob_match(tmp_path):
    (tmp_path / "reports").mkdir()
    (tmp_path / "reports" / "a.xml").write_text("x")
    assert verify.check({"type": "glob", "pattern": "reports/*.xml"}, tmp_path) is True
    assert verify.check({"type": "glob", "pattern": "reports/*.json"}, tmp_path) is False


def test_json_pointer_equals(tmp_path):
    (tmp_path / "r.json").write_text(json.dumps({"summary": {"passed": True}}))
    assert verify.check({"type": "json", "path": "r.json", "pointer": "/summary/passed", "equals": True}, tmp_path) is True
    assert verify.check({"type": "json", "path": "r.json", "pointer": "/summary/passed", "equals": False}, tmp_path) is False


def test_json_min(tmp_path):
    (tmp_path / "r.json").write_text(json.dumps({"coverage": 87}))
    assert verify.check({"type": "json", "path": "r.json", "pointer": "/coverage", "min": 80}, tmp_path) is True
    assert verify.check({"type": "json", "path": "r.json", "pointer": "/coverage", "min": 90}, tmp_path) is False


def test_json_missing_file_is_false(tmp_path):
    assert verify.check({"type": "json", "path": "absent.json", "pointer": "/x"}, tmp_path) is False


def test_json_bad_pointer_is_false(tmp_path):
    (tmp_path / "r.json").write_text(json.dumps({"a": 1}))
    assert verify.check({"type": "json", "path": "r.json", "pointer": "/missing"}, tmp_path) is False


def test_sandbox_escape_is_none(tmp_path):
    assert verify.check({"type": "file", "path": "../../etc/passwd"}, tmp_path) is None


def test_unknown_or_malformed_is_none(tmp_path):
    assert verify.check(None, tmp_path) is None
    assert verify.check({"type": "weird"}, tmp_path) is None
    assert verify.check({"type": "file"}, tmp_path) is None  # no path
