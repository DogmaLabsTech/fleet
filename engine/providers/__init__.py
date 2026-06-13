"""engine.providers — the registry of session providers.

Provider modules are imported lazily (importlib, on first use) so that
`from .providers import base` in collector.py never triggers a circular import
through claude.py -> collector.py at module-load time.

Enablement: FLEET_PROVIDERS (comma-separated ids) pins an explicit set;
otherwise every provider whose tool is detected on disk is included.
"""

import importlib
import os

# Order here is the order providers are merged (claude first keeps its sessions
# at the top of the table, as before).
_PROVIDER_IDS = ["claude", "codex", "gemini", "qwen"]
_cache = {}


def _mod(pid):
    if pid not in _cache:
        _cache[pid] = importlib.import_module(f".{pid}", __name__)
    return _cache[pid]


def all_providers():
    return [_mod(pid) for pid in _PROVIDER_IDS]


def get(provider_id):
    """The provider module for an id, or None for an unknown id."""
    return _mod(provider_id) if provider_id in _PROVIDER_IDS else None


def _safe_detect(mod):
    try:
        return mod.detect()
    except Exception:
        return False


def enabled_providers():
    forced = os.environ.get("FLEET_PROVIDERS")
    if forced:
        ids = [s.strip() for s in forced.split(",") if s.strip()]
        return [_mod(pid) for pid in ids if pid in _PROVIDER_IDS]
    return [_mod(pid) for pid in _PROVIDER_IDS if _safe_detect(_mod(pid))]
