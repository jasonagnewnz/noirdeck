# noirdeck

**The dark console for your Claude Code estate.** A local companion platform —
live dashboard, IDE-feel workspace, autonomous pipelines with enforced guardrails,
and a plain-English front door for people who don't read code, all at
`http://127.0.0.1:4747`, all on your own machine, nothing leaving the box.

> Crimson on warm black, scanlines, one signal colour. Noir by design.

![overview](docs/screenshots/overview.png)

## What it does

**Sees the whole estate, live**
- Reads `~/.claude` — skills, agents, memory namespaces, session history — and
  `~/projects` (the git fleet), refreshed by a filesystem event stream (SSE).
- **The morning digest**: the Overview opens with "while you were away" in plain
  English — what finished overnight, what's stuck with a question for you, what's
  waiting on your approval, when your last *verified* backup ran, and what the
  automation spent. Every line assembled deterministically from state, never by
  a model.
- **Ask your estate**: type a question ("which projects have unpushed work?") and
  a read-only session answers it from your actual files — its tool set is
  Read/Grep/Glob only, so it *cannot* change anything while answering.
- Estate overview: stat tiles, open loops (sessions that ended unfinished), fleet
  attention (uncommitted/unpushed work), follow-on radar, session history
  intelligence over every prompt ever typed.

**Works like an IDE**
- VS Code-style shell: activity bar (pops out to a labelled sidebar, `Ctrl+B`),
  status bar with live telemetry (stream state, pending approvals, backup age),
  command palette (`Ctrl+K`), quick keys (`1`–`0` views, `?` cheat sheet with the
  full Claude Code reference, verified against the installed CLI).
- Workspace: real `claude` sessions in the browser (PTY + xterm), project file
  explorer, read-only file tabs with syntax highlighting — and sessions can be
  **paused across restarts and resumed later**, exact conversation and all.
- Views deep-link (`#builds`, `#queue`…): refresh, bookmarks and the back button
  keep your place.

**Builds software for you — no code knowledge required**
- **Guided Build**: pick a **recipe card** (a booking page, a team tracker, a
  quote calculator…) or answer a short plain-English interview; the tool compiles
  a professional brief, plans first, and **parks for your approval** — nothing is
  built until you approve the plan in plain English. It finishes with your own
  acceptance checklist and a deterministic evidence pack (commits, tests, gates)
  assembled by code, not a model.
- **Try it**: when a finished build has a web page, a *try it — see it working*
  button opens the actual app in a sandboxed frame, right on the build card.
  You judge software by using it, not by reading a report.
- **Builds (expert)**: full brief in → code-ready software out. Five phases
  (plan → build → test → review → finish) with per-phase model routing, QA gates
  run *between* phases outside the LLM, crash-nets, and resume from the last
  completed phase. Stops at code-ready. Never ships.
- **Overnight queue**: ticket-shaped tasks run one at a time via headless Claude;
  anything uncertain parks as a question and the night moves on.
- **Design Studio**: propose a brief → three parallel design directions
  (8-direction × 6-library deck: Fluent 2, Material 3, IBM Carbon, Ant, shadcn,
  or bespoke) rendered as sandboxed live mocks → human Apply gate.

**Improves itself quietly, and protects its own memory**
- **Improve**: a *local* model (via Ollama — zero cloud calls, zero cost) quietly
  proposes docstring/comment/README improvements on branches, inside a trust
  cage: temporary worktree, AST-verified that executable code is unchanged, test
  gate, human merge. It **learns from your decisions** — kinds you keep
  discarding go quiet, per repo. Skills and memory notes can be targets too,
  each individually armed with an expiry, output only via proposals.
- **Miner + hygiene**: mines session history for skill gaps and drafts them as
  proposals; finds duplicate/oversized memory notes and proposes merges.
  Originals are never deleted by automation.
- **The Vault**: nightly encrypted offsite backup (restic) of your memories,
  skills, agents, rules and the noirdeck state — plus bundles of any repo with
  unpushed work — with an actual **restore test**, byte-for-byte verified. The
  status bar shows time since the last *verified* restore, because a backup that
  has never been restored is a hope, not a backup.

**Every applied change is reversible**
- Approving a proposal snapshots what it replaces. One click reverts it —
  restoring the previous content or removing the file the approval created — and
  it refuses to clobber hand-edits made since, unless you confirm. Fear of
  breaking things is the real barrier for non-experts; undo removes it.

## Cheap to run, by design

The harness is code, not model calls: the dashboard, digest, QA gates, evidence
packs, hygiene scans and briefings all cost **zero tokens**. Where models do run,
the spend is engineered:

- **Weight-routed tasks** — small tasks get one cheap session; heavy ones
  (architecture, migrations, security, long briefs) automatically stage
  *plan → build → check*: a thinking model plans in a **read-only cage** (it
  literally cannot edit), a cheaper model executes the brief, and a review model
  checks once. A failed plan falls back to single-session — staging never costs
  you a night.
- **Context packs** — the harness computes each project's briefing (layout, test
  command, recent commits, dirty state, memory index) *in code* and prepends it,
  so sessions skip their token-hungry discovery wander.
- **Reviews only when they earn it** — one deterministic rule decides whether a
  paid review pass can add value: security-flagged paths always review, anything
  unmeasurable reviews (fail-safe), and small clean changes with green gates
  skip it — logged, never silent.
- **A visible bill** — the digest reports what automation spent, daily, and
  arming contracts hard-cap tokens per run.

## The safety model

Four layers, all fail-closed:

1. **Enforced guardrails** — every headless pipeline session launches with a
   PreToolUse hook (`ops/pipeline-guard.py`) that denies `git push`, publishing,
   deploys, kubernetes/terraform mutation, and remote access *before execution*.
   Not a prompt instruction — a harness boundary, verified against a live session.
2. **Propose → approve → revert** — the only write path into `~/.claude` is
   proposal approval in the UI, allowlisted to `skills/` and one memory
   namespace, traversal-checked, audited, and reversible after the fact.
3. **Arming contracts** — autonomous subsystems (overnight, mining, improve)
   need the env master flag *and* a live contract: expiring, task-budgeted,
   token-budgeted, revocable, re-checked before every task. An armed system
   disarms itself.
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
- Optional: **[Ollama](https://ollama.com)** with a local code model for the
  Improve engine (everything else works without it).

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

First run is deliberately quiet: everything autonomous ships **disarmed**. You
get the dashboard, workspace, digest and builds immediately; overnight runs,
mining and the improver each need you to arm a contract in the Queue view first.

Config (env): `NOIRDECK_CLAUDE_DIR` (default `~/.claude`), `NOIRDECK_PROJECTS_DIR`
(`~/projects`), `NOIRDECK_DB_PATH`, `NOIRDECK_PRIMARY_NAMESPACE` (defaults to your
home-directory namespace), and the master arming flags `NOIRDECK_MINING_ARMED` /
`NOIRDECK_OVERNIGHT_ARMED` / `NOIRDECK_IMPROVER_ARMED` (default **off**).

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

![guided build](docs/screenshots/guided.png)

**Eight built-in themes** — noir (default), instrument, aurora, brutalist,
editorial, botanical, swiss, neo-material — switchable from the status bar,
every one verified to WCAG AA contrast.

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
