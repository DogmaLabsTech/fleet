# Contributing to Fleet

Thanks for considering a contribution. Fleet is small, dependency-light, and has
two non-negotiable principles — please keep them intact:

1. **100% local, zero egress.** Fleet reads your own files and binds `127.0.0.1`
   only. No telemetry, no analytics, no outbound network, ever. A PR that phones
   home will be declined.
2. **Read, never execute.** Fleet observes Claude Code's state and verifies
   progress by *reading* artifacts — it never runs commands, tests, or builds to
   do so. The progress `verify` engine is read-only and sandboxed to the repo root.

## Setup

```bash
git clone https://github.com/DogmaLabsTech/fleet
cd fleet
pip install -e ".[app]"     # editable install; [app] adds the native window
python -m pytest -q         # the test suite (should be green)
python scripts/grep_gate.py # the scrub gate (no machine-specific paths may ship)
```

## Working on it

- **Fail-soft everywhere.** A malformed transcript line, a missing file, or a
  schema-drifted event should yield *less detail*, never a crash or an error page.
- **Match the style.** Stdlib-first, small focused modules, no new dependencies
  without a strong reason. All OS-specific code goes in `engine/oscompat.py`.
- **Tests first.** New behavior comes with a test. The suite must stay green and
  must pass on Linux CI (no unguarded Windows-only calls on the POSIX path).
- **Keep the trust boundary provable.** If you touch I/O, make sure it's still
  obvious from the code that nothing leaves the machine.

## Pull requests

Open an issue first for anything beyond a small fix. Keep PRs focused, describe
what you changed and why, and confirm `pytest` + the scrub gate are green.
