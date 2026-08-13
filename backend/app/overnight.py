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


def route_agent(text: str, claude_dir: Path) -> str | None:
    """Best-overlap match between the task text and agent descriptions."""
    words = {w for w in re.split(r"[^a-z0-9]+", text.lower()) if len(w) > 3}
    best, best_score = None, 0
    for agent in list_agents(claude_dir):
        desc_words = {w for w in re.split(r"[^a-z0-9]+",
                      (agent["name"] + " " + agent["description"]).lower()) if len(w) > 3}
        score = len(words & desc_words)
        if score > best_score:
            best, best_score = agent["name"], score
    return best if best_score >= 3 else None


def parse_cli_json(stdout: str) -> tuple[str, int | None, int | None]:
    """(result_text, tokens_in, tokens_out) from `claude -p --output-format json`.
    CLI ≥2.1.x emits a LIST of messages ending in a type=='result' object; older
    versions emitted that object alone. Verified empirically 2026-08-13."""
    payload = json.loads(stdout)
    obj = None
    if isinstance(payload, list):
        for item in reversed(payload):
            if isinstance(item, dict) and item.get("type") == "result":
                obj = item
                break
    elif isinstance(payload, dict):
        obj = payload
    if not isinstance(obj, dict):
        return "", None, None
    usage = obj.get("usage") or {}
    return str(obj.get("result") or ""), usage.get("input_tokens"), usage.get("output_tokens")


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
            verdict["summary"] = (proc.stderr or "claude exited nonzero")[-300:]
    except subprocess.TimeoutExpired:
        verdict = {"status": "blocked", "summary": "Task exceeded the 60-minute session cap.",
                   "question": "Split this task or raise the cap?"}
    except (OSError, json.JSONDecodeError) as exc:
        verdict["summary"] = f"{type(exc).__name__}: {exc}"[:300]

    status = "done" if verdict.get("status") == "done" else "blocked"
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
