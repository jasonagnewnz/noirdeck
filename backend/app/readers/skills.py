"""Skills and agents catalogues from ~/.claude."""
from __future__ import annotations

from pathlib import Path

from .frontmatter import parse_frontmatter


def list_skills(claude_dir: Path) -> list[dict]:
    skills_dir = claude_dir / "skills"
    out: list[dict] = []
    if not skills_dir.is_dir():
        return out
    for entry in sorted(skills_dir.iterdir()):
        skill_md = entry / "SKILL.md"
        # is_dir/is_file are False for dangling symlinks, but stat can still race — guard it
        if not (entry.is_dir() and skill_md.is_file()):
            continue
        fm, _ = parse_frontmatter(skill_md)
        try:
            stat = skill_md.stat()
        except OSError:
            continue
        out.append({
            "name": fm.get("name") or entry.name,
            "description": (fm.get("description") or "").strip(),
            "model": fm.get("model"),
            "dir": entry.name,
            "size": stat.st_size,
            "mtime": stat.st_mtime,
            "has_references": any(p.is_dir() for p in entry.iterdir()),
        })
    return out


def list_agents(claude_dir: Path) -> list[dict]:
    agents_dir = claude_dir / "agents"
    out: list[dict] = []
    if not agents_dir.is_dir():
        return out
    for f in sorted(agents_dir.glob("*.md")):
        try:
            mtime = f.stat().st_mtime  # glob can return dangling symlinks (seen live)
        except OSError:
            continue
        fm, _ = parse_frontmatter(f)
        out.append({
            "name": fm.get("name") or f.stem,
            "description": (fm.get("description") or "").strip()[:600],
            "model": fm.get("model"),
            "tools": fm.get("tools"),
            "file": f.name,
            "mtime": mtime,
        })
    return out
