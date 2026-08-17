"""Vault — recurring encrypted offsite backup with a VERIFIED restore, wrapping
restic (boring, proven; no hand-rolled crypto per the security doctrine).

Backup set (the irreplaceable knowledge, not the bulk):
- <claude_dir>: skills/, agents/, rules/, docs/, CLAUDE.md, history.jsonl,
  projects/ EXCLUDING *.jsonl (raw session transcripts are large and can
  contain sensitive values; the distilled knowledge lives in memory files)
- the noirdeck database
- git bundles of every fleet repo that has unpushed/local-only work, AND a
  capture of any uncommitted working tree (a bundle carries commits only, so
  a pushed-but-dirty repo would otherwise be backed up nowhere at all)

The restore test IS the feature: every run restores a sample from the fresh
snapshot and byte-compares it against the live file. An unverified backup is
reported as exactly that. Fail-closed: unconfigured or missing passphrase file
means status 'not configured', never a silent no-op that looks healthy."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tarfile
import tempfile
import threading
from pathlib import Path

from .config import Settings
from .db import audit, connect, init_db, utcnow

MAX_BUNDLE_BYTES = 200 * 1024 * 1024  # skip monster repos, note them instead
MAX_DIRTY_BYTES = 25 * 1024 * 1024  # per repo, working-tree capture
# .gitignore is the real secret filter here: untracked files are chosen with
# --exclude-standard, which is what keeps a gitignored .env out. This pattern
# is defence in depth for a repo that never ignored its secrets in the first
# place. Skips are COUNTED in the report — never dropped silently.
SECRET_NAME_RE = re.compile(
    r"(^|/)(\.env(\..+)?|.+\.(pem|key|p12|pfx|jks|keystore|kdbx)|id_(rsa|dsa|ecdsa|ed25519))$",
    re.IGNORECASE,
)
_RUN_LOCK = threading.Lock()


def repo_url() -> str:
    return os.environ.get("NOIRDECK_VAULT_REPO", "")


def pass_file() -> Path:
    return Path(os.environ.get("NOIRDECK_VAULT_PASSFILE", "~/.config/noirdeck/vault-pass")).expanduser()


def restic_bin() -> str | None:
    found = shutil.which("restic")
    if found:
        return found
    fallback = Path.home() / ".local" / "bin" / "restic"
    return str(fallback) if fallback.is_file() else None


def configured() -> tuple[bool, str]:
    if not repo_url():
        return False, "NOIRDECK_VAULT_REPO not set"
    if not pass_file().is_file():
        return False, f"passphrase file missing: {pass_file()}"
    if not restic_bin():
        return False, "restic binary not found"
    return True, "ok"


def _restic(*args: str, timeout: int = 1800) -> subprocess.CompletedProcess:
    env = dict(os.environ, RESTIC_PASSWORD_FILE=str(pass_file()))
    return subprocess.run(
        [restic_bin(), "-r", repo_url(), "--json", *args], capture_output=True, text=True, timeout=timeout, env=env
    )


def _git(repo: Path, *args: str, timeout: int = 60) -> subprocess.CompletedProcess | None:
    """Run git in repo. None means the call itself failed — distinct from a
    non-zero return, so callers can report 'could not check' rather than 'clean'."""
    try:
        return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        return None


def _ok(proc: subprocess.CompletedProcess | None) -> str:
    return proc.stdout if proc is not None and proc.returncode == 0 else ""


def _make_bundle(repo: Path, staging: Path, entry: dict) -> None:
    """Bundle every local branch. Mutates entry with the outcome."""
    dest = staging / f"{repo.name}.bundle"
    made = _git(repo, "bundle", "create", str(dest), "--branches", timeout=300)
    if made is None:
        entry["note"] = "bundle failed/timeout"
        return
    if made.returncode != 0:
        entry["note"] = (made.stderr or "bundle failed")[-120:]
        return
    size = dest.stat().st_size
    if size > MAX_BUNDLE_BYTES:
        dest.unlink(missing_ok=True)
        entry["note"] = f"skipped: bundle {size // 1_048_576}MB > cap — push this repo"
        return
    entry["bundled"] = True
    entry["bytes"] = size


def _capture_dirty(repo: Path, staging: Path, entry: dict) -> None:
    """Archive uncommitted work: a patch of tracked changes, plus the untracked
    files git itself would agree to add. Mutates entry; never raises."""
    patch = _ok(_git(repo, "diff", "HEAD", "--binary", timeout=120))
    if patch:
        raw = patch.encode()
        if len(raw) > MAX_DIRTY_BYTES:
            entry["tracked_patch"] = False
            entry["tracked_note"] = f"patch {len(raw) // 1_048_576}MB > cap — commit this repo"
        else:
            (staging / f"{repo.name}.dirty.patch").write_bytes(raw)
            entry["tracked_patch"] = True
            entry["tracked_bytes"] = len(raw)

    names = [n for n in _ok(_git(repo, "ls-files", "--others", "--exclude-standard")).splitlines() if n]
    secrets = [n for n in names if SECRET_NAME_RE.search(n)]
    keep = [n for n in names if n not in set(secrets)]
    if secrets:
        # Counted, not listed: the names themselves can be revealing.
        entry["secrets_skipped"] = len(secrets)
    if not keep:
        return

    sized = []
    for name in keep:
        f = repo / name
        if not f.is_file() or f.is_symlink():
            continue
        try:
            sized.append((f.stat().st_size, name, f))
        except OSError:
            continue
    # Smallest first. Under a byte cap the source files must beat regenerable
    # bulk: one repo here carries 4.8MB test screenshots alongside its work, and
    # in git's own listing order those would evict the code. Trading a big PNG
    # for fifty text files is always right in a backup.
    sized.sort()

    dest = staging / f"{repo.name}.untracked.tar"
    total = added = 0
    with tarfile.open(dest, "w") as tar:
        for i, (size, name, f) in enumerate(sized):
            if total + size > MAX_DIRTY_BYTES:
                entry["untracked_truncated"] = True
                entry["untracked_skipped"] = len(sized) - i  # sorted, so none of the rest fit
                break
            tar.add(f, arcname=name)
            total += size
            added += 1
    if added:
        entry["untracked_files"] = added
        entry["untracked_bytes"] = total
    else:
        dest.unlink(missing_ok=True)


def _bundle_unpushed(projects_dir: Path, staging: Path) -> list[dict]:
    """One entry per repo holding work that exists nowhere but this disk:
    local-only commits (a git bundle) and/or an uncommitted working tree.

    A repo with nothing at risk is omitted. A repo WITH something at risk is
    never omitted silently — the old version skipped clean-HEAD-but-dirty repos
    before recording anything, so an unprotected tree read as 'nothing to do'."""
    out = []
    for repo in sorted(p for p in projects_dir.iterdir() if (p / ".git").exists()):
        probe = _git(repo, "log", "--branches", "--not", "--remotes", "--oneline", "-1", timeout=30)
        status = _git(repo, "status", "--porcelain")
        if probe is None or status is None:
            out.append({"repo": repo.name, "bundled": False, "note": "git probe failed — COULD NOT CHECK"})
            continue

        has_local_commits = probe.returncode == 0 and bool(probe.stdout.strip())
        dirty = len([ln for ln in _ok(status).splitlines() if ln.strip()])
        if not has_local_commits and not dirty:
            continue

        entry: dict = {"repo": repo.name, "bundled": False}
        if has_local_commits:
            _make_bundle(repo, staging, entry)
        if dirty:
            entry["dirty_files"] = dirty
            _capture_dirty(repo, staging, entry)
        out.append(entry)
    return out


# What the vault protects, declared ONCE so the UI can show the user exactly
# this list rather than a hand-written copy that drifts. Adding an entry here
# changes both what is backed up and what the product tells you it backs up.
CLAUDE_DIR_ITEMS: list[tuple[str, str]] = [
    ("CLAUDE.md", "your global instructions"),
    ("settings.json", "settings"),
    ("settings.local.json", "local settings and permissions"),
    ("skills", "skills"),
    ("agents", "agent definitions"),
    ("commands", "custom slash commands"),
    ("rules", "rules"),
    ("docs", "notes and documents"),
    ("projects", "project memories"),
    ("agent-memory", "per-agent memory"),
]

# NEVER backed up, whatever else changes: live auth material. A backup is a
# copy in another place — a copy of a credential is a second thing to steal.
NEVER_BACKUP = {".credentials.json"}


def manifest(settings: Settings) -> dict:
    """The disclosure the UI renders: what is protected, what is deliberately not."""
    cd = settings.claude_dir
    included = [{"path": name, "what": what, "present": (cd / name).exists()} for name, what in CLAUDE_DIR_ITEMS]
    included.append({"path": "*.md", "what": "loose notes in your Claude folder", "present": True})
    included.append(
        {"path": "history.jsonl", "what": "your prompt history", "present": (cd / "history.jsonl").is_file()}
    )
    included.append(
        {"path": "(database)", "what": "proposals, queue and audit log", "present": settings.db_path.exists()}
    )
    included.append(
        {
            "path": "(git bundles)",
            "what": "commits and uncommitted work that exist only on this machine",
            "present": True,
        }
    )
    return {
        "root": str(cd),
        "included": included,
        "excluded": [
            {"path": ".credentials.json", "why": "live auth token — a backup would be a second copy to steal"},
            {
                "path": "*.jsonl transcripts",
                "why": "large, and can contain secrets; the distilled memory files are kept instead",
            },
        ],
    }


def _backup_paths(settings: Settings, staging: Path) -> list[str]:
    # history.jsonl is deliberately NOT here: this pass runs with --exclude
    # '*.jsonl' (transcripts), which would eat it — it gets its own pass
    cd = settings.claude_dir
    candidates = [cd / name for name, _ in CLAUDE_DIR_ITEMS]
    # loose notes people leave at the top level (README, scratch .md files)
    candidates += sorted(cd.glob("*.md"))
    candidates += [settings.db_path, staging]
    # Allowlist, never the whole directory: handing restic <claude_dir> itself
    # would sweep in .credentials.json. The filter is belt to that braces.
    return [str(p) for p in dict.fromkeys(candidates) if p.exists() and p.name not in NEVER_BACKUP]


def _restore_test(settings: Settings, snapshot: str = "latest") -> tuple[bool, str]:
    """Restore the primary MEMORY.md from the given snapshot and byte-compare.
    Callers pass the MAIN snapshot id — 'latest' may be the history-only pass."""
    from .config import primary_namespace

    live = settings.claude_dir / "projects" / primary_namespace() / "memory" / "MEMORY.md"
    if not live.is_file():
        return False, "no primary MEMORY.md to verify against"
    with tempfile.TemporaryDirectory(prefix="noirdeck-vault-verify-") as td:
        p = _restic("restore", snapshot, "--target", td, "--include", str(live), timeout=600)
        if p.returncode != 0:
            return False, f"restore failed: {(p.stderr or '')[-200:]}"
        restored = Path(td) / live.relative_to("/")
        if not restored.is_file():
            return False, "restored tree missing the sample file"
        same = hashlib.sha256(restored.read_bytes()).digest() == hashlib.sha256(live.read_bytes()).digest()
        return (
            same,
            "restored MEMORY.md matches live byte-for-byte"
            if same
            else "restored MEMORY.md DIFFERS from live (snapshot may predate an edit — investigate)",
        )


def run_backup(settings: Settings) -> dict:
    ok, why = configured()
    if not ok:
        return {"status": "not_configured", "detail": why}
    if not _RUN_LOCK.acquire(blocking=False):
        return {"status": "already_running"}
    conn = connect(settings.db_path)
    started = utcnow()
    result: dict = {"status": "failed", "detail": "unknown"}
    try:
        cur = conn.execute("INSERT INTO vault_runs (started_at, status) VALUES (?, 'running')", (started,))
        run_id = cur.lastrowid
        conn.commit()
        with tempfile.TemporaryDirectory(prefix="noirdeck-vault-bundles-") as td:
            staging = Path(td)
            bundles = _bundle_unpushed(settings.projects_dir, staging)
            p = _restic("backup", "--exclude", "*.jsonl", *_backup_paths(settings, staging), timeout=3600)
        # second pass without excludes for the one .jsonl we DO want
        hist = settings.claude_dir / "history.jsonl"
        if p.returncode == 0 and hist.exists():
            p2 = _restic("backup", str(hist), timeout=600)
            if p2.returncode != 0:
                p = p2
        if p.returncode != 0:
            detail = (p.stderr or "restic backup failed")[-300:]
            conn.execute(
                "UPDATE vault_runs SET status='failed', finished_at=?, detail=? WHERE id=?", (utcnow(), detail, run_id)
            )
            conn.commit()
            audit(conn, "vault", "backup_failed", detail[:200])
            return {"status": "failed", "detail": detail}
        summary = {}
        for line in (p.stdout or "").splitlines():
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if obj.get("message_type") == "summary":
                summary = obj
        _restic("forget", "--keep-daily", "14", "--keep-weekly", "8", "--keep-monthly", "6", "--prune", timeout=1800)
        verified, verify_note = _restore_test(settings, summary.get("snapshot_id") or "latest")
        detail = json.dumps(
            {
                "snapshot": summary.get("snapshot_id", "")[:10],
                "added_bytes": summary.get("data_added"),
                "files": summary.get("total_files_processed"),
                "bundles": bundles,
                "verify": verify_note,
            }
        )[:2000]
        conn.execute(
            "UPDATE vault_runs SET status=?, finished_at=?, restore_verified=?, detail=? WHERE id=?",
            ("ok" if verified else "unverified", utcnow(), int(verified), detail, run_id),
        )
        conn.commit()
        audit(
            conn,
            "vault",
            "backup_" + ("ok" if verified else "unverified"),
            f"run={run_id} snapshot={summary.get('snapshot_id', '')[:10]}",
        )
        result = {
            "status": "ok" if verified else "unverified",
            "snapshot": summary.get("snapshot_id", "")[:10],
            "restore_verified": verified,
            "verify": verify_note,
            "bundles": bundles,
        }
        return result
    except Exception as exc:  # noqa: BLE001 — a crashed backup must be recorded, not lost
        detail = f"{type(exc).__name__}: {exc}"[:300]
        try:
            conn.execute(
                "UPDATE vault_runs SET status='failed', finished_at=?, detail=? WHERE status='running'",
                (utcnow(), detail),
            )
            conn.commit()
        except Exception:  # noqa: BLE001
            pass
        return {"status": "failed", "detail": detail}
    finally:
        conn.close()
        _RUN_LOCK.release()


def status(conn) -> dict:
    ok, why = configured()
    rows = [dict(r) for r in conn.execute("SELECT * FROM vault_runs ORDER BY id DESC LIMIT 10").fetchall()]
    last_ok = next((r for r in rows if r["status"] == "ok"), None)
    return {
        "configured": ok,
        "reason": None if ok else why,
        "repo": repo_url() or None,
        "last_runs": rows,
        "last_verified": last_ok["finished_at"] if last_ok else None,
    }


if __name__ == "__main__":
    s = Settings.load()
    init_db(s.db_path)
    print(json.dumps(run_backup(s)))
