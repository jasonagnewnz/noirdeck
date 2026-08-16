"""Deterministic context pack — the harness does the research, in code, for free.

Every headless session historically spent its opening turns rediscovering the
same facts: what's in the repo, how to run the tests, what changed recently.
This module computes that once, deterministically, and the runners prepend it —
input tokens instead of exploration turns, and zero model spend to produce.

Hard-capped: a context pack that bloats the prompt would defeat its purpose."""

from __future__ import annotations

import subprocess
from pathlib import Path

from .config import Settings

PACK_CAP_CHARS = 7000  # ~1.8k tokens ceiling for the whole pack
_SECTION_CAP = 1600


def _git(repo: Path, *args: str) -> str:
    try:
        r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, timeout=15)
        return r.stdout.strip() if r.returncode == 0 else ""
    except (subprocess.TimeoutExpired, OSError):
        return ""


def _layout(repo: Path) -> str:
    try:
        entries = sorted(repo.iterdir(), key=lambda p: (p.is_file(), p.name))
    except OSError:
        return ""
    keep = [e for e in entries if e.name not in {".git", "node_modules", "__pycache__", ".venv", "venv", "dist"}]
    return "\n".join(f"  {e.name}{'/' if e.is_dir() else ''}" for e in keep[:30])


def _test_command(repo: Path) -> str:
    if (
        any(repo.glob("**/pytest.ini"))
        or (repo / "tests").is_dir()
        or any(repo.glob("*/tests"))
        or any(repo.glob("**/test_*.py"))
    ):
        hint = "python3 -m pytest"
        for sub in ("backend", "tests", "."):
            if (repo / sub / "tests").is_dir() or (sub == "tests" and (repo / sub).is_dir()):
                hint = f"python3 -m pytest  (from {sub}/)" if sub != "." else hint
                break
        return hint
    pkg = repo / "package.json"
    if pkg.is_file() and '"test"' in pkg.read_text(errors="replace"):
        return "npm test"
    if (repo / "Makefile").is_file() and "test" in (repo / "Makefile").read_text(errors="replace"):
        return "make test"
    return "none detected"


def _memory_hooks(repo: Path, settings: Settings) -> str:
    """First lines of the project's own memory index, when one exists."""
    ns = str(repo).replace("/", "-")
    index = settings.claude_dir / "projects" / ns / "memory" / "MEMORY.md"
    try:
        lines = index.read_text(errors="replace").splitlines()
    except OSError:
        return ""
    return "\n".join(lines[:25])


def context_pack(repo: Path, settings: Settings) -> str:
    """Plain-text pack. Empty string for an unreadable/empty target — callers
    prepend it verbatim, so absence must cost nothing."""
    sections: list[tuple[str, str]] = []
    layout = _layout(repo)
    if layout:
        sections.append(("Top-level layout", layout))
        sections.append(("Test command", _test_command(repo)))
    commits = _git(repo, "log", "--format=%h %s", "-5")
    if commits:
        sections.append(("Recent commits", commits))
    porcelain = _git(repo, "status", "--porcelain")
    if porcelain:
        dirty = porcelain.splitlines()
        sections.append(
            (
                "Uncommitted right now",
                "\n".join(dirty[:10]) + (f"\n  …and {len(dirty) - 10} more" if len(dirty) > 10 else ""),
            )
        )
    readme = repo / "README.md"
    if readme.is_file():
        sections.append(("README head", "\n".join(readme.read_text(errors="replace").splitlines()[:12])))
    hooks = _memory_hooks(repo, settings)
    if hooks:
        sections.append(("Project memory index (read the note files for detail)", hooks))

    if not sections:
        return ""
    body = "\n\n".join(f"## {title}\n{text[:_SECTION_CAP]}" for title, text in sections)
    pack = (
        "PROJECT CONTEXT PACK (computed by the harness from the live repo — "
        "use it instead of re-discovering these facts; verify only what you rely on):\n\n" + body
    )
    return pack[:PACK_CAP_CHARS]
