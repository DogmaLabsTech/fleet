# Adopting Fleet's rings in your own repos

The only thing Fleet needs to light up a project's Mission Control ring is **one
file: `<repo>/.fleet/progress.json`.** No vault, no CI integration, no account, no
network. Write that one file (or have your coding agent maintain it) and register
the repo. That's the whole contract.

## 1. Scaffold the sidecar

From inside the repo you want to track:

```bash
fleet init
```

This writes a starter `.fleet/progress.json` (it won't overwrite an existing one).
The template has one `in-progress` milestone and one `done`-with-`verify`
milestone to copy from. Open it, then run `fleet dash` to see your rings.

The starter looks like this:

```json
{
  "schema": "fleet-progress/1",
  "title": "<your project>",
  "milestones": [
    {
      "name": "First milestone",
      "weight": 1,
      "status": "in-progress",
      "provenance": "branch or PR that proves it"
    },
    {
      "name": "A verified one",
      "weight": 2,
      "status": "done",
      "provenance": "commit sha",
      "verify": { "type": "file", "path": "path/to/an/artifact" }
    }
  ]
}
```

## 2. Fill it in

You maintain the sidecar one of two ways.

### By hand

Edit `.fleet/progress.json` directly. List your real milestones, set each
`status` to `planned` / `in-progress` / `done`, and add a `provenance` receipt
(commit, PR, branch, URL) so a finished milestone reads as **attested** rather than
**uncited**. For the milestones that have a real artifact — a coverage file, a test
report, a build output — add a `verify` block pointing at it to earn **verified**.

See [`PROGRESS-MANIFEST.md`](PROGRESS-MANIFEST.md) for every field and the three
`verify` types.

### Or have your coding agent maintain it

Because the sidecar is plain JSON in the repo, the agent already working in your
codebase can keep it honest for you. Drop an instruction like this into your
agent's project rules (`CLAUDE.md`, `AGENTS.md`, or equivalent):

> **Maintain `.fleet/progress.json`.** When you finish a unit of work, update the
> matching milestone's `status` (`planned` → `in-progress` → `done`) and set its
> `provenance` to the commit or PR that proves it. When a milestone produces a
> durable artifact (a coverage report, a passing-test JSON, a generated file),
> add a `verify` block pointing at that repo-relative artifact so it reads as
> *verified*, not just *attested*. Never mark a milestone `done` without at least a
> `provenance` receipt. Schema is `fleet-progress/1`; see `docs/PROGRESS-MANIFEST.md`.

The agent writes the receipts as a side effect of doing the work, so your rings
stay truthful without you babysitting them.

## 3. Register the repo

Fleet's Mission Control shows repos you register plus any repo a live session is
currently working in. To pin a repo so it always appears:

```bash
fleet projects add /path/to/repo
```

This records the repo in Fleet's per-user config (`%APPDATA%\fleet\projects.json`
on Windows, `~/.config/fleet/projects.json` elsewhere — or wherever
`FLEET_PROJECTS_JSON` points). The file holds only `{ "slug": "repo-root" }`
pairs and never ships with real paths.

Then open Mission Control:

```bash
fleet dash      # browser dashboard; switch from the sessions monitor to Mission Control
```

## The principle: one required file, optional enrichers

The **only required surface is `.fleet/progress.json`.** Everything that makes a
milestone *more* than `attested` is an **optional artifact you point `verify`
at** — and that artifact is something you already produce:

- **CI / test reports** — point a `json` verify at the result file (e.g.
  `{"type":"json","path":"junit.json","pointer":"/passed","equals":true}`).
- **Coverage** — `{"type":"json","path":"coverage/summary.json","pointer":"/total/lines/pct","min":80}`.
- **Build outputs / generated files** — `{"type":"file","path":"dist/app.js"}` or
  a `glob`.

Fleet **reads** those artifacts; it never runs the tooling that makes them (see
[`HONESTY.md`](HONESTY.md)). The internal machinery some teams run — relay
pipelines, visual audits, retrieval engines — is **not required and not shipped**;
if you happen to run it and it leaves a file behind, that file is just one more
artifact you can aim a `verify` block at. The doctrine scales down to a single
hand-edited JSON and up to a fully-instrumented pipeline, with the same one file
at its center.

## Optional: give the agent a memory vault

Separate from the progress sidecar — and just as optional — Fleet can scaffold a
generic **knowledge vault** for your AI to use as long-term memory:

```bash
fleet init-vault
```

This writes a `CLAUDE.md` that points your agent at a `wiki/` folder, plus a skeleton
and note templates — all generic, none of it required by Mission Control. It makes the
agent *use* the vault; to make the vault self-building and searchable, install the MIT
[`claude-obsidian`](https://github.com/AgriciDaniel/claude-obsidian) plugin by
AgriciDaniel. Fleet ships the skeleton, never the engine. See the README's "Give your
AI a memory" section for the full flow.
