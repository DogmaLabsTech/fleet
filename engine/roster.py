"""engine.roster — the project list + Mission Control roll-up (public).

Projects = pins from FLEET_PROJECTS_JSON (or <user_config>/projects.json) unioned
with live session cwds, deduped by slug. Roll-up adds the progress ring + a tiny
team summary. No agents / relay / crew / goals — those are internal-only enrichers.
"""

import json
import os
from pathlib import Path

from . import collector, oscompat, progress


def projects_json_path():
    override = os.environ.get("FLEET_PROJECTS_JSON")
    return Path(override) if override else oscompat.user_config_dir() / "projects.json"


def _load_pins():
    try:
        data = json.loads(projects_json_path().read_text(encoding="utf-8"))
        return {str(k): str(v) for k, v in data.items()} if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def add_project(repo_root):
    """Register a repo in the user config (used by `fleet projects add`)."""
    root = str(Path(repo_root).resolve())
    slug = collector.slug_for(root)
    path = projects_json_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    pins = _load_pins()
    pins[slug] = root
    path.write_text(json.dumps(pins, indent=2), encoding="utf-8")
    return slug


def discover(sessions):
    pins = _load_pins()
    entries = {slug: {"slug": slug, "repo_root": root} for slug, root in pins.items()}
    sess_slug = {}
    for s in sessions:
        root = collector.repo_root_for(s.get("cwd") or "")
        slug = next((sl for sl, r in pins.items()
                     if str(r).rstrip("\\/").lower() == str(root).rstrip("\\/").lower()),
                    collector.slug_for(root))
        sess_slug[s["session_id"]] = slug
        entries.setdefault(slug, {"slug": slug, "repo_root": root})
    for e in entries.values():
        e["title"] = e["slug"].replace("-", " ").title()
    return entries, sess_slug


def _team(slug, sessions, sess_slug):
    mine = [s for s in sessions if sess_slug.get(s["session_id"]) == slug]
    return {"sessions": len(mine), "busy": sum(1 for s in mine if s["status"] == "busy"),
            "waiting": sum(1 for s in mine if s["status"] == "waiting"), "mine": mine}


def roll_up():
    data = collector.collect()
    sessions = data["sessions"]
    entries, sess_slug = discover(sessions)
    projects = []
    for slug, e in entries.items():
        prog = progress.progress_for(e["repo_root"], slug)
        team = _team(slug, sessions, sess_slug)
        projects.append({"slug": slug, "title": e["title"], "repo_root": e["repo_root"],
                         "progress": {"percent": prog["percent"], "source": prog["source"],
                                      "split": prog["split"], "flags": prog["flags"]},
                         "team": {k: team[k] for k in ("sessions", "busy", "waiting")}})
    projects.sort(key=lambda p: (-p["team"]["waiting"], -p["team"]["sessions"],
                                 -p["progress"]["percent"], p["slug"]))
    return {"generated_at": data["generated_at"], "projects": projects}


def project_detail(slug):
    data = collector.collect()
    entries, sess_slug = discover(data["sessions"])
    e = entries.get(slug)
    if e is None:
        return None
    prog = progress.progress_for(e["repo_root"], slug)
    team = _team(slug, data["sessions"], sess_slug)
    mine = [{"session_id": s["session_id"], "status": s["status"], "title": s.get("title"),
             "activity": s.get("activity")} for s in team["mine"]]
    return {"slug": slug, "title": e["title"], "repo_root": e["repo_root"],
            "progress": prog, "team": {"sessions": mine}}
