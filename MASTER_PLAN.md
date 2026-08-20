# noirdeck — plan and standing decisions

A local companion console for a Claude Code estate. This file records the load-bearing
decisions and the assumptions behind them; docs/ carries the operational detail.

## Decisions
- **Local-only by design.** Binds 127.0.0.1; Host+Origin allowlist; no auth layer —
  explicitly risk-accepted for a single-user loopback tool (docs/SECURITY.md). Exposing
  it wider requires adding auth first.
- **Propose → approve is the only write path** into `~/.claude`, allowlisted to
  `skills/` and the primary memory namespace, traversal-checked, audited.
- **Enforcement over instruction.** Headless pipeline sessions launch with a PreToolUse
  guard (ops/pipeline-guard.py) that denies push/publish/deploy/remote access before
  execution, and denies any write into `~/.claude`. Prompt guardrails remain as the first
  line, never the boundary.
  > **Fixed 2026-08-19.** This was TRUE IN A CHECKOUT AND FALSE IN THE SHIPPED WHEEL
  > for the product's whole life: the guard lived in `ops/`, `pyproject` packages only
  > `backend/noirdeck`, so it was absent from every wheel and `guard_settings_args()`
  > returned `[]` — unattended sessions ran with `--permission-mode acceptEdits` and no
  > hook at all. It passed every test, because tests run in a checkout where `ops/`
  > exists. The guard now lives at `backend/noirdeck/pipeline_guard.py`, is invoked by
  > path beside its own module (⛔ NOT `-m`, which is the mirror-image trap: works in a
  > wheel, fails in a checkout where `backend/` is not on `sys.path`), and **fails
  > closed** — a missing guard now refuses to start a pipeline instead of warning to a
  > daemon's stderr. Asserted against an INSTALLED WHEEL in the release workflow and in
  > `test_packaging.py`. Keep `pipeline_guard.py` stdlib-only or the path invocation
  > breaks.

- **Arming is a contract, not a switch**: env master flag AND a live, expiring,
  task/token-budgeted contract, re-checked before every task.
- **Additive-only migrations** with a schema high-water mark; single SQLite file of
  rebuildable derived state + proposals/queue/audit.
- **Zero-egress UI**: no external fonts/scripts/assets; all transcript text passes
  secret-shape redaction before any LLM prompt.

## Assumptions the operator should review
- The `claude` CLI is installed and authenticated for live sessions and pipelines;
  model IDs are configurable via `NOIRDECK_MODEL_*` and default to the author's routing
  preferences. The console itself no longer REQUIRES it: as of 2026-08-19 a missing
  `~/.claude` is reported, not fatal (it used to exit 1 on first run, for any runner,
  which contradicted the Codex/Ollama/"bring your own CLI" promise).
- QA gates and fleet boards assume conventional git repos under one projects dir.

## Definition of done (per release)
Tests green by exit code, SPA builds clean, axe-core WCAG 2A/2AA zero violations on the
main surfaces, docs updated with the change, version bumped, audit log covering every
new state-changing action.
