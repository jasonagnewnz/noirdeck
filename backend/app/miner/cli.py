"""CLI entry for the nightly timer: `python -m app.miner.cli [heuristic|nightly]`."""

from __future__ import annotations

import json
import sys

from ..config import Settings
from ..db import connect, init_db
from .heuristics import run_heuristics
from .runner import run_llm_mining


def main() -> None:
    mode = sys.argv[1] if len(sys.argv) > 1 else "heuristic"
    settings = Settings.load()
    init_db(settings.db_path)
    conn = connect(settings.db_path)
    try:
        out = {"heuristics": run_heuristics(conn, settings.claude_dir)}
        if mode == "nightly":
            out["llm"] = run_llm_mining(conn, settings)
        print(json.dumps(out))
    finally:
        conn.close()


if __name__ == "__main__":
    main()
