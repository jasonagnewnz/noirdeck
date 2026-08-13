"""SQLite layer. Additive-only migrations: NEVER edit a shipped entry in MIGRATIONS —
the high-water scheme would silently skip the change on existing databases. Append."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

MIGRATIONS: list[str] = [
    """CREATE TABLE proposals (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        kind TEXT NOT NULL,
        title TEXT NOT NULL,
        body TEXT NOT NULL,
        target_path TEXT,
        status TEXT NOT NULL DEFAULT 'proposed',
        created_at TEXT NOT NULL,
        decided_at TEXT,
        note TEXT
    )""",
    """CREATE TABLE insights (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        kind TEXT NOT NULL,
        title TEXT NOT NULL,
        body TEXT NOT NULL,
        source TEXT NOT NULL,
        created_at TEXT NOT NULL
    )""",
    """CREATE TABLE mined_files (
        path TEXT PRIMARY KEY,
        mtime REAL NOT NULL,
        mined_at TEXT NOT NULL
    )""",
    """CREATE TABLE audit_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts TEXT NOT NULL,
        actor TEXT NOT NULL,
        action TEXT NOT NULL,
        detail TEXT NOT NULL
    )""",
    """CREATE TABLE queue (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        project TEXT NOT NULL,
        title TEXT NOT NULL,
        prompt TEXT NOT NULL,
        agent_type TEXT,
        model TEXT,
        status TEXT NOT NULL DEFAULT 'queued',
        verdict TEXT,
        question TEXT,
        answer TEXT,
        tokens_in INTEGER,
        tokens_out INTEGER,
        created_at TEXT NOT NULL,
        started_at TEXT,
        finished_at TEXT
    )""",
    """CREATE TABLE builds (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        path TEXT NOT NULL,
        prompt TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'queued',
        phase TEXT,
        phase_index INTEGER DEFAULT 0,
        log TEXT DEFAULT '[]',
        question TEXT,
        cancel_requested INTEGER DEFAULT 0,
        tokens_out INTEGER DEFAULT 0,
        created_at TEXT NOT NULL,
        started_at TEXT,
        finished_at TEXT
    )""",
    """CREATE TABLE design_rounds (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        project TEXT NOT NULL,
        brief TEXT NOT NULL,
        library TEXT NOT NULL DEFAULT 'mix',
        status TEXT NOT NULL DEFAULT 'proposing',
        variants TEXT NOT NULL DEFAULT '[]',
        applied_variant TEXT,
        apply_summary TEXT,
        created_at TEXT NOT NULL
    )""",
    # 8: arming contracts — approval as a CONTRACT (expiry + task/token limits),
    # double-gated with the env master flags; one active contract per subsystem
    """CREATE TABLE arm_contracts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        subsystem TEXT NOT NULL,
        armed_until TEXT NOT NULL,
        max_tasks INTEGER,
        used_tasks INTEGER NOT NULL DEFAULT 0,
        max_tokens INTEGER,
        used_tokens INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL,
        revoked_at TEXT
    )""",
]


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")  # worker threads write concurrently
    return conn


def init_db(db_path: Path) -> None:
    conn = connect(db_path)
    try:
        conn.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)")
        row = conn.execute("SELECT MAX(version) AS v FROM schema_version").fetchone()
        current = row["v"] or 0
        for i, stmt in enumerate(MIGRATIONS, start=1):
            if i > current:
                conn.execute(stmt)
                conn.execute("INSERT INTO schema_version (version) VALUES (?)", (i,))
        conn.commit()
    finally:
        conn.close()


def audit(conn: sqlite3.Connection, actor: str, action: str, detail: str) -> None:
    conn.execute(
        "INSERT INTO audit_log (ts, actor, action, detail) VALUES (?,?,?,?)",
        (utcnow(), actor, action, detail),
    )
    conn.commit()
