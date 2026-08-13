# noirdeck

**The dark console for your Claude Code estate.** A local companion platform —
live dashboard, IDE-feel workspace, autonomous pipelines with enforced guardrails,
and a code mentor, all at `http://127.0.0.1:4747`, all on your own machine,
nothing leaving the box.

> Crimson on warm black, scanlines, one signal colour. Noir by design.

![overview](docs/screenshots/overview.png)

## What it does

**Sees the whole estate, live**
- Reads `~/.claude` — skills, agents, memory namespaces, session history — and
  `~/projects` (the git fleet), refreshed by a filesystem event stream (SSE).
- Estate overview: stat tiles, open loops (sessions that ended unfinished), fleet
  attention (uncommitted/unpushed work), follow-on radar (schema changes missing
  tests, env-contract drift), recent sessions with one-click resume.
- History intelligence over every prompt ever typed: repeated asks, skill gaps.

**Works like an IDE**
- VS Code-style shell: activity bar (pops out to a labelled sidebar, `Ctrl+B`),
  status bar, command palette (`Ctrl+K`) over your skills + the full Claude Code
  reference, quick keys (`1`–`0` views, `?` cheat sheet with session keys, slash
  commands, and CLI flags verified against the installed CLI).
- Workspace: real `claude` sessions in the browser (PTY + xterm), project file
  explorer, read-only file tabs, one-click "review structure" / "tidy comments &
  legacy" actions — live in a terminal or queued for overnight.

**Builds and improves autonomously — inside hard boundaries**
- **Builds**: full brief in → code-ready software out. Five phases
  (plan → build → test → review → finish) with per-phase model routing, QA gates
  run *between* phases outside the LLM, crash-nets, and resume from the last
  completed phase. Stops at code-ready. Never ships.
- **Overnight queue**: ticket-shaped tasks run one at a time via headless Claude;
  anything uncertain parks as a question and the night moves on.
- **Design Studio**: propose a brief → three parallel design directions
  (8-direction × 6-library deck: Fluent 2, Material 3, IBM Carbon, Ant, shadcn,
  or bespoke) rendered as sandboxed live mocks → human Apply gate.
- **Miner**: mines session history for skill gaps and memory consolidation
  candidates → drafts proposals. **Hygiene**: dedupe/tidy findings over memories
  and skills (exact/near dupes, token-diet offenders, index drift) → propose-only
  merges.

## The safety model

Four layers, all fail-closed:

1. **Enforced guardrails** — every headless pipeline session launches with a
   PreToolUse hook (`ops/pipeline-guard.py`) that denies `git push`, publishing,
   deploys, kubernetes/terraform mutation, and remote access *before execution*.
   Not a prompt instruction — a harness boundary, verified against a live session.
2. **Propose → approve** — the only write path into `~/.claude` is proposal
   approval in the UI, allowlisted to `skills/` and one memory namespace,
   traversal-checked, audited. Originals are never deleted by automation.
3. **Arming contracts** — autonomous subsystems (overnight, mining) need the env
   master flag *and* a live contract: expiring, task-budgeted, token-budgeted,
   revocable, re-checked before every task. An armed system disarms itself.
4. **Browser boundary** — binds `127.0.0.1` only, with Host + Origin allowlists
   against DNS rebinding and cross-origin WebSocket hijack (the workspace WS is
   shell-equivalent; never tunnel it without auth). All transcript text passes
   secret-shape redaction before any LLM sees it. Zero external assets in the UI.

Every state-changing action lands in an audit log (UTC, actor, action, detail),
including what the autonomous subsystems did while you slept.

## Prerequisites

- **[Claude Code](https://claude.com/claude-code)** installed and authenticated —
  noirdeck reads `~/.claude` and shells out to `claude` for the workspace and every
  pipeline. Startup fails closed if `~/.claude` doesn't exist.
- **Python 3.10+** and **Node 18+**.
- Pipeline model IDs default to the author's routing (`claude-fable-5` for planning,
  `claude-sonnet-5` for building, `claude-opus-4-8` for review). If your install
  doesn't resolve those ids, override with `NOIRDECK_MODEL_THINK` /
  `NOIRDECK_MODEL_BUILD` / `NOIRDECK_MODEL_REVIEW`.
- Pipelines run `claude -p` with `--permission-mode acceptEdits`, inside the
  PreToolUse guard described below.

## Run it

```bash
# backend
python3 -m venv .venv && .venv/bin/pip install -r backend/requirements.txt
# frontend
cd frontend && npm install && npm run build && cd ..
# serve (dev)
.venv/bin/uvicorn app.main:app --app-dir backend --port 4747
# or install the systemd user service (survives logout via linger)
mkdir -p ~/.config/systemd/user && cp ops/noirdeck*.{service,timer} ~/.config/systemd/user/
systemctl --user daemon-reload && systemctl --user enable --now noirdeck.service
```

Config (env): `NOIRDECK_CLAUDE_DIR` (default `~/.claude`), `NOIRDECK_PROJECTS_DIR`
(`~/projects`), `NOIRDECK_DB_PATH`, `NOIRDECK_PRIMARY_NAMESPACE` (defaults to your
home-directory namespace), and the master arming flags `NOIRDECK_MINING_ARMED` /
`NOIRDECK_OVERNIGHT_ARMED` (default **off**; arming also requires a live,
expiring contract created in the Queue view).

State: single SQLite file (`data/noirdeck.db`, WAL, additive-only migrations).

## Development

```bash
.venv/bin/python -m pytest backend/tests -q   # full suite
cd frontend && npm run build                   # SPA build
```

Stack: FastAPI + SQLite, React 18 + Vite, xterm.js, headless `claude -p` runners
with pinned model IDs per task class. UI meets WCAG 2.1 AA: full keyboard
operability, focus management and dialog traps, screen-reader landmarks and
labels, AA contrast throughout, `prefers-reduced-motion` respected.

![workspace](docs/screenshots/workspace.png)

## Keyboard

| Key | Action |
|-----|--------|
| `1` – `0` | jump between views |
| `Ctrl+K` | command palette — skills, shortcuts, tips |
| `Ctrl+B` | expand / collapse the sidebar |
| `?` | quick keys + full Claude Code reference |
| `Esc` | close overlays |

## License

MIT — see [LICENSE](LICENSE).
