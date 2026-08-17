# Architecture

One FastAPI process on `127.0.0.1:4747` serving a built React SPA and a JSON API.

```
~/.claude (source of truth, read-only)        ~/projects (fleet, read-only)
   skills/ agents/ projects/*/memory/            git state via subprocess
   projects/*/*.jsonl  history.jsonl
        │                                             │
        ▼                                             ▼
  app/readers/*  ──────────────► FastAPI /api/* ◄──── app/readers/fleet.py, app/qa.py
        │                            │
        │        SQLite data/noirdeck.db
        │        (queue, approvals, workspace prefs, audit, derived indexes)
        │                            │
  watchfiles ─► SSE /api/events ─► React SPA (frontend/dist)
```

Layers:
- **readers/** — pure functions over the `~/.claude` filesystem. Never write. In-memory caches keyed by file mtime. Transcripts are head/tail-sampled (bounded reads), never fully loaded.
- **miner/** — heuristics (no egress) + a gated headless `claude -p` runner. All transcript text passes `redact.py` before reaching any prompt.
- **proposals.py** — propose→approve→execute. Approval is the ONLY code path that writes into `~/.claude`, restricted to an allowlist of roots, audited.
- **ai_runtime.py** — server-owned runner registry. The browser can choose a runner/model id, but argv construction stays on the server.
- **workspace.py** — PTY-backed live sessions, pause/resume metadata, terminal-context handoff prompts for runtime takeover.
- **overnight.py** — queue runner: one headless session at a time, runner/model routing, structured verdict, park-on-uncertainty, audit with token usage.
- **qa.py** — Commercial-readiness gates per project (BLOCKER/GAP/PASS).

The SQLite DB is mostly derived state, plus user decisions and runtime state:
proposals, queue rows, workspace defaults, transfer packs, paused sessions, and
the audit log. Deleting it forces indexes to rebuild but also loses those user
decisions and workspace records. `~/.claude` is never the write target except via
approved proposals.
