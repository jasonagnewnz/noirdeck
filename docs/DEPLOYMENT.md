# Deployment (local)

No remote deploy — noirdeck runs only on the operator's own machine.

## First run
```bash
cd ~/noirdeck
make venv frontend test     # deps, SPA build, tests
make run                    # foreground on 127.0.0.1:4747
```

## Install as a service (opt-in, after review)
`make install-service` prints the exact commands (systemd **user** units from `ops/`).
Timers (`noirdeck-mine.timer` nightly heuristics+LLM mining, `noirdeck-overnight.timer`
queue runner) are separate opt-ins.

## Verify the deploy actually took (playbook D-1/P-5)
```bash
curl -s http://127.0.0.1:4747/api/health   # expect {"status":"ok","version":"<expected>"}
```
The health payload carries the running `version` — compare against `app/version.py`.
If you changed the frontend: hard-refresh and check the footer version matches too;
the SPA is served from `frontend/dist`, so an un-rebuilt dist == stale UI.

## Rollback
`git log` → `git checkout <good-sha>` → `make frontend && systemctl --user restart noirdeck`.
The DB migrates forward-only but schema changes are additive; if a DB migration breaks,
delete `data/noirdeck.db` (loses proposals/queue only — see DATA_MODEL.md) and restart.
