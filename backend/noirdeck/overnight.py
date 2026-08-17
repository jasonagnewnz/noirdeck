"""Overnight mode: autonomous queue runner over headless Claude Code sessions.

Contract:
- Fail-closed: refuses unless NOIRDECK_OVERNIGHT_ARMED=true.
- One task at a time, bounded turns, model routed per the estate routing table.
- The session must end with a structured verdict; uncertainty PARKS the task with a
  question for the operator and the runner MOVES ON — one ambiguity never stops the night.
- Never pushes, deploys, or takes outward-facing action: stops at code-ready.
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import subprocess
import time
from pathlib import Path

from . import ai_runtime
from .config import Settings

# Routing table: explicit pinned IDs, never family aliases (override via
# NOIRDECK_MODEL_THINK/BUILD/REVIEW — see config.model()).
from .config import model as _model
from .db import audit, connect, init_db, utcnow
from .readers.skills import list_agents

_ROUTES = [
    (
        re.compile(r"(security|auth|secret|tenan|schema|migrat|billing|invoice|reconcil|perform|review)", re.I),
        _model("review"),
    ),
    (re.compile(r"(architect|design|trade[- ]?off|strategy|root[- ]?cause|why)", re.I), _model("think")),
]
_DEFAULT_MODEL = _model("build")

_GUARDRAILS = """

--- OPERATING RULES (non-negotiable) ---
1. Work only inside this project directory. NEVER `git push`, deploy, publish, send
   email/messages, call outward-facing services, or delete files/tests. Stop at
   code-ready; local commits are allowed.
2. Minimise tokens: no exploratory reading beyond what the task needs.
3. If you hit a decision that is the operator's to make (unsafe, irreversible, or the work
   would be useless if guessed wrong), STOP and report it as a question instead of guessing.
4. End your FINAL message with exactly one line:
   VERDICT: {"status":"done"|"blocked","summary":"<1-2 sentences>","question":"<only if blocked>"}
"""


def route_model(text: str) -> str:
    for pat, model in _ROUTES:
        if pat.search(text):
            return model
    return _DEFAULT_MODEL


# Weight routing: staging (think → do → check) pays for itself only when a wrong
# approach would cost more than the extra sessions' discovery overhead. Small
# tasks stay single-session — three stages on a one-file fix roughly triples the
# fixed cost for the same change.
_HEAVY_HINT = re.compile(
    r"(architect|redesign|\bdesign\b|migrat|refactor|rewrite|overhaul|restructur"
    r"|schema|security|audit|investigat|root[- ]?cause|strategy"
    r"|across (the|all)|every (file|module|route|view|page)|end[- ]?to[- ]?end|pipeline)",
    re.I,
)
_HEAVY_PROMPT_CHARS = 900


def route_weight(title: str, prompt: str) -> str:
    if _HEAVY_HINT.search(f"{title} {prompt}") or len(prompt) > _HEAVY_PROMPT_CHARS:
        return "heavy"
    return "light"


def _stems(text: str) -> set[str]:
    words = {w for w in re.split(r"[^a-z0-9]+", text.lower()) if len(w) > 3}
    return {w[:-1] if w.endswith("s") else w for w in words}


def route_agent(text: str, claude_dir: Path) -> str | None:
    """Name-weighted match between the task text and agent descriptions.
    Raw prose overlap routed a UI task to a phone-system specialist
    (2026-08-13, task #1): long descriptions accumulate accidental overlap,
    so a bare word count is not evidence of relevance. An agent is eligible
    only when the task names it (plus minimal topic overlap), or the topic
    overlap is both large and dense relative to the description's size.
    No confident match → no specialist hint, which is the correct default."""
    task = _stems(text)
    best, best_score = None, 0
    for agent in list_agents(claude_dir):
        name = _stems(agent["name"].replace("-", " "))
        desc = _stems(agent["description"])
        name_hits = len(task & name)
        overlap = len(task & desc)
        eligible = (name_hits >= 1 and overlap >= 2) or (overlap >= 5 and desc and overlap >= 0.2 * len(desc))
        score = 10 * name_hits + overlap
        if eligible and score > best_score:
            best, best_score = agent["name"], score
    return best


def parse_cli_result(stdout: str) -> dict | None:
    """The type=='result' object from `claude -p --output-format json`, or None.
    CLI ≥2.1.x emits a LIST of messages ending in a type=='result' object; older
    versions emitted that object alone. Verified empirically 2026-08-13. Raises
    json.JSONDecodeError on non-JSON, matching parse_cli_json's old contract."""
    payload = json.loads(stdout)
    if isinstance(payload, list):
        for item in reversed(payload):
            if isinstance(item, dict) and item.get("type") == "result":
                return item
        return None
    return payload if isinstance(payload, dict) else None


def parse_cli_json(stdout: str) -> tuple[str, int | None, int | None]:
    """(result_text, tokens_in, tokens_out) from `claude -p --output-format json`."""
    obj = parse_cli_result(stdout)
    if not isinstance(obj, dict):
        return "", None, None
    usage = obj.get("usage") or {}
    return str(obj.get("result") or ""), usage.get("input_tokens"), usage.get("output_tokens")


def _git_state(project_dir: Path) -> dict | None:
    """HEAD + dirty-file set, or None when the dir isn't a readable git repo.
    Snapshotted around each session to detect work a failed run strands in the
    SHARED working tree (the tree is not ours alone — never auto-revert it)."""
    try:
        head = subprocess.run(
            ["git", "-C", str(project_dir), "rev-parse", "HEAD"], capture_output=True, text=True, timeout=15
        )
        if head.returncode != 0:
            return None
        porcelain = subprocess.run(
            ["git", "-C", str(project_dir), "status", "--porcelain"], capture_output=True, text=True, timeout=15
        )
        return {"head": head.stdout.strip(), "dirty": {ln[3:] for ln in porcelain.stdout.splitlines() if len(ln) > 3}}
    except OSError:
        return None


def _parse_verdict(result_text: str) -> dict:
    idx = result_text.rfind("VERDICT:")
    if idx < 0:
        return {
            "status": "blocked",
            "summary": result_text[-300:],
            "question": "Session ended without a structured verdict — review the summary.",
        }
    try:
        raw = result_text[idx + len("VERDICT:") :].strip()
        end = raw.rfind("}")
        return json.loads(raw[: end + 1])
    except (json.JSONDecodeError, ValueError):
        return {
            "status": "blocked",
            "summary": result_text[-300:],
            "question": "Verdict line was malformed — review the summary.",
        }


def _session_argv(model: str, max_turns: int, prompt: str, readonly: bool = False, runner: str = "claude") -> list[str]:
    return ai_runtime.queue_argv(runner, model, max_turns, prompt, readonly=readonly)


def _execute(argv: list[str], cwd: Path, timeout: int = 3600) -> tuple[bool, str, int | None, int, str]:
    """(ok, result_text, tokens_in, tokens_out, failure_note). Salvages the CLI's
    own JSON on nonzero exit — error_max_turns and friends still emit a result
    object whose subtype names the cause. Test seam: monkeypatch this."""
    proc = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, cwd=str(cwd))
    expects_json = "--output-format" in argv and "json" in argv
    if proc.returncode == 0 and proc.stdout and not expects_json:
        return True, proc.stdout.strip(), None, 0, ""
    if proc.returncode == 0 and proc.stdout:
        text, tin, tout = parse_cli_json(proc.stdout)
        return True, text, tin, tout or 0, ""
    subtype, tin, tout, text = None, None, 0, ""
    try:
        obj = parse_cli_result(proc.stdout) if proc.stdout and expects_json else None
    except json.JSONDecodeError:
        obj = None
    if obj:
        subtype = obj.get("subtype")
        usage = obj.get("usage") or {}
        tin = usage.get("input_tokens")
        tout = usage.get("output_tokens") or 0
        text = str(obj.get("result") or "")
    note = (
        f"rc={proc.returncode}"
        + (f" subtype={subtype}" if subtype else "")
        + f"; stderr: {(proc.stderr or '').strip()[-200:] or '(empty)'}"
        + f"; result: {text[-200:] or '(none)'}"
    )
    return False, text, tin, tout, note


_PLAN_INSTRUCTION = """
You are the PLANNING pass of a two-stage task. READ-ONLY: survey exactly what this
task needs and produce a COMPACT EXECUTION BRIEF (max ~50 lines) for the builder:
GOAL (one line), APPROACH (short), FILES TO TOUCH (paths), ORDERED STEPS, RISKS /
things that look easy but aren't here, ACCEPTANCE (how the builder proves it worked).
No code, no fluff — every line must change what the builder does. Output ONLY the brief.
"""

_CHECK_INSTRUCTION = (
    """
You are the CHECK pass after an unattended change. Review ONLY the change described
below as a hostile senior reviewer — correctness, security, data handling, tests.
FIX anything real you find and re-run the relevant tests; ignore style nits.
"""
    + _GUARDRAILS
)


def run_task(conn: sqlite3.Connection, settings: Settings, task: sqlite3.Row) -> None:
    from .context_pack import context_pack
    from .qa import evaluate_project
    from .review_policy import diff_since, review_needed

    project_dir = Path(task["project"]).expanduser()
    conn.execute("UPDATE queue SET status='running', started_at=? WHERE id=?", (utcnow(), task["id"]))
    conn.commit()

    text_all = task["title"] + " " + task["prompt"]
    runner = task["runner"] if "runner" in task.keys() and task["runner"] else "claude"
    model = task["model"] or (route_model(text_all) if runner == "claude" else ai_runtime.default_model(runner))
    agent = task["agent_type"] or route_agent(text_all, settings.claude_dir)
    weight = (task["weight"] if "weight" in task.keys() else None) or route_weight(task["title"], task["prompt"])
    base_prompt = task["prompt"]
    if task["answer"]:
        base_prompt += f"\n\nThe operator answered your earlier question: {task['answer']}"
    if agent:
        base_prompt += f"\n\nPreferred specialist subagent for delegation if useful: {agent}"
    pack = context_pack(project_dir, settings)

    verdict = {
        "status": "blocked",
        "summary": "runner error",
        "question": "Runner failed before the session produced output.",
    }
    tokens_in = None
    tokens_out = 0
    stage_notes: list[str] = []
    before = _git_state(project_dir)
    try:
        brief = ""
        if weight == "heavy":
            plan_prompt = (f"{pack}\n\n" if pack else "") + f"THE TASK:\n{base_prompt}\n{_PLAN_INSTRUCTION}"
            ok, text, _tin, tout, note = _execute(
                _session_argv(_model("think"), 12, plan_prompt, readonly=True), project_dir, timeout=1200
            )
            tokens_out += tout
            if ok and text.strip():
                brief = text.strip()[:6000]
                stage_notes.append(f"plan {tout} tok")
            else:
                # staging must never cost a night: a failed plan falls back to
                # the single-session path instead of blocking the task
                weight = "light"
                stage_notes.append(f"plan failed ({note[:120]}) — fell back to single-session")

        do_prompt = (f"{pack}\n\n" if pack else "") + base_prompt
        if brief:
            do_prompt += (
                "\n\nEXECUTION BRIEF from the planning pass "
                "(follow it unless it is clearly wrong on the ground):\n" + brief
            )
        do_prompt += _GUARDRAILS
        ok, text, tokens_in, tout, note = _execute(_session_argv(model, 40, do_prompt, runner=runner), project_dir)
        tokens_out += tout
        if ok:
            verdict = _parse_verdict(text)
        else:
            verdict["summary"] = f"claude exited {note[:200]}"
            verdict["question"] = f"Runner failed: {note}"

        if weight == "heavy" and verdict.get("status") == "done":
            baseline = before["head"] if before else None
            stats = diff_since(project_dir, baseline) if baseline else None
            if stats is None:
                needed, reason = True, "change could not be measured — reviewing (fail-safe)"
            else:
                gates = evaluate_project(project_dir, light=True)["overall"]
                needed, reason = review_needed(stats["lines"], stats["files"], gates, stats["untracked"])
            if needed:
                changed = ", ".join((stats or {}).get("files", [])[:20]) or "(unmeasured)"
                check_prompt = (
                    (f"{pack}\n\n" if pack else "")
                    + f"THE TASK THAT WAS JUST EXECUTED:\n{base_prompt}\n\n"
                    + f"BUILDER'S OWN SUMMARY: {verdict.get('summary', '')}\n"
                    + f"FILES CHANGED: {changed}\n"
                    + _CHECK_INSTRUCTION
                )
                ok2, text2, _tin2, tout2, note2 = _execute(
                    _session_argv(_model("review"), 25, check_prompt), project_dir, timeout=1800
                )
                tokens_out += tout2
                if ok2:
                    v2 = _parse_verdict(text2)
                    if v2.get("status") == "done":
                        stage_notes.append(f"check passed ({tout2} tok)")
                    else:
                        stage_notes.append(f"check flagged issues ({tout2} tok)")
                        verdict = {
                            "status": "blocked",
                            "summary": f"{verdict.get('summary', '')} | check: {v2.get('summary', '')}"[:1800],
                            "question": v2.get("question") or "The check pass flagged issues — see summary.",
                        }
                else:
                    stage_notes.append(f"check failed to run ({note2[:120]}) — result stands unreviewed")
            else:
                stage_notes.append(f"check skipped: {reason}")
    except subprocess.TimeoutExpired:
        verdict = {
            "status": "blocked",
            "summary": "A session exceeded its time cap.",
            "question": "Split this task or raise the cap?",
        }
    except (OSError, json.JSONDecodeError) as exc:
        verdict["summary"] = f"{type(exc).__name__}: {exc}"[:300]
    if stage_notes:
        verdict["summary"] = (str(verdict.get("summary", "")) + " [" + "; ".join(stage_notes) + "]")[:2000]

    status = "done" if verdict.get("status") == "done" else "blocked"
    after = _git_state(project_dir)
    if before and after:
        stranded = sorted(after["dirty"] - before["dirty"])
        if stranded:
            note = (
                f"session left {len(stranded)} uncommitted file(s) in the shared tree: "
                + ", ".join(stranded[:6])
                + ("…" if len(stranded) > 6 else "")
            )
            audit(conn, "overnight", "tree_stranded", f"id={task['id']} {note}"[:300])
            if status == "blocked":
                verdict["question"] = (
                    verdict.get("question") or ""
                ) + f" ⚠ {note} — review, commit or revert before any other commit in this repo."
    conn.execute(
        "UPDATE queue SET status=?, runner=?, model=?, agent_type=?, weight=?, verdict=?, question=?, "
        "tokens_in=?, tokens_out=?, finished_at=? WHERE id=?",
        (
            status,
            runner,
            model,
            agent,
            weight,
            str(verdict.get("summary", ""))[:2000],
            (verdict.get("question") or "")[:1000] if status == "blocked" else None,
            tokens_in,
            tokens_out,
            utcnow(),
            task["id"],
        ),
    )
    audit(
        conn,
        "overnight",
        f"task_{status}",
        f"id={task['id']} runner={runner} model={model} weight={weight} agent={agent or '-'} tokens_out={tokens_out}",
    )
    conn.commit()


def requeue_stale_running(conn: sqlite3.Connection) -> None:
    conn.execute("UPDATE queue SET status='queued', started_at=NULL WHERE status='running'")
    conn.commit()


def run_queue(settings: Settings, window_hours: float | None, once: bool) -> dict:
    if not settings.overnight_armed:
        return {"skipped": True, "reason": "NOIRDECK_OVERNIGHT_ARMED != true (fail-closed)"}
    from .arming import check, consume

    init_db(settings.db_path)
    conn = connect(settings.db_path)
    deadline = time.monotonic() + (window_hours or 6) * 3600
    done = 0
    try:
        requeue_stale_running(conn)
        while time.monotonic() < deadline:
            # the contract is re-checked before EVERY task so an exhausted
            # budget or a mid-window expiry stops the run, not just its start
            allowed, reason = check(conn, "overnight")
            if not allowed:
                audit(conn, "overnight", "run_halted", f"contract: {reason}")
                return {"tasks_run": done, "halted": reason}
            task = conn.execute("SELECT * FROM queue WHERE status='queued' ORDER BY id LIMIT 1").fetchone()
            if not task:
                break
            run_task(conn, settings, task)
            row = conn.execute("SELECT tokens_out FROM queue WHERE id=?", (task["id"],)).fetchone()
            consume(conn, "overnight", tasks=1, tokens=(row["tokens_out"] or 0) if row else 0)
            done += 1
            if once:
                break
        return {"tasks_run": done}
    finally:
        conn.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--window-hours", type=float, default=6)
    args = ap.parse_args()
    print(json.dumps(run_queue(Settings.load(), args.window_hours, args.once)))
