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

from .config import Settings
from .db import audit, connect, init_db, utcnow
from .readers.skills import list_agents

# Routing table: explicit pinned IDs, never family aliases (override via
# NOIRDECK_MODEL_THINK/BUILD/REVIEW — see config.model()).
from .config import model as _model

_ROUTES = [
    (re.compile(r"(security|auth|secret|tenan|schema|migrat|billing|invoice|reconcil|perform|review)", re.I),
     _model("review")),
    (re.compile(r"(architect|design|trade[- ]?off|strategy|root[- ]?cause|why)", re.I),
     _model("think")),
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
        eligible = (name_hits >= 1 and overlap >= 2) or \
                   (overlap >= 5 and desc and overlap >= 0.2 * len(desc))
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
        head = subprocess.run(["git", "-C", str(project_dir), "rev-parse", "HEAD"],
                              capture_output=True, text=True, timeout=15)
        if head.returncode != 0:
            return None
        porcelain = subprocess.run(["git", "-C", str(project_dir), "status", "--porcelain"],
                                   capture_output=True, text=True, timeout=15)
        return {"head": head.stdout.strip(),
                "dirty": {ln[3:] for ln in porcelain.stdout.splitlines() if len(ln) > 3}}
    except OSError:
        return None


def _parse_verdict(result_text: str) -> dict:
    idx = result_text.rfind("VERDICT:")
    if idx < 0:
        return {"status": "blocked", "summary": result_text[-300:],
                "question": "Session ended without a structured verdict — review the summary."}
    try:
        raw = result_text[idx + len("VERDICT:"):].strip()
        end = raw.rfind("}")
        return json.loads(raw[:end + 1])
    except (json.JSONDecodeError, ValueError):
        return {"status": "blocked", "summary": result_text[-300:],
                "question": "Verdict line was malformed — review the summary."}


def run_task(conn: sqlite3.Connection, settings: Settings, task: sqlite3.Row) -> None:
    project_dir = Path(task["project"]).expanduser()
    conn.execute("UPDATE queue SET status='running', started_at=? WHERE id=?",
                 (utcnow(), task["id"]))
    conn.commit()

    model = task["model"] or route_model(task["title"] + " " + task["prompt"])
    agent = task["agent_type"] or route_agent(task["title"] + " " + task["prompt"], settings.claude_dir)
    prompt = task["prompt"]
    if task["answer"]:
        prompt += f"\n\nThe operator answered your earlier question: {task['answer']}"
    if agent:
        prompt += f"\n\nPreferred specialist subagent for delegation if useful: {agent}"
    prompt += _GUARDRAILS

    verdict = {"status": "blocked", "summary": "runner error", "question": "Runner failed before the session produced output."}
    tokens_in = tokens_out = None
    before = _git_state(project_dir)
    try:
        from .guard import guard_settings_args
        from .workspace import claude_bin
        proc = subprocess.run(
            [claude_bin(), "-p", prompt, "--output-format", "json",
             "--model", model, "--max-turns", "40", "--permission-mode", "acceptEdits",
             *guard_settings_args()],
            capture_output=True, text=True, timeout=3600, cwd=str(project_dir),
        )
        if proc.returncode == 0 and proc.stdout:
            result_text, tokens_in, tokens_out = parse_cli_json(proc.stdout)
            verdict = _parse_verdict(result_text)
        else:
            # salvage the JSON even on nonzero exit — error_max_turns and
            # friends still emit a result object whose subtype names the cause
            subtype = None
            try:
                obj = parse_cli_result(proc.stdout) if proc.stdout else None
            except json.JSONDecodeError:
                obj = None
            if obj:
                subtype = obj.get("subtype")
                usage = obj.get("usage") or {}
                tokens_in = usage.get("input_tokens")
                tokens_out = usage.get("output_tokens")
            verdict["summary"] = (f"claude exited rc={proc.returncode}"
                                  + (f" subtype={subtype}" if subtype else ""))
            verdict["question"] = (
                f"Runner failed: rc={proc.returncode}"
                + (f", subtype={subtype}" if subtype else "")
                + f"; stderr: {(proc.stderr or '').strip()[-200:] or '(empty)'}"
                + f"; result: {str((obj or {}).get('result') or '')[-200:] or '(none)'}")
    except subprocess.TimeoutExpired:
        verdict = {"status": "blocked", "summary": "Task exceeded the 60-minute session cap.",
                   "question": "Split this task or raise the cap?"}
    except (OSError, json.JSONDecodeError) as exc:
        verdict["summary"] = f"{type(exc).__name__}: {exc}"[:300]

    status = "done" if verdict.get("status") == "done" else "blocked"
    after = _git_state(project_dir)
    if before and after:
        stranded = sorted(after["dirty"] - before["dirty"])
        if stranded:
            note = (f"session left {len(stranded)} uncommitted file(s) in the shared tree: "
                    + ", ".join(stranded[:6]) + ("…" if len(stranded) > 6 else ""))
            audit(conn, "overnight", "tree_stranded", f"id={task['id']} {note}"[:300])
            if status == "blocked":
                verdict["question"] = ((verdict.get("question") or "")
                                       + f" ⚠ {note} — review, commit or revert before "
                                         f"any other commit in this repo.")
    conn.execute(
        "UPDATE queue SET status=?, model=?, agent_type=?, verdict=?, question=?, "
        "tokens_in=?, tokens_out=?, finished_at=? WHERE id=?",
        (status, model, agent, verdict.get("summary", "")[:2000],
         (verdict.get("question") or "")[:1000] if status == "blocked" else None,
         tokens_in, tokens_out, utcnow(), task["id"]))
    audit(conn, "overnight", f"task_{status}",
          f"id={task['id']} model={model} agent={agent or '-'} tokens_out={tokens_out}")
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
            task = conn.execute(
                "SELECT * FROM queue WHERE status='queued' ORDER BY id LIMIT 1").fetchone()
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
