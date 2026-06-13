"""Build-boundary guard: the source tree is not the shipped artifact.

The other tests import `fleet` from the checkout and read the source-tree skeleton, so
they pass even if `vault_skeleton/` never makes it into the wheel. This test builds a
real wheel and asserts every skeleton file (dotfiles included) is inside it — i.e. a
`pip install fleet-cc` adopter actually gets a working `fleet init-vault`."""
import subprocess
import sys
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

EXPECTED = {
    "CLAUDE.md",
    ".gitignore",
    ".obsidian/app.json",
    ".raw/README.md",
    "_templates/source.md",
    "_templates/concept.md",
    "_templates/entity.md",
    "wiki/index.md",
    "wiki/overview.md",
    "wiki/hot.md",
    "wiki/log.md",
    "wiki/meta/conventions.md",
    "wiki/general/_index.md",
}

PREFIX = "engine/vault_skeleton/"


def test_wheel_ships_vault_skeleton(tmp_path):
    r = subprocess.run(
        [sys.executable, "-m", "pip", "wheel", str(REPO), "--no-deps", "-w", str(tmp_path)],
        capture_output=True, text=True,
    )
    assert r.returncode == 0, f"pip wheel failed:\n{r.stdout}\n{r.stderr}"
    wheels = list(tmp_path.glob("fleet_cc-*.whl"))
    assert wheels, "no wheel was produced"
    names = zipfile.ZipFile(wheels[0]).namelist()
    shipped = {n[len(PREFIX):] for n in names if PREFIX in n and n[len(PREFIX):]}
    missing = EXPECTED - shipped
    assert not missing, f"wheel does not ship skeleton files: {sorted(missing)}"
