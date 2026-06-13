"""engine.verify — read-only milestone verification for the public honesty model.

Decides whether an independent repo-local artifact backs a `done` milestone.
NEVER executes anything: it only reads files inside repo_root. Returns:
  True  -> artifact backs the claim   (milestone earns "verified")
  False -> artifact contradicts it    (claimed done, receipt absent/mismatched)
  None  -> no readable/usable signal  (fall back to attested/uncited)
"""

import json
from pathlib import Path

MAX_JSON_BYTES = 1_048_576
_MISSING = object()


def _sandboxed(root, rel):
    """Resolved repo-relative path that stays within root, or None on escape/error."""
    try:
        target = (root / rel).resolve()
        return target if target.is_relative_to(root) else None
    except (OSError, ValueError):
        return None


def _pointer(data, pointer):
    """Resolve an RFC-6901-ish JSON pointer ('/a/b/0'), or _MISSING."""
    if not pointer:
        return data
    cur = data
    for raw in pointer.lstrip("/").split("/"):
        key = raw.replace("~1", "/").replace("~0", "~")
        if isinstance(cur, dict) and key in cur:
            cur = cur[key]
        elif isinstance(cur, list) and key.isdigit() and int(key) < len(cur):
            cur = cur[int(key)]
        else:
            return _MISSING
    return cur


def _compare(val, spec):
    if "equals" in spec:
        return val == spec["equals"]
    if "min" in spec:
        return isinstance(val, (int, float)) and not isinstance(val, bool) and val >= spec["min"]
    if "max" in spec:
        return isinstance(val, (int, float)) and not isinstance(val, bool) and val <= spec["max"]
    return val is not _MISSING and val is not None  # mere existence


def check(verify, repo_root):
    if not isinstance(verify, dict):
        return None
    try:
        root = Path(repo_root).resolve()
    except (OSError, ValueError):
        return None
    vtype = verify.get("type")

    if vtype == "glob":
        pattern = verify.get("pattern")
        if not pattern:
            return None
        try:
            for p in root.glob(pattern):
                if p.resolve().is_relative_to(root):
                    return True
            return False
        except (OSError, ValueError):
            return None

    rel = verify.get("path")
    if not rel:
        return None
    target = _sandboxed(root, rel)
    if target is None:
        return None

    if vtype == "file":
        return target.is_file()

    if vtype == "json":
        if not target.is_file():
            return False
        try:
            if target.stat().st_size > MAX_JSON_BYTES:
                return None
            data = json.loads(target.read_text(encoding="utf-8", errors="replace"))
        except (OSError, ValueError):
            return None
        val = _pointer(data, verify.get("pointer", ""))
        if val is _MISSING:
            return False
        return bool(_compare(val, verify))

    return None
