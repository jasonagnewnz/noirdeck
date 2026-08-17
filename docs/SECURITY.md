# Security

## Boundary and accepted risk
- Binds `127.0.0.1` only. Single local user. **No auth layer — an explicit, documented risk acceptance** because the transport boundary is the loopback interface. If this is ever exposed (tunnel, LAN bind), an auth layer MUST be added first; do not expose as-is.
- The app reads `~/.claude`, which may contain sensitive project data and occasionally secret-shaped values inside transcripts. Noirdeck itself does not ship data to a cloud service directly. When you choose a cloud-backed CLI runtime such as Claude or Codex, that CLI may send prompts, repo context, and takeover handoff text through its own authenticated provider path. Ollama local runs stay on the machine.

## Redaction (miner/redact.py)
Secret-shape patterns (AWS keys, GitHub PATs, Anthropic/OpenAI keys, Slack/Google tokens, JWTs, private key blocks, `password=`/`secret:` assignments, bearer headers) are stripped before any transcript text reaches an LLM prompt. Redaction counts are logged; raw matched values never are.

## Write authority
- The only write path into `~/.claude` is proposal approval: allowlisted roots (`skills/`, `projects/<home-namespace>/memory/`), realpath-checked against traversal, no silent overwrite, audit-logged.
- Overnight runner edits only inside the task's project directory. Claude-backed runs use Claude Code's permission model and the pipeline guard; other configured runtimes follow that CLI's own sandbox/auth model. Runs are instructed and audited to stop short of push, deploy, or outward-facing action.

## Browser boundary (v0.3.0)
Loopback binding does not stop the user's own browser being turned against the API:
DNS rebinding defeats "only on 127.0.0.1", and WebSockets have no same-origin policy.
Every HTTP request and the workspace WebSocket therefore enforce a **Host allowlist**
(127.0.0.1 / localhost — kills rebinding) and an **Origin allowlist** (kills cross-site
requests and cross-origin WS hijack). Requests without an Origin (curl, local tools)
pass the Host check only — a non-browser attacker on this box is the same OS user and
out of scope. Covered by tests.

## Workspace terminal (v0.2.0)
The Workspace WebSocket is **shell-equivalent access** and is treated as such:
- The browser never supplies a command. The server spawns only the fixed `claude`
  / `codex` / `ollama` / configured-runner argv for a server-owned runtime id
  (optionally `--resume <validated-id>` for Claude or an initial prompt string)
  in a cwd that must resolve to a git repo under the projects dir.
- Client messages are keystrokes and resize events only; max 6 concurrent sessions.
- Runtime auth is the machine's existing CLI auth. The platform stores no provider credentials.
- Takeover starts a new session with a recent terminal-context handoff. Treat that handoff like prompt text sent to the target runtime; choose Ollama local when the handoff must stay on the machine.
- This is exactly why the localhost-only rule above is load-bearing: exposing this
  port would hand out interactive sessions. Never tunnel it without adding auth.

## Apply-a-UI mocks (v0.4.0)
Generated mocks are untrusted LLM-authored HTML. They are produced in a staging dir
(never the target repo), served only with `Content-Security-Policy: sandbox; default-src
'none'` and rendered in `<iframe sandbox>` — zero script authority. Variant keys and
round ids are strictly validated against path traversal. Applying a design to a real
repo is an explicit human action per round.

## Fail-closed switches
- Startup fails if `NOIRDECK_CLAUDE_DIR` doesn't exist.
- LLM mining: refuses unless `NOIRDECK_MINING_ARMED=true`.
- Overnight runner: refuses unless `NOIRDECK_OVERNIGHT_ARMED=true`; per-run batch/turn caps bound cost.

## Logging
Structured app log; never logs secret values, redaction matches, or transcript bodies. Audit log records actor/action/target for every write and every overnight run.
