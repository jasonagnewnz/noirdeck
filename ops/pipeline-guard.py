#!/usr/bin/env python3
"""PreToolUse hook for noirdeck headless pipelines (builds / overnight /
design / miner). Enforces the code-ready boundary at the HARNESS level instead
of trusting prompt guardrails: a pipeline session cannot push, publish, deploy,
or reach into remote infrastructure even if its prompt goes sideways.

Contract (Claude Code hooks): JSON on stdin {tool_name, tool_input}; exit 0
allows the call, exit 2 blocks it and feeds stderr back to the model.
Fail-closed: if input cannot be parsed, the call is denied LOUDLY — a silently
inert guard is worse than a broken pipeline."""
import json
import re
import sys

# each entry: (compiled pattern, reason shown to the model)
DENY = [
    (r"\bgit\b[^|;&]*\bpush\b", "git push — pipelines stop at code-ready; the operator pushes"),
    (r"\bgh\s+(pr|release|repo)\s+(create|merge|edit|delete)", "gh publishing — outward actions are the operator's"),
    (r"\bnpm\s+publish\b|\byarn\s+publish\b|\bpnpm\s+publish\b", "package publish"),
    (r"\btwine\s+upload\b|\bpython[0-9.]*\s+-m\s+twine\b", "PyPI upload"),
    (r"\bdocker\s+push\b|\bpodman\s+push\b", "container registry push"),
    (r"\b(flyctl|fly)\s+deploy\b|\bwrangler\s+(deploy|publish)\b|\bvercel\b|\bnetlify\s+deploy\b",
     "platform deploy"),
    (r"\bkubectl\b|\bhelm\s+(install|upgrade|rollback|uninstall)\b", "kubernetes mutation"),
    (r"\bterraform\s+(apply|destroy)\b|\bcdk\s+(deploy|destroy)\b|\bpulumi\s+(up|destroy)\b",
     "infrastructure mutation"),
    (r"\bgcloud\b[^|;&]*\bdeploy\b|\baz\b[^|;&]*\b(up|deploy)\b|\baws\b[^|;&]*\bdeploy\b",
     "cloud deploy"),
    (r"\b(ssh|scp|sftp|rsync)\s+[^|;&]*@", "remote host access"),
    (r"\bsystemctl\b(?!.*--user\s+(status|show|list))", "service state change"),
    (r"pkill\s+-f\s+uvicorn|killall\s+uvicorn", "estate landmine: unrelated uvicorn on this box"),
    (r"\bcrontab\b|\bat\s+-f\b", "scheduling persistence"),
]
_COMPILED = [(re.compile(p, re.I), reason) for p, reason in DENY]


def main() -> int:
    try:
        payload = json.load(sys.stdin)
        tool = payload.get("tool_name", "")
        command = (payload.get("tool_input") or {}).get("command", "")
    except Exception:
        print("pipeline-guard: could not parse hook input — denying (fail-closed)",
              file=sys.stderr)
        return 2
    if tool != "Bash" or not command:
        return 0
    for pat, reason in _COMPILED:
        if pat.search(command):
            print(f"pipeline-guard DENIED: {reason}. This session is a noirdeck "
                  "pipeline and stops at code-ready — commit locally and report instead.",
                  file=sys.stderr)
            return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
