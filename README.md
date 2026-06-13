# Fleet — Claude Code session monitor

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
