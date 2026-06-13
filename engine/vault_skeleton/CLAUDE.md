# CLAUDE.md — your AI's memory vault

This folder is a **knowledge vault**: long-term memory your AI reads and writes as it
works. When an agent that reads this file runs here, it should treat `wiki/` as the
source of truth for what you have learned, decided, and built.

## How your AI should use this vault

- **Search the vault before answering a domain question.** Look in `wiki/` for an
  existing page and prefer what is written here over guessing.
- **One home per fact.** Each fact lives on exactly one page; link related pages with
  `[[Page Name]]` instead of copying text between them.
- **Write what is durable, not the conversation.** New decisions, facts, and lessons
  become a new `wiki/` page or update an existing one. Skip throwaway chatter.

## Layout — a folder per domain

Pages live flat under `wiki/<domain>/`, where a *domain* is a top-level area of your
work — a product, a client, a subject. Start in `wiki/general/` and add a folder as
each theme emerges. Notes that span domains go in `wiki/shared/`.

- `wiki/index.md` — master catalog, one line per page.
- `wiki/overview.md` — the standing briefing.
- `wiki/hot.md` — a short cache of recent context; overwrite it each session.
- `wiki/log.md` — append-only history, newest entry first.
- `wiki/meta/conventions.md` — the page conventions.
- `_templates/` — starting points for new notes.
- `.raw/` — drop source documents here to ingest.

## Frontmatter on every page

```yaml
---
type: source | concept | entity | note
title: Page Title
created: 2026-01-01
updated: 2026-01-01
tags: []
status: draft | active
domain: general
---
```

## Make it self-building (optional)

This skeleton is already a plain-markdown notebook your AI reads. To turn it into a
*self-building, searchable* vault — auto-ingest sources, lint links, local retrieval —
install the **claude-obsidian** engine (MIT, by AgriciDaniel):

```
/plugin marketplace add AgriciDaniel/claude-obsidian
```

Its `/ingest`, `/wiki-lint`, and retrieval commands then maintain `wiki/` for you.
Obsidian (the desktop app) is optional — the vault is just markdown; install it from
obsidian.md only if you want the graph view.

Your AI also has Claude Code's built-in memory, which persists key facts across
sessions on its own. This vault is the larger, browsable store you and your AI share.
