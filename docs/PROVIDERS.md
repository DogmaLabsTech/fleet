# Providers — reading more than one AI agent

Fleet monitors several terminal AI coding agents by reading each one's own
on-disk state (read-only, local-only, never executing anything). Each agent is a
**provider**: a small module under `engine/providers/`. Adding support for a new
tool is one module — the core never changes.

## The seam

`collector.collect()` is a **merger**. It asks every enabled provider for its
sessions, concatenates them, then does the shared sort / counts / age over the
union. Per-session drill-down (`/session/<id>`, `/vault/<id>`) dispatches by
`record.provider` to that provider's parser.

```
collect()  ──► enabled_providers() ──► each provider.collect(now_ms)
                                          └─► (live[], stopped[])  normalized records
deep_for() ──► providers.get(rec.provider).deep_parse(rec, transcript)
```

Enablement: `FLEET_PROVIDERS` (comma-separated ids) pins an explicit set;
otherwise every provider whose tool is `detect()`ed on disk is included.

## The provider interface

A provider module exposes:

| Symbol | Returns | Notes |
|---|---|---|
| `ID` | `str` | short id, e.g. `"codex"` |
| `LABEL` | `str` | display name |
| `detect()` | `bool` | is the tool present on disk? |
| `collect(now_ms)` | `(live, stopped)` | lists of records from `base.make_record(...)` |
| `find_transcript(rec)` | `Path \| None` | the transcript for a record |
| `deep_parse(rec, path)` | `dict \| None` | `{head, timeline, timeline_total, files}` |

Every record comes from `base.make_record(**fields)` so the table and UI never
have to check for missing keys. Always set `provider`, `session_id`, `cwd`,
`project`, `status`, `started_at`, `updated_at`, `live`, and (so drill-down works)
`transcript`.

`deep_parse` returns the same shape Claude's `deep.parse_full` does:
- `head`: `ctx_tokens`, `ctx_window`, `model`, `branch`, `rules`, `files`
  (`read`/`edited`/`written`/`searched`), `skills`, `agents`, `mcp`, `warnings`
- `timeline`: `[{ts, kind, text}]` — kinds `prompt` / `writing` / `edit` / `write`
  / `tool` / `skill` / `error` / `note`
- `files`: same buckets as `head.files`

## The honesty model (liveness)

This is the one rule that matters most. **Only report a status you can actually
read.**

- A provider whose tool writes a **live status / PID file** (Claude Code's session
  state; Qwen's `*.runtime.json`) can report *verified* liveness: `live=True`,
  `live_inferred=False`, and a real `pid`. Those sessions can also be ended from
  the UI.
- A provider with only an **after-the-fact transcript** (Codex, Gemini) must set
  `live_inferred=True` and derive `status` from transcript freshness
  (`base.infer_status(updated_ms, now_ms)` → `active` within 5 min, else
  `stopped`). The UI renders these calmly and tags them `~live (inferred)` — never
  as Claude's verified busy. Don't fabricate `busy`/`waiting`; you don't know it.

Never run the tool, its tests, or a shell to learn more. Reading is the contract.

## Current providers

| id | file | transcript | liveness |
|---|---|---|---|
| `claude` | `claude.py` (over `collector`/`deep`) | `~/.claude/projects/**/*.jsonl` | verified (PID + busy/waiting/idle) |
| `qwen` | `qwen.py` | `~/.qwen/projects/**/chats/*.jsonl` + `*.runtime.json` | verified (PID from sidecar) |
| `codex` | `codex.py` | `~/.codex/sessions/**/rollout-*.jsonl` | inferred (freshness) |
| `gemini` | `gemini.py` | `~/.gemini/tmp/**/chats/session-*.jsonl` | inferred (freshness) |

Gemini and Qwen share one transcript parser, `_geminish.py` (Qwen is a Gemini-CLI
fork). All paths are env-overridable (`FLEET_<ID>_DIR`).

## Add a provider

1. Create `engine/providers/<id>.py` with the interface above. Reuse
   `base.make_record`, `base.infer_status`, `base.rules_chain`, `base.tail_lines`,
   `base.iso_ms`.
2. Register the id in `engine/providers/__init__.py` (`_PROVIDER_IDS`).
3. Add `tests/test_providers_<id>.py` with a synthetic transcript fixture — assert
   `collect()` tiers (active/stopped/dropped), the `deep_parse` timeline + file
   buckets, and the liveness honesty (`live_inferred` set correctly).
4. If the tool exposes a real PID, wire verified liveness via
   `oscompat.proc_create_ms(pid)` (zombies count as dead). Otherwise use freshness.
5. Note the tool in the README provider table and here.

Keep it small and fail-soft: one malformed line or one broken provider must never
take down the table (`collect()` and the parsers swallow per-item errors).
