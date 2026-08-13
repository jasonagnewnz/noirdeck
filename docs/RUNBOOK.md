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

## Cold boot order
Single service — systemd user unit starts it; no dependencies beyond the filesystem.
WSL note: user units need `loginctl enable-linger $USER` to run without an open session.

## Backup / restore
Original state = this git repo + `data/noirdeck.db` (proposals, queue, audit).
Everything else is re-derived from `~/.claude`. To restore: clone repo, restore the DB
file, `make venv frontend`, start. Restore is a file copy — test by copying the DB
aside and pointing `NOIRDECK_DB_PATH` at it.
