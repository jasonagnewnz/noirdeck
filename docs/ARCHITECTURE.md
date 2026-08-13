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
        │        SQLite data/noirdeck.db  (ONLY original state:
        │        proposals, queue, insights, audit_log, mined_files)
        │                            │
  watchfiles ─► SSE /api/events ─► React SPA (frontend/dist)
```

Layers:
- **readers/** — pure functions over the `~/.claude` filesystem. Never write. In-memory caches keyed by file mtime. Transcripts are head/tail-sampled (bounded reads), never fully loaded.
- **miner/** — heuristics (no egress) + a gated headless `claude -p` runner. All transcript text passes `redact.py` before reaching any prompt.
- **proposals.py** — propose→approve→execute. Approval is the ONLY code path that writes into `~/.claude`, restricted to an allowlist of roots, audited.
- **overnight.py** — queue runner: one headless session at a time, agent+model routing, structured verdict, park-on-uncertainty, audit with token usage.
- **qa.py** — Commercial-readiness gates per project (BLOCKER/GAP/PASS).

The SQLite DB is a derived cache except for proposals/queue/audit; deleting it loses only those. `~/.claude` is never the write target except via approved proposals.
