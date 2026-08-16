"""Try-it preview — serve a build's static web output read-only so the operator
can USE the thing, not just read that it exists.

Same trust boundary as the file APIs: the project must be a single path segment
naming a direct child of the projects dir (~ is itself a git repo, so any
multi-segment or dot form could escape — 4th instance of that class), and every
served file must resolve inside the discovered preview root. The frontend
embeds this in a sandboxed iframe (no same-origin), so previewed code can't
reach the noirdeck API with page authority."""

from __future__ import annotations

import mimetypes
from pathlib import Path

from .config import Settings

# Where web builds conventionally put a browsable entry point, most-built first.
_ENTRY_DIRS = ("dist", "build", "public", "site", "")
_MAX_BYTES = 5 * 1024 * 1024


class PreviewError(RuntimeError):
    pass


def _safe_project(settings: Settings, project: str) -> Path:
    if "/" in project or "\\" in project or project in ("", ".", ".."):
        raise PreviewError("bad project name")
    base = settings.projects_dir.resolve()
    repo = (base / project).resolve()
    if repo.parent != base or not repo.is_dir():
        raise PreviewError(f"no such project: {project}")
    return repo


def preview_root(settings: Settings, project: str) -> Path | None:
    """The directory whose index.html anchors the preview, or None if this
    project has no static web entry point."""
    repo = _safe_project(settings, project)
    for sub in _ENTRY_DIRS:
        root = (repo / sub) if sub else repo
        if (root / "index.html").is_file():
            return root.resolve()
    return None


def info(settings: Settings, project: str) -> dict:
    root = preview_root(settings, project)
    repo = _safe_project(settings, project)
    return {"available": root is not None, "entry": str(root.relative_to(repo)) if root else None}


def resolve_file(settings: Settings, project: str, path: str) -> tuple[Path, str]:
    """(file, media-type) for a path inside the preview root; traversal-checked
    against the RESOLVED path so encoded dots can't escape."""
    root = preview_root(settings, project)
    if root is None:
        raise PreviewError(f"{project} has no web preview (no index.html found)")
    rel = path or "index.html"
    if rel.startswith(("/", "\\")) or ".." in Path(rel).parts:
        raise PreviewError("bad path")
    f = (root / rel).resolve()
    if root != f and root not in f.parents:
        raise PreviewError("path escapes the preview root")
    if f.is_dir():
        f = f / "index.html"
    if not f.is_file():
        raise PreviewError(f"not found: {rel}")
    if f.stat().st_size > _MAX_BYTES:
        raise PreviewError("file too large to preview")
    media = mimetypes.guess_type(f.name)[0] or "application/octet-stream"
    return f, media
