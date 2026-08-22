"""Credential scanner for the operator's AI workspace.

WHY THIS EXISTS (2026-08-19): a generated skill file, `~/.claude/skills/ddonald01/
SKILL.md`, was found containing a sudo password in cleartext: three times, in the
frontmatter name, the description and the body: because a keyword generator turned
the typed prompt "Ddonald01! is sudo" into a "skill". That file loaded into every
session on the machine and sat in the tree the miner reads and ships to an LLM.

Two design rules follow from the estate's own landmines:

1. A FINDING NEVER CARRIES THE SECRET. `fb_secrets_readable_datto_vars_and_
   cove_configini` records that PARTIAL REDACTION IS NOT REDACTION: printing
   `Ddonald0…` into a report, an audit row or a UI list just moves the credential
   somewhere new and calls it safe. Findings therefore carry detector name,
   file, line, and a SHA-256 fingerprint prefix: enough to correlate two copies
   of the same secret and to confirm a fix, and useless to an attacker.

2. FILENAME IS NOT EVIDENCE. `quarantine_keys_exposed_2026_08_12` records that
   scanning by filename MISSES hardcoded secrets and must be confirmed BY CONTENT.
   This scanner only ever reads content.

Report-only by design. `scan()` and everything it touches is read-only; the one
mutating helper, `quarantine()`, moves a single file by explicit id after a human
confirms it, and is never reachable from a scheduled job.
"""

from __future__ import annotations

import hashlib
import math
import re
import sqlite3
from collections.abc import Iterator
from dataclasses import asdict, dataclass
from pathlib import Path

from .db import audit, utcnow

# ── detectors ────────────────────────────────────────────────────────────────
# (name, pattern, confidence, needs_entropy, flags)
# confidence "high" = the shape alone is conclusive (vendor-prefixed keys, PEM
# headers). "medium" = shape plus context, and entropy is checked before it counts.
_DETECTORS: list[tuple[str, str, str, bool, int]] = [
    ("aws_access_key_id", r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b", "high", False, 0),
    ("github_pat", r"\bgh[pousr]_[A-Za-z0-9]{36,}\b", "high", False, 0),
    ("github_fine_grained_pat", r"\bgithub_pat_[A-Za-z0-9_]{60,}\b", "high", False, 0),
    ("slack_token", r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b", "high", False, 0),
    ("stripe_live_key", r"\b(?:sk|rk)_live_[A-Za-z0-9]{20,}\b", "high", False, 0),
    ("google_api_key", r"\bAIza[0-9A-Za-z_-]{35}\b", "high", False, 0),
    ("openai_key", r"\bsk-(?:proj-)?[A-Za-z0-9_-]{32,}\b", "high", False, 0),
    ("anthropic_key", r"\bsk-ant-[A-Za-z0-9_-]{32,}\b", "high", False, 0),
    ("private_key_block", r"-----BEGIN (?:RSA |EC |OPENSSH |PGP |DSA )?PRIVATE KEY-----", "high", False, 0),
    ("jwt", r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b", "high", False, 0),
    ("connection_string_password", r"\b[a-z][a-z0-9+.-]*://[^\s:/@]+:([^\s@/]{6,})@", "high", False, 0),
    # SCREAMING_SNAKE_CASE=value: the commonest shape a secret takes in .env
    # files and pasted terminal output. This is the same shape the miner's own
    # redaction missed until 2026-08-18 (\b does not match at an underscore).
    (
        "assigned_secret",
        r"\b(?:[A-Z][A-Z0-9_]*)?(?:KEY|TOKEN|SECRET|PASSWORD|PASSWD|PWD|CREDENTIAL|APIKEY)S?\s*[=:]\s*[\"']?([^\s\"';]{8,})",
        "high",
        True,
        0,  # case-SENSITIVE on purpose: this is the SCREAMING_SNAKE shape
    ),
    (
        "lowercase_assigned_secret",
        r"\b(?:api[_-]?key|secret|password|passwd|token|client[_-]?secret|encryptionkey)\s*[=:]\s*[\"']?([^\s\"';]{8,})",
        "medium",
        True,
        re.I,  # "EncryptionKey=", "Api_Key:", "Secret ="
    ),
    # Prose. This is the shape that leaked the sudo password, and no KEY=value
    # pattern would ever have caught it.
    ("password_in_prose", r"\b(?:password|passwd|pw|passphrase)\s+(?:is|was|=)\s+[\"']?(\S{6,})", "medium", True, re.I),
    (
        "credential_is_prose",
        r"\b(\S{8,})\s+is\s+(?:the\s+)?(?:sudo|root|admin|the)\s*(?:password|pw|pass)\b",
        "medium",
        True,
        re.I,
    ),
    ("sudo_prose", r"\b(\S{8,})[!]?\s+is\s+sudo\b", "medium", True, re.I),
    ("bearer_token", r"\bBearer\s+([A-Za-z0-9_\-.=]{20,})", "medium", True, re.I),
    ("basic_auth_header", r"\bAuthorization:\s*Basic\s+([A-Za-z0-9+/=]{16,})", "high", False, re.I),
]
_COMPILED = [(n, re.compile(p, f), c, e) for n, p, c, e, f in _DETECTORS]

# Values that look like secrets but are not. Placeholders, shell/template
# indirection, and: importantly: this scanner's own documentation and tests,
# which must be able to name these shapes without tripping the scanner.
_PLACEHOLDER = re.compile(
    r"^(?:\$|\$\{|\{\{|<|%|x{4,}|\*{4,}|\.{3,}|changeme|example|placeholder|your[_-]?|my[_-]?|some|test|dummy|fake|sample|redacted|\[redacted)",
    re.I,
)
_PLACEHOLDER_CONTAINS = re.compile(r"REDACTED|EXAMPLE|PLACEHOLDER|CHANGEME|YOUR_?KEY|XXXX|\.\.\.|NOT_?A_?REAL", re.I)

_SKIP_DIR_NAMES = {".git", "node_modules", "__pycache__", "shell-snapshots", "todos", ".venv"}


def _entropy(s: str) -> float:
    """Shannon entropy per character. A real key is dense; "the-password" is not."""
    if not s:
        return 0.0
    counts: dict[str, int] = {}
    for ch in s:
        counts[ch] = counts.get(ch, 0) + 1
    n = len(s)
    return -sum((c / n) * math.log2(c / n) for c in counts.values())


def _looks_real(value: str) -> bool:
    if not value or len(value) < 6:
        return False
    if _PLACEHOLDER.match(value) or _PLACEHOLDER_CONTAINS.search(value):
        return False
    # a path, a URL or a sentence is not a credential
    if value.startswith(("/", "./", "~/", "http://", "https://")) or " " in value:
        return False
    # needs some mix: all-lowercase dictionary-ish words are usually prose
    classes = sum(
        [
            bool(re.search(r"[a-z]", value)),
            bool(re.search(r"[A-Z]", value)),
            bool(re.search(r"[0-9]", value)),
            bool(re.search(r"[^A-Za-z0-9]", value)),
        ]
    )
    return classes >= 2 and _entropy(value) >= 2.2


def fingerprint(value: str) -> str:
    """Stable, non-reversible id for a secret. Lets two copies of the same
    credential be recognised as one without ever storing the credential."""
    return hashlib.sha256(value.encode("utf-8", "replace")).hexdigest()[:12]


@dataclass
class Finding:
    detector: str
    confidence: str
    path: str
    line: int
    fingerprint: str
    # Context with the secret ELIDED: the surrounding words are what make a
    # finding actionable ("which setting is this?") and they are not the secret.
    context: str


def _elide(line: str, secret: str) -> str:
    """The line with the credential replaced. Never a prefix, never a suffix:
    partial redaction is not redaction."""
    out = line.replace(secret, f"[REDACTED:{len(secret)} chars]")
    return out.strip()[:200]


def scan_text(text: str, path_label: str) -> list[Finding]:
    found: list[Finding] = []
    seen: set[tuple[str, int, str]] = set()
    for lineno, line in enumerate(text.splitlines(), start=1):
        if len(line) > 4000:  # minified/base64 blobs: skip rather than false-positive
            continue
        for name, pat, confidence, needs_entropy in _COMPILED:
            for m in pat.finditer(line):
                # group(1) when the pattern isolates the value, else the whole match
                secret = m.group(1) if m.re.groups >= 1 else m.group(0)
                if needs_entropy and not _looks_real(secret):
                    continue
                if not needs_entropy and _PLACEHOLDER_CONTAINS.search(secret):
                    continue
                fp = fingerprint(secret)
                key = (name, lineno, fp)
                if key in seen:
                    continue
                seen.add(key)
                found.append(
                    Finding(
                        detector=name,
                        confidence=confidence,
                        path=path_label,
                        line=lineno,
                        fingerprint=fp,
                        context=_elide(line, secret),
                    )
                )
    return found


def _walk(root: Path, include_transcripts: bool) -> Iterator[Path]:
    """Files worth reading. Markdown and settings always; transcripts only when
    asked, because there are tens of thousands of them."""
    if not root.exists():
        return
    for p in root.rglob("*"):
        if any(part in _SKIP_DIR_NAMES for part in p.parts):
            continue
        if not p.is_file() or p.is_symlink():
            continue
        suffix = p.suffix.lower()
        if suffix in {".md", ".markdown", ".json", ".yaml", ".yml", ".toml", ".txt", ".env"}:
            yield p
        elif include_transcripts and suffix == ".jsonl":
            yield p


def scan(claude_dir: Path, include_transcripts: bool = False, max_files: int = 20000) -> dict:
    """Read-only sweep. Returns findings plus what was actually covered, because
    "no findings" and "did not look" must never be the same answer
    (fb_empty_is_not_evidence_of_absence)."""
    findings: list[Finding] = []
    scanned = 0
    skipped_unreadable = 0
    truncated = False
    for path in _walk(claude_dir, include_transcripts):
        if scanned >= max_files:
            truncated = True
            break
        try:
            text = path.read_text(errors="replace")
        except OSError:
            skipped_unreadable += 1
            continue
        scanned += 1
        try:
            rel = str(path.relative_to(claude_dir))
        except ValueError:
            rel = str(path)
        findings.extend(scan_text(text, rel))
    return {
        "findings": [asdict(f) for f in findings],
        "files_scanned": scanned,
        "files_unreadable": skipped_unreadable,
        "transcripts_included": include_transcripts,
        "truncated": truncated,
        "distinct_secrets": len({f.fingerprint for f in findings}),
    }


# ── persistence + alerting ───────────────────────────────────────────────────


def record(conn: sqlite3.Connection, result: dict) -> dict:
    """Store findings and report what is NEW since the last scan. New findings are
    what an alert should be about: re-alerting on the same known one every hour
    trains the operator to ignore the alert."""
    new = 0
    for f in result["findings"]:
        existing = conn.execute(
            "SELECT id, status FROM secret_findings WHERE path=? AND line=? AND fingerprint=?",
            (f["path"], f["line"], f["fingerprint"]),
        ).fetchone()
        if existing:
            conn.execute("UPDATE secret_findings SET last_seen_at=? WHERE id=?", (utcnow(), existing["id"]))
            continue
        conn.execute(
            "INSERT INTO secret_findings (detector,confidence,path,line,fingerprint,context,status,"
            "first_seen_at,last_seen_at) VALUES (?,?,?,?,?,?,'open',?,?)",
            (
                f["detector"],
                f["confidence"],
                f["path"],
                f["line"],
                f["fingerprint"],
                f["context"],
                utcnow(),
                utcnow(),
            ),
        )
        new += 1
    open_count = conn.execute("SELECT COUNT(*) c FROM secret_findings WHERE status='open'").fetchone()["c"]
    audit(
        conn,
        "secret_scan",
        "scan_completed",
        f"scanned={result['files_scanned']} findings={len(result['findings'])} new={new} open={open_count}"
        f" transcripts={result['transcripts_included']} truncated={result['truncated']}",
    )
    conn.commit()
    return {
        **{k: v for k, v in result.items() if k != "findings"},
        "findings": len(result["findings"]),
        "new_findings": new,
        "open_findings": open_count,
        # The alert flag the UI and the digest key off. A scan that finds nothing
        # new is deliberately silent.
        "alert": new > 0,
    }


def run_scan(settings, include_transcripts: bool = False) -> dict:
    """Scheduler entry point. Report-only: never edits or moves a file."""
    from .db import connect

    conn = connect(settings.db_path)
    try:
        return record(conn, scan(settings.claude_dir, include_transcripts=include_transcripts))
    finally:
        conn.close()


def list_findings(conn: sqlite3.Connection, status: str = "open") -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM secret_findings WHERE status=? ORDER BY "
        "CASE confidence WHEN 'high' THEN 0 ELSE 1 END, first_seen_at DESC LIMIT 500",
        (status,),
    ).fetchall()
    return [dict(r) for r in rows]


class SecretScanError(RuntimeError):
    pass


def acknowledge(conn: sqlite3.Connection, finding_id: int, note: str = "") -> dict:
    """Mark a finding handled: the credential was rotated, or it was a false
    positive. Acknowledging changes no file; it records a human judgement."""
    row = conn.execute("SELECT * FROM secret_findings WHERE id=?", (finding_id,)).fetchone()
    if not row:
        raise SecretScanError(f"no finding {finding_id}")
    conn.execute(
        "UPDATE secret_findings SET status='acknowledged', decided_at=?, note=? WHERE id=?",
        (utcnow(), note[:500], finding_id),
    )
    audit(conn, "operator", "secret_finding_acknowledged", f"id={finding_id} {row['detector']} {row['path']}")
    conn.commit()
    return {"id": finding_id, "status": "acknowledged"}


def quarantine(conn: sqlite3.Connection, claude_dir: Path, finding_id: int) -> dict:
    """Move the whole leaking FILE out of the workspace, by explicit id.

    Deliberately not a redaction. Editing the secret out in place would leave a
    file whose history still contains it, would modify a file noirdeck did not
    create (the standing create-only rule), and would let the operator believe
    the credential is safe when the only real remedy is ROTATION. Moving the file
    stops it loading into sessions and stops the miner reading it; the message
    returned says plainly that rotation is still required.

    Never called by a scheduled job: the caller must be a human action.
    """
    row = conn.execute("SELECT * FROM secret_findings WHERE id=?", (finding_id,)).fetchone()
    if not row:
        raise SecretScanError(f"no finding {finding_id}")
    if row["status"] == "quarantined":
        raise SecretScanError(f"finding {finding_id} is already quarantined")

    # Containment check on the real path: a finding row is data, and data must
    # not be able to address a file outside the tree being protected.
    target = (claude_dir / row["path"]).resolve()
    root = claude_dir.resolve()
    if root not in target.parents:
        raise SecretScanError(f"refusing to move a path outside {root}: {row['path']}")
    if not target.is_file():
        raise SecretScanError(f"file is gone (already handled?): {row['path']}")

    dest_dir = claude_dir.parent / "noirdeck-quarantine"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{utcnow().replace(':', '-')}__{row['path'].replace('/', '__')}"
    target.rename(dest)

    conn.execute(
        "UPDATE secret_findings SET status='quarantined', decided_at=?, note=? WHERE id=?",
        (utcnow(), f"moved to {dest}", finding_id),
    )
    # Any other finding in the same file moved with it.
    conn.execute(
        "UPDATE secret_findings SET status='quarantined', decided_at=?, note=? "
        "WHERE path=? AND status='open' AND id!=?",
        (utcnow(), f"file moved to {dest}", row["path"], finding_id),
    )
    audit(
        conn,
        "operator",
        "secret_finding_quarantined",
        f"id={finding_id} {row['detector']} {row['path']} -> {dest}",
    )
    conn.commit()
    return {
        "id": finding_id,
        "status": "quarantined",
        "moved_to": str(dest),
        "next_step": (
            "The file is out of the workspace, but the credential is still disclosed: "
            "it remains in session transcripts and in any backup taken before now. "
            "ROTATE it."
        ),
    }


# ── moving many at once, safely ───────────────────────────────────────────────


def _movable(claude_dir: Path, entry: dict) -> bool:
    target = (claude_dir / entry["path"]).resolve()
    return bool(target.is_file() and claude_dir.resolve() in target.parents)


def plan_sweep(conn: sqlite3.Connection, claude_dir: Path, ids: list[int] | None = None) -> dict:
    """What a sweep WOULD move, grouped by file, without moving anything.

    THE LANDMINE THIS IS BUILT AROUND: on this estate, irreversible actions must
    be selected by EXPLICIT ID: never by a time window, a status filter or a LIMIT.
    So there is no "quarantine everything" call. This returns a plan the operator
    reads and then confirms with the exact id list, and `sweep()` refuses any id that
    was not in a plan the caller has seen.

    Grouped by FILE because that is the unit of action: moving one finding moves the
    whole file, so a per-finding count misrepresents what is about to happen.
    """
    rows = conn.execute(
        "SELECT id, path, line, detector, confidence, fingerprint FROM secret_findings WHERE status='open'"
    ).fetchall()
    chosen = [dict(r) for r in rows if ids is None or r["id"] in set(ids)]

    files: dict[str, dict] = {}
    for f in chosen:
        entry = files.setdefault(
            f["path"],
            {"path": f["path"], "finding_ids": [], "detectors": set(), "fingerprints": set()},
        )
        entry["finding_ids"].append(f["id"])
        entry["detectors"].add(f["detector"])
        entry["fingerprints"].add(f["fingerprint"])

    out = []
    for entry in files.values():
        target = (claude_dir / entry["path"]).resolve()
        out.append(
            {
                "path": entry["path"],
                "finding_ids": sorted(entry["finding_ids"]),
                "findings": len(entry["finding_ids"]),
                "distinct_secrets": len(entry["fingerprints"]),
                "detectors": sorted(entry["detectors"]),
                "exists": target.is_file(),
                "movable": _movable(claude_dir, entry),
                # Loud, because these are the files whose contents reach every session.
                "loads_into_sessions": entry["path"].split("/")[0] in {"skills", "agents", "rules", "commands"}
                or entry["path"] == "CLAUDE.md"
                or "/memory/" in entry["path"],
            }
        )
    out.sort(key=lambda e: (not e["loads_into_sessions"], -e["findings"]))
    movable = [e for e in out if e["movable"]]
    return {
        "files": out,
        "files_movable": len(movable),
        "files_skipped": len(out) - len(movable),
        "findings_covered": sum(e["findings"] for e in movable),
        # A true distinct count over FINGERPRINTS: the same credential often appears in
        # several files, and summing per-file counts would overstate the exposure.
        "distinct_secrets": len({fp for e in files.values() for fp in e["fingerprints"] if _movable(claude_dir, e)}),
        # The id list the operator must send back. Confirming a plan means confirming
        # THIS, not "everything that is open right now": which could have changed.
        "confirm_ids": sorted(i for e in movable for i in e["finding_ids"]),
        "note": (
            "Moving a file takes it out of the workspace so sessions and the miner stop "
            "reading it. It does NOT undo the disclosure: every credential here is still "
            "in git history, in session transcripts and in any backup taken before now. "
            "Rotate each one."
        ),
    }


def sweep(conn: sqlite3.Connection, claude_dir: Path, ids: list[int], confirm: bool = False) -> dict:
    """Move every file named by these finding ids, one at a time, recording each.

    Requires the explicit id list from plan_sweep() and confirm=True. Each file is
    moved by the same single-file quarantine() path, so a bulk action cannot do
    anything a single action could not: same containment check, same audit row, same
    manifest entry.
    """
    if not confirm:
        return {"performed": False, "reason": "confirm=true and an explicit id list are both required"}
    if not ids:
        return {"performed": False, "reason": "no ids given: there is no 'move everything' call, by design"}

    moved, failed = [], []
    seen_paths: set[str] = set()
    for fid in ids:
        row = conn.execute("SELECT path, status FROM secret_findings WHERE id=?", (fid,)).fetchone()
        if not row:
            failed.append({"id": fid, "why": "no such finding"})
            continue
        if row["status"] != "open":
            failed.append({"id": fid, "why": f"already {row['status']}"})
            continue
        if row["path"] in seen_paths:
            continue  # its file went with an earlier id in this sweep
        try:
            result = quarantine(conn, claude_dir, fid)
            seen_paths.add(row["path"])
            moved.append({"id": fid, "path": row["path"], "moved_to": result["moved_to"]})
        except SecretScanError as exc:
            failed.append({"id": fid, "why": str(exc)})

    audit(conn, "operator", "secret_sweep", f"requested={len(ids)} moved={len(moved)} failed={len(failed)}")
    conn.commit()
    return {
        "performed": True,
        "files_moved": len(moved),
        "moved": moved,
        "failed": failed,
        "next_step": (
            f"{len(moved)} file(s) are out of the workspace. Every credential in them is still "
            "disclosed: rotate each one, then store the replacements in a secret manager rather "
            "than in a note. See docs/SECRET_HYGIENE.md."
        ),
    }
