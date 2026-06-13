import json
import threading
import urllib.error
import urllib.request

import pytest

from engine import server


@pytest.fixture
def live_server(fixture_claude_dir, fixture_vault):
    srv = server.make_server(0)  # ephemeral port
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()
    srv.server_close()


def get(url):
    with urllib.request.urlopen(url, timeout=5) as r:
        return r.status, r.read()


def post_json(url, payload, headers=None):
    h = {"Content-Type": "application/json"}
    h.update(headers or {})
    req = urllib.request.Request(url, method="POST",
                                 data=json.dumps(payload).encode(), headers=h)
    with urllib.request.urlopen(req, timeout=5) as r:
        return r.status, json.loads(r.read())


def test_data_route(live_server):
    status, body = get(live_server + "/data")
    d = json.loads(body)
    assert status == 200 and "sessions" in d and "counts" in d


def test_session_route_serves_dead_session_detail(live_server):
    # fixture session is dead but its transcript exists; /session works off stopped_recent too
    status, body = get(live_server + "/session/fix-1")
    d = json.loads(body)
    assert status == 200
    assert d["head"]["model"] == "claude-fable-5"
    assert d["timeline"][0]["kind"] == "note"  # "session started"
    assert d["timeline"][1]["kind"] == "prompt"


def test_session_route_404s_unknown(live_server):
    with pytest.raises(urllib.error.HTTPError) as e:
        get(live_server + "/session/nope")
    assert e.value.code == 404
    assert json.loads(e.value.read())["error"] == "unknown session"


def test_session_404_is_json(live_server):
    with pytest.raises(urllib.error.HTTPError) as e:
        get(live_server + "/session/nope")
    assert e.value.code == 404
    assert json.loads(e.value.read())["error"] == "unknown session"


def test_vault_route(live_server):
    status, body = get(live_server + "/vault/fix-1")
    d = json.loads(body)
    assert status == 200
    labels = [n["label"] for n in d["nodes"]]
    assert "Quality Bar" in labels
    assert d["vault_dir"]


def test_vault_route_cached_per_transcript(live_server, monkeypatch):
    from engine import vault as vault_mod
    calls = []
    real = vault_mod.build_graph
    monkeypatch.setattr(vault_mod, "build_graph", lambda files: calls.append(1) or real(files))
    get(live_server + "/vault/fix-1")
    get(live_server + "/vault/fix-1")
    assert len(calls) == 1  # second hit served from cache


def test_action_route_rejects_unknown(live_server):
    status, d = post_json(live_server + "/action", {"action": "nope"})
    assert d["ok"] is False


def test_action_requires_json_content_type(live_server):
    req = urllib.request.Request(live_server + "/action", method="POST", data=b"{}")
    # urllib defaults Content-Type to application/x-www-form-urlencoded -> must be rejected
    with pytest.raises(urllib.error.HTTPError) as e:
        urllib.request.urlopen(req, timeout=5)
    assert e.value.code == 403


def test_action_rejects_cross_origin(live_server):
    with pytest.raises(urllib.error.HTTPError) as e:
        post_json(live_server + "/action", {"action": "nope"},
                  headers={"Origin": "http://evil.example"})
    assert e.value.code == 403


def test_action_allows_same_origin_header(live_server):
    port = live_server.rsplit(":", 1)[1]
    status, d = post_json(live_server + "/action", {"action": "nope"},
                          headers={"Origin": f"http://127.0.0.1:{port}"})
    assert d["ok"] is False and "unknown" in d["message"]


def test_static_ui_served(live_server):
    status, body = get(live_server + "/")
    assert status == 200 and b"<!doctype html>" in body.lower()


def test_static_traversal_blocked(live_server):
    with pytest.raises(urllib.error.HTTPError) as e:
        get(live_server + "/../fleet.py")
    assert e.value.code == 404


def test_post_with_body_to_unknown_path_gets_404(live_server):
    for _ in range(5):  # was intermittent (TCP RST) before the drain reorder
        req = urllib.request.Request(live_server + "/other", method="POST",
                                     data=json.dumps({"action": "x"}).encode(),
                                     headers={"Content-Type": "application/json"})
        with pytest.raises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(req, timeout=5)
        assert e.value.code == 404


def test_session_transcript_missing_fail_soft(live_server, fixture_claude_dir):
    # delete the transcript out from under the route
    t = next((fixture_claude_dir / "projects" / "C--projects-my-vault").glob("*.jsonl"))
    t.unlink()
    status, body = get(live_server + "/session/fix-1")
    d = json.loads(body)
    assert status == 200
    assert d["head"]["warnings"] == ["transcript not found"]
    assert d["timeline"] == [] and d["head"]["files"]["read"] == []


def test_foreign_host_header_rejected(live_server):
    port = live_server.rsplit(":", 1)[1]
    req = urllib.request.Request(live_server + "/data", headers={"Host": f"evil.example:{port}"})
    with pytest.raises(urllib.error.HTTPError) as e:
        urllib.request.urlopen(req, timeout=5)
    assert e.value.code == 403


def test_oversized_post_rejected(live_server):
    req = urllib.request.Request(live_server + "/action", method="POST",
                                 data=b"x" * (1_048_576 + 1),
                                 headers={"Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=5)
        assert False, "expected rejection"
    except urllib.error.HTTPError as e:
        assert e.code == 413
    except (ConnectionError, OSError):
        pass  # RST before response is acceptable for oversized abuse


def test_action_malformed_json_gets_400(live_server):
    req = urllib.request.Request(live_server + "/action", method="POST",
                                 data=b"{not json", headers={"Content-Type": "application/json"})
    with pytest.raises(urllib.error.HTTPError) as e:
        urllib.request.urlopen(req, timeout=5)
    assert e.value.code == 400


def test_projects_route(live_server):
    server._projects_cache["data"] = None  # bust the cross-test TTL cache
    status, body = get(live_server + "/projects")
    d = json.loads(body)
    assert status == 200
    assert "generated_at" in d and isinstance(d["projects"], list)


def test_project_unknown_404(live_server):
    with pytest.raises(urllib.error.HTTPError) as e:
        get(live_server + "/project/definitely-not-a-real-slug")
    assert e.value.code == 404
    assert json.loads(e.value.read())["error"] == "unknown project"


def test_no_spawns_route(live_server):
    # spawn must never come back: /spawns and /spawn-log must not exist
    for p in ("/spawns", "/spawn-log/x"):
        with pytest.raises(urllib.error.HTTPError) as e:
            get(live_server + p)
        assert e.value.code == 404
