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

from engine.collector import collect

PORT_DEFAULT = 8377

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
    w_proj, w_title, w_age, w_model, w_branch = 16, 28, 6, 10, 12
    fixed = 8 + 2 + w_proj + 2 + w_title + 2 + w_age + 2 + w_model + 2
    if show_branch:
        fixed += w_branch + 2
    w_now = max(20, width - fixed - 1)

    header = (DIM + "STATUS".ljust(8) + "  " + "PROJECT".ljust(w_proj) + "  "
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


# ---------------------------------------------------------------- entry point

def main():
    parser = argparse.ArgumentParser(description="Claude Code session fleet monitor")
    parser.add_argument("command", nargs="?", choices=["dash", "app"],
                        help="dash: browser dashboard server; app: native desktop window")
    parser.add_argument("--serve", action="store_true", help="run the live dashboard server")
    parser.add_argument("--port", type=int, default=PORT_DEFAULT)
    parser.add_argument("--json", action="store_true", help="dump collector output")
    args = parser.parse_args()

    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

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
