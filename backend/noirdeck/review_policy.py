"""When is a model review worth its tokens? One deterministic answer, shared by
the build pipeline and the staged queue runner.

The rule is asymmetric on purpose: every path that can't be measured reviews
anyway (fail-safe), and security-flagged paths ALWAYS review regardless of
size. Skipping is only allowed when the change is measurably small, fully
tracked, and the deterministic QA gates found nothing blocking: the exact
territory where a paid review pass reliably finds nothing the gates didn't."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

# Paths where a small diff can still be a large mistake.
SECURITY_PATH = re.compile(
    r"(auth|guard|secret|token|crypt|passw|permission|proposal|tenan|session"
    r"|login|acl|sandbox|redact|arming)",
    re.I,
)

SMALL_CHANGE_LINES = 40


def review_needed(
    lines_changed: int, files: list[str], gates_overall: str, untracked: list[str] | None = None
) -> tuple[bool, str]:
    """(needed, reason). Reasons are operator-facing: they appear in phase logs."""
    if untracked:
        return True, f"{len(untracked)} untracked file(s) present: content unmeasured, reviewing"
    flagged = sorted(f for f in files if SECURITY_PATH.search(f))
    if flagged:
        return True, f"security-flagged path touched ({flagged[0]}): always reviewed"
    if gates_overall == "BLOCKER":
        return True, "a deterministic QA gate is at BLOCKER"
    if lines_changed <= SMALL_CHANGE_LINES:
        return False, (
            f"small change ({lines_changed} lines), no security paths, "
            f"gates {gates_overall}: deterministic rule, no model review"
        )
    return True, f"substantial change ({lines_changed} lines)"


def _git(repo: Path, *args: str) -> tuple[int, str]:
    try:
        r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, timeout=20)
        return r.returncode, r.stdout
    except (subprocess.TimeoutExpired, OSError):
        return 1, ""


def head(repo: Path) -> str | None:
    rc, out = _git(repo, "rev-parse", "HEAD")
    return out.strip() if rc == 0 and out.strip() else None


def diff_since(repo: Path, baseline: str) -> dict | None:
    """Worktree-vs-baseline change account: committed AND uncommitted tracked
    changes plus untracked names. None when it can't be measured (callers must
    treat None as review-needed)."""
    rc, numstat = _git(repo, "diff", "--numstat", baseline)
    if rc != 0:
        return None
    lines = 0
    files: list[str] = []
    for row in numstat.splitlines():
        parts = row.split("\t")
        if len(parts) != 3:
            continue
        add, rm, name = parts
        lines += (int(add) if add.isdigit() else 0) + (int(rm) if rm.isdigit() else 0)
        files.append(name)
    rc, porcelain = _git(repo, "status", "--porcelain")
    if rc != 0:
        return None
    untracked = [ln[3:] for ln in porcelain.splitlines() if ln.startswith("??")]
    return {"lines": lines, "files": files, "untracked": untracked}
