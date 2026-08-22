"""Harness-level guardrails for headless pipeline sessions. Converts the
prompt-level 'never push / never deploy / never touch the operator's knowledge'
instructions into ENFORCEMENT: every pipeline launch carries a PreToolUse hook
(noirdeck.pipeline_guard) that denies, before execution, both outward-mutating
Bash and any write into the operator's AI workspace.

THE GUARD MUST LIVE INSIDE THE PACKAGE, AND BE INVOKED BY PATH.
Until 2026-08-19 it was `ops/pipeline-guard.py`, resolved as
`Path(__file__).parents[2] / "ops" / ...`. That works in a git checkout and NEVER
works in an installed wheel, because pyproject packages only `backend/noirdeck`:
so for every pip-installed copy this returned [] and unattended sessions ran with
`--permission-mode acceptEdits` and no hook whatsoever. The safety story was
checkout-only.

It is invoked as a FILE PATH next to this module, not as `-m
noirdeck.pipeline_guard`. The module form is the mirror-image trap: it works in a
wheel and fails in a checkout, where `backend/` is not on sys.path (the app runs
via `--app-dir backend`). The guard imports nothing from the package: stdlib
only, deliberately: so a path invocation needs no importable package and works
in both. Keep it dependency-free or this breaks.

FAILS CLOSED. A missing guard used to print a warning and continue, which in
an unattended background process is exactly a silently inert guard. It now
raises: no boundary means no pipeline.

The matcher MUST cover the file-writing tools, not just Bash. Until
2026-08-19 it was "Bash" alone, so Write/Edit/MultiEdit/NotebookEdit were never
handed to the hook at all. Narrowing this matcher re-opens a hole that let a
pipeline rewrite CLAUDE.md, memories and skills unreviewed.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Every tool that can create or modify a file, plus Bash. Keep in step with
# WRITE_TOOLS in pipeline_guard.py: the hook can only judge calls the harness
# actually routes to it.
GUARDED_TOOLS = ("Bash", "Write", "Edit", "MultiEdit", "NotebookEdit")

# Beside this module, therefore inside the packaged directory, therefore in the
# wheel. test_packaging.py asserts both halves of that sentence.
GUARD_SCRIPT = Path(__file__).with_name("pipeline_guard.py")


class GuardUnavailable(RuntimeError):
    """The harness guard cannot be located, so no pipeline may start."""


def guard_available() -> bool:
    """Whether the guard file is actually present. Checked rather than assumed:
    this is the exact thing that was false in every shipped wheel."""
    return GUARD_SCRIPT.is_file()


def guard_settings_args() -> list[str]:
    """CLI args enforcing the code-ready + knowledge-read-only boundaries.

    Raises GuardUnavailable rather than degrading. An unattended session with no
    boundary is worse than no session, and a warning on a daemon's stderr is not
    a control.
    """
    if not guard_available():
        raise GuardUnavailable(
            f"the pipeline guard ({GUARD_SCRIPT}) could not be found, so no unattended "
            "session may start. This means the noirdeck install is incomplete: reinstall "
            "the package."
        )
    # sys.executable, not "python3": the hook must run under an interpreter that
    # certainly exists, and a bare `python3` may not be on a service's PATH.
    settings = {
        "hooks": {
            "PreToolUse": [
                {
                    "matcher": "|".join(GUARDED_TOOLS),
                    "hooks": [{"type": "command", "command": f"{sys.executable} {GUARD_SCRIPT}"}],
                }
            ]
        }
    }
    return ["--settings", json.dumps(settings)]
