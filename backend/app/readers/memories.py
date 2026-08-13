"""Memory namespaces: ~/.claude/projects/<ns>/memory/*.md"""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from pathlib import Path

from .frontmatter import parse_frontmatter

_STOP = {
    "the", "a", "and", "for", "with", "not", "are", "is", "of", "to", "in", "on",
    "feedback", "fb", "reference", "gotcha", "check", "api",
}


def _namespaces(claude_dir: Path):
    projects = claude_dir / "projects"
    if not projects.is_dir():
        return
    for ns in sorted(projects.iterdir()):
        mem = ns / "memory"
        if mem.is_dir():
            yield ns.name, mem


_cache: dict[str, tuple[float, list]] = {}
_TTL = 120  # 15k+ frontmatter reads across 133 namespaces — never do it per request


def list_memories(claude_dir: Path) -> list[dict]:
    import time
    hit = _cache.get(str(claude_dir))
    if hit and time.monotonic() - hit[0] < _TTL:
        return hit[1]
    out: list[dict] = []
    for ns_name, mem in _namespaces(claude_dir):
        for f in sorted(mem.glob("*.md")):
            if f.name == "MEMORY.md":
                continue
            fm, _ = parse_frontmatter(f, max_bytes=4096)
            meta = fm.get("metadata") or {}
            out.append({
                "namespace": ns_name,
                "name": fm.get("name") or f.stem,
                "description": (fm.get("description") or "").strip(),
                "type": meta.get("type") if isinstance(meta, dict) else None,
                "file": f.name,
                "size": f.stat().st_size,
                "mtime": f.stat().st_mtime,
            })
    import time
    _cache[str(claude_dir)] = (time.monotonic(), out)
    return out


def _topic_tokens(name: str) -> list[str]:
    name = re.sub(r"^(feedback|fb|reference)_", "", name)
    toks = [t for t in re.split(r"[_\-.]", name.lower()) if len(t) > 2 and t not in _STOP]
    return toks


def group_memories(memories: list[dict], min_group: int = 4) -> list[dict]:
    """Cluster memory files sharing a topic token within a namespace — consolidation candidates."""
    buckets: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for m in memories:
        for tok in set(_topic_tokens(m["name"])):
            buckets[(m["namespace"], tok)].append(m)
    groups = []
    seen_membersets: set[frozenset] = set()
    for (ns, tok), members in buckets.items():
        if len(members) < min_group:
            continue
        key = frozenset(m["name"] for m in members)
        if key in seen_membersets:
            continue
        seen_membersets.add(key)
        groups.append({
            "namespace": ns,
            "topic": tok,
            "count": len(members),
            "members": sorted(m["name"] for m in members),
        })
    groups.sort(key=lambda g: -g["count"])
    return groups


def memory_stats(memories: list[dict]) -> dict:
    by_type = Counter(m["type"] or "untyped" for m in memories)
    by_ns = Counter(m["namespace"] for m in memories)
    return {
        "total": len(memories),
        "by_type": dict(by_type),
        "namespaces": len(by_ns),
        "top_namespaces": by_ns.most_common(10),
    }
