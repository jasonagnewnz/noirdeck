#!/usr/bin/env python3
"""PreToolUse hook for noirdeck headless pipelines (builds / overnight /
design / miner). Enforces two boundaries at the HARNESS level instead of
trusting prompt guardrails:

1. CODE-READY — a pipeline session cannot push, publish, deploy, or reach into
   remote infrastructure even if its prompt goes sideways.
2. KNOWLEDGE IS READ-ONLY — a pipeline session cannot modify the operator's AI
   workspace (~/.claude): CLAUDE.md, memory files, skills, agents, rules,
   settings, commands. It may READ all of it. The only way anything is written
   there is a human clicking Approve on a noirdeck proposal.

Boundary 2 was open until 2026-08-19: this hook only ever inspected Bash, so
Write/Edit/MultiEdit/NotebookEdit were never seen, and pipelines run with
--permission-mode acceptEdits, which auto-approves them. A session could
rewrite the instructions the whole estate obeys with nothing in the way.

Contract (Claude Code hooks): JSON on stdin {tool_name, tool_input}; exit 0
allows the call, exit 2 blocks it and feeds stderr back to the model.
Fail-closed: if input cannot be parsed, the call is denied LOUDLY — a silently
inert guard is worse than a broken pipeline."""

import json
import os
import re
import sys
from pathlib import Path

# --- boundary 1: outward-mutating Bash -------------------------------------
# each entry: (pattern, reason shown to the model)
DENY = [
    (r"\bgit\b[^|;&]*\bpush\b", "git push — pipelines stop at code-ready; the operator pushes"),
    (r"\bgh\s+(pr|release|repo)\s+(create|merge|edit|delete)", "gh publishing — outward actions are the operator's"),
    (r"\bnpm\s+publish\b|\byarn\s+publish\b|\bpnpm\s+publish\b", "package publish"),
    (r"\btwine\s+upload\b|\bpython[0-9.]*\s+-m\s+twine\b", "PyPI upload"),
    (r"\bdocker\s+push\b|\bpodman\s+push\b", "container registry push"),
    (r"\b(flyctl|fly)\s+deploy\b|\bwrangler\s+(deploy|publish)\b|\bvercel\b|\bnetlify\s+deploy\b", "platform deploy"),
    (r"\bkubectl\b|\bhelm\s+(install|upgrade|rollback|uninstall)\b", "kubernetes mutation"),
    (
        r"\bterraform\s+(apply|destroy)\b|\bcdk\s+(deploy|destroy)\b|\bpulumi\s+(up|destroy)\b",
        "infrastructure mutation",
    ),
    (r"\bgcloud\b[^|;&]*\bdeploy\b|\baz\b[^|;&]*\b(up|deploy)\b|\baws\b[^|;&]*\bdeploy\b", "cloud deploy"),
    (r"\b(ssh|scp|sftp|rsync)\s+[^|;&]*@", "remote host access"),
    (r"\bsystemctl\b(?!.*--user\s+(status|show|list))", "service state change"),
    (r"pkill\s+-f\s+uvicorn|killall\s+uvicorn", "estate landmine: unrelated uvicorn on this box"),
    (r"\bcrontab\b|\bat\s+-f\b", "scheduling persistence"),
]
_COMPILED = [(re.compile(p, re.I), reason) for p, reason in DENY]

# --- boundary 2: the protected knowledge tree ------------------------------
# Tools that take a path and write to it. tool_input key varies by tool, so we
# sweep every known path-bearing field rather than special-casing each tool.
WRITE_TOOLS = {"Write", "Edit", "MultiEdit", "NotebookEdit"}
PATH_KEYS = ("file_path", "path", "notebook_path", "filePath")

# Bash verbs that can create or modify a file. Presence of one of these AND a
# protected path in the same command is a deny. Deliberately broad: a false
# deny costs a pipeline one retry, a false allow silently rewrites governance.
BASH_WRITE = re.compile(
    r"""(
        >|>>                                  # any redirection
      | \bsed\b[^|;&]*-[a-zA-Z]*i             # sed -i / -Ei / -i.bak
      | \btee\b
      | \b(cp|mv|install|ln|touch|truncate|dd|rsync)\b
      | \b(rm|rmdir|shred|unlink)\b
      | \b(mkdir|mktemp)\b
      | \bchmod\b | \bchown\b | \bchattr\b
      | \bpatch\b | \bgit\s+apply\b
      | \b(tar|unzip|gunzip|zcat)\b           # extraction can land files anywhere
      | \bpython[0-9.]*\s+-c\b | \bperl\b[^|;&]*-[a-zA-Z]*e | \bawk\b[^|;&]*>
      | \bcat\s*<<                            # heredoc
    )""",
    re.I | re.X,
)


def protected_roots() -> list[Path]:
    """The trees a pipeline may never write. CLAUDE_CONFIG_DIR is honoured so a
    relocated config dir is still protected; ~/.claude is always included."""
    roots = [Path.home() / ".claude"]
    env_dir = os.environ.get("CLAUDE_CONFIG_DIR")
    if env_dir:
        roots.append(Path(env_dir).expanduser())
    # user-level governance that lives outside .claude
    roots.append(Path.home() / "CLAUDE.md")
    out = []
    for r in roots:
        try:
            out.append(r.expanduser().resolve())
        except OSError:
            out.append(r)
    return out


def _is_protected(raw: str) -> Path | None:
    """Resolve a candidate path and return the protected root it falls under.
    Resolution is symlink-aware and does not require the file to exist, so a
    write to a not-yet-created memory file is caught too."""
    if not raw or not isinstance(raw, str):
        return None
    try:
        p = Path(raw).expanduser()
        if not p.is_absolute():
            p = Path.cwd() / p
        # strict=False: resolve as far as it exists, keep the rest literal
        resolved = p.resolve()
    except (OSError, RuntimeError, ValueError):
        return None
    for root in protected_roots():
        if resolved == root or root in resolved.parents:
            return root
    return None


def _looks_like_a_protected_path(expanded: str) -> bool:
    """Cheap prefilter deciding which tokens are worth resolving.

    ⛔ This MUST be derived from the actual protected roots, not from the literal
    string ".claude". An earlier version hardcoded that substring, so when
    CLAUDE_CONFIG_DIR pointed the workspace somewhere else — a relocated config
    dir, which the guard otherwise honours — every Bash write into it was skipped
    before it was ever checked. A prefilter that does not know what it is
    protecting is a hole with a fast path.

    A prefilter is still needed: without one, a bare `sed` script fragment like
    `s/a/b/` resolves against the cwd, and a cwd inside the tree would turn it
    into a false denial.
    """
    if ".claude" in expanded or "CLAUDE.md" in expanded:
        return True
    return any(str(root) in expanded for root in protected_roots())


def _bash_protected_hit(command: str) -> Path | None:
    """A protected path mentioned in a command that also contains a write verb.
    Tokens are scanned individually so `sed -i ~/.claude/CLAUDE.md` and
    `cat > "$HOME/.claude/x"` are both caught."""
    if not BASH_WRITE.search(command):
        return None
    # split on shell punctuation, keep path-ish tokens, strip quotes
    for tok in re.split(r"[\s;|&()<>\"']+", command):
        tok = tok.strip()
        if not tok:
            continue
        if tok.startswith("-"):
            # a flag can carry the path: --directory=/home/user/.claude
            if "=" not in tok:
                continue
            tok = tok.split("=", 1)[1]
            if not tok:
                continue
        expanded = tok.replace("$HOME", str(Path.home())).replace("${HOME}", str(Path.home()))
        if not _looks_like_a_protected_path(expanded):
            continue
        hit = _is_protected(expanded)
        if hit:
            return hit
    return None


def _deny(reason: str) -> int:
    print(f"pipeline-guard DENIED: {reason}", file=sys.stderr)
    return 2


def main() -> int:
    try:
        payload = json.load(sys.stdin)
        tool = payload.get("tool_name", "")
        tool_input = payload.get("tool_input") or {}
        if not isinstance(tool_input, dict):
            tool_input = {}
    except Exception:
        print("pipeline-guard: could not parse hook input — denying (fail-closed)", file=sys.stderr)
        return 2

    # boundary 2 — file-writing tools may not touch the knowledge tree
    if tool in WRITE_TOOLS:
        for key in PATH_KEYS:
            hit = _is_protected(tool_input.get(key, ""))
            if hit:
                return _deny(
                    f"{tool} targets the operator's AI workspace ({hit}). Pipeline sessions "
                    "read that tree and never modify it — memory, skills, CLAUDE.md, agents "
                    "and settings change only when a human approves a noirdeck proposal. "
                    "Report what you would have changed instead."
                )
        return 0

    if tool != "Bash":
        return 0

    command = tool_input.get("command") or ""
    if not command:
        return 0

    # boundary 2 — same tree, reached through the shell
    hit = _bash_protected_hit(command)
    if hit:
        return _deny(
            f"this command writes into the operator's AI workspace ({hit}). Pipeline "
            "sessions read that tree and never modify it. Report what you would have "
            "changed instead."
        )

    # boundary 1 — outward-mutating commands
    for pat, reason in _COMPILED:
        if pat.search(command):
            return _deny(
                f"{reason}. This session is a noirdeck pipeline and stops at "
                "code-ready — commit locally and report instead."
            )
    return 0


if __name__ == "__main__":
    sys.exit(main())
