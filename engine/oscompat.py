"""engine.oscompat — the single home for OS-specific operations.

Everything platform-dependent lives here so the rest of the engine is portable:
  - process liveness + creation time (psutil, replacing Windows ctypes)
  - opening a file / folder / URI with the OS default handler
  - locating Obsidian's registry file

proc_create_ms preserves collector's original tri-state contract:
  None  -> process is dead / no such pid
  -1    -> alive but we cannot read its identity (access denied)
  int   -> unix-ms creation time
"""

import os
import subprocess
import sys
from pathlib import Path

import psutil


def proc_create_ms(pid):
    """Process creation time in unix ms, or None (dead) / -1 (alive-unreadable).

    A POSIX zombie (terminated, awaiting reap by its parent) still exposes a
    creation time but is not running — treat it as dead so liveness/kill checks
    don't see a defunct session as alive. (No-op on Windows, which has no zombies.)
    """
    if not isinstance(pid, int) or pid <= 0:
        return None
    try:
        p = psutil.Process(pid)
        if p.status() == psutil.STATUS_ZOMBIE:
            return None
        return int(p.create_time() * 1000)
    except (psutil.NoSuchProcess, psutil.ZombieProcess):
        return None
    except (psutil.AccessDenied, OSError):
        return -1


def open_in_os(target):
    """Open a file, folder, or URI with the OS default handler.

    Non-destructive hand-off to the user's editor / file manager / browser.
    Raises OSError on any failure (callers already catch OSError)."""
    if sys.platform == "win32":
        os.startfile(target)  # noqa: S606 - deliberate local launcher
        return
    launcher = "open" if sys.platform == "darwin" else "xdg-open"
    try:
        subprocess.run([launcher, target], check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except (subprocess.SubprocessError, FileNotFoundError) as e:
        raise OSError(f"{launcher} failed: {e}") from e


def user_config_dir():
    """Per-OS app config dir for fleet (created lazily by callers)."""
    import sys
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", str(Path.home())))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config")))
    return base / "fleet"


def obsidian_registry_path():
    """Path to Obsidian's obsidian.json registry, per-OS."""
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", ""))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config")))
    return base / "obsidian" / "obsidian.json"
