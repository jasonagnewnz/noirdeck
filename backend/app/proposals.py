"""Propose → approve → execute. Approval is the ONLY path that writes into ~/.claude.
Targets are allowlisted, traversal-checked, never silently overwritten, and audited."""
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


def approve(conn: sqlite3.Connection, claude_dir: Path, proposal_id: int, overwrite: bool = False) -> dict:
    row = conn.execute("SELECT * FROM proposals WHERE id=?", (proposal_id,)).fetchone()
    if not row:
        raise ProposalError(f"no proposal {proposal_id}")
    if row["status"] != "proposed":
        raise ProposalError(f"proposal {proposal_id} already {row['status']}")

    written_to = None
    prior_body = None
    prior_existed = 0
    if row["target_path"]:
        target = _resolve_target(claude_dir, row["target_path"])
        if target.exists():
            if not overwrite:
                raise ProposalError(f"target exists (pass overwrite=true to replace): {row['target_path']}")
            prior_body = target.read_text()
            prior_existed = 1
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(row["body"])
        written_to = str(target)

    conn.execute(
        "UPDATE proposals SET status='approved', decided_at=?, prior_body=?, prior_existed=? WHERE id=?",
        (utcnow(), prior_body, prior_existed, proposal_id))
    audit(conn, "operator", "proposal_approved",
          f"id={proposal_id} kind={row['kind']} target={row['target_path'] or '-'}")
    return {"id": proposal_id, "written_to": written_to}


def revert(conn: sqlite3.Connection, claude_dir: Path, proposal_id: int,
           overwrite: bool = False) -> dict:
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
        raise ProposalError(
            f"proposal {proposal_id} predates undo support — no pre-apply snapshot exists")

    target = _resolve_target(claude_dir, row["target_path"])
    if target.exists() and target.read_text() != row["body"] and not overwrite:
        raise ProposalError(
            "file changed since this was applied (pass overwrite=true to revert anyway): "
            f"{row['target_path']}")

    if row["prior_existed"]:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(row["prior_body"])
        outcome = "restored previous content"
    else:
        target.unlink(missing_ok=True)
        outcome = "removed the file this approval created"

    conn.execute(
        "UPDATE proposals SET status='reverted', reverted_at=? WHERE id=?",
        (utcnow(), proposal_id))
    audit(conn, "operator", "proposal_reverted",
          f"id={proposal_id} target={row['target_path']} ({outcome})")
    return {"id": proposal_id, "outcome": outcome}


def dismiss(conn: sqlite3.Connection, proposal_id: int, note: str = "") -> dict:
    row = conn.execute("SELECT status FROM proposals WHERE id=?", (proposal_id,)).fetchone()
    if not row:
        raise ProposalError(f"no proposal {proposal_id}")
    if row["status"] != "proposed":
        raise ProposalError(f"proposal {proposal_id} already {row['status']}")
    conn.execute(
        "UPDATE proposals SET status='dismissed', decided_at=?, note=? WHERE id=?",
        (utcnow(), note, proposal_id))
    audit(conn, "operator", "proposal_dismissed", f"id={proposal_id}")
    return {"id": proposal_id}
