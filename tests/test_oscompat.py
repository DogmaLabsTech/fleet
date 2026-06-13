import os
import subprocess
import sys
import types

import pytest

from engine import oscompat


def test_proc_create_ms_dead_pid_is_none():
    assert oscompat.proc_create_ms(0) is None
    assert oscompat.proc_create_ms(-5) is None


def test_proc_create_ms_self_is_positive_int():
    ms = oscompat.proc_create_ms(os.getpid())
    assert isinstance(ms, int) and ms > 0


def test_proc_create_ms_missing_process_is_none(monkeypatch):
    import psutil

    def boom(pid):
        raise psutil.NoSuchProcess(pid)

    monkeypatch.setattr(oscompat.psutil, "Process", boom)
    assert oscompat.proc_create_ms(999999) is None


def test_proc_create_ms_access_denied_is_minus_one(monkeypatch):
    import psutil

    def denied(pid):
        raise psutil.AccessDenied(pid)

    monkeypatch.setattr(oscompat.psutil, "Process", denied)
    assert oscompat.proc_create_ms(4) == -1


def test_open_in_os_macos_uses_open(monkeypatch):
    calls = {}
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: calls.setdefault("argv", a[0]))
    oscompat.open_in_os("/tmp/x")
    assert calls["argv"][0] == "open"


def test_open_in_os_linux_uses_xdg_open(monkeypatch):
    calls = {}
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: calls.setdefault("argv", a[0]))
    oscompat.open_in_os("/tmp/x")
    assert calls["argv"][0] == "xdg-open"


def test_open_in_os_launcher_failure_is_oserror(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")

    def boom(*a, **k):
        raise FileNotFoundError("no xdg-open")

    monkeypatch.setattr(subprocess, "run", boom)
    with pytest.raises(OSError):
        oscompat.open_in_os("/tmp/x")


def test_obsidian_registry_path_per_os(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    assert oscompat.obsidian_registry_path().as_posix().endswith(
        "Library/Application Support/obsidian/obsidian.json"
    )
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setenv("XDG_CONFIG_HOME", "/home/u/.config")
    assert oscompat.obsidian_registry_path().as_posix() == "/home/u/.config/obsidian/obsidian.json"
