"""Session transcripts: bounded head/tail sampling, never full loads.

A transcript can be hundreds of MB across the estate; the dashboard only needs
"what was the task, when, and did it finish" — head 64KB + tail 64KB answers all three.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

_HEAD_BYTES = 65536
_TAIL_BYTES = 65536
_OPEN_LOOP = re.compile(
    r"(next steps?|shall i|do you want|let me know|waiting (on|for)|blocked|"
    r"once you (confirm|approve)|\?\s*$)",
    re.IGNORECASE,
)

_cache: dict[str, tuple[float, dict]] = {}


def _text_of(record: dict) -> str:
    msg = record.get("message") or {}
    content = msg.get("content") or record.get("content") or ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")
    return ""


def _iter_json(lines: list[str]):
    for line in lines:
        try:
            yield json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue


def summarize_session(path: Path) -> dict:
    stat = path.stat()
    cached = _cache.get(str(path))
    if cached and cached[0] == stat.st_mtime:
        return cached[1]

    with open(path, "rb") as fh:
        head = fh.read(_HEAD_BYTES).decode(errors="replace")
        tail = ""
        if stat.st_size > _HEAD_BYTES:
            fh.seek(max(stat.st_size - _TAIL_BYTES, _HEAD_BYTES))
            tail = fh.read().decode(errors="replace")

    first_prompt = ""
    for rec in _iter_json(head.splitlines()):
        if rec.get("type") == "user":
            text = _text_of(rec).strip()
            # skip harness-injected wrappers, slash-command echoes, tool results
            if text and not text.startswith(("<", "/")) and "tool_result" not in text[:40]:
                first_prompt = text
                break

    last_assistant = ""
    # tail lines may start mid-record; drop the first partial line
    tail_lines = tail.splitlines()[1:] if tail else head.splitlines()
    for rec in _iter_json(tail_lines):
        if rec.get("type") == "assistant":
            text = _text_of(rec).strip()
            if text:
                last_assistant = text

    summary = {
        "session_id": path.stem,
        "namespace": path.parent.name,
        "mtime": stat.st_mtime,
        "size": stat.st_size,
        "first_prompt": first_prompt[:400],
        "last_assistant": last_assistant[-500:],
        "open_loop": bool(last_assistant and _OPEN_LOOP.search(last_assistant[-400:])),
    }
    _cache[str(path)] = (stat.st_mtime, summary)
    return summary


def recent_sessions(claude_dir: Path, limit: int = 40, namespace: str | None = None) -> list[dict]:
    projects = claude_dir / "projects"
    if not projects.is_dir():
        return []
    candidates: list[Path] = []
    dirs = [projects / namespace] if namespace else list(projects.iterdir())
    for ns in dirs:
        if ns.is_dir():
            candidates.extend(ns.glob("*.jsonl"))
    candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return [summarize_session(p) for p in candidates[:limit]]


def namespace_display(ns: str) -> str:
    """Best-effort prettifier for the path-encoded namespace directory name."""
    home_ns = str(Path.home()).replace("/", "-")
    if ns.startswith(home_ns + "-projects-"):
        return ns[len(home_ns + "-projects-") :]
    if ns == home_ns:
        return "(home estate)"
    return ns
