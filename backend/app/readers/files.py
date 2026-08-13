"""Read-only project file browsing for the IDE shell. Strictly inside the
projects dir; heavy/derived dirs skipped; file reads capped and text-only."""
from __future__ import annotations

from pathlib import Path

SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", "dist",
             ".pytest_cache", ".mypy_cache", ".ruff_cache", "data", ".next", "build"}
MAX_FILE_BYTES = 200_000


class FilesError(RuntimeError):
    pass


def _resolve(projects_dir: Path, project: str, rel: str) -> Path:
    # `project` must be a single path segment naming a direct child of the
    # projects dir — ~ is itself a git repo, so ".." would pass the .git check
    # and expose the whole home directory.
    if "/" in project or "\\" in project or project in ("", ".", ".."):
        raise FilesError(f"unknown project {project}")
    base = projects_dir.resolve()
    repo = (base / project).resolve()
    if repo.parent != base:
        raise FilesError(f"unknown project {project}")
    if not (repo.is_dir() and (repo / ".git").exists()):
        raise FilesError(f"unknown project {project}")
    target = (repo / rel).resolve() if rel else repo
    if target != repo and repo not in target.parents:
        raise FilesError("path outside project")
    return target


def list_dir(projects_dir: Path, project: str, rel: str = "") -> list[dict]:
    target = _resolve(projects_dir, project, rel)
    if not target.is_dir():
        raise FilesError("not a directory")
    out = []
    for p in sorted(target.iterdir(), key=lambda x: (x.is_file(), x.name.lower())):
        if p.name in SKIP_DIRS or p.name.startswith(".git"):
            continue
        try:
            stat = p.stat()
        except OSError:
            continue
        out.append({
            "name": p.name,
            "type": "dir" if p.is_dir() else "file",
            "size": stat.st_size if p.is_file() else None,
            "path": f"{rel}/{p.name}".lstrip("/"),
        })
    return out


def read_file(projects_dir: Path, project: str, rel: str) -> dict:
    target = _resolve(projects_dir, project, rel)
    if not target.is_file():
        raise FilesError("not a file")
    raw = target.read_bytes()[:MAX_FILE_BYTES + 1]
    if b"\x00" in raw[:8000]:
        raise FilesError("binary file")
    truncated = len(raw) > MAX_FILE_BYTES
    return {
        "path": rel,
        "content": raw[:MAX_FILE_BYTES].decode("utf-8", errors="replace"),
        "truncated": truncated,
        "size": target.stat().st_size,
    }
