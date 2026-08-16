"""Git fleet board across ~/projects: dirty trees, unpushed commits, local-only branches.

Guard (estate landmine): only treat <dir> as a repo if <dir>/.git exists — `git -C`
walks UP to an enclosing repo otherwise and reports the wrong project.
"""

from __future__ import annotations

import subprocess
from pathlib import Path


def _git(repo: Path, *args: str) -> str | None:
    try:
        r = subprocess.run(
            ["git", "-C", str(repo), *args],
            capture_output=True,
            text=True,
            timeout=8,
        )
        return r.stdout.strip() if r.returncode == 0 else None
    except (subprocess.TimeoutExpired, OSError):
        return None


def repo_state(repo: Path) -> dict:
    branch = _git(repo, "rev-parse", "--abbrev-ref", "HEAD") or "?"
    status = _git(repo, "status", "--porcelain")
    dirty = len(status.splitlines()) if status else 0
    unpushed = _git(repo, "rev-list", "--count", "@{u}..HEAD")
    has_upstream = unpushed is not None
    last_ct = _git(repo, "log", "-1", "--format=%ct")
    return {
        "name": repo.name,
        "path": str(repo),
        "branch": branch,
        "dirty_files": dirty,
        "has_upstream": has_upstream,
        "unpushed_commits": int(unpushed) if unpushed and unpushed.isdigit() else None,
        "last_commit_ts": int(last_ct) if last_ct and last_ct.isdigit() else None,
    }


def repo_dirs(projects_dir: Path) -> list[Path]:
    if not projects_dir.is_dir():
        return []
    return [c for c in sorted(projects_dir.iterdir()) if c.is_dir() and (c / ".git").exists()]


_cache: dict = {"ts": 0.0, "data": None}
_TTL = 60  # seconds


def fleet(projects_dir: Path) -> list[dict]:
    """~4 git subprocesses per repo × 50+ repos: parallelised + TTL-cached, or the
    overview endpoint hangs for tens of seconds (bit the first live run)."""
    import time
    from concurrent.futures import ThreadPoolExecutor

    if _cache["data"] is not None and time.monotonic() - _cache["ts"] < _TTL:
        return _cache["data"]
    dirs = repo_dirs(projects_dir)
    with ThreadPoolExecutor(max_workers=8) as ex:
        out = list(ex.map(repo_state, dirs))
    _cache.update(ts=time.monotonic(), data=out)
    return out


def fleet_attention(states: list[dict]) -> list[dict]:
    """Repos needing eyes: dirty, unpushed, or local-only branch."""
    flagged = []
    for s in states:
        reasons = []
        if s["dirty_files"]:
            reasons.append(f"{s['dirty_files']} uncommitted file(s)")
        if s["unpushed_commits"]:
            reasons.append(f"{s['unpushed_commits']} unpushed commit(s)")
        if not s["has_upstream"]:
            reasons.append(f"branch '{s['branch']}' has no upstream (local-only)")
        if reasons:
            flagged.append({**s, "reasons": reasons})
    return flagged
