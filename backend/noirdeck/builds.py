"""Builds mode: full prompt in → production-quality software out, unattended.

Pipeline: plan → build → test-until-green → adversarial review → docs & finish.
- Model per phase follows the estate routing table (thinking on Fable, building on
  Sonnet, review on Opus 4.8) — pinned explicit IDs, never family aliases.
- Between phases the deterministic QA gates (qa.py) run OUTSIDE the LLM and their
  failures are fed into the next phase — a phase never grades its own homework.
- Hard boundary: the pipeline ends at CODE-READY. It commits locally but NEVER
  pushes, deploys, publishes, or calls external services. Shipping stays a human act.
- Each headless phase inherits the machine's Claude auth and the global CLAUDE.md,
  so estate governance applies inside every phase automatically.
"""

from __future__ import annotations

import json
import subprocess
import threading
import time
from pathlib import Path

from .config import Settings
from .db import audit, connect, utcnow
from .overnight import _parse_verdict, parse_cli_json
from .qa import evaluate_project
from .workspace import init_repo

GUARDRAILS = """

--- OPERATING RULES (non-negotiable) ---
1. Work ONLY inside this repository. NEVER git push, deploy, publish, send messages,
   or call external services. Local git commits at sensible points are required.
2. Follow the estate CLAUDE.md: security non-negotiables, never weaken tests,
   no hardcoded secrets, fail-closed defaults, docs are part of the product.
3. If something is genuinely undecidable without the owner, choose the most sensible
   reversible default, record it in MASTER_PLAN.md under "Assumptions", and continue.
   Only report blocked if continuing would make the work worthless.
4. End your FINAL message with exactly one line:
   VERDICT: {"status":"done"|"blocked","summary":"<2-3 sentences>","question":"<only if blocked>"}
"""

# (key, pinned model id, max_turns, phase instruction) — ids via config.model()
from .config import model as _model  # noqa: E402

PHASES: list[tuple[str, str, int, str]] = [
    (
        "plan",
        _model("think"),
        25,
        "PHASE 1 — PLAN. Design this software before any product code: write MASTER_PLAN.md "
        "(problem, decisions, data model, security model, assumptions, definition of done), "
        "docs/ARCHITECTURE.md, and scaffold the repo skeleton (.gitignore covering .env*, "
        ".env.example if config is needed, test harness wiring). Choose boring, operable "
        "technology. Commit when done.",
    ),
    (
        "build",
        _model("build"),
        80,
        "PHASE 2 — BUILD. Implement the software per MASTER_PLAN.md, small verifiable "
        "increments, tests alongside code. Fail-closed on missing config. If the software "
        "has ANY user interface, it must lead with design: read "
        "~/.claude/skills/frontend-design/SKILL.md if present and commit to one bold, "
        "coherent, enterprise-grade aesthetic (distinctive typography, committed palette "
        "via CSS variables, intentional composition, a few high-impact motion moments) — "
        "never default-looking, never purple-gradient-on-white AI slop. Commit when done.",
    ),
    (
        "test",
        _model("build"),
        50,
        "PHASE 3 — TEST. Run the full test suite and make it genuinely green: fix the code, "
        "never weaken or delete tests. Add missing tests for error handling, edge cases, and "
        "any security boundary. Actually execute the software once end-to-end and fix what "
        "breaks. Commit when done.",
    ),
    (
        "review",
        _model("review"),
        90,
        "PHASE 4 — ADVERSARIAL REVIEW. Review the whole repo as a hostile senior reviewer: "
        "security (input validation, secrets, injection, authz), correctness, data handling, "
        "operability — and design: if there is a UI, judge it as a demanding design director "
        "(would this pass as a polished enterprise product, or does it look generated?). "
        "FIX everything you find; re-run tests after fixes. Commit when done.",
    ),
    (
        "finish",
        _model("build"),
        60,
        "PHASE 5 — FINISH. Complete README.md (what it is, how to run it, how to verify it "
        "works), docs/RUNBOOK.md, and a final MASTER_PLAN.md status section listing all "
        "assumptions made and anything the owner should decide before shipping. Then verify "
        "BOUNDED: run the test suite once and one real end-to-end invocation; do NOT build "
        "fresh venvs/clean checkouts — that verification belongs to the owner's go-live. "
        "If deliverables already exist from a prior attempt, confirm rather than redo. "
        "Commit when done.",
    ),
]

PHASE_TIMEOUT_S = 2400  # 40 min per phase


class BuildRunner:
    """One background thread per build. claude_argv_base is injectable for tests."""

    def __init__(self, settings: Settings, claude_argv_base: list[str] | None = None):
        self.settings = settings
        self.claude_argv_base = claude_argv_base  # tests only
        self.procs: dict[int, subprocess.Popen] = {}

    # --- db helpers (each thread owns short-lived connections) ---
    def _db(self):
        return connect(self.settings.db_path)

    def _update(self, build_id: int, **fields) -> None:
        conn = self._db()
        try:
            sets = ", ".join(f"{k}=?" for k in fields)
            conn.execute(f"UPDATE builds SET {sets} WHERE id=?", (*fields.values(), build_id))
            conn.commit()
        finally:
            conn.close()

    def _row(self, build_id: int):
        conn = self._db()
        try:
            return conn.execute("SELECT * FROM builds WHERE id=?", (build_id,)).fetchone()
        finally:
            conn.close()

    def _append_log(self, build_id: int, entry: dict) -> None:
        row = self._row(build_id)
        log = json.loads(row["log"] or "[]")
        log.append(entry)
        self._update(build_id, log=json.dumps(log))

    # --- lifecycle ---
    def start(
        self, name: str, prompt: str, gated: bool = False, intake: dict | None = None, acceptance: list | None = None
    ) -> int:
        target = init_repo(self.settings.projects_dir, name)
        conn = self._db()
        try:
            cur = conn.execute(
                "INSERT INTO builds (name,path,prompt,status,created_at,gated,intake,acceptance) "
                "VALUES (?,?,?,'queued',?,?,?,?)",
                (
                    name,
                    str(target),
                    prompt,
                    utcnow(),
                    int(gated),
                    json.dumps(intake) if intake else None,
                    json.dumps(acceptance) if acceptance else None,
                ),
            )
            build_id = cur.lastrowid
            audit(conn, "operator", "build_started", f"id={build_id} name={name} gated={int(gated)}")
            conn.commit()
        finally:
            conn.close()
        threading.Thread(target=self._run, args=(build_id,), daemon=True).start()
        return build_id

    def decide_plan(self, build_id: int, action: str, feedback: str = "") -> None:
        """The Guided Build plan gate: the operator approves the plain-English plan
        (build continues) or requests changes (plan phase re-runs with feedback)."""
        row = self._row(build_id)
        if not row or row["status"] != "awaiting_plan":
            raise ValueError(f"build {build_id} is not awaiting plan approval")
        conn = self._db()
        try:
            if action == "approve":
                audit(conn, "operator", "plan_approved", f"id={build_id}")
                self._update(build_id, status="running")
                threading.Thread(target=self._run, args=(build_id, 1), daemon=True).start()
            elif action == "revise":
                if not feedback.strip():
                    raise ValueError("revise requires feedback")
                audit(conn, "operator", "plan_revision_requested", f"id={build_id} feedback={feedback[:120]}")
                new_prompt = (
                    row["prompt"] + f"\n\nOPERATOR FEEDBACK ON YOUR PREVIOUS PLAN (address it):"
                    f"\n{feedback.strip()[:2000]}"
                )
                self._update(build_id, prompt=new_prompt, status="running", plan_summary=None)
                threading.Thread(target=self._run, args=(build_id, 0), daemon=True).start()
            else:
                raise ValueError(f"unknown action {action!r}")
        finally:
            conn.close()

    def cancel(self, build_id: int) -> None:
        row = self._row(build_id)
        if row and row["status"] == "awaiting_plan":
            # parked at the plan gate — no thread is polling cancel_requested,
            # so the decline is applied directly
            self._update(build_id, status="cancelled", finished_at=utcnow())
            conn = self._db()
            try:
                audit(conn, "operator", "plan_declined", f"id={build_id}")
            finally:
                conn.close()
            return
        self._update(build_id, cancel_requested=1)
        proc = self.procs.get(build_id)
        if proc and proc.poll() is None:
            proc.terminate()

    def _phase_argv(self, model: str, max_turns: int, prompt: str) -> list[str]:
        if self.claude_argv_base is not None:
            return self.claude_argv_base + [prompt]
        from .guard import guard_settings_args
        from .workspace import claude_bin

        return [
            claude_bin(),
            "-p",
            prompt,
            "--output-format",
            "json",
            "--model",
            model,
            "--max-turns",
            str(max_turns),
            "--permission-mode",
            "acceptEdits",
            *guard_settings_args(),
        ]

    def _run_phase(self, build_id: int, cwd: Path, argv: list[str]) -> tuple[dict, int]:
        import os
        import signal as _signal

        # own process group: phase runners spawn grandchildren that would otherwise
        # survive a kill and hold the stdout pipe open (hung a real build)
        proc = subprocess.Popen(
            argv, cwd=str(cwd), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True
        )
        self.procs[build_id] = proc
        try:
            out, err = proc.communicate(timeout=PHASE_TIMEOUT_S)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(proc.pid, _signal.SIGKILL)
            except ProcessLookupError:
                pass
            proc.communicate()  # reap + close pipes
            return {
                "status": "blocked",
                "summary": "phase exceeded 40-minute cap",
                "question": "Phase timed out — resume the build or split the brief?",
            }, 0
        finally:
            self.procs.pop(build_id, None)
        try:
            result_text, _, tokens = parse_cli_json(out)
        except json.JSONDecodeError:
            result_text, tokens = None, 0
        if proc.returncode != 0:
            # the CLI exits nonzero on max-turns/limits but still emits its JSON —
            # salvage the session's own account instead of discarding the phase.
            # On error_max_turns the result field is None, so inspect the subtype too.
            subtype = None
            try:
                payload = json.loads(out)
                tail_obj = payload[-1] if isinstance(payload, list) and payload else payload
                if isinstance(tail_obj, dict):
                    subtype = tail_obj.get("subtype") or tail_obj.get("terminal_reason")
            except (json.JSONDecodeError, ValueError):
                pass
            if result_text or subtype:
                return {
                    "status": "blocked",
                    "summary": f"phase ended early ({subtype or f'exit {proc.returncode}'}): "
                    f"{(result_text or '')[-300:]}",
                    "question": "Phase hit a session limit — resume the build to continue.",
                }, tokens or 0
            return {
                "status": "blocked",
                "summary": (err or "claude exited nonzero")[-400:],
                "question": "Phase failed to run — see summary.",
            }, 0
        if result_text is not None:
            return _parse_verdict(result_text), tokens or 0
        # test stubs / plain-text output: parse the verdict straight from stdout
        return _parse_verdict(out), 0

    def _run(self, build_id: int, start_idx: int = 0) -> None:
        # any escape marks the build blocked — a silently dead thread loses the build
        # (happened live: build stuck 'running' with no process and no trace)
        try:
            self._run_inner(build_id, start_idx)
        except Exception as exc:  # noqa: BLE001
            self._update(
                build_id,
                status="blocked",
                finished_at=utcnow(),
                question=f"Pipeline crashed: {type(exc).__name__}: {exc}"[:600],
            )

    def resume(self, build_id: int) -> None:
        row = self._row(build_id)
        if not row or row["status"] not in ("blocked", "cancelled", "attention"):
            raise ValueError(f"build {build_id} is not resumable ({row['status'] if row else 'missing'})")
        log = json.loads(row["log"] or "[]")
        # DISTINCT phases: a revised plan logs 'plan' done twice — counting entries
        # would skip a real phase on resume
        done_phases = {e["phase"] for e in log if e.get("status") == "done"}
        start_idx = len(done_phases)
        self._update(build_id, status="running", question=None, cancel_requested=0)
        conn = self._db()
        try:
            audit(conn, "operator", "build_resumed", f"id={build_id} from_phase_index={start_idx}")
        finally:
            conn.close()
        threading.Thread(target=self._run, args=(build_id, start_idx), daemon=True).start()

    def _run_inner(self, build_id: int, start_idx: int = 0) -> None:
        from .context_pack import context_pack
        from .review_policy import diff_since, review_needed
        from .review_policy import head as git_head

        row = self._row(build_id)
        cwd = Path(row["path"])
        full_prompt = row["prompt"]
        self._update(build_id, status="running", started_at=row["started_at"] or utcnow())
        log = json.loads(row["log"] or "[]")
        prior_summary = log[-1]["summary"] if log else ""
        total_tokens = row["tokens_out"] or 0
        # head before the build phase writes code — the review phase measures its
        # change against this. Unknown (fresh repo, resume-into-review) → review
        # runs, never skips: the policy fails safe.
        baseline_head: str | None = None

        for idx, (key, model, max_turns, instruction) in enumerate(PHASES):
            if idx < start_idx:
                continue
            if self._row(build_id)["cancel_requested"]:
                self._update(build_id, status="cancelled", finished_at=utcnow())
                return
            self._update(build_id, phase=key, phase_index=idx)
            qa_before = evaluate_project(cwd)

            if key == "build":
                baseline_head = git_head(cwd)
            if key == "review" and baseline_head:
                stats = diff_since(cwd, baseline_head)
                if stats is not None:
                    needed, reason = review_needed(
                        stats["lines"], stats["files"], qa_before["overall"], stats["untracked"]
                    )
                    if not needed:
                        # the deterministic gates already judged this change —
                        # a paid review pass can't earn its tokens here
                        self._append_log(
                            build_id,
                            {
                                "phase": key,
                                "model": "(skipped)",
                                "seconds": 0,
                                "status": "done",
                                "summary": f"review skipped: {reason}",
                                "qa_overall": qa_before["overall"],
                                "tokens": 0,
                            },
                        )
                        prior_summary = f"review skipped: {reason}"
                        continue

            gate_feedback = (
                "; ".join(f"{g['id']}: {g['evidence']}" for g in qa_before["gates"] if g["verdict"] != "PASS")
                or "all gates pass"
            )
            pack = context_pack(cwd, self.settings)
            phase_prompt = (
                f"You are one phase of an unattended build pipeline.\n\n"
                f"THE FULL BUILD BRIEF:\n{full_prompt}\n\n" + (f"{pack}\n\n" if pack else "") + f"{instruction}\n\n"
                f"Previous phase summary: {prior_summary or 'none — this is the first phase'}\n"
                f"Objective QA gate state before this phase: {gate_feedback}\n"
                f"{GUARDRAILS}"
            )
            t0 = time.monotonic()
            verdict, tokens = self._run_phase(build_id, cwd, self._phase_argv(model, max_turns, phase_prompt))
            total_tokens += tokens
            qa_after = evaluate_project(cwd)
            self._append_log(
                build_id,
                {
                    "phase": key,
                    "model": model,
                    "seconds": round(time.monotonic() - t0),
                    "status": verdict.get("status"),
                    "summary": str(verdict.get("summary", ""))[:500],
                    "qa_overall": qa_after["overall"],
                    "tokens": tokens,
                },
            )
            self._update(build_id, tokens_out=total_tokens)
            if verdict.get("status") != "done":
                self._update(
                    build_id, status="blocked", finished_at=utcnow(), question=str(verdict.get("question", ""))[:800]
                )
                return
            prior_summary = str(verdict.get("summary", ""))[:600]

            # Guided Build plan gate: park after a successful plan phase and wait
            # for the operator's plain-English approval before any code is written
            if idx == 0 and row["gated"]:
                from .guided import read_plain_plan

                plan = read_plain_plan(cwd) or prior_summary
                self._update(build_id, status="awaiting_plan", plan_summary=plan[:4000])
                conn = self._db()
                try:
                    audit(conn, "builds", "plan_ready", f"id={build_id}")
                finally:
                    conn.close()
                return

        final_qa = evaluate_project(cwd)
        status = "done" if final_qa["overall"] != "BLOCKER" else "attention"
        from .guided import evidence_pack

        evidence = evidence_pack(cwd, json.loads(self._row(build_id)["log"] or "[]"))
        self._update(build_id, status=status, phase="complete", finished_at=utcnow(), evidence=json.dumps(evidence))
        conn = self._db()
        try:
            audit(
                conn,
                "builds",
                "build_finished",
                f"id={build_id} status={status} qa={final_qa['overall']} tokens={total_tokens}",
            )
        finally:
            conn.close()

    def requeue_stale(self) -> None:
        """Builds left 'running' by a server crash can't be resumed — mark them blocked."""
        conn = self._db()
        try:
            conn.execute(
                "UPDATE builds SET status='blocked', question='Server restarted mid-build — "
                "review the repo state and start a new build or finish in the Workspace.' "
                "WHERE status IN ('queued','running')"
            )
            conn.commit()
        finally:
            conn.close()
