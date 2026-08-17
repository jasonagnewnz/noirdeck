# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and the project uses semantic-style `0.x` versioning while pre-1.0.

## [0.26.0] - 2026-08-16
### Changed
- **The sidebar is now the daily loop only** — Home, Build Live, Guided Builds,
  Tasks, Review, History, Guide. Design, Helpers, Knowledge and Checks moved
  behind a new Settings view (the gear below the rail, or press `0`). Nothing
  was removed: each keeps its own link and works exactly as before.
- **Settings** also collects the switches you set once — theme, what background
  automation is armed, which assistants this machine can run and their models.
- Claude's model list refreshed to the line that ships today: Fable 5, Opus 5,
  Sonnet 5 and Haiku 4.5. The review role moves from Opus 4.8 to Opus 5, and
  Opus 5 and Haiku 4.5 are now selectable at all — previously the picker could
  only ever contain the three models the pipeline roles happened to pin.

## [0.25.0] - 2026-08-16
### Added
- **Mono Dark and Mono Light themes**, and Mono Dark is now the default UI:
  greyscale structure with a single crimson accent, so anything coloured is
  asking for attention. Both meet the existing contrast contract.
- `ops/check-contrast.mjs` measures every theme's tokens against that contract
  and now runs in CI, so a token edit can no longer quietly fail AA.
- **Your backup**, on the front page: what noirdeck copies, what it never
  copies and why, and how long ago a restore was last actually verified.

### Changed
- **History search groups near-identical prompts**, collapsed by default, with
  a repeat count and an expander. Grouping uses the same normalisation as the
  skill miner, so what you see grouped is what becomes a proposal.
- **The backup now covers your whole Claude setup**: settings, custom slash
  commands, agent memory and loose notes join the skills, agents, rules, docs
  and project memories already kept. `.credentials.json` is explicitly never
  copied — a backup of a live token is a second token to steal — and the set
  is declared once so the disclosure cannot drift from the behaviour.

## [0.24.0] - 2026-08-16
### Added
- **Installable distribution.** `pipx install noirdeck` (or `uv tool install`)
  then `noirdeck` — the built web UI ships inside the package, so an installed
  copy needs no checkout and no build step.
- `noirdeck` CLI: `serve` (the default), `doctor` (reports what is set up and
  what is missing), and `run <job>` to run one scheduled job in the foreground.
- **In-process scheduler** for the recurring jobs, so installs need no systemd
  and behave the same off Linux. A source checkout keeps using the systemd
  timers; `NOIRDECK_SCHEDULER` overrides either way. Every job stays fail-closed
  behind its own arming contract, and failures are audited, never silently skipped.
- `GET /api/scheduler` reports mode and next due times.
- Release workflow: builds the wheel on a version tag, verifies tag/version
  agreement, smoke-tests the built artifact, signs artifacts and SBOM keylessly
  via OIDC, and publishes to PyPI with trusted publishing.
### Changed
- The Python package is now `noirdeck` (was `app` — too generic to install
  safely into a shared site-packages).
- State locations follow the install mode: a checkout keeps `data/noirdeck.db`,
  an installed copy uses the XDG data directory so uninstalling never eats data.
### Fixed
- The SPA route no longer serves files resolved outside the build directory.

## [0.23.1] - 2026-08-16
### Added
- Frontend test suite (Vitest + React Testing Library, 16 tests): hash-router
  behavior, ImprovePanel fail-closed controls and merge-target confirm,
  GuidedCard stepper truth, plan gate, and evidence-backed acceptance checks.
  Wired into CI ahead of the production build.

## [0.23.0] - 2026-08-16
### Added
- `pyproject.toml` with PEP 621 project metadata, pinned `requires-python`, and Ruff configuration.
- Biome for frontend linting and formatting (`npm run lint`, `npm run format`).
- `backend/requirements.lock` freezing the full transitive Python dependency set.
- `.python-version`, `frontend/.nvmrc`, and an `engines` field pinning runtime versions.
- `CHANGELOG.md` and `CONTRIBUTING.md`.
### Changed
- Whole-codebase format pass (Ruff for Python, Biome for the frontend); behavior unchanged, verified by the full test suite and a production build.
- Removed redundant default `React` imports (automatic JSX runtime).

## [0.22.0] - 2026-08-14
### Added
- Terminal: WebGL renderer with robust scroll/resize, copy-screen and copy-session export.

## [0.21.0] - 2026-08-14
### Added
- Help view: a full in-app manual with deep-linkable sections (`#help:<section>`).
### Changed
- UI coherence pass: every view shares one anatomy (title, function line, help link); Quality view untangled.

## [0.20.0] - 2026-08-14
### Added
- Token-economy routing: weight-staged queue (light/heavy), deterministic context packs, conditional review policy, digest spend line.

## [0.19.0] - 2026-08-14
### Added
- Five accessibility features: recipe cards, try-it preview, universal undo for applied proposals, deterministic digest, caged read-only ask.

## [0.18.0] - 2026-08-14
### Changed
- Builds page redesign: builds-first layout, hash routing with deep links, phase-chip status now reflects the best outcome per phase.

## [0.17.0] - 2026-08-14
### Added
- Estate improve targets beyond repos (skills, memory notes), individually armed with expiry; proposals carry unified diffs.

## [0.16.0] - 2026-08-14
### Added
- Decision learning for improve proposals; pause/resume workspace sessions across restarts.
### Fixed
- Bug-check hardening across the queue runner, improver, and router.

## [0.15.0] - 2026-08-14
### Added
- Per-repo local-model picker for Improve; reasoning-model generation fix.

## [0.14.0] - 2026-08-13
### Added
- Improve: a small local model proposes documentation tidy-ups in a trust cage (temp worktree, AST-verified code-unchanged, human merge).

## [0.13.0] - 2026-08-13
### Added
- Vault: encrypted offsite backup with verified restore and retention.

## [0.12.1] - 2026-08-13
### Changed
- Raised type and icon scale one step.

## [0.12.0] - 2026-08-13
### Added
- Guided Build: plain-English intake, plan approval gate, narrated phases, deterministic evidence pack; eight built-in themes.

## [0.11.0] - 2026-08-13
### Changed
- WCAG 2.1 AA pass (axe-verified); product renamed noirdeck.

## [0.10.0] - 2026-08-13
### Added
- Enforced guardrails (pre-execution deny hooks for pipeline sessions) and expiring arming contracts.

## [0.9.0] - 2026-08-13
### Added
- Hygiene engine: auto-dedupe/tidy findings for memories and skills, propose-only.

## [0.8.0] - 2026-08-13
### Added
- Full CLI reference in the quick-keys menu.

## [0.7.0] - 2026-08-13
### Added
- Quick keys: digit view-jumping, `?` cheat sheet, sidebar hints.

## [0.6.0] - 2026-08-13
### Added
- Crimson/black theme and pop-out sidebar.

## [0.5.0] - 2026-08-13
### Added
- IDE shell: activity bar, lazy file explorer, read-only file tabs, command palette, code actions; read-only project file APIs.

## [0.4.0] - 2026-08-13
### Added
- Design Studio: parallel mock directions in staging with a human apply gate; build resume and crash hardening; hosted service units.

## [0.3.0] - 2026-08-13
### Added
- Builds mode: unattended five-phase build pipeline with QA gates between phases; browser-boundary hardening; pagination everywhere.

## [0.2.0] - 2026-08-13
### Added
- Workspace: real CLI sessions in the browser over PTY + WebSocket.

## [0.1.0] - 2026-08-12
### Added
- Initial release: local companion console — live estate overview, transcript mining, QA gates, overnight queue.
