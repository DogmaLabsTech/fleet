# The progress manifest: `<repo>/.fleet/progress.json`

One file per repo. It's the **only** surface Fleet needs to light up that repo's
Mission Control ring. Fleet reads it; nothing writes to it but you (or your own
coding agent). If it's missing or malformed, that project shows a friendly
empty-state — never a crash.

## Top-level shape

```json
{
  "schema": "fleet-progress/1",
  "title": "My Project",
  "milestones": [ ... ]
}
```

| Field | Type | Required | Meaning |
|---|---|---|---|
| `schema` | string | **yes** | Must be exactly `"fleet-progress/1"`. Any other value (or a missing field) makes Fleet ignore the file. |
| `title` | string | no | Human name for the project. |
| `milestones` | array | **yes** | The list of milestones, scored and rolled up into the ring. An empty array is valid (0%). |

## A milestone

```json
{
  "name": "Auth flow",
  "weight": 3,
  "status": "done",
  "provenance": "commit a1b2c3d, PR #42",
  "verify": { "type": "file", "path": "coverage/auth.lcov" }
}
```

| Field | Type | Required | Meaning |
|---|---|---|---|
| `name` | string | yes | What the milestone is. |
| `weight` | number | no | Relative size. Must be `> 0`; defaults to `1`. A weight-3 milestone moves the ring three times as much as a weight-1. |
| `status` | string | yes | One of `"planned"`, `"in-progress"`, `"done"`. |
| `provenance` | string | no | Free-text receipt — a commit sha, PR number, branch, or URL. **Its presence alone earns at least `attested`.** |
| `verify` | object | no | A read-only check that, when it **passes**, earns `verified`. See below. |

### How `status` moves the ring

`percent` = Σ(weight of `done`) + 0.5 · Σ(weight of `in-progress`), over Σ(all
weight). A `planned` milestone contributes to the denominator but adds nothing
yet. The total is split into **verified / attested / in-progress** arcs:

- a `done` milestone scored `verified` lands in the **verified** arc;
- any other `done` milestone (attested, uncited, or contradicted) lands in the
  **attested** arc;
- an `in-progress` milestone contributes half its weight to the **in-progress**
  arc.

The roll-up also carries two honesty **flags**: `uncited` (count of bare
assertions) and `contradicted` (count of `done` claims whose `verify` check
failed). These are what surface the "this ring is lying" cases.

## The `verify` block

`verify` is optional. When present on a `done` milestone, its read-only result
decides **verified** (passes) vs **contradicted** (fails). If Fleet can't read it
at all, the milestone falls back to `attested`/`uncited`. There are three types.

### `file` — the artifact exists

```json
{ "type": "file", "path": "coverage/auth.lcov" }
```

Passes if `path` (repo-relative) is an existing file.

### `glob` — at least one match

```json
{ "type": "glob", "pattern": "reports/*.xml" }
```

Passes if `pattern` matches one or more files inside the repo.

### `json` — a value in a report satisfies a predicate

```json
{ "type": "json", "path": "report.json", "pointer": "/summary/passed", "equals": true }
```

Fleet reads the JSON at `path`, follows the JSON-pointer `pointer`
(RFC-6901-ish: `/a/b/0`), and compares the value found:

| Comparator | Passes when |
|---|---|
| `equals` | the value `==` the given literal |
| `min` | the value is a number `>=` `min` |
| `max` | the value is a number `<=` `max` |
| *(none)* | the value merely exists and is not `null` |

```json
{ "type": "json", "path": "coverage/summary.json", "pointer": "/total/lines/pct", "min": 80 }
```

A **missing file**, or a **pointer that doesn't resolve**, makes the check **fail**
— for a `done` milestone that means `contradicted` (claimed done, but the receipt
isn't there). An **unreadable/malformed JSON** or a file **over the size cap
(1 MiB)** is treated as **no signal** (not a failure): the milestone falls back to
`attested`/`uncited`, because a receipt Fleet *couldn't read* is not the same as a
receipt that *disproved* the claim.

## The sandbox rule

Every `path` and `pattern` is **repo-relative and confined to the repo root**. A
value that resolves outside the repo — `../../etc/passwd`,
`/absolute/elsewhere` — is treated as **no signal** and is *never read*. Fleet
will not follow your sidecar out of its own directory. Combined with the
read-only, no-execution rule (see [`HONESTY.md`](HONESTY.md)), pointing Fleet at a
repo can never run code or read files outside that repo.

## Worked example

```json
{
  "schema": "fleet-progress/1",
  "title": "Acme Checkout",
  "milestones": [
    {
      "name": "Cart + line-item math",
      "weight": 2,
      "status": "done",
      "provenance": "PR #18",
      "verify": { "type": "glob", "pattern": "tests/cart/*.test.js" }
    },
    {
      "name": "Stripe integration",
      "weight": 3,
      "status": "done",
      "provenance": "commit 9f3c1aa",
      "verify": { "type": "json", "path": "coverage/summary.json", "pointer": "/total/lines/pct", "min": 75 }
    },
    {
      "name": "Refund flow",
      "weight": 2,
      "status": "in-progress",
      "provenance": "branch feat/refunds"
    },
    {
      "name": "Tax rules",
      "weight": 1,
      "status": "planned"
    }
  ]
}
```

How Fleet scores it:

- **Cart** — `done`, the glob matches test files → **verified**, full weight 2 in
  the verified arc.
- **Stripe** — `done`; if `coverage/summary.json` exists and `/total/lines/pct` is
  ≥ 75 → **verified** (weight 3). If that file is missing → **contradicted**
  (weight 3 stays in the attested arc, and the `contradicted` flag is raised).
- **Refund** — `in-progress` → half of weight 2 in the in-progress arc; with
  `provenance` it's **attested**.
- **Tax** — `planned` → nothing yet (denominator only).

With both verified milestones passing, the ring reads
`percent = (2 + 3 + 0.5·2) / (2 + 3 + 2 + 1)` ≈ **75%**, with a fat verified arc, a
thin in-progress arc, and no uncited slice — a ring you can trust because every
green segment has a receipt Fleet actually read.
