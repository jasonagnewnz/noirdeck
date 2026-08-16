"""Environment-driven settings. Fails closed on a missing Claude dir."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


class ConfigError(RuntimeError):
    pass


def _path(env: str, default: str) -> Path:
    return Path(os.environ.get(env, default)).expanduser()


_MODEL_DEFAULTS = {"think": "claude-fable-5", "build": "claude-sonnet-5", "review": "claude-opus-4-8"}


def model(role: str) -> str:
    """Pinned model id for a pipeline role (think/build/review). Defaults are the
    author's routing preferences — override with NOIRDECK_MODEL_THINK/BUILD/REVIEW
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

    @classmethod
    def load(cls) -> "Settings":
        claude_dir = _path("NOIRDECK_CLAUDE_DIR", "~/.claude")
        if not claude_dir.is_dir():
            raise ConfigError(f"NOIRDECK_CLAUDE_DIR does not exist: {claude_dir}")
        projects_dir = _path("NOIRDECK_PROJECTS_DIR", "~/projects")
        db_raw = os.environ.get("NOIRDECK_DB_PATH", "data/noirdeck.db")
        db_path = Path(db_raw)
        if not db_path.is_absolute():
            db_path = REPO_ROOT / db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        return cls(
            claude_dir=claude_dir,
            projects_dir=projects_dir,
            db_path=db_path,
            port=int(os.environ.get("NOIRDECK_PORT", "4747")),
            mining_armed=os.environ.get("NOIRDECK_MINING_ARMED", "") == "true",
            overnight_armed=os.environ.get("NOIRDECK_OVERNIGHT_ARMED", "") == "true",
            mine_max_batches=int(os.environ.get("NOIRDECK_MINE_MAX_BATCHES", "8")),
        )
