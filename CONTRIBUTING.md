# Contributing

Thanks for your interest. This project is currently developed by a single maintainer;
issues and pull requests are welcome, but expect review turnaround to vary.

## Development setup

Requirements: Python 3.12 (see `.python-version`) and Node 22 (see `frontend/.nvmrc`).

```sh
make venv       # create .venv and install backend deps
make frontend   # npm install + production SPA build
make test       # backend test suite (must pass before any PR)
make run        # serve on 127.0.0.1 (port: NOIRDECK_PORT, default 4747)
```

## Ground rules

- **Localhost-only is load-bearing.** The app binds 127.0.0.1 and its WebSocket is
  shell-equivalent. Never add code that binds other interfaces, weakens the Host/Origin
  allowlist, or exposes the service through a tunnel without authentication.
- **Propose-only writes.** The only write path into the user's estate is proposal
  approval in the UI, behind the existing allowlist and audit trail. New features that
  write anywhere must go through that spine.
- **Zero egress by default.** Background jobs must not call external services unless
  explicitly armed by the user. Keep it that way.
- **Path safety.** Any parameter that names a project or file must stay a single path
  segment and a direct child of the allowed root. This class of traversal has been
  found and fixed multiple times; check every new endpoint.

## Style and checks

- Python: `ruff check backend/ && ruff format backend/` (config in `pyproject.toml`).
- Frontend: `npm run lint` / `npm run format` (Biome, config in `frontend/biome.json`).
- Tests live in `backend/tests`; add or extend tests with behavior changes.
- Migrations are append-only; never edit an applied migration.

## Commits and PRs

- Target `main`. Keep commits focused; explain *why* in the message body when the
  change isn't self-evident.
- Update `CHANGELOG.md` under a new version heading for user-visible changes.
- No secrets in code, tests, fixtures, or commit messages — synthetic values only.
