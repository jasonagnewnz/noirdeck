# Runbook

## Is it up?
`make status` → health JSON, or `systemctl --user status noirdeck`.

## Logs
`journalctl --user -u noirdeck -f` (service) or stdout in foreground mode.

## Common issues
| Symptom | Cause | Fix |
|---|---|---|
| Startup exits "claude dir missing" | `NOIRDECK_CLAUDE_DIR` wrong | fix `.env`, restart |
| Dashboard stale / SSE dot red | watcher died or service restarted | refresh page; check journal |
| Mining run does nothing | `NOIRDECK_MINING_ARMED` not `true` (fail-closed by design) | arm it deliberately, re-run |
| Overnight task stuck `running` after crash | runner killed mid-task | restart service; stale `running` tasks are re-queued on boot |
| UI shows old version after update | `frontend/dist` not rebuilt | `make frontend`, restart |
| Workspace only shows Claude | old backend is still serving, or other runner binary is missing | restart the current backend; check `/api/workspace/runtimes` |
| Runner says "not found" | CLI is not on PATH in the service env | install it or set `NOIRDECK_CODEX_BIN`, `NOIRDECK_OLLAMA_BIN`, or `NOIRDECK_GROK_BIN` |
| Codex terminal appears to wait | Codex is asking whether to trust the repo | answer the Codex prompt in the terminal; choose yes only for trusted repos |
| Local models missing | Ollama is stopped or no tags are pulled | start Ollama and run `ollama list`; pull the model if needed |

## Workspace runtimes
`/api/workspace/runtimes` is the source of truth for the runner dropdown. It
reports each runner, whether its CLI was found, its default model, and model
suggestions. Codex and Claude use their own authenticated CLIs. Ollama uses
local tags from `http://127.0.0.1:11434`.

To move work between tools, select the active terminal tab and use **take over
with**. Noirdeck opens a new session in the same repo with a recent terminal
handoff brief. Check **close source** when the new session should replace the old
one instead of running beside it.

## Cold boot order
Single service — systemd user unit starts it; no dependencies beyond the filesystem.
WSL note: user units need `loginctl enable-linger $USER` to run without an open session.

## Backup / restore
Original state = this git repo + `data/noirdeck.db` (proposals, queue, audit).
Everything else is re-derived from `~/.claude`. To restore: clone repo, restore the DB
file, `make venv frontend`, start. Restore is a file copy — test by copying the DB
aside and pointing `NOIRDECK_DB_PATH` at it.
