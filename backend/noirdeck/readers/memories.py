"""Memory namespaces: ~/.claude/projects/<ns>/memory/*.md

PERFORMANCE, AND WHY THE INDEX EXISTS. Rendering a summary of this tree meant
parsing frontmatter from every file: measured at 19,308 files, ~13s of parsing and
**43.9s cold** on a real estate. A 120-second in-memory TTL hid it from the second
page load and from nobody's first: every session's first visit, and any two-minute
idle, paid full price. A background pre-warm existed to paper over it, which is a
workaround that concedes the point.

Walking the same tree with stat() only costs **0.15s**. So the parse is cached on
disk keyed by (path, mtime, size): unchanged files are never re-read, and the common
case degenerates to the stat walk. The in-memory TTL stays as a second layer for
repeat calls inside one request burst.
"""

from __future__ import annotations

import sqlite3
import threading
import time
from collections import Counter
from pathlib import Path

from .frontmatter import parse_frontmatter

# ── on-disk parse cache ──────────────────────────────────────────────────────
_index_lock = threading.Lock()
_index_conn: sqlite3.Connection | None = None
# Buffered, not committed per file. Committing each of 19k rows individually made
# the FIRST run slower than having no cache at all (75s vs 44s): an optimisation
# that only pays back on the second visit is a regression on the first.
_pending: list[tuple] = []


def _index() -> sqlite3.Connection | None:
    """Lazily open the index. Returns None if it cannot be opened: the reader must
    still work (slowly) on a read-only or unwritable data dir, because a cache that
    can fail the feature is worse than no cache."""
    global _index_conn
    if _index_conn is not None:
        return _index_conn
    try:
        from ..config import default_db_path

        # Beside the main database, never at data_home() itself: in a source checkout
        # data_home() IS the repo root, so the index landed next to the source as an
        # untracked artifact.
        path = default_db_path().parent / "memory-index.db"
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(path), check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute(
            """CREATE TABLE IF NOT EXISTS memory_index (
                 path TEXT PRIMARY KEY,
                 mtime REAL NOT NULL,
                 size INTEGER NOT NULL,
                 namespace TEXT NOT NULL,
                 name TEXT,
                 description TEXT,
                 type TEXT
               )"""
        )
        conn.commit()
        _index_conn = conn
    except (OSError, sqlite3.Error):
        return None
    return _index_conn


def _namespaces(claude_dir: Path):
    projects = claude_dir / "projects"
    if not projects.is_dir():
        return
    for ns in sorted(projects.iterdir()):
        mem = ns / "memory"
        if mem.is_dir():
            yield ns.name, mem


_cache: dict[str, tuple[float, list]] = {}
_TTL = 120  # 15k+ frontmatter reads across 133 namespaces: never do it per request
_LOCK = threading.Lock()


def _parse_summary(ns_name: str, f: Path, st) -> dict:
    fm, _ = parse_frontmatter(f, max_bytes=4096)
    meta = fm.get("metadata") or {}
    return {
        "namespace": ns_name,
        "name": fm.get("name") or f.stem,
        "description": (fm.get("description") or "").strip(),
        "type": meta.get("type") if isinstance(meta, dict) else None,
        "file": f.name,
        "size": st.st_size,
        "mtime": st.st_mtime,
    }


def _memory_summary(ns_name: str, f: Path) -> dict:
    """One file's summary, from the index when the file has not changed.

    The key is (mtime, size), not mtime alone: a same-second edit that changes length
    is common when a file is rewritten by a tool, and mtime resolution is not always
    fine enough to catch it on its own.
    """
    st = f.stat()
    conn = _index()
    if conn is None:
        return _parse_summary(ns_name, f, st)
    key = str(f)
    try:
        row = conn.execute(
            "SELECT mtime, size, name, description, type FROM memory_index WHERE path=?", (key,)
        ).fetchone()
        if row and row[0] == st.st_mtime and row[1] == st.st_size:
            return {
                "namespace": ns_name,
                "name": row[2] or f.stem,
                "description": row[3] or "",
                "type": row[4],
                "file": f.name,
                "size": st.st_size,
                "mtime": st.st_mtime,
            }
    except sqlite3.Error:
        return _parse_summary(ns_name, f, st)

    summary = _parse_summary(ns_name, f, st)
    with _index_lock:
        _pending.append(
            (key, st.st_mtime, st.st_size, ns_name, summary["name"], summary["description"], summary["type"])
        )
    return summary


def _flush_index() -> int:
    """Write buffered summaries in one transaction. Called after a walk, so a cold
    run pays one commit instead of tens of thousands."""
    conn = _index()
    if conn is None:
        return 0
    with _index_lock:
        rows, _pending[:] = list(_pending), []
    if not rows:
        return 0
    try:
        conn.executemany(
            "INSERT INTO memory_index (path, mtime, size, namespace, name, description, type) "
            "VALUES (?,?,?,?,?,?,?) ON CONFLICT(path) DO UPDATE SET "
            "mtime=excluded.mtime, size=excluded.size, namespace=excluded.namespace, "
            "name=excluded.name, description=excluded.description, type=excluded.type",
            rows,
        )
        conn.commit()
    except sqlite3.Error:
        return 0  # a cache miss is slow, never wrong
    return len(rows)


def list_memories_for_namespaces(claude_dir: Path, namespaces: set[str], limit: int | None = None) -> list[dict]:
    """Read a small namespace subset without sweeping the full estate."""
    out: list[dict] = []
    projects = claude_dir / "projects"
    for ns_name in sorted(namespaces):
        mem = projects / ns_name / "memory"
        if not mem.is_dir():
            continue
        for f in sorted(mem.glob("*.md")):
            if f.name == "MEMORY.md":
                continue
            out.append(_memory_summary(ns_name, f))
            if limit is not None and len(out) >= limit:
                _flush_index()
                return out
    _flush_index()
    return out


def list_memories(claude_dir: Path) -> list[dict]:
    with _LOCK:
        hit = _cache.get(str(claude_dir))
        if hit and time.monotonic() - hit[0] < _TTL:
            return hit[1]
    out: list[dict] = []
    for ns_name, mem in _namespaces(claude_dir):
        for f in sorted(mem.glob("*.md")):
            if f.name == "MEMORY.md":
                continue
            out.append(_memory_summary(ns_name, f))
    _flush_index()
    with _LOCK:
        _cache[str(claude_dir)] = (time.monotonic(), out)
    return out


def refresh_memories_async(claude_dir: Path) -> None:
    key = str(claude_dir)
    with _LOCK:
        hit = _cache.get(key)
        if hit and time.monotonic() - hit[0] < _TTL:
            return
        refreshing = getattr(refresh_memories_async, "_refreshing", set())
        if key in refreshing:
            return
        refreshing.add(key)
        refresh_memories_async._refreshing = refreshing

    def run():
        try:
            list_memories(claude_dir)
        finally:
            with _LOCK:
                refresh_memories_async._refreshing.discard(key)

    threading.Thread(target=run, daemon=True).start()


def cached_memories(claude_dir: Path, refresh: bool = False) -> list[dict]:
    key = str(claude_dir)
    with _LOCK:
        hit = _cache.get(key)
        data = hit[1] if hit and time.monotonic() - hit[0] < _TTL else None
    if refresh and data is None:
        refresh_memories_async(claude_dir)
    return data or []


# REMOVED 2026-08-19: group_memories() / _topic_tokens() / _STOP.
# Files were clustered when they shared ONE filename token >2 chars that was not
# in a 22-word stopword list, and each cluster was staged as a memory-consolidation
# proposal. Against the live estate (18,062 files) that yielded 96 "candidates",
# led by topic='2026' with 166 members (every date-suffixed file) and topic='wazuh'
# with 35 unrelated incidents. Sharing a word is not sharing a topic, and a
# consolidation proposal built on that is a request to merge unrelated knowledge.
# Do not reintroduce clustering by filename; if consolidation is worth proposing,
# a model must read the files and name the specific redundancy (miner/evidence.py).


def memory_stats(memories: list[dict]) -> dict:
    by_type = Counter(m["type"] or "untyped" for m in memories)
    by_ns = Counter(m["namespace"] for m in memories)
    return {
        "total": len(memories),
        "by_type": dict(by_type),
        "namespaces": len(by_ns),
        "top_namespaces": by_ns.most_common(10),
    }
