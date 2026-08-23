# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and the project uses semantic-style `0.x` versioning while pre-1.0.

## [0.29.0] - 2026-08-23
### Added
- **It knows what machine it is on.** On WSL there is a Linux home and a Windows
  profile, each with its own `.claude` and its own `.codex`, and noirdeck read
  one of them and called it the estate. It now reports the platform and, on WSL,
  the version, distro, whether interop is live and where the Windows profiles
  are, then looks for sixteen assistant runtimes on both sides. A configuration
  directory with no local binary is exactly the environment across the boundary
  this exists to surface. `GET /api/environment`, and the tail of `noirdeck doctor`.
- **A licence key has somewhere to go.** Settings shows what the server says about
  the current licence and, when one is actually required, a field to install it.
  On an unlicensed build it says so and offers no field.

### Changed
- **The console sends security headers, and one of them closes a real hole.** The
  Host and Origin allowlists stop a cross-origin page calling the API and do
  nothing about a page framing the console: any site could have embedded it in an
  invisible iframe and harvested a click on Approve from someone who never saw the
  screen. Consent that can be clickjacked is not consent. `frame-ancestors 'none'`
  now, with a CSP naming no external origin, nosniff, and no referrer. The policy
  carries a hash of the pre-paint appearance script rather than allowing inline
  script, because blocking that script silently reintroduces the flash it exists
  to prevent.
- Thirteen ARIA attributes sat on elements whose role does not support them, so
  assistive technology ignored every one. The build stepper carried hand-written
  labels for each phase, announced to nobody; it is a real list now. Thirty-one
  buttons gained the explicit type they lacked.

### Fixed
- **The published artifact had drifted from the source.** The download served a
  build made before the changes above, and because the version had not moved,
  nothing anywhere reported it. A release check now fails when the artifact the
  installer would fetch does not match the version in the tree.

## [0.28.0] - 2026-08-22
### Added
- **Three interface kits: Carbon, Fluent and Claude.** A kit sets type, corner
  radius, density and the accent family together, so they are structural choices
  rather than three colour schemes. Carbon is square-cornered on an eight-pixel
  grid; Fluent is cool, layered and softly rounded; Claude is warm neutrals and a
  clay accent. Carbon dark is the new default.
- **Four independent dials instead of a list of skins**: kit, mode (dark, light
  or match the system), density and text size. Because they are independent,
  three kits cover six palettes without six lists to keep in step. Density and
  text size are accessibility rather than taste, and neither was adjustable
  before. Kit switches from the status bar; all four live in Settings.
- **A terminal panel that belongs to the shell**, opened with Ctrl+` from any
  view, resizable by drag or keyboard and remembered between visits. Until now
  the only terminal lived inside Build Live, so checking a running session meant
  leaving whatever you were reading. Build Live still owns the full viewport, and
  the panel stays out of its way there rather than running a second emulator.

### Changed
- **Design tokens are named for their role, not their colour.** `--amber` held
  crimson and `--teal` held dark red, which is how two earlier themes came to set
  the accent to red and make an alarm panel look like ordinary UI. The vocabulary
  is now `--surface-*`, `--text-*`, `--accent`, `--danger`, `--warning`,
  `--success`, plus `--radius`, `--row-h` and `--space` so a kit can change shape
  and density and not only hue. 548 references rewritten.
- **CI now enforces that the accent is perceptually distinct from the alarm
  colour**, measured as CIE76 distance in Lab, alongside the existing WCAG ratios
  for all six palettes. This is the rule that makes adding a kit safe, and it
  rejected two candidate palettes while these three were being built.
- **Appearance is applied before the first paint.** Palettes moved out of
  JavaScript into the stylesheet, and a small inline script in `index.html`
  stamps the stored dials. Light mode used to flash dark on every load while the
  bundle parsed, because the tokens only landed once React had mounted.
- Seven views are now loaded on demand. Initial JavaScript falls from 369 KB to
  298 KB, 111 KB to 92 KB compressed, and the terminal emulator moved into a
  shared chunk that loads when a terminal is actually opened.

### Fixed
- Three design tokens were referenced but never defined, so each silently fell
  back to a colour hardcoded at the call site, including a stray red border. A
  further 22 `var()` fallbacks named colours from themes deleted in August, which
  meant a stylesheet that failed to load painted a palette the product no longer
  had.
- The README described eight themes, and a tagline promised nine more plus one
  named Calm Pro. All of them were deleted on 19 August.

## [0.27.6] - 2026-08-19
### Added
- **Share what happened in a session, without sharing the session.** A Share button in
  the terminal exports a readable Markdown transcript you can send however you already
  send things. Stage 0 of session sharing, and deliberately all of it for now: no socket
  is opened, nothing binds beyond loopback, no invite exists and no second identity is
  introduced — so the auth layer `docs/SECURITY.md` requires before the workspace is
  exposed is not bypassed.
- ⛔ **The export redacts first, says what it removed, and then re-scans its own output.**
  A transcript is a disclosure channel: this estate found a sudo password in a generated
  skill file and 125 distinct secrets across its workspace, all from text that was "just"
  printed once. If the scanner still matches something after redaction, the document says
  **CHECK BEFORE SENDING** and the UI warns before the file is saved — because redaction
  matches known secret shapes, and a password that looks like an ordinary word survives it.
- Exports are audited. "Who shared what, when" only has an answer if it was recorded then.

## [0.27.5] - 2026-08-19
### Added
- **Move many leaking files at once, safely.** `GET /api/secrets/sweep` returns a plan
  grouped by file — moving nothing — with the session-loading files (`skills/`, `agents/`,
  `rules/`, `CLAUDE.md`, anything under `memory/`) listed first, because those are the ones
  actively being read. `POST` moves them, one file at a time, through the same
  single-file path so a bulk action cannot do anything a single action could not.
- ⛔ **There is deliberately no "move everything" call.** The plan hands back an explicit
  id list and confirming means confirming *those* ids: on this estate, irreversible
  actions are selected by id and never by a filter, a status or a time window, because a
  bulk action driven by a query does whatever the query happened to match at that moment.
  An empty id list refuses rather than meaning "all".
- `docs/SECRET_HYGIENE.md` — what to do after a finding, in the order that matters, and
  where credentials should live instead. Leads with the thing people get wrong: moving or
  deleting the file does not fix anything, because the credential is already in git
  history, transcripts and backups. Rotation is the fix; moving only stops the bleeding.

## [0.27.4] - 2026-08-19
### Added
- **`noirdeck do "..."` — a task from the terminal, no browser, no clicks.** Runs now and
  prints a structured verdict, or `--later` to hand it to the unattended runner. The
  project defaults to the git repo you are standing in, because being made to name it is
  the friction that makes a CLI feel slower than clicking. A repo outside the projects
  dir is refused rather than silently worked in.
- **`noirdeck status`** — one screen of "is anything wrong", worst news first: unresolved
  credential findings, then whether unattended work can actually run, then what is
  waiting on you. Exits non-zero when there are open findings so it is scriptable, and
  `--json` for machines.
- `do` deliberately delegates to the queue's own task path rather than growing a second
  implementation: it gets the context pack, the operating guardrails, the PreToolUse
  guard, the staged plan/build/check and the verdict, and a test pins that it keeps
  doing so. It also respects the licence gate — the terminal is not a way around it —
  and arms only when nothing is live, never widening a budget you set.

## [0.27.3] - 2026-08-19
### Changed
- **Commercial use is free during Early Access.** LICENCE amended to v1.1: a new clause
  3A grants a Commercial Licence at no charge, and clauses 1.7 and 3.1 no longer require
  a purchase that cannot be made — previously a business installing noirdeck was in
  technical breach through no fault of its own, because the agreement demanded a paid
  licence and there was no way to pay. Charging will not begin without at least 60 days'
  written notice to every licence holder, and a term already granted will not be
  shortened.
- ⛔ **The licence text ships inside the wheel**, so amending it only reaches anyone on a
  release — and installing is what constitutes acceptance. This version exists so the
  published artifact carries v1.1 rather than v1.0. No release has been published yet, so
  nobody has accepted v1.0.
- No product change was needed: price is orthogonal to the key mechanism. The licence
  gate, the 402 response and manual issuance are unchanged, deliberately — there is no
  revocation by design, so an install that ever ran ungated would stay ungated forever.

## [0.27.2] - 2026-08-19
### Changed
- **One word per concept.** Six of twelve navigation items called the same thing two
  different names: you clicked Knowledge and landed on Memories, clicked Tasks and
  landed on Run later. Now Memories, Skills, Tasks, Builds, Checks and Guide, in the
  rail and on the page. A test pins the relationship rather than the strings, and it
  immediately caught a seventh (Build Live / Build live).
- **One way to begin.** Home offered five: an intent bar, four mode cards, a project
  strip, a ten-category builder and an ask box. The bar was always sufficient — its
  submit only ever needed a project, not typed text — so the cards and the strip are
  deleted and the builder is a closed disclosure. The placeholder now says the text is
  optional instead of implying it is required.
- **Nine of eleven themes deleted.** One dark, one light. The other nine cost a
  contrast-checking script to keep honest and caused a real defect: in two of them the
  accent was red, so an alarm panel rendered indistinguishable from ordinary UI.
- **The Guide left the primary rail.** 2,563 words of manual beside the seven things
  you do is the UI admitting it needs one. Still a first-class view, still one click
  from every screen's "how this works", and a test pins that it stays reachable.
- **Every blocking browser dialog is gone** — all nine. Destructive actions confirm in
  place with a verb, not a paragraph: one ran to four sentences, and a confirmation
  nobody reads is a speed bump with a false conscience. Consequences moved to beside
  the control, where they can be read before the click.
- **"Run later" now runs later.** Queuing used to need arming first, on another screen,
  with three numbers to invent — and queuing while unarmed accepted the task and then
  silently never ran it. Queuing is the intent, so it arms with a modest default budget
  and says what it armed. An existing budget is never widened.
- **One screen answers "will my background work run?"** Scheduler liveness and arming
  contracts each held half the answer, and half an answer in two places is how a user
  concludes the product is broken when it is merely off.

### Performance
- **A cold page load went from 43.9 seconds to 0.42 seconds.** Rendering a summary of
  the memory tree parsed frontmatter from every file — 19,163 files on a real estate —
  behind a 120-second cache that hid it from the second visit and from nobody's first.
  Walking the same tree with stat() costs 0.15s, so the parse is now cached on disk
  keyed by (path, mtime, size). The key is both fields because a same-second rewrite
  that changes length is common and mtime resolution alone misses it.

### Fixed
- Restored `.visually-hidden`, `.skip-link` and `.skip-link:focus`, which an automated
  deletion of dead theme CSS consumed along with its target — every screen-reader-only
  label rendered visibly and the skip link lost its off-screen position. Caught by
  looking at a screenshot; no test would have. Automated CSS surgery must be verified
  by diffing the selector set.

## [0.27.1] - 2026-08-19
### Security
- **The pipeline guard now ships.** It lived in `ops/`, which `pyproject` does not
  package, so it was absent from every wheel: `guard_settings_args()` returned `[]`
  and unattended sessions ran with `--permission-mode acceptEdits` and no
  PreToolUse hook at all — no code-ready boundary and no protection for your
  memories, skills or CLAUDE.md. It passed every test, because tests run in a
  checkout where `ops/` exists. It now lives inside the package and is invoked by
  path beside its own module; the release build asserts it is present in the
  installed wheel and that it actually denies a write, alongside the existing SPA
  and licensing checks.
- **A missing guard now fails closed.** Previously it warned to stderr and
  continued, which in a background process is an inert control. No boundary, no
  pipeline.

### Fixed
- **A brand-new install starts.** `Settings.load()` raised when `~/.claude` was
  absent, so a first run exited 1 instead of opening a console — for any runner,
  while Codex, Ollama and "bring your own CLI" need no Claude directory at all.
  The default location is created; an explicitly-named one is never fabricated,
  because that would hide a typo. Health, `doctor` and Home now report a missing
  workspace, so "nothing here yet" and "cannot see your workspace" are no longer
  indistinguishable.
- Licence messages no longer send you somewhere that cannot help: keys are not
  being issued yet, and the product says that instead of "sign up to get one".
- The gated-feature list explains itself. "mining" read as though mining did not
  work, when the instant local pass is free and only the model pass is paid.
- Background work is visible in Settings — whether the scheduler is actually
  running and when each job is next due. Nothing reported this before, so a
  stopped scheduler looked exactly like a quiet night.
- The backup panel names which prerequisite is missing rather than one of three.

### Added
- `docs/LICENCE_KEY_CUSTODY.md` — custody requirements, a restore rehearsal that
  has been performed, and the compromise procedure, written before it is needed.
- `docs/ISSUING_LICENCES.md` — the manual issuance runbook, and why automating it
  is a design task rather than an extension.
- `PROJECT_PLAN.md` — the launch remediation plan this release works through.

## [0.27.0] - 2026-08-19
### Security
- **A pipeline session can no longer modify your AI workspace.** The PreToolUse
  guard was registered for `Bash` only and also allowed any non-Bash tool
  internally, while every unattended session runs with `--permission-mode
  acceptEdits` — which auto-approves file writes. An overnight, guided or design
  session could therefore rewrite `CLAUDE.md`, a memory file or a skill with
  nothing in the way, and the Bash deny list matched no filesystem writes either.
  The guard now inspects `Write`/`Edit`/`MultiEdit`/`NotebookEdit` as well as
  Bash, resolves candidate paths with `Path.resolve()` so `~`, `$HOME`, `./`,
  `../` and symlinks all collapse to one real path, and denies writes anywhere
  under the Claude config directory. Reading it is still allowed — that is the
  point of the miner.
- **Applying a proposal is create-only.** `approve()` refuses a target that
  already exists and the `overwrite` parameter is gone rather than defaulted off,
  so there is no route — API or UI — by which noirdeck replaces a file it did not
  create. Improvements to existing files now land beside the original as
  `<name>.noirdeck-proposed.md`, which the harness does not load, for a human to
  merge.
- **New credential scanner** for the workspace, after a generated skill file was
  found holding a password in cleartext. Runs nightly at 02:00, deliberately
  ahead of mining at 02:30, and on demand. A finding never carries the secret:
  detector, file, line, a SHA-256 fingerprint prefix, and the source line with
  the value replaced rather than truncated. Report-only — acknowledging changes
  no file, and quarantine moves the whole file by explicit id after you confirm,
  and tells you plainly that rotation is still required.

### Removed
- **The two keyword-based proposal generators.** Skill drafting called a repeated
  prompt a "skill gap" whenever half its long words were absent from existing
  skill vocabulary, and memory consolidation grouped files that shared a single
  filename token. Against a real estate of 18,062 memory files the latter
  produced 96 "consolidation candidates" led by the token `2026` with 166
  members — every date-suffixed file in the namespace. The former had written ten
  draft skills to disk, among them a pasted filesystem path and a username.
- Filename-token clustering is gone from the Knowledge view and `/api/memories`
  with it.

### Added
- **Proposals now require evidence.** A skill draft exists only when a model has
  read the material and supplied a quoted excerpt, a cited source transcript, a
  trigger phrased "Use when …", and at least three occurrences. The model's own
  candidates were previously discarded while the keyword heuristic did the
  proposing; that is now the only path. Rejections are audited with the reason.
- **Take over a running task.** A running unattended task can be claimed from
  Tasks: the headless run stops and its conversation reopens as a terminal you
  can type into, in the same repo. Claimed is a distinct outcome from done and
  failed, so the runner neither reports your work as a failure nor picks the task
  back up.
- **Local models, for people who do not want to learn any of this.** A Settings
  section that measures what the machine can actually run, installs Ollama into
  your home folder with no admin rights, starts it, and recommends a model by
  what it is FOR. Models that do not fit are shown as out of reach with the
  reason rather than hidden. Nothing installs or downloads without confirmation,
  and the size is stated first.
- `ops/preview-shots.py` — deterministic screenshots of the console against
  synthetic data, for documentation without exposing real projects.

### Changed
- **One obvious way to start.** "Start building" was a single row of eight
  controls in which the primary action looked like just another option; it is now
  one project picker and one button that names the repo it will open, with helper,
  model and new-project behind closed disclosures. Home gains a matching strip
  directly under the hero, above the essentials builder.
- **The terminal is readable again.** Jump to top and bottom, a "scrolled back"
  marker so a paused view does not read as a hung session, and a wider,
  always-visible scrollbar with a tracked channel. In a full-screen TUI the jump
  controls disable themselves and say why, because the alternate buffer genuinely
  keeps no scrollback.

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
