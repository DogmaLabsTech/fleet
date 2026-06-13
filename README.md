# Fleet — Claude Code session monitor

[![ci](https://github.com/DogmaLabsTech/fleet/actions/workflows/ci.yml/badge.svg)](https://github.com/DogmaLabsTech/fleet/actions/workflows/ci.yml)
&nbsp;![python](https://img.shields.io/badge/python-3.9%2B-blue)
&nbsp;![license](https://img.shields.io/badge/license-MIT-green)
&nbsp;![local-only](https://img.shields.io/badge/network-zero%20egress-success)

**One window over every running Claude Code session — and an honest ring per repo
that won't pretend work is done when it isn't.** 100% local; nothing leaves your
machine.

![Fleet Mission Control — honest progress rings](docs/demo-rings.png)

*Mission Control: one ring per repo, split into **verified** (an independent
artifact backs it) / **attested** (a cited receipt) / **uncited** (no receipt) —
and flagged **contradicted** when a `done` claim's receipt is missing.*

See, supervise, and inspect every running Claude Code session from one window —
the live table, what each session has in its head, which files it touched, and how
its work connects to your Obsidian vault.

## 100% local. Nothing leaves your machine.

Fleet reads **only your own local files** — Claude Code's session state and
transcripts under `~/.claude`, and (optionally) an Obsidian vault you point it at.

- The server binds **`127.0.0.1` only**, with Host-header and CSRF guards.
- **No network egress. No telemetry. No analytics.** Fonts are self-hosted.
- The only actions are opening a file/folder/page (hand-off to your OS) and
  ending a session (confirm-gated, with a PID-reuse guard). Fleet never writes to
  `~/.claude` or your vault.

## Mission Control & the honesty rings

Beyond the live session monitor, Fleet has a **Mission Control** view: a ring per
project showing how far it is to done — and, crucially, **how trustworthy that
number is.** One file per repo, `<repo>/.fleet/progress.json`, lights up the ring,
split into three honesty arcs:

- **verified** — a `done` milestone whose `verify` block points at a real repo
  artifact that Fleet read and confirmed;
- **attested** — a milestone with a cited receipt (commit / PR / branch) taken on
  trust;
- **uncited** — a bare assertion with no receipt (and `contradicted` flags any
  `done` claim whose artifact is missing).

A ring can't silently lie: green that means *verified* and green that means *I said
so* are coloured differently. And the trust boundary is the same as the rest of the
tool — **Fleet decides every tier by reading local files only. It never executes
anything to verify** (no tests run, no build, no shell, no network); every path is
sandboxed to the repo root.

Adopt it in one file:

```bash
fleet init                 # scaffold .fleet/progress.json in the current repo
fleet projects add <path>  # pin a repo to Mission Control
fleet dash                 # then switch from the sessions monitor to Mission Control
```

- [`docs/HONESTY.md`](docs/HONESTY.md) — the verified / attested / uncited /
  contradicted doctrine, and why Fleet reads but never runs.
- [`docs/PROGRESS-MANIFEST.md`](docs/PROGRESS-MANIFEST.md) — the
  `.fleet/progress.json` schema reference, with a worked example.
- [`docs/ADOPTING.md`](docs/ADOPTING.md) — fill the sidecar by hand or have your
  coding agent maintain it.

The sessions monitor stays the default view; Mission Control is opt-in via the
switcher.

## Install

```bash
pip install fleet-cc          # core (terminal + browser dashboard)
pip install "fleet-cc[app]"   # + native desktop window (pywebview)
```

## Use

```bash
fleet          # compact table of live sessions in your terminal
fleet dash     # live dashboard in your browser at http://127.0.0.1:8377
fleet app      # native desktop window (needs the [app] extra)
fleet --json   # raw collector output (debugging)
```

Click a session for three tabs: **HEAD** (context size, loaded rules, files
read/edited, skills/agents/MCP used), **VAULT WEB** (Obsidian pages it touched +
their wikilinks — set `FLEET_VAULT_DIR` to your vault), **TIMELINE** (what it did).

## Platforms

macOS, Linux, Windows. The terminal table and browser dashboard need no GUI
toolkit; the native window (`fleet app`) uses pywebview (built in on macOS/Windows;
on Linux install a Qt or GTK backend, or just use `fleet dash`).

## Caveat

Fleet reads Claude Code's **internal, undocumented** on-disk state. It's
best-effort and fail-soft: a format change in a future CLI release may show less
detail until Fleet catches up, but it will not crash. Issues and PRs welcome.

## Configuration

| Env var | Meaning |
|---|---|
| `FLEET_CLAUDE_DIR` | Override `~/.claude` (default) |
| `FLEET_VAULT_DIR` | Your Obsidian vault root (enables the VAULT WEB tab) |
| `FLEET_OBSIDIAN_JSON` | Override the Obsidian registry path |
| `FLEET_PROJECTS_JSON` | Mission Control project pins (`{slug: repo_path}`); defaults to your per-OS config dir |

## License & credits

MIT — see [`LICENSE`](LICENSE). Built by [Dogma Labs](https://github.com/DogmaLabsTech).
Contributions welcome; please open an issue or PR.
