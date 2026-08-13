"""Harness-level guardrails for headless pipeline sessions. Converts the
prompt-level 'never push / never deploy' instruction into ENFORCEMENT: every
pipeline `claude -p` launches with a PreToolUse hook (ops/pipeline-guard.py)
that denies outward-mutating Bash before execution."""
from __future__ import annotations

import json
import sys
from pathlib import Path

GUARD_SCRIPT = Path(__file__).resolve().parents[2] / "ops" / "pipeline-guard.py"


def guard_settings_args() -> list[str]:
    """CLI args enforcing the code-ready boundary; [] only if the guard script
    is missing (never expected — loud fallback beats a silently inert guard)."""
    if not GUARD_SCRIPT.is_file():
        print(f"WARNING: pipeline guard missing at {GUARD_SCRIPT} — "
              "sessions run with prompt-level guardrails only", file=sys.stderr)
        return []
    settings = {"hooks": {"PreToolUse": [{
        "matcher": "Bash",
        "hooks": [{"type": "command", "command": f"python3 {GUARD_SCRIPT}"}],
    }]}}
    return ["--settings", json.dumps(settings)]
