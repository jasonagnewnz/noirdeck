"""Where things live in the two ways noirdeck runs.

Development: a git checkout, SPA built into frontend/dist, state under the
repo (data/noirdeck.db), timers driven by systemd units in ops/.

Installed: a wheel in site-packages. The repo is gone, so the SPA travels
inside the package (noirdeck/web) and state moves to the user data dir. This
module is the only place that knows the difference.
"""

from __future__ import annotations

import os
from pathlib import Path

PKG_DIR = Path(__file__).resolve().parent
REPO_ROOT = PKG_DIR.parents[1]


def is_repo_checkout() -> bool:
    """True when running from a source tree rather than an installed wheel."""
    return (REPO_ROOT / "pyproject.toml").is_file() and (REPO_ROOT / "backend").is_dir()


def web_dir() -> Path | None:
    """The built SPA, or None when the frontend has not been built.

    Bundled copy wins: an installed wheel always ships the matching build,
    while a stale frontend/dist in a checkout should not shadow it.
    """
    for candidate in (PKG_DIR / "web", REPO_ROOT / "frontend" / "dist"):
        if (candidate / "index.html").is_file():
            return candidate
    return None


def data_home() -> Path:
    """Directory for state we create: the database, vault scratch, exports.

    A checkout keeps state in the repo (unchanged from how it has always
    worked). An installed copy follows XDG so uninstalling never eats data.
    """
    if is_repo_checkout():
        return REPO_ROOT
    base = os.environ.get("XDG_DATA_HOME") or "~/.local/share"
    return Path(base).expanduser() / "noirdeck"


def default_db_path() -> Path:
    """Default database location for each mode (NOIRDECK_DB_PATH overrides)."""
    if is_repo_checkout():
        return REPO_ROOT / "data" / "noirdeck.db"
    return data_home() / "noirdeck.db"
