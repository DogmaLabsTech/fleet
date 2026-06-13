"""engine.progress — a repo's "% to done" + the honesty split, from one sidecar.

Reads <repo>/.fleet/progress.json (schema "fleet-progress/1"). Each done milestone
is scored verified|contradicted|attested|uncited via the read-only verify engine,
so a ring can't silently lie. Fail-soft: a broken sidecar contributes nothing.
"""

import json
import time
from pathlib import Path

from . import verify

SCHEMA = "fleet-progress/1"
_ZERO_SPLIT = {"verified": 0, "attested": 0, "in_progress": 0}
_NO_FLAGS = {"uncited": 0, "contradicted": 0}


def _read_manifest(repo_root):
    path = Path(repo_root) / ".fleet" / "progress.json"
    for attempt in range(2):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            break
        except (OSError, ValueError):
            if attempt == 0:
                time.sleep(0.05)
            else:
                return None
    if not isinstance(data, dict) or data.get("schema") != SCHEMA:
        return None
    ms = data.get("milestones")
    return ms if isinstance(ms, list) else None


def _confidence(m, repo_root):
    status = m.get("status")
    if status not in ("done", "in-progress"):
        return None
    has_prov = bool((m.get("provenance") or "").strip())
    if status == "done" and m.get("verify"):
        backed = verify.check(m["verify"], repo_root)
        if backed is True:
            return "verified"
        if backed is False:
            return "contradicted"
    return "attested" if has_prov else "uncited"


def _evaluate(milestones, repo_root):
    total = verified_w = attested_w = inprog_w = 0.0
    uncited = contradicted = 0
    enriched = []
    for m in milestones:
        if not isinstance(m, dict):
            continue
        w = m.get("weight")
        w = float(w) if isinstance(w, (int, float)) and not isinstance(w, bool) and w > 0 else 1.0
        total += w
        conf = _confidence(m, repo_root)
        status = m.get("status")
        if status == "done":
            verified_w += w if conf == "verified" else 0
            attested_w += w if conf != "verified" else 0
        elif status == "in-progress":
            inprog_w += 0.5 * w
        if conf == "uncited":
            uncited += 1
        elif conf == "contradicted":
            contradicted += 1
        em = dict(m)
        em["confidence"] = conf
        em["provenance"] = m.get("provenance") or ""
        enriched.append(em)
    if total:
        v = round(100 * verified_w / total)
        a = round(100 * attested_w / total)
        ip = round(100 * inprog_w / total)
        split = {"verified": v, "attested": a, "in_progress": ip}
        percent = v + a + ip
    else:
        split, percent = dict(_ZERO_SPLIT), 0
    return percent, enriched, split, {"uncited": uncited, "contradicted": contradicted}


def progress_for(repo_root, slug=None):
    milestones = _read_manifest(repo_root) if repo_root else None
    if milestones is None:
        return {"percent": 0, "source": "none", "milestones": [],
                "split": dict(_ZERO_SPLIT), "flags": dict(_NO_FLAGS)}
    percent, enriched, split, flags = _evaluate(milestones, repo_root)
    return {"percent": percent, "source": "manifest", "milestones": enriched,
            "split": split, "flags": flags}
