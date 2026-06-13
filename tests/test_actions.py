import subprocess
import time

from engine import actions, vault


def test_kill_refuses_on_pid_mismatch():
    # PID 4 is the Windows System process - startedAt of "now" can't match its creation time;
    # it may also be unreadable (access denied), which is equally a valid refusal
    res = actions.kill_session(4, int(time.time() * 1000))
    assert res["ok"] is False
    assert ("mismatch" in res["message"] or "not alive" in res["message"]
            or "unverifiable" in res["message"])


def test_kill_terminates_throwaway_process():
    p = subprocess.Popen(["ping", "-n", "30", "127.0.0.1"],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    started_ms = int(time.time() * 1000)
    res = actions.kill_session(p.pid, started_ms)
    assert res["ok"] is True
    assert isinstance(p.wait(timeout=10), int)


def test_open_obsidian_builds_uri_without_launching(fixture_vault, monkeypatch):
    launched = []
    monkeypatch.setattr(actions, "_launch", lambda target: launched.append(target))
    res = actions.open_obsidian("wiki/shared/Quality Bar.md")
    assert res["ok"] is True
    assert launched == ["obsidian://open?vault=abc123def456&file=wiki%2Fshared%2FQuality%20Bar"]


def test_open_path_rejects_missing(monkeypatch):
    monkeypatch.setattr(actions, "_launch", lambda target: None)
    assert actions.open_path("C:\\definitely\\not\\real\\x.txt")["ok"] is False


def test_dispatch_rejects_unknown_action():
    assert actions.dispatch({"action": "format-c-drive"})["ok"] is False


def test_dispatch_rejects_non_dict_payload():
    assert actions.dispatch([1, 2])["ok"] is False
    assert actions.dispatch(None)["ok"] is False


def test_dispatch_kill_rejects_bad_types():
    res = actions.dispatch({"action": "kill", "pid": "abc", "started_at": 0})
    assert res["ok"] is False


def test_dispatch_null_rel_opens_vault(fixture_vault, monkeypatch):
    launched = []
    monkeypatch.setattr(actions, "_launch", lambda target: launched.append(target))
    res = actions.dispatch({"action": "open-obsidian", "rel": None})
    assert res["ok"] is True
    assert launched == ["obsidian://open?vault=abc123def456"]


def test_dispatch_stop_server_unavailable_without_server():
    res = actions.dispatch({"action": "stop-server"})
    assert res["ok"] is False
    assert "unavailable" in res["message"]


def test_dispatch_stop_server_calls_shutdown():
    class Stub:
        def __init__(self):
            self.called = False
        def shutdown(self):
            self.called = True
    s = Stub()
    res = actions.dispatch({"action": "stop-server"}, server=s)
    assert res["ok"] is True
    import time as _t
    deadline = _t.time() + 2
    while not s.called and _t.time() < deadline:
        _t.sleep(0.05)
    assert s.called is True


def test_open_obsidian_cli_fallback(fixture_vault, monkeypatch):
    def boom(target):
        raise OSError("no protocol handler")
    popened = []
    monkeypatch.setattr(actions, "_launch", boom)
    monkeypatch.setattr(actions.subprocess, "Popen",
                        lambda args, **kw: popened.append(args))
    res = actions.open_obsidian("wiki/x.md")
    assert res["ok"] is True and "cli fallback" in res["message"]
    assert popened[0][0] == "obsidian" and popened[0][1].startswith("obsidian://open?vault=")


def test_open_obsidian_reports_launch_failure(fixture_vault, monkeypatch):
    def boom(*a, **kw):
        raise OSError("fail")
    monkeypatch.setattr(actions, "_launch", boom)
    monkeypatch.setattr(actions.subprocess, "Popen", boom)
    res = actions.open_obsidian("wiki/x.md")
    assert res["ok"] is False
