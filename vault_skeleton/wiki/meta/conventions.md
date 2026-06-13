---
type: note
title: Conventions
created: 2026-01-01
updated: 2026-01-01
tags: [meta]
status: active
domain: general
---

# Conventions

How pages in this vault are written, so the graph stays consistent.

- **Frontmatter on every page** — `type, title, created, updated, tags, status, domain`.
  Flat YAML only.
- **Wikilinks** — connect pages with `[[Page Name]]`. Link generously; a link to a page
  that does not exist yet marks something worth writing.
- **One home per fact** — each fact lives on exactly one page. Point at it from
  elsewhere; do not copy.
- **`index.md`** is updated whenever a page is added or renamed.
- **`log.md`** is append-only, newest entry first.
- **Domains are folders** — `wiki/<domain>/`. Cross-cutting notes go in `wiki/shared/`.
