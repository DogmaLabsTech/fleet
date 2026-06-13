from engine import vault


def test_vault_id_resolution(fixture_vault):
    assert vault.vault_id() == "abc123def456"


def test_page_rel(fixture_vault):
    inside = str(fixture_vault / "wiki" / "shared" / "Quality Bar.md")
    assert vault.page_rel(inside) == "wiki/shared/Quality Bar.md"
    assert vault.page_rel("C:\\elsewhere\\x.md") is None
    assert vault.page_rel(str(fixture_vault / "scripts" / "x.py")) is None


def test_obsidian_uri(fixture_vault):
    uri = vault.obsidian_uri("wiki/shared/Quality Bar.md")
    assert uri == "obsidian://open?vault=abc123def456&file=wiki%2Fshared%2FQuality%20Bar"


def test_obsidian_uri_vault_only(fixture_vault):
    assert vault.obsidian_uri("") == "obsidian://open?vault=abc123def456"


def test_build_graph(fixture_vault):
    files = {
        "read": [{"path": str(fixture_vault / "wiki" / "shared" / "Quality Bar.md"),
                  "count": 1, "last": "t"}],
        "edited": [{"path": str(fixture_vault / "wiki" / "projects" / "Kitchen Compass.md"),
                    "count": 2, "last": "t"}],
        "written": [], "searched": [],
    }
    g = vault.build_graph(files)
    labels = {n["label"]: n for n in g["nodes"]}
    assert "Quality Bar" in labels and labels["Quality Bar"]["touch"] == "read"
    assert labels["Kitchen Compass"]["touch"] == "edited"
    assert any(n["kind"] == "session" for n in g["nodes"])
    # wikilink Quality Bar -> Kitchen Compass resolved as edge between existing nodes
    ids = {n["label"]: n["id"] for n in g["nodes"]}
    assert {"from": ids["Quality Bar"], "to": ids["Kitchen Compass"], "kind": "link"} in g["edges"]
    # [[Missing Page]] doesn't resolve -> no phantom node
    assert "Missing Page" not in labels


def test_build_graph_empty(fixture_vault):
    g = vault.build_graph({"read": [], "edited": [], "written": [], "searched": []})
    assert g["nodes"] == [] and g["edges"] == []


# Fix 1 — NUL byte in path
def test_build_graph_tolerates_nul_paths(fixture_vault):
    files = {"read": [{"path": "C:\\bad\x00path\\x.md", "count": 1, "last": "t"}],
             "edited": [], "written": [], "searched": []}
    g = vault.build_graph(files)
    assert g["nodes"] == [] and g["edges"] == []


# Fix 2 — dot-directories excluded
def test_dot_directories_excluded(fixture_vault):
    hidden = fixture_vault / ".claude" / "agents"
    hidden.mkdir(parents=True)
    (hidden / "Secret Agent.md").write_text("[[Quality Bar]]", encoding="utf-8")
    assert vault.page_rel(str(hidden / "Secret Agent.md")) is None
    assert "secret agent" not in vault._stem_index()


# Fix 3 — overflow counts unique skipped nodes
def test_node_cap_and_overflow(fixture_vault):
    hub = fixture_vault / "wiki" / "hub"
    hub.mkdir(parents=True)
    links = " ".join(f"[[Page {i:03d}]]" for i in range(80))
    (hub / "Hub.md").write_text(links, encoding="utf-8")
    for i in range(80):
        (hub / f"Page {i:03d}.md").write_text("leaf", encoding="utf-8")
    files = {"read": [{"path": str(hub / "Hub.md"), "count": 1, "last": "t"}],
             "edited": [], "written": [], "searched": []}
    g = vault.build_graph(files)
    assert len(g["nodes"]) == 60  # session + Hub + 58 neighbors
    assert g["overflow"] == 22    # 80 - 58 unique skipped


# Fix 4 — cheap test gaps
def test_edited_wins_over_read_same_page(fixture_vault):
    p = str(fixture_vault / "wiki" / "shared" / "Quality Bar.md")
    files = {"read": [{"path": p, "count": 1, "last": "t"}],
             "edited": [{"path": p, "count": 1, "last": "t"}],
             "written": [], "searched": []}
    g = vault.build_graph(files)
    node = next(n for n in g["nodes"] if n["label"] == "Quality Bar")
    assert node["touch"] == "edited"


def test_written_maps_to_edited_touch(fixture_vault):
    p = str(fixture_vault / "wiki" / "shared" / "Quality Bar.md")
    files = {"read": [], "edited": [],
             "written": [{"path": p, "count": 1, "last": "t"}], "searched": []}
    g = vault.build_graph(files)
    node = next(n for n in g["nodes"] if n["label"] == "Quality Bar")
    assert node["touch"] == "edited"


def test_duplicate_stem_shortest_path_wins(fixture_vault):
    deep_dir = fixture_vault / "wiki" / "very" / "deep" / "nested"
    deep_dir.mkdir(parents=True)
    (deep_dir / "Quality Bar.md").write_text("dup", encoding="utf-8")
    index = vault._stem_index()
    assert index["quality bar"] == "wiki/shared/Quality Bar.md"


from engine import vault


def test_vault_dir_from_env(monkeypatch, tmp_path):
    monkeypatch.setenv("FLEET_VAULT_DIR", str(tmp_path))
    assert vault.vault_dir() == tmp_path


def test_vault_dir_none_without_env_or_single_vault(monkeypatch):
    monkeypatch.delenv("FLEET_VAULT_DIR", raising=False)
    monkeypatch.setattr(vault, "_registered_vaults", lambda: {})
    assert vault.vault_dir() is None
