"""Arming contracts — approval as a contract, not a switch.

The env flags (NOIRDECK_*_ARMED) stay as fail-closed master enables; a
subsystem additionally needs an ACTIVE contract: not revoked, not expired,
task/token budget not exhausted. So autonomous runs require BOTH a deploy-time
capability (env) and a session-scoped, expiring consent (contract) — and an
armed system disarms ITSELF when the window closes or the budget is spent."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

from .db import audit, utcnow

SUBSYSTEMS = ("overnight", "mining")
MAX_HOURS = 24 * 7  # a contract may never exceed a week


class ArmingError(RuntimeError):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _active_row(conn: sqlite3.Connection, subsystem: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM arm_contracts WHERE subsystem=? AND revoked_at IS NULL "
        "ORDER BY id DESC LIMIT 1", (subsystem,)).fetchone()


def _is_live(row: sqlite3.Row | None) -> bool:
    if row is None:
        return False
    if datetime.fromisoformat(row["armed_until"]) <= _now():
        return False
    if row["max_tasks"] is not None and row["used_tasks"] >= row["max_tasks"]:
        return False
    if row["max_tokens"] is not None and row["used_tokens"] >= row["max_tokens"]:
        return False
    return True


def arm(conn: sqlite3.Connection, subsystem: str, hours: float,
        max_tasks: int | None = None, max_tokens: int | None = None) -> dict:
    if subsystem not in SUBSYSTEMS:
        raise ArmingError(f"unknown subsystem {subsystem!r}")
    if not (0 < hours <= MAX_HOURS):
        raise ArmingError(f"hours must be in (0, {MAX_HOURS}]")
    if max_tasks is not None and max_tasks < 1:
        raise ArmingError("max_tasks must be >= 1")
    if max_tokens is not None and max_tokens < 1000:
        raise ArmingError("max_tokens must be >= 1000")
    revoke(conn, subsystem, quiet=True)  # one active contract per subsystem
    until = (_now() + timedelta(hours=hours)).isoformat()
    cur = conn.execute(
        "INSERT INTO arm_contracts (subsystem, armed_until, max_tasks, max_tokens, created_at) "
        "VALUES (?,?,?,?,?)", (subsystem, until, max_tasks, max_tokens, utcnow()))
    conn.commit()
    audit(conn, "operator", "armed",
          f"subsystem={subsystem} until={until} max_tasks={max_tasks} max_tokens={max_tokens}")
    return {"id": cur.lastrowid, "subsystem": subsystem, "armed_until": until}


def revoke(conn: sqlite3.Connection, subsystem: str, quiet: bool = False) -> bool:
    row = _active_row(conn, subsystem)
    if row is None:
        return False
    conn.execute("UPDATE arm_contracts SET revoked_at=? WHERE id=?", (utcnow(), row["id"]))
    conn.commit()
    if not quiet:
        audit(conn, "operator", "disarmed", f"subsystem={subsystem} contract={row['id']}")
    return True


def check(conn: sqlite3.Connection, subsystem: str) -> tuple[bool, str]:
    """(allowed, reason). The runner gate — call before every task."""
    row = _active_row(conn, subsystem)
    if row is None:
        return False, "no arming contract — arm from the Overnight Queue view"
    if not _is_live(row):
        if datetime.fromisoformat(row["armed_until"]) <= _now():
            return False, f"contract expired {row['armed_until']}"
        return False, "contract budget exhausted (tasks or tokens)"
    return True, "armed"


def consume(conn: sqlite3.Connection, subsystem: str, tasks: int = 1, tokens: int = 0) -> None:
    row = _active_row(conn, subsystem)
    if row is None:
        return
    conn.execute(
        "UPDATE arm_contracts SET used_tasks=used_tasks+?, used_tokens=used_tokens+? WHERE id=?",
        (tasks, tokens, row["id"]))
    conn.commit()


def status(conn: sqlite3.Connection) -> dict:
    out = {}
    for sub in SUBSYSTEMS:
        row = _active_row(conn, sub)
        out[sub] = dict(row) | {"live": _is_live(row)} if row else {"live": False}
    return out
