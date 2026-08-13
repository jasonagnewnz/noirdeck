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
    # 9-13: Guided Build — gated plan approval, intake answers, acceptance
    # criteria, plain-English plan, deterministic evidence pack
    "ALTER TABLE builds ADD COLUMN gated INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE builds ADD COLUMN intake TEXT",
    "ALTER TABLE builds ADD COLUMN acceptance TEXT",
    "ALTER TABLE builds ADD COLUMN plan_summary TEXT",
    "ALTER TABLE builds ADD COLUMN evidence TEXT",
    # 14: Vault — encrypted offsite backup runs with verified-restore state
    """CREATE TABLE vault_runs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        started_at TEXT NOT NULL,
        finished_at TEXT,
        status TEXT NOT NULL,
        restore_verified INTEGER NOT NULL DEFAULT 0,
        detail TEXT
    )""",
    # 15-16: Improve — mapped repos a small LOCAL model quietly improves on
    # branches; every change is a proposal, merging is a human act
    """CREATE TABLE improve_repos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        project TEXT NOT NULL UNIQUE,
        enabled INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL
    )""",
    """CREATE TABLE improve_changes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        project TEXT NOT NULL,
        branch TEXT NOT NULL,
        kind TEXT NOT NULL,
        target_file TEXT,
        summary TEXT,
        diff TEXT,
        tests TEXT,
        model TEXT,
        status TEXT NOT NULL DEFAULT 'proposed',
        created_at TEXT NOT NULL,
        decided_at TEXT
    )""",
    # 17: per-repo model override — NULL means the NOIRDECK_LOCAL_MODEL default;
    # only locally-pulled Ollama models are valid (the improver stays zero-egress)
    "ALTER TABLE improve_repos ADD COLUMN model TEXT",
    # 18: paused workspace sessions — survive a full machine shutdown; the
    # claude session id is captured AT PAUSE TIME so resume targets that exact
    # conversation, not whatever ran in the cwd afterwards
    """CREATE TABLE paused_sessions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        project TEXT NOT NULL,
        claude_session_id TEXT,
        label TEXT,
        paused_at TEXT NOT NULL,
        resumed_at TEXT
    )""",
    # 19: estate improve targets — assets under ~/.claude (skills, memory notes)
    # the improver may work on, but ONLY while manually armed (fail-closed
    # per-target expiry); output goes through the proposals spine, never direct
    """CREATE TABLE improve_targets (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        kind TEXT NOT NULL,
        target_path TEXT NOT NULL UNIQUE,
        model TEXT,
        armed_until TEXT,
        last_proposed_at TEXT,
        created_at TEXT NOT NULL
    )""",
    # 20: proposals carry a unified diff so review reads as a change, not a
    # wall of full-file text (filled by writers that replace existing files)
    "ALTER TABLE proposals ADD COLUMN diff TEXT",
    # 21-22: universal undo — approve() snapshots the target's pre-apply content
    # (NULL = the file did not exist) so every applied proposal is reversible;
    # prior_existed disambiguates "no snapshot taken" from "file was absent"
    "ALTER TABLE proposals ADD COLUMN prior_body TEXT",
    "ALTER TABLE proposals ADD COLUMN prior_existed INTEGER",
    "ALTER TABLE proposals ADD COLUMN reverted_at TEXT",
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
