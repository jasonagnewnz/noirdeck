"""Share what happened in a session, without sharing the session.

Stage 0 of session sharing, and deliberately the whole of it for now. It produces a
readable, self-contained export of a session's scrollback that the operator can send
however they already send things. There is no socket, no invite, no relay, no bind
beyond loopback and no second identity: so none of the auth work that
`docs/SECURITY.md` requires before exposing the workspace is bypassed here:

    Binds 127.0.0.1 only ... No auth layer: an explicit, documented risk
    acceptance ... If this is ever exposed (tunnel, LAN bind), an auth layer MUST
    be added first; do not expose as-is.

A TRANSCRIPT IS A DISCLOSURE CHANNEL. Terminal output is precisely where
credentials show up: this estate found a sudo password inside a generated skill file
and 125 distinct secrets across its workspace, both from text that was "just" typed or
printed once. So an export REDACTS first, reports how much it removed, and then
re-scans its own output to check the redaction actually held. A guarantee you cannot
see is one you are taking on trust (the same reason consult surfaces its counts).

Redaction is not a promise of safety. It matches known secret SHAPES; a password
that looks like a word will pass through, and the export says so rather than implying
it is clean.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

from .miner.redact import redact
from .secrets_scan import scan_text
from .version import VERSION

MAX_CHARS = 200_000


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def build_export(
    *,
    scrollback: str,
    project: str,
    runner: str | None = None,
    model: str | None = None,
    note: str = "",
) -> dict:
    """A redacted, human-readable Markdown export plus the numbers behind it.

    Returns the text, the redaction counts, and: importantly: anything the scanner
    still finds in the REDACTED output. That last field is what makes the guarantee
    checkable instead of asserted.
    """
    raw = scrollback[-MAX_CHARS:]
    clean, counts = redact(raw)
    removed = sum(counts.values())

    # Check our own work. If the scanner finds a credential shape in text we just
    # redacted, the operator must be told before they send it to anyone.
    residual = scan_text(clean, "shared-transcript")
    residual_summary = sorted({f.detector for f in residual})

    header = [
        f"# noirdeck session: {project}",
        "",
        f"- Exported: {_stamp()} by noirdeck {VERSION}",
    ]
    if runner:
        header.append(f"- Assistant: {runner}{f' / {model}' if model else ''}")
    if note.strip():
        header.append(f"- Note: {note.strip()[:500]}")
    header += [
        f"- Secrets removed before export: **{removed}**"
        + (f" ({', '.join(f'{k}×{v}' for k, v in sorted(counts.items()) if v)})" if removed else ""),
    ]
    if residual_summary:
        header.append(
            "- ⛔ **CHECK BEFORE SENDING**: after redaction the scanner still matched "
            f"{len(residual)} possible credential(s): {', '.join(residual_summary)}. "
            "Read the transcript below before sharing it."
        )
    header += [
        "",
        "> Redaction matches known secret shapes. A credential that looks like an "
        "ordinary word is not removed, so read this before sending it on.",
        "",
        "---",
        "",
        "```text",
        clean.rstrip("\n") or "(no terminal output captured)",
        "```",
        "",
    ]

    return {
        "markdown": "\n".join(header),
        "filename": _safe_filename(project),
        "chars": len(clean),
        "secrets_removed": removed,
        "redactions": {k: v for k, v in counts.items() if v},
        # Empty list is a real answer here: it means the scanner looked and found
        # nothing, which is different from not having looked.
        "residual_findings": len(residual),
        "residual_detectors": residual_summary,
        "safe_to_send": not residual_summary,
    }


def _safe_filename(project: str) -> str:
    """A filename that cannot escape a directory or surprise a shell."""
    stem = re.sub(r"[^A-Za-z0-9._-]+", "-", project).strip("-.") or "session"
    return f"noirdeck-{stem[:48]}-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M')}.md"
