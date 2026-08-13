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
  execution. Prompt guardrails remain as the first line, never the boundary.
- **Arming is a contract, not a switch**: env master flag AND a live, expiring,
  task/token-budgeted contract, re-checked before every task.
- **Additive-only migrations** with a schema high-water mark; single SQLite file of
  rebuildable derived state + proposals/queue/audit.
- **Zero-egress UI**: no external fonts/scripts/assets; all transcript text passes
  secret-shape redaction before any LLM prompt.

## Assumptions the operator should review
- The `claude` CLI is installed and authenticated; pipeline model IDs are configurable
  via `NOIRDECK_MODEL_*` and default to the author's routing preferences.
- QA gates and fleet boards assume conventional git repos under one projects dir.

## Definition of done (per release)
Tests green by exit code, SPA builds clean, axe-core WCAG 2A/2AA zero violations on the
main surfaces, docs updated with the change, version bumped, audit log covering every
new state-changing action.
