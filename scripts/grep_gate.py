#!/usr/bin/env python3
"""Fail if any personal/business token survives in shipped files.

Run before publish and in CI. Scans tracked text files (excludes .git, the gate
itself, and this script's denylist literal) for tokens that must never ship."""
import sys
from pathlib import Path

# Tokens that must never ship. Multi-word internal names are listed in every
# spelling that could appear (underscore / space / joined) — a space-variant
# slipping past the underscore token is exactly how "Kitchen Compass" leaked
# once. We deliberately do NOT blind-normalize: that would flag the intentional
# "Dogma Labs" attribution and common phrases (e.g. "paper trail").
DENYLIST = [
    r"C:\HUB",
    "DogmaLabs_OS", "DogmaLabs OS",
    "dogmalabs",
    "Benny",
    "Knowledge",
    "Kitchen_Compass", "Kitchen Compass", "KitchenCompass",
    "TitanTamers", "Titan Tamers",
    "PaperTrail",
]
ROOT = Path(__file__).resolve().parent.parent
SKIP_DIRS = {".git", "__pycache__", ".pytest_cache", "node_modules", ".venv"}
SKIP_FILES = {"grep_gate.py"}
TEXT_SUFFIXES = {".py", ".md", ".toml", ".json", ".html", ".css", ".js", ".yml", ".yaml", ".txt", ".cfg", ".ini"}
# Extension-less text files have no suffix, so scan them by name too — otherwise a
# token could hide in a shipped dotfile like .gitignore.
TEXT_NAMES = {".gitignore", ".gitattributes", "MANIFEST.in", "LICENSE", "CONTRIBUTING"}


def main():
    hits = []
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix.lower() not in TEXT_SUFFIXES and path.name not in TEXT_NAMES:
            continue
        if any(part in SKIP_DIRS for part in path.parts) or path.name in SKIP_FILES:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for token in DENYLIST:
            if token in text:
                hits.append(f"{path.relative_to(ROOT).as_posix()}: '{token}'")
    if hits:
        print("SCRUB GATE FAILED — forbidden tokens found:")
        for h in hits:
            print("  " + h)
        return 1
    print("scrub gate passed — no forbidden tokens")
    return 0


if __name__ == "__main__":
    sys.exit(main())
