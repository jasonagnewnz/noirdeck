"""history.jsonl intelligence: activity stats, search, repeated-prompt detection."""

from __future__ import annotations

import json
import re
from collections import Counter
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

NZ = ZoneInfo("Pacific/Auckland")
_cache: dict[str, tuple[float, list[dict]]] = {}


def load_history(claude_dir: Path) -> list[dict]:
    path = claude_dir / "history.jsonl"
    if not path.is_file():
        return []
    stat = path.stat()
    cached = _cache.get(str(path))
    if cached and cached[0] == stat.st_mtime:
        return cached[1]
    records: list[dict] = []
    with open(path, errors="replace") as fh:
        for line in fh:
            try:
                rec = json.loads(line)
            except (json.JSONDecodeError, ValueError):
                continue
            display = (rec.get("display") or "").strip()
            if not display:
                continue
            records.append(
                {
                    "display": display,
                    "ts": rec.get("timestamp", 0),
                    "project": rec.get("project") or "?",
                    "session_id": rec.get("sessionId"),
                }
            )
    _cache[str(path)] = (stat.st_mtime, records)
    return records


def normalize(prompt: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", "", prompt.lower())).strip()


def history_stats(records: list[dict]) -> dict:
    by_project: Counter = Counter()
    by_hour: Counter = Counter()
    by_day: Counter = Counter()
    slash: Counter = Counter()
    prompt_lengths: list[int] = []
    for r in records:
        by_project[r["project"]] += 1
        dt = datetime.fromtimestamp(r["ts"] / 1000, tz=NZ)
        by_hour[dt.hour] += 1
        by_day[dt.strftime("%Y-%m-%d")] += 1
        d = r["display"]
        if d.startswith("/"):
            slash[d.split()[0]] += 1
        else:
            prompt_lengths.append(len(d))
    days_sorted = sorted(by_day.items())[-30:]
    return {
        "total_prompts": len(records),
        "top_projects": by_project.most_common(15),
        "by_hour": [by_hour.get(h, 0) for h in range(24)],
        "last_30_days": days_sorted,
        "top_slash": slash.most_common(20),
        "avg_prompt_chars": round(sum(prompt_lengths) / len(prompt_lengths)) if prompt_lengths else 0,
    }


def search_history(records: list[dict], q: str, limit: int = 200) -> list[dict]:
    ql = q.lower()
    hits = [r for r in records if ql in r["display"].lower()]
    hits.sort(key=lambda r: -r["ts"])
    return hits[:limit]


def repeated_prompts(records: list[dict], min_count: int = 3) -> list[dict]:
    """Non-slash prompts typed near-identically N+ times — skill-gap candidates."""
    buckets: dict[str, list[dict]] = {}
    for r in records:
        d = r["display"]
        if d.startswith("/") or len(d) < 12:
            continue
        key = normalize(d)[:120]
        buckets.setdefault(key, []).append(r)
    out = []
    for key, rs in buckets.items():
        if len(rs) >= min_count:
            out.append(
                {
                    "normalized": key,
                    "count": len(rs),
                    "example": rs[-1]["display"][:300],
                    "projects": sorted({x["project"] for x in rs}),
                    "last_ts": max(x["ts"] for x in rs),
                }
            )
    out.sort(key=lambda x: -x["count"])
    return out
