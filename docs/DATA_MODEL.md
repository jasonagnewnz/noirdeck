# Data model

## Read-only sources (never written)
- `~/.claude/skills/*/SKILL.md` — YAML frontmatter `name`, `description`, `model`.
- `~/.claude/agents/*.md` — frontmatter `name`, `description`, `tools`, `model`.
- `~/.claude/projects/<ns>/memory/*.md` — frontmatter `name`, `description`, `metadata.type`; `MEMORY.md` index.
- `~/.claude/projects/<ns>/*.jsonl` — session transcripts; typed records (`user`, `assistant`, `last-prompt`, …). Sampled head/tail only.
- `~/.claude/history.jsonl` — `{display, timestamp(ms), project, sessionId?}` per prompt.

## SQLite (`data/noirdeck.db`) — additive migrations in `app/db.py`
- `schema_version(version)`
- `proposals(id, kind, title, body, target_path, status, created_at, decided_at, note)`
  - kind: `skill` | `memory_group` | `profile_doc` | `insight`; status: `proposed` | `approved` | `dismissed`
  - target_path is RELATIVE to `~/.claude`, must resolve under an allowlisted root.
- `queue(id, project, title, prompt, agent_type, model, status, verdict, question, answer, tokens_in, tokens_out, created_at, started_at, finished_at)`
  - status: `queued` | `running` | `done` | `blocked` | `cancelled`; `blocked` tasks carry `question` and re-queue when `answer` is set.
- `insights(id, kind, title, body, source, created_at)` — miner observations that aren't file proposals.
- `mined_files(path PRIMARY KEY, mtime, mined_at)` — dedup so a transcript is mined once per version.
- `audit_log(id, ts, actor, action, detail)` — every write into `~/.claude`, every overnight run, every arm/approve/dismiss.

All timestamps ISO-8601 UTC (tz-aware); the UI renders Pacific/Auckland.

## Join keys
Sessions join history via `sessionId` (both sides are the vendor's uuid — no internal PK exists, so there is no external-vs-internal trap here; the transcript filename stem IS the sessionId).
