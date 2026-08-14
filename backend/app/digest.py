"""The morning digest — what happened while you were away, in plain English.

Deterministic by design: every sentence is assembled from database state, no
model involvement, so the operator can trust it the way they trust the evidence
pack. Attention items lead; the quiet state is a single reassuring line."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

from .db import utcnow


def _plural(n: int, one: str, many: str | None = None) -> str:
    return one if n == 1 else (many or one + "s")


def _age_phrase(iso: str | None) -> str:
    if not iso:
        return "at an unknown time"
    try:
        then = datetime.fromisoformat(iso)
    except ValueError:
        return "at an unknown time"
    if then.tzinfo is None:
        then = then.replace(tzinfo=timezone.utc)
    hours = max(0.0, (datetime.now(timezone.utc) - then).total_seconds() / 3600)
    if hours < 1:
        return "under an hour ago"
    if hours < 48:
        return f"{round(hours)} {_plural(round(hours), 'hour')} ago"
    return f"{round(hours / 24)} days ago"


def compose(conn: sqlite3.Connection) -> dict:
    """Digest lines, attention-first. `attention` counts the lines that need a
    human decision so the UI can badge them."""
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    attention: list[str] = []
    info: list[str] = []

    pending = conn.execute(
        "SELECT COUNT(*) c FROM proposals WHERE status='proposed'").fetchone()["c"]
    if pending:
        attention.append(
            f"{pending} {_plural(pending, 'proposal')} "
            f"{_plural(pending, 'is', 'are')} waiting for your decision.")

    qrows = conn.execute(
        "SELECT status, COUNT(*) c FROM queue WHERE finished_at >= ? GROUP BY status",
        (cutoff,)).fetchall()
    qdone = sum(r["c"] for r in qrows if r["status"] == "done")
    qblocked = sum(r["c"] for r in qrows if r["status"] == "blocked")
    if qblocked:
        attention.append(
            f"{qblocked} overnight {_plural(qblocked, 'task')} got stuck and "
            f"{_plural(qblocked, 'has', 'have')} a question for you.")
    if qdone:
        info.append(f"{qdone} overnight {_plural(qdone, 'task')} finished while you were away.")

    brows = conn.execute(
        "SELECT id, name, status FROM builds "
        "WHERE status IN ('awaiting_plan','blocked','attention') ORDER BY id").fetchall()
    for b in brows:
        what = {"awaiting_plan": "is waiting for you to approve its plan",
                "blocked": "is stuck and needs your attention",
                "attention": "finished and is ready for you to look at"}[b["status"]]
        attention.append(f"Build #{b['id']} ({b['name']}) {what}.")

    improve_pending = conn.execute(
        "SELECT COUNT(*) c FROM improve_changes WHERE status='proposed'").fetchone()["c"]
    if improve_pending:
        attention.append(
            f"The improver has {improve_pending} suggested "
            f"{_plural(improve_pending, 'change')} for you to review.")

    trow = conn.execute(
        "SELECT COALESCE(SUM(tokens_out),0) t, COUNT(*) c FROM queue "
        "WHERE finished_at >= ? AND tokens_out > 0", (cutoff,)).fetchone()
    brow = conn.execute(
        "SELECT COALESCE(SUM(tokens_out),0) t, COUNT(*) c FROM builds "
        "WHERE finished_at >= ? AND tokens_out > 0", (cutoff,)).fetchone()
    spent = trow["t"] + brow["t"]
    jobs = trow["c"] + brow["c"]
    if spent:
        info.append(f"Automation spent {round(spent / 1000)}k output tokens across "
                    f"{jobs} {_plural(jobs, 'job')} in the last day.")

    vrow = conn.execute(
        "SELECT finished_at FROM vault_runs WHERE restore_verified=1 "
        "ORDER BY id DESC LIMIT 1").fetchone()
    if vrow:
        info.append(f"Your last verified offsite backup was {_age_phrase(vrow['finished_at'])}.")
    else:
        configured = conn.execute("SELECT COUNT(*) c FROM vault_runs").fetchone()["c"]
        if configured:
            attention.append("No offsite backup has passed a restore test yet.")

    lines = attention + info
    if not lines:
        lines = ["All quiet. Nothing needs you right now."]
    return {"generated_at": utcnow(), "lines": lines, "attention": len(attention)}
