#!/usr/bin/env python3
"""fleet — Claude Code session fleet monitor (stdlib only).

Reads Claude Code's own on-disk state (no hooks, read-only):
  ~/.claude/sessions/*.json                   live session state (pid, cwd, status)
  ~/.claude/projects/<slug>/<sessionId>.jsonl session transcript (title, prompt, activity)
  ~/.claude/history.jsonl                     prompt fallback

Usage:
  python fleet.py            compact ANSI table of live sessions
  python fleet.py --serve    live dashboard at http://127.0.0.1:8377
  python fleet.py --json     raw collector output (debug)
"""

import argparse
import json
import os
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

from engine.collector import collect

PORT_DEFAULT = 8377

# ---------------------------------------------------------------- repo scaffold (fleet init)

TEMPLATE = {
    "schema": "fleet-progress/1",
    "title": "<your project>",
    "milestones": [
        {"name": "First milestone", "weight": 1, "status": "in-progress",
         "provenance": "branch or PR that proves it"},
        {"name": "A verified one", "weight": 2, "status": "done",
         "provenance": "commit sha",
         "verify": {"type": "file", "path": "path/to/an/artifact"}}
    ]
}


def init_repo(repo="."):
    d = Path(repo) / ".fleet"
    d.mkdir(parents=True, exist_ok=True)
    target = d / "progress.json"
    if target.exists():
        print(f"{target} already exists — leaving it untouched")
        return
    target.write_text(json.dumps(TEMPLATE, indent=2), encoding="utf-8")
    print(f"wrote {target}\nEdit it, then run `fleet dash` to see your rings. Docs: docs/ADOPTING.md")

# ---------------------------------------------------------------- vault scaffold (fleet init-vault)

VAULT_SKELETON = Path(__file__).resolve().parent / "engine" / "vault_skeleton"


def _obsidian_status():
    """'detected' / 'not found' — detection only, never installs anything."""
    try:
        from engine import oscompat
        return "detected" if oscompat.obsidian_registry_path().exists() else "not found"
    except Exception:
        return "not found"


def _slug(name):
    return re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-") or "my-vault"


def _name_from_path(dest):
    return Path(dest).resolve().name or "my-vault"


def _detect_clis():
    """Which terminal AI CLIs are installed on this machine (best-effort).
    Reuses the session-monitor provider detectors, so it never guesses."""
    found = []
    try:
        from engine import providers
        for pid in ("claude", "codex", "gemini", "qwen"):
            p = providers.get(pid)
            try:
                if p and p.detect():
                    found.append(p.LABEL)
            except Exception:
                pass
    except Exception:
        pass
    return found


def _onboarding_md(name, use, detected):
    clis = ", ".join(detected) if detected else "none detected"
    use_line = use.strip() if use else "_(not provided — ask the owner)_"
    return f"""---
type: note
title: Onboarding
status: pending
domain: general
---

# Onboarding — {name}

**Status:** `pending` → set to `complete` when this checklist is done, so it never runs again.

The owner ran `fleet init-vault` to create **{name}**. Finish setting it up before
other work.

- **Vault name:** {name}
- **Planned use:** {use_line}
- **AI CLIs detected on this machine:** {clis}

## Do this on first run

- [ ] Confirm the vault's name and the owner's goals for it.
- [ ] Ask what this vault needs to **connect to** — MCP servers, APIs, repos, data
      sources — and record each as a page under `wiki/`.
- [ ] Recommend a **skill set** for how they work, and how to enable it (the
      self-building engine is `/plugin marketplace add AgriciDaniel/claude-obsidian`).
- [ ] Create the `wiki/<domain>/` folders that match their domains/projects.
- [ ] Seed `wiki/overview.md` with a one-paragraph briefing of what this vault is for.
- [ ] Set this file's **status to `complete`**.
"""


def scaffold_vault(dest=".", name=None, use=None, open_after=False):
    """Scaffold a named knowledge vault into dest, no-clobber per file.

    Substitutes the vault NAME into the skeleton, then writes an onboarding.md
    brief (name, planned use, detected CLIs + a build-out checklist) that the
    scaffolded CLAUDE.md tells the AI to act on at first launch — the hybrid
    half of onboarding. If dest/CLAUDE.md already exists and isn't ours, our
    contract goes to wiki/_vault-contract.md so we never overwrite the adopter's.
    Ships zero third-party code; the self-building engine is a plugin (printed)."""
    dest = Path(dest)
    name = name or _name_from_path(dest)
    written, skipped, adopter_claude = [], [], False
    for src in sorted(VAULT_SKELETON.rglob("*")):
        if not src.is_file():
            continue
        rel = src.relative_to(VAULT_SKELETON)
        target = dest / rel
        content = src.read_text(encoding="utf-8").replace("{{VAULT_NAME}}", name)
        is_claude = rel.as_posix() == "CLAUDE.md"
        if is_claude and target.exists():
            # If the existing CLAUDE.md is ours (re-run), skip it. If it's the
            # adopter's own, route our contract to a sidecar instead of overwriting.
            if target.read_text(encoding="utf-8") == content:
                skipped.append("CLAUDE.md")
                continue
            adopter_claude = True
            target = dest / "wiki" / "_vault-contract.md"
        if target.exists():
            skipped.append(target.relative_to(dest).as_posix())
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        written.append(target.relative_to(dest).as_posix())

    onboarding = dest / "onboarding.md"
    if onboarding.exists():
        skipped.append("onboarding.md")
    else:
        onboarding.write_text(_onboarding_md(name, use, _detect_clis()), encoding="utf-8")
        written.append("onboarding.md")

    print(f"Created {name} at {dest}  ({len(written)} written, {len(skipped)} skipped).")
    if adopter_claude:
        print("  note: you already have a CLAUDE.md - merge the routing block from "
              "wiki/_vault-contract.md")
    print("\nNext: launch your AI in this folder — it reads onboarding.md and finishes setup.")
    print(f"    cd {dest} && claude        (or codex / gemini / qwen)")
    print("\nTo make the vault self-building + searchable, install the engine (MIT, by AgriciDaniel):")
    print("    /plugin marketplace add AgriciDaniel/claude-obsidian")
    print(f"\nObsidian (the GUI) is optional - the vault is just markdown. [{_obsidian_status()}]")
    print("Docs: docs/ADOPTING.md")

    if open_after:
        try:
            from engine import oscompat
            oscompat.open_in_os(str(dest.resolve()))
        except Exception:
            pass

# ---------------------------------------------------------------- ANSI / Windows console

RESET = "\x1b[0m"
BOLD = "\x1b[1m"
DIM = "\x1b[38;2;156;163;175m"
ACCENT = "\x1b[38;2;255;130;0m"
GREEN = "\x1b[38;2;74;222;128m"
AMBER = "\x1b[38;2;251;191;36m"


def enable_ansi():
    if os.name != "nt":
        return  # POSIX terminals interpret VT natively
    import ctypes
    from ctypes import wintypes
    try:
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        handle = k32.GetStdHandle(-11)
        mode = wintypes.DWORD()
        if k32.GetConsoleMode(handle, ctypes.byref(mode)):
            k32.SetConsoleMode(handle, mode.value | 0x0004)
    except Exception:
        pass  # Windows Terminal interprets VT regardless


# ---------------------------------------------------------------- table renderer

def humanize_age(seconds):
    if seconds < 60:
        return f"{seconds}s"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}m"
    return f"{minutes // 60}h{minutes % 60:02d}m"


def _fit(text, width):
    text = text or ""
    if len(text) > width:
        text = text[: max(0, width - 1)] + "…"
    return text.ljust(width)


def _short_model(model):
    return (model or "?").removeprefix("claude-")


def _status_cell(rec):
    status = rec["status"]
    if status == "busy":
        return ACCENT + "● BUSY".ljust(8) + RESET
    if status == "waiting":
        return AMBER + "◌ WAIT".ljust(8) + RESET
    if status == "active":            # inferred-live (Codex/Gemini): no verified PID
        return GREEN + "◍ live".ljust(8) + RESET
    if status == "idle":
        return DIM + "○ idle".ljust(8) + RESET
    return DIM + _fit("· " + status, 8) + RESET


def render_table(data):
    width = shutil.get_terminal_size((120, 30)).columns
    c = data["counts"]
    out = []
    parts = [f"{c['live']} live", ACCENT + f"{c['busy']} busy" + RESET]
    if c["waiting"]:
        parts.append(AMBER + f"{c['waiting']} waiting" + RESET)
    parts.append(DIM + f"{c['idle']} idle" + RESET)
    if c["background"]:
        parts.append(DIM + f"{c['background']} background" + RESET)
    clock = datetime.fromtimestamp(data["generated_at"] / 1000).strftime("%H:%M:%S")
    out.append(f"{BOLD}{ACCENT}FLEET{RESET}  " + (DIM + " · " + RESET).join(parts)
               + f"  {DIM}{clock}{RESET}")
    out.append("")

    show_branch = width >= 110
    w_prov, w_proj, w_title, w_age, w_model, w_branch = 7, 16, 28, 6, 10, 12
    fixed = 8 + 2 + w_prov + 2 + w_proj + 2 + w_title + 2 + w_age + 2 + w_model + 2
    if show_branch:
        fixed += w_branch + 2
    w_now = max(20, width - fixed - 1)

    header = (DIM + "STATUS".ljust(8) + "  " + "PROV".ljust(w_prov) + "  "
              + "PROJECT".ljust(w_proj) + "  "
              + "TITLE".ljust(w_title) + "  " + "AGE".rjust(w_age) + "  "
              + "MODEL".ljust(w_model) + "  "
              + ("BRANCH".ljust(w_branch) + "  " if show_branch else "")
              + "NOW" + RESET)
    out.append(header)

    def row(rec, dim_all=False):
        status = rec["status"]
        if status == "busy":
            now = ACCENT + _fit(rec["activity"] or "working…", w_now) + RESET
        elif status == "waiting":
            now = AMBER + _fit("⚠ " + (rec["waiting_for"] or "waiting on you"), w_now) + RESET
        else:
            now = DIM + _fit("last: " + (rec["last_prompt"] or "—"), w_now) + RESET
        title = rec["name"] or rec["title"] or ""
        line = (_status_cell(rec) + "  "
                + DIM + _fit(rec.get("provider", "claude"), w_prov) + RESET + "  "
                + _fit(rec["project"], w_proj) + "  "
                + DIM + _fit(title, w_title) + RESET + "  "
                + humanize_age(rec["age_s"]).rjust(w_age) + "  "
                + _fit(_short_model(rec["model"]), w_model) + "  "
                + (DIM + _fit(rec["branch"] or "", w_branch) + RESET + "  " if show_branch else "")
                + now)
        return DIM + re.sub(r"\x1b\[[0-9;]*m", "", line) + RESET if dim_all else line

    interactive = [r for r in data["sessions"] if r["kind"] == "interactive"]
    background = [r for r in data["sessions"] if r["kind"] != "interactive"]
    if not data["sessions"]:
        out.append(DIM + "  no live sessions" + RESET)
    for rec in interactive:
        out.append(row(rec))
    if background:
        out.append(DIM + "background:" + RESET)
        for rec in background:
            out.append(row(rec, dim_all=True))
    if data["stopped_recent"]:
        names = ", ".join(f"{r['project']} ({humanize_age(r['age_s'])} ago)"
                          for r in data["stopped_recent"][:5])
        out.append("")
        out.append(DIM + f"recently stopped: {names}" + RESET)
    return "\n".join(out)


# ---------------------------------------------------------------- onboarding inputs

_EOF = object()  # sentinel: stdin closed / at EOF — stop prompting, fall back


def _prompt(question, default=None):
    """Ask once. Returns the answer, `default` on a blank line, or the _EOF
    sentinel if the stream is closed. Returning a sentinel (not "") on EOF is
    what lets callers fall back instead of re-prompting into an EOF busy-spin."""
    try:
        ans = input(question).strip()
    except (EOFError, KeyboardInterrupt):
        return _EOF
    return ans or default


def _onboarding_inputs(args):
    """Resolve (name, dest, use) for init-vault. Prompts only on a real TTY and
    only for values not supplied by flags/positional. Every prompt is EOF-safe:
    a closed stream (incl. a fake/at-EOF TTY where isatty() lies) falls back to a
    derived default instead of re-prompting, so init-vault can never hang."""
    try:
        interactive = sys.stdin.isatty() and not args.yes
    except (ValueError, AttributeError):
        interactive = False
    positional = args.rest[0] if args.rest else None

    name = args.name or (_name_from_path(positional) if positional else None)
    if not name and interactive:
        for _ in range(3):  # bounded; EOF or repeated blanks -> derived fallback below
            ans = _prompt("Name your vault (e.g. 'Acme Brain'): ")
            if ans is _EOF:
                interactive = False  # stream is closed — stop prompting entirely
                break
            if ans:
                name = ans
                break

    if args.here:
        dest = "."
    elif args.dir:
        dest = args.dir
    elif positional:
        dest = positional
    elif interactive:
        default_dir = str(Path.home() / _slug(name or "my-vault"))
        ans = _prompt(f"Where to create it [{default_dir}]: ", default_dir)
        if ans is _EOF:
            interactive, dest = False, default_dir
        else:
            dest = ans or default_dir
    else:
        dest = "."

    if not name:
        name = _name_from_path(dest)

    use = args.use
    if use is None and interactive:
        ans = _prompt("In one line, how will you use it? (optional): ")
        use = None if (ans is _EOF or not ans) else ans

    return name, dest, use


# ---------------------------------------------------------------- entry point

def main():
    parser = argparse.ArgumentParser(description="Claude Code session fleet monitor")
    parser.add_argument("command", nargs="?",
                        choices=["dash", "app", "init", "init-vault", "projects"],
                        help="dash: browser dashboard; app: desktop window; "
                             "init: scaffold .fleet/progress.json; "
                             "init-vault: scaffold an AI-memory vault; "
                             "projects: manage the roster")
    parser.add_argument("rest", nargs="*",
                        help="for `projects`: add <path>; for `init-vault`: target dir")
    parser.add_argument("--repo", help="target repo for `init` (default: current dir)")
    parser.add_argument("--open", action="store_true",
                        help="for `init-vault`: open the scaffolded folder afterwards")
    parser.add_argument("--name", help="for `init-vault`: name your vault (skips the prompt)")
    parser.add_argument("--dir", help="for `init-vault`: where to create it")
    parser.add_argument("--here", action="store_true", help="for `init-vault`: use the current directory")
    parser.add_argument("--use", help="for `init-vault`: one line on how you'll use it")
    parser.add_argument("--yes", action="store_true", help="for `init-vault`: skip prompts, use defaults")
    parser.add_argument("--serve", action="store_true", help="run the live dashboard server")
    parser.add_argument("--port", type=int, default=PORT_DEFAULT)
    parser.add_argument("--json", action="store_true", help="dump collector output")
    args = parser.parse_args()

    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    if args.command == "init":
        init_repo(args.repo or ".")
        return
    if args.command == "init-vault":
        name, dest, use = _onboarding_inputs(args)
        scaffold_vault(dest, name=name, use=use, open_after=args.open)
        return
    if args.command == "projects":
        from engine import roster
        if len(args.rest) >= 2 and args.rest[0] == "add":
            slug = roster.add_project(args.rest[1])
            print(f"registered '{slug}' -> {Path(args.rest[1]).resolve()}")
        else:
            print("usage: fleet projects add <path>")
        return
    if args.json:
        print(json.dumps(collect(), indent=2))
        return
    if args.command == "app":
        import app as _app
        _app.main()
        return
    if args.command == "dash" or args.serve:
        from engine.server import serve
        serve(args.port)
        return
    enable_ansi()
    print(render_table(collect()))


if __name__ == "__main__":
    main()
