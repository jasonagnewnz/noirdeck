"""Propose → approve → execute. Approval is the ONLY path that writes into ~/.claude.
Targets are allowlisted, traversal-checked, CREATE-ONLY, and audited.

⛔ CREATE-ONLY is the operator's standing rule (2026-08-19): noirdeck may READ the
knowledge tree and ADD its own files to it, and may never modify a file it did not
create — not autonomously, and not with approval either. There is deliberately no
overwrite escape hatch on approve(): a proposal whose target already exists is
refused outright. The reason is that an approval is a click, and a click is a poor
record of intent when what it silently replaced was a governance file that every
other session on the estate obeys. If the improved version of an existing file is
worth having, it lands beside the original under its own name and a human merges it.

revert() keeps an overwrite flag, which is a different thing: it guards against
destroying edits made AFTER an apply. Under create-only, revert of a new proposal
only ever removes a file noirdeck itself created."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from .config import primary_namespace
from .db import audit, utcnow


def allowed_roots() -> tuple[str, ...]:
    return ("skills", f"projects/{primary_namespace()}/memory")


class ProposalError(RuntimeError):
    pass


def list_proposals(conn: sqlite3.Connection, status: str | None = None) -> list[dict]:
    q = "SELECT * FROM proposals"
    args: tuple = ()
    if status:
        q += " WHERE status=?"
        args = (status,)
    q += " ORDER BY id DESC LIMIT 200"
    return [dict(r) for r in conn.execute(q, args).fetchall()]


def _resolve_target(claude_dir: Path, target_path: str) -> Path:
    rel = Path(target_path)
    if rel.is_absolute():
        raise ProposalError("target_path must be relative to the Claude dir")
    resolved = (claude_dir / rel).resolve()
    roots = allowed_roots()
    for root in roots:
        root_resolved = (claude_dir / root).resolve()
        if resolved == root_resolved or root_resolved in resolved.parents:
            return resolved
    raise ProposalError(f"target_path outside allowed roots {roots}: {target_path}")


def approve(conn: sqlite3.Connection, claude_dir: Path, proposal_id: int) -> dict:
    """Apply a proposal. Create-only: an existing target is refused, with no flag
    that relaxes it. See the module docstring for why there is no overwrite."""
    row = conn.execute("SELECT * FROM proposals WHERE id=?", (proposal_id,)).fetchone()
    if not row:
        raise ProposalError(f"no proposal {proposal_id}")
    if row["status"] != "proposed":
        raise ProposalError(f"proposal {proposal_id} already {row['status']}")

    written_to = None
    if row["target_path"]:
        target = _resolve_target(claude_dir, row["target_path"])
        if target.exists():
            raise ProposalError(
                f"create-only: {row['target_path']} already exists and noirdeck never replaces a file "
                "it did not create. Apply this by hand, or dismiss it."
            )
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(row["body"])
        written_to = str(target)

    conn.execute(
        "UPDATE proposals SET status='approved', decided_at=?, prior_body=?, prior_existed=? WHERE id=?",
        (utcnow(), None, 0, proposal_id),
    )
    audit(
        conn, "operator", "proposal_approved", f"id={proposal_id} kind={row['kind']} target={row['target_path'] or '-'}"
    )
    return {"id": proposal_id, "written_to": written_to}


def revert(conn: sqlite3.Connection, claude_dir: Path, proposal_id: int, overwrite: bool = False) -> dict:
    """Undo an applied proposal: restore the pre-apply snapshot, or remove the
    file if the approval created it. Refuses when the file has drifted from what
    the approval wrote (someone edited it since) unless overwrite is explicit —
    a revert must never silently destroy work it didn't do."""
    row = conn.execute("SELECT * FROM proposals WHERE id=?", (proposal_id,)).fetchone()
    if not row:
        raise ProposalError(f"no proposal {proposal_id}")
    if row["status"] != "approved":
        raise ProposalError(f"proposal {proposal_id} is {row['status']}, not approved")
    if row["reverted_at"]:
        raise ProposalError(f"proposal {proposal_id} was already reverted")
    if not row["target_path"]:
        raise ProposalError(f"proposal {proposal_id} wrote no file, nothing to revert")
    if row["prior_existed"] is None:
        raise ProposalError(f"proposal {proposal_id} predates undo support — no pre-apply snapshot exists")

    target = _resolve_target(claude_dir, row["target_path"])
    if target.exists() and target.read_text() != row["body"] and not overwrite:
        raise ProposalError(
            f"file changed since this was applied (pass overwrite=true to revert anyway): {row['target_path']}"
        )

    if row["prior_existed"]:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(row["prior_body"])
        outcome = "restored previous content"
    else:
        target.unlink(missing_ok=True)
        outcome = "removed the file this approval created"

    conn.execute("UPDATE proposals SET status='reverted', reverted_at=? WHERE id=?", (utcnow(), proposal_id))
    audit(conn, "operator", "proposal_reverted", f"id={proposal_id} target={row['target_path']} ({outcome})")
    return {"id": proposal_id, "outcome": outcome}


def dismiss(conn: sqlite3.Connection, proposal_id: int, note: str = "") -> dict:
    row = conn.execute("SELECT status FROM proposals WHERE id=?", (proposal_id,)).fetchone()
    if not row:
        raise ProposalError(f"no proposal {proposal_id}")
    if row["status"] != "proposed":
        raise ProposalError(f"proposal {proposal_id} already {row['status']}")
    conn.execute(
        "UPDATE proposals SET status='dismissed', decided_at=?, note=? WHERE id=?", (utcnow(), note, proposal_id)
    )
    audit(conn, "operator", "proposal_dismissed", f"id={proposal_id}")
    return {"id": proposal_id}
