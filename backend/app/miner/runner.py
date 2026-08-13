"""Gated LLM mining pass: headless `claude -p` over REDACTED transcript excerpts.

Fail-closed: refuses unless NOIRDECK_MINING_ARMED=true. Dedup via mined_files
(path+mtime) so no transcript version is ever mined twice — dry-run cost runaways
are an estate-documented failure mode. Batches are capped per run.
"""
from __future__ import annotations

import json
import sqlite3
import subprocess
from pathlib import Path

from ..config import Settings
from ..db import audit, utcnow
from ..miner.redact import redact
from ..readers.sessions import _text_of, _iter_json  # bounded readers

_BATCH_CHARS = 20000
_PROMPT = """You are analysing REDACTED excerpts of a developer's own Claude Code session
transcripts (their machine, their data). Extract, as strict JSON only:
{"skill_candidates":[{"slug":"...","evidence":"...","draft_description":"..."}],
 "methodology_notes":["..."],
 "memory_notes":["..."]}
skill_candidates = recurring procedures worth packaging as a reusable skill.
methodology_notes = observations about HOW this developer likes work done (style, gates, order).
memory_notes = durable facts/landmines worth a memory file. No prose outside the JSON.

EXCERPTS:
"""


def _user_texts(path: Path, cap: int = 40) -> list[str]:
    texts: list[str] = []
    try:
        with open(path, errors="replace") as fh:
            for rec in _iter_json(fh.readlines()[:2000]):
                if rec.get("type") == "user":
                    t = _text_of(rec).strip()
                    if t and not t.startswith("<"):
                        texts.append(t[:1500])
                        if len(texts) >= cap:
                            break
    except OSError:
        pass
    return texts


def pick_unmined(conn: sqlite3.Connection, claude_dir: Path, max_files: int) -> list[Path]:
    projects = claude_dir / "projects"
    if not projects.is_dir():
        return []
    all_files = sorted(
        (p for ns in projects.iterdir() if ns.is_dir() for p in ns.glob("*.jsonl")),
        key=lambda p: p.stat().st_mtime, reverse=True,
    )
    picked: list[Path] = []
    for p in all_files:
        row = conn.execute("SELECT mtime FROM mined_files WHERE path=?", (str(p),)).fetchone()
        if row and row["mtime"] == p.stat().st_mtime:
            continue
        picked.append(p)
        if len(picked) >= max_files:
            break
    return picked


def run_llm_mining(conn: sqlite3.Connection, settings: Settings) -> dict:
    if not settings.mining_armed:
        return {"skipped": True, "reason": "NOIRDECK_MINING_ARMED != true (fail-closed)"}
    from ..arming import check, consume

    files = pick_unmined(conn, settings.claude_dir, settings.mine_max_batches)
    results = {"batches": 0, "insights": 0, "redactions": 0}
    for path in files:
        allowed, reason = check(conn, "mining")
        if not allowed:
            results["halted"] = reason
            break
        texts = _user_texts(path)
        if not texts:
            conn.execute(
                "INSERT OR REPLACE INTO mined_files (path,mtime,mined_at) VALUES (?,?,?)",
                (str(path), path.stat().st_mtime, utcnow()))
            conn.commit()
            continue
        blob = "\n---\n".join(texts)[:_BATCH_CHARS]
        clean, counts = redact(blob)
        results["redactions"] += sum(counts.values())
        try:
            from ..overnight import parse_cli_json
            from ..workspace import claude_bin
            from ..config import model as _mining_model_fn
            from ..guard import guard_settings_args
            proc = subprocess.run(
                [claude_bin(), "-p", _PROMPT + clean, "--output-format", "json",
                 "--max-turns", "1", "--model", _mining_model_fn("build"),
                 *guard_settings_args()],
                capture_output=True, text=True, timeout=300,
            )
            result_text = parse_cli_json(proc.stdout)[0] if proc.returncode == 0 else None
        except (subprocess.TimeoutExpired, OSError, json.JSONDecodeError):
            result_text = None
        if result_text:
            try:
                start, end = result_text.find("{"), result_text.rfind("}")
                data = json.loads(result_text[start:end + 1]) if start >= 0 else {}
            except (json.JSONDecodeError, ValueError):
                data = {}
            for note in (data.get("methodology_notes") or [])[:5]:
                conn.execute(
                    "INSERT INTO insights (kind,title,body,source,created_at) VALUES (?,?,?,?,?)",
                    ("methodology", str(note)[:120], str(note), path.name, utcnow()))
                results["insights"] += 1
            for note in (data.get("memory_notes") or [])[:5]:
                conn.execute(
                    "INSERT INTO insights (kind,title,body,source,created_at) VALUES (?,?,?,?,?)",
                    ("memory", str(note)[:120], str(note), path.name, utcnow()))
                results["insights"] += 1
        conn.execute(
            "INSERT OR REPLACE INTO mined_files (path,mtime,mined_at) VALUES (?,?,?)",
            (str(path), path.stat().st_mtime, utcnow()))
        conn.commit()
        results["batches"] += 1
        consume(conn, "mining", tasks=1)
    audit(conn, "miner", "llm_mining_run", json.dumps(results))
    return results
