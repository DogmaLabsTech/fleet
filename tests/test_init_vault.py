import argparse
import importlib.util
from pathlib import Path

import fleet


def _args(**kw):
    base = dict(rest=[], name=None, dir=None, here=False, use=None, yes=True)
    base.update(kw)
    return argparse.Namespace(**base)


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


# ---------------------------------------------------------------- onboarding

def test_scaffold_substitutes_vault_name(tmp_path):
    fleet.scaffold_vault(str(tmp_path), name="Acme Brain")
    claude = (tmp_path / "CLAUDE.md").read_text(encoding="utf-8")
    assert "Acme Brain" in claude
    assert "Acme Brain" in (tmp_path / "wiki" / "index.md").read_text(encoding="utf-8")
    # no template token survives anywhere in the scaffold
    for p in tmp_path.rglob("*"):
        if p.is_file():
            assert "{{VAULT_NAME}}" not in p.read_text(encoding="utf-8", errors="replace")


def test_claude_md_has_first_run_onboarding_trigger(tmp_path):
    fleet.scaffold_vault(str(tmp_path), name="X")
    claude = (tmp_path / "CLAUDE.md").read_text(encoding="utf-8")
    assert "First run" in claude and "onboarding.md" in claude


def test_scaffold_writes_onboarding_brief(tmp_path):
    fleet.scaffold_vault(str(tmp_path), name="Acme Brain", use="track the sales pipeline")
    ob = tmp_path / "onboarding.md"
    assert ob.is_file()
    text = ob.read_text(encoding="utf-8")
    assert "Acme Brain" in text
    assert "track the sales pipeline" in text
    assert "status: pending" in text
    assert "connect to" in text.lower()   # connections checklist item
    assert "skill set" in text.lower()     # skill recommendation item
    assert "AI CLIs detected" in text      # machine scan recorded


def test_onboarding_md_is_no_clobber(tmp_path):
    fleet.scaffold_vault(str(tmp_path), name="X")
    first = (tmp_path / "onboarding.md").read_text(encoding="utf-8")
    fleet.scaffold_vault(str(tmp_path), name="X")   # re-run must not overwrite
    assert (tmp_path / "onboarding.md").read_text(encoding="utf-8") == first


def test_detect_clis_returns_known_labels():
    labels = fleet._detect_clis()
    assert isinstance(labels, list)
    assert all(l in {"Claude Code", "Codex CLI", "Gemini CLI", "Qwen Code"} for l in labels)


def test_onboarding_inputs_positional_derives_name(tmp_path):
    name, dest, use = fleet._onboarding_inputs(_args(rest=[str(tmp_path)]))
    assert name == tmp_path.name and dest == str(tmp_path) and use is None


def test_onboarding_inputs_honors_flags(tmp_path):
    name, dest, use = fleet._onboarding_inputs(
        _args(name="Acme Brain", dir=str(tmp_path), use="notes"))
    assert name == "Acme Brain" and dest == str(tmp_path) and use == "notes"


def test_onboarding_inputs_here_flag():
    name, dest, _ = fleet._onboarding_inputs(_args(here=True, name="X"))
    assert dest == "." and name == "X"


def test_onboarding_inputs_noninteractive_never_blocks():
    # no flags, no TTY, yes=True: must resolve without prompting (would hang CI)
    name, dest, use = fleet._onboarding_inputs(_args())
    assert dest == "." and name and use is None
