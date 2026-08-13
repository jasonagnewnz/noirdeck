"""Commit intelligence over the local fleet (local clones of the GitHub estate).

Two jobs:
- a cross-repo commit feed (what changed lately, everywhere)
- follow-on detection: changes whose customary companion change is missing —
  the "pre-empt what comes next" signal for briefings.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

_TEST_HINT = re.compile(r"(^|/)(tests?/|test_[^/]+$|[^/]+[._]test\.[jt]sx?$|conftest\.py$)")
_SCHEMA_HINT = re.compile(r"(migrations?/|alembic/|schema|models?\.py$)", re.I)
_WIP = re.compile(r"^\s*(wip|tmp|fixup|checkpoint)\b", re.I)


def _git(repo: Path, *args: str, timeout: int = 10) -> str | None:
    try:
        r = subprocess.run(["git", "-C", str(repo), *args],
                           capture_output=True, text=True, timeout=timeout)
        return r.stdout if r.returncode == 0 else None
    except (subprocess.TimeoutExpired, OSError):
        return None


def recent_commits(repo: Path, n: int = 20) -> list[dict]:
    out = _git(repo, "log", f"-{n}", "--format=%h%x1f%ct%x1f%an%x1f%s")
    commits = []
    for line in (out or "").splitlines():
        parts = line.split("\x1f")
        if len(parts) == 4:
            commits.append({
                "repo": repo.name, "sha": parts[0], "ts": int(parts[1]),
                "author": parts[2], "subject": parts[3][:160],
            })
    return commits


def follow_on_flags(repo: Path, depth: int = 10) -> list[dict]:
    """Recent commits whose customary companion change is missing."""
    out = _git(repo, "log", f"-{depth}", "--name-only", "--format=%x1e%h%x1f%s", timeout=15)
    flags: list[dict] = []
    if not out:
        return flags
    for chunk in out.split("\x1e"):
        chunk = chunk.strip()
        if not chunk:
            continue
        header, _, body = chunk.partition("\n")
        sha, _, subject = header.partition("\x1f")
        files = [f.strip() for f in body.splitlines() if f.strip()]

        def flag(kind: str, detail: str) -> None:
            flags.append({"repo": repo.name, "sha": sha, "subject": subject[:120],
                          "kind": kind, "detail": detail})

        if _WIP.search(subject):
            flag("wip-commit", "WIP/checkpoint commit left at or near the tip")
        touched_schema = [f for f in files if _SCHEMA_HINT.search(f)]
        touched_tests = any(_TEST_HINT.search(f) for f in files)
        if touched_schema and not touched_tests:
            flag("schema-no-tests",
                 f"schema/migration files changed with no test change ({touched_schema[0]}…)")
        if any(f.endswith(".env.example") for f in files):
            flag("env-contract",
                 "env contract changed — server .env and docs need the same change")
    return flags


def fleet_feed(projects_dir: Path, per_repo: int = 5, limit: int = 40) -> list[dict]:
    from concurrent.futures import ThreadPoolExecutor

    from .fleet import repo_dirs
    dirs = repo_dirs(projects_dir)
    with ThreadPoolExecutor(max_workers=8) as ex:
        chunks = ex.map(lambda r: recent_commits(r, per_repo), dirs)
    feed = [c for chunk in chunks for c in chunk]
    feed.sort(key=lambda c: -c["ts"])
    return feed[:limit]


def fleet_flags(projects_dir: Path, limit: int = 30) -> list[dict]:
    from concurrent.futures import ThreadPoolExecutor

    from .fleet import repo_dirs
    dirs = repo_dirs(projects_dir)
    with ThreadPoolExecutor(max_workers=8) as ex:
        chunks = ex.map(follow_on_flags, dirs)
    return [f for chunk in chunks for f in chunk][:limit]
