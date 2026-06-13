"""Vault linker: which Obsidian pages a session touched and how they interlink."""

import json
import os
import re
import urllib.parse
from pathlib import Path

from . import oscompat

WIKILINK_RE = re.compile(r"\[\[([^\]\|#\n]+)")
NODE_CAP = 60


def _registry_path() -> Path:
    override = os.environ.get("FLEET_OBSIDIAN_JSON")
    return Path(override) if override else oscompat.obsidian_registry_path()


def _registered_vaults():
    """{path: id} from Obsidian's registry, or {} if unreadable."""
    try:
        reg = json.loads(_registry_path().read_text(encoding="utf-8"))
        return {str(info.get("path", "")): vid
                for vid, info in (reg.get("vaults") or {}).items() if info.get("path")}
    except (OSError, ValueError):
        return {}


def vault_dir():
    """The vault root: FLEET_VAULT_DIR if set; else the sole registered Obsidian
    vault if there is exactly one; else None (VAULT WEB shows an empty-state)."""
    override = os.environ.get("FLEET_VAULT_DIR")
    if override:
        return Path(override)
    vaults = _registered_vaults()
    if len(vaults) == 1:
        return Path(next(iter(vaults)))
    return None


def vault_id():
    """Obsidian's id for the vault whose path matches vault_dir(). None if unknown."""
    root = vault_dir()
    if root is None:
        return None
    target = str(root).rstrip("\\/").lower()
    for path, vid in _registered_vaults().items():
        if str(path).rstrip("\\/").lower() == target:
            return vid
    return None


def page_rel(path):
    """Vault-relative posix path for .md files inside the vault, else None."""
    root = vault_dir()
    if root is None:
        return None
    if any(ord(c) < 32 for c in str(path)):
        return None
    try:
        rel = Path(path).resolve().relative_to(root.resolve())
    except (ValueError, OSError):
        return None
    if any(part.startswith(".") for part in rel.parts):
        return None
    return rel.as_posix() if rel.suffix.lower() == ".md" else None


def obsidian_uri(rel):
    root = vault_dir()
    vid = vault_id() or (root.name if root is not None else "")
    if not rel:  # vault-only deep link (used by the empty-state "open vault" button)
        return f"obsidian://open?vault={urllib.parse.quote(vid)}"
    file = rel[:-3] if rel.lower().endswith(".md") else rel
    return f"obsidian://open?vault={urllib.parse.quote(vid)}&file={urllib.parse.quote(file, safe='')}"


def _stem_index():
    """page-name (lower) -> vault-relative path; shortest path wins on duplicates."""
    index = {}
    root = vault_dir()
    if root is None:
        return index
    try:
        for p in root.rglob("*.md"):
            rel_path = p.relative_to(root)
            if any(part.startswith(".") for part in rel_path.parts):
                continue
            rel = rel_path.as_posix()
            key = p.stem.lower()
            if key not in index or len(rel) < len(index[key]):
                index[key] = rel
    except OSError:
        pass
    return index


def build_graph(files):
    """files = deep.parse_full(...)['files']. Returns {nodes, edges, overflow, warnings}."""
    root = vault_dir()
    if root is None:
        return {"nodes": [], "edges": [], "overflow": 0, "warnings": []}
    warnings = []
    touched = {}  # rel -> "edited" | "read"   (edited wins)
    for bucket, touch in (("edited", "edited"), ("written", "edited"), ("read", "read")):
        for f in files.get(bucket, []):
            rel = page_rel(f["path"])
            if rel and touched.get(rel) != "edited":
                touched[rel] = touch
    if not touched:
        return {"nodes": [], "edges": [], "overflow": 0, "warnings": warnings}

    index = _stem_index()
    nodes = [{"id": "__session__", "label": "session", "kind": "session", "touch": None}]
    edges = []
    rel_to_id = {}
    for rel, touch in touched.items():
        rel_to_id[rel] = rel
        nodes.append({"id": rel, "label": Path(rel).stem, "kind": "page", "touch": touch})
        edges.append({"from": "__session__", "to": rel, "kind": touch})

    skipped = set()
    for rel in list(touched):
        try:
            text = (root / rel).read_text(encoding="utf-8", errors="replace")
        except (OSError, ValueError) as e:
            warnings.append(f"unreadable: {rel} ({e})")
            continue
        for match in WIKILINK_RE.findall(text):
            target = index.get(match.strip().lower())
            if not target:
                continue  # unresolved link -> no phantom node
            if target not in rel_to_id:
                if len(nodes) >= NODE_CAP:
                    skipped.add(target)
                    continue
                rel_to_id[target] = target
                nodes.append({"id": target, "label": Path(target).stem,
                              "kind": "neighbor", "touch": None})
            edge = {"from": rel, "to": target, "kind": "link"}
            if edge not in edges and rel != target:
                edges.append(edge)
    return {"nodes": nodes, "edges": edges, "overflow": len(skipped), "warnings": warnings}
