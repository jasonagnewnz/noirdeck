"""Environment-driven settings. Fails closed on a missing Claude dir."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from .paths import data_home, default_db_path


class ConfigError(RuntimeError):
    pass


def _path(env: str, default: str) -> Path:
    return Path(os.environ.get(env, default)).expanduser()


_MODEL_DEFAULTS = {"think": "claude-fable-5", "build": "claude-sonnet-5", "review": "claude-opus-5"}


def model(role: str) -> str:
    """Pinned model id for a pipeline role (think/build/review). Defaults are the
    author's routing preferences: override with NOIRDECK_MODEL_THINK/BUILD/REVIEW
    if your Claude install doesn't resolve these ids."""
    return os.environ.get(f"NOIRDECK_MODEL_{role.upper()}", _MODEL_DEFAULTS[role])


def primary_namespace() -> str:
    """The Claude Code memory namespace automation may write to (via proposals).
    Claude Code names namespaces after the launch path with '/' -> '-', so the
    home-directory namespace is derived, never hardcoded to any one machine."""
    return os.environ.get("NOIRDECK_PRIMARY_NAMESPACE") or str(Path.home()).replace("/", "-")


@dataclass(frozen=True)
class Settings:
    claude_dir: Path
    projects_dir: Path
    db_path: Path
    port: int
    mining_armed: bool
    overnight_armed: bool
    mine_max_batches: int
    # Whether the AI workspace actually exists. Not fatal: a first run without
    # Claude Code is legitimate: but the UI and `doctor` must be able to say so,
    # because "no skills, no memories" and "no workspace" look identical otherwise
    # and silence would read as an empty estate rather than a missing one.
    claude_dir_ready: bool = True

    @classmethod
    def load(cls) -> "Settings":
        # This used to raise when ~/.claude was absent, which meant a
        # brand-new install exited 1 instead of starting: for ANY runner. The
        # product advertises Codex, Ollama and "bring your own CLI", none of
        # which need a Claude directory, and the error named `doctor` as the
        # remedy when doctor can only diagnose. An EMPTY directory works fine
        # (every reader is is_dir()-guarded), so absence must never be fatal.
        # projects_dir has always been unvalidated; claude_dir now matches.
        claude_dir = _path("NOIRDECK_CLAUDE_DIR", "~/.claude")
        explicitly_set = bool(os.environ.get("NOIRDECK_CLAUDE_DIR"))
        if not claude_dir.is_dir() and not explicitly_set:
            # Only ever create the DEFAULT location. If someone named a directory
            # explicitly and it is not there, that is likely a typo and inventing
            # it would hide their mistake: so it is surfaced, not fabricated.
            try:
                claude_dir.mkdir(parents=True, exist_ok=True)
            except OSError:
                pass  # reported via claude_dir_ready, never fatal
        projects_dir = _path("NOIRDECK_PROJECTS_DIR", "~/projects")
        db_raw = os.environ.get("NOIRDECK_DB_PATH")
        # A relative override resolves against the data home for the current
        # mode, so an installed copy never writes into site-packages.
        db_path = default_db_path() if not db_raw else Path(db_raw).expanduser()
        if not db_path.is_absolute():
            db_path = data_home() / db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        return cls(
            claude_dir=claude_dir,
            claude_dir_ready=claude_dir.is_dir(),
            projects_dir=projects_dir,
            db_path=db_path,
            port=int(os.environ.get("NOIRDECK_PORT", "4747")),
            mining_armed=os.environ.get("NOIRDECK_MINING_ARMED", "") == "true",
            overnight_armed=os.environ.get("NOIRDECK_OVERNIGHT_ARMED", "") == "true",
            mine_max_batches=int(os.environ.get("NOIRDECK_MINE_MAX_BATCHES", "8")),
        )
