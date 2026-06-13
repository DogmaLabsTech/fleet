import importlib.util
from pathlib import Path

import fleet


def _denylist():
    """Load grep_gate.DENYLIST by path — the single source of truth for forbidden
    tokens — without requiring scripts/ to be an importable package."""
    p = Path(__file__).resolve().parent.parent / "scripts" / "grep_gate.py"
    spec = importlib.util.spec_from_file_location("grep_gate", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.DENYLIST


def test_scaffold_writes_skeleton(tmp_path):
    fleet.scaffold_vault(str(tmp_path))
    assert (tmp_path / "CLAUDE.md").is_file()
    assert (tmp_path / "wiki" / "index.md").is_file()
    assert (tmp_path / "wiki" / "meta" / "conventions.md").is_file()
    assert (tmp_path / "_templates" / "source.md").is_file()
    assert (tmp_path / ".raw" / "README.md").is_file()


def test_scaffold_no_clobber_claude_md_uses_sidecar(tmp_path, capsys):
    (tmp_path / "CLAUDE.md").write_text("MY OWN RULES", encoding="utf-8")
    fleet.scaffold_vault(str(tmp_path))
    # the adopter's own CLAUDE.md is preserved byte-for-byte
    assert (tmp_path / "CLAUDE.md").read_text(encoding="utf-8") == "MY OWN RULES"
    # the contract lands in the sidecar instead, with a merge notice
    assert (tmp_path / "wiki" / "_vault-contract.md").is_file()
    assert "merge" in capsys.readouterr().out.lower()


def test_scaffold_is_idempotent(tmp_path):
    fleet.scaffold_vault(str(tmp_path))
    before = sorted(p.relative_to(tmp_path).as_posix()
                    for p in tmp_path.rglob("*") if p.is_file())
    fleet.scaffold_vault(str(tmp_path))  # second run must not raise or duplicate
    after = sorted(p.relative_to(tmp_path).as_posix()
                   for p in tmp_path.rglob("*") if p.is_file())
    assert before == after


def test_scaffold_output_is_scrub_clean(tmp_path):
    fleet.scaffold_vault(str(tmp_path))
    denylist = _denylist()
    leaks = []
    for p in tmp_path.rglob("*"):
        if p.is_file():
            text = p.read_text(encoding="utf-8", errors="replace")
            leaks += [(p.relative_to(tmp_path).as_posix(), t) for t in denylist if t in text]
    assert leaks == [], f"denylisted tokens leaked into scaffold: {leaks}"


def test_main_init_vault_command(tmp_path, monkeypatch):
    monkeypatch.setattr("sys.argv", ["fleet.py", "init-vault", str(tmp_path)])
    fleet.main()
    assert (tmp_path / "CLAUDE.md").is_file()
    assert (tmp_path / "wiki" / "index.md").is_file()
