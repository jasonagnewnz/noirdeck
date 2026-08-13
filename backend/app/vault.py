"""Vault — recurring encrypted offsite backup with a VERIFIED restore, wrapping
restic (boring, proven; no hand-rolled crypto per the security doctrine).

Backup set (the irreplaceable knowledge, not the bulk):
- <claude_dir>: skills/, agents/, rules/, docs/, CLAUDE.md, history.jsonl,
  projects/ EXCLUDING *.jsonl (raw session transcripts are large and can
  contain sensitive values; the distilled knowledge lives in memory files)
- the noirdeck database
- git bundles of every fleet repo that has unpushed/local-only work

The restore test IS the feature: every run restores a sample from the fresh
snapshot and byte-compares it against the live file. An unverified backup is
reported as exactly that. Fail-closed: unconfigured or missing passphrase file
means status 'not configured', never a silent no-op that looks healthy."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import threading
from pathlib import Path

from .config import Settings
from .db import audit, connect, init_db, utcnow

MAX_BUNDLE_BYTES = 200 * 1024 * 1024  # skip monster repos, note them instead
_RUN_LOCK = threading.Lock()


def repo_url() -> str:
    return os.environ.get("NOIRDECK_VAULT_REPO", "")


def pass_file() -> Path:
    return Path(os.environ.get(
        "NOIRDECK_VAULT_PASSFILE", "~/.config/noirdeck/vault-pass")).expanduser()


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
    return subprocess.run([restic_bin(), "-r", repo_url(), "--json", *args],
                          capture_output=True, text=True, timeout=timeout, env=env)


def _bundle_unpushed(projects_dir: Path, staging: Path) -> list[dict]:
    """One bundle per repo holding commits that exist nowhere but this disk."""
    out = []
    for repo in sorted(p for p in projects_dir.iterdir() if (p / ".git").exists()):
        try:
            probe = subprocess.run(
                ["git", "-C", str(repo), "log", "--branches", "--not", "--remotes",
                 "--oneline", "-1"], capture_output=True, text=True, timeout=30)
        except (OSError, subprocess.TimeoutExpired):
            continue
        if probe.returncode != 0 or not probe.stdout.strip():
            continue
        dest = staging / f"{repo.name}.bundle"
        try:
            made = subprocess.run(
                ["git", "-C", str(repo), "bundle", "create", str(dest), "--branches"],
                capture_output=True, text=True, timeout=300)
        except (OSError, subprocess.TimeoutExpired):
            out.append({"repo": repo.name, "bundled": False, "note": "bundle failed/timeout"})
            continue
        if made.returncode != 0:
            out.append({"repo": repo.name, "bundled": False,
                        "note": (made.stderr or "bundle failed")[-120:]})
            continue
        size = dest.stat().st_size
        if size > MAX_BUNDLE_BYTES:
            dest.unlink(missing_ok=True)
            out.append({"repo": repo.name, "bundled": False,
                        "note": f"skipped: bundle {size // 1_048_576}MB > cap — push this repo"})
        else:
            out.append({"repo": repo.name, "bundled": True, "bytes": size})
    return out


def _backup_paths(settings: Settings, staging: Path) -> list[str]:
    # history.jsonl is deliberately NOT here: this pass runs with --exclude
    # '*.jsonl' (transcripts), which would eat it — it gets its own pass
    cd = settings.claude_dir
    candidates = [cd / "skills", cd / "agents", cd / "rules", cd / "docs",
                  cd / "CLAUDE.md", cd / "projects",
                  settings.db_path, staging]
    return [str(p) for p in candidates if p.exists()]


def _restore_test(settings: Settings, snapshot: str = "latest") -> tuple[bool, str]:
    """Restore the primary MEMORY.md from the given snapshot and byte-compare.
    Callers pass the MAIN snapshot id — 'latest' may be the history-only pass."""
    from .config import primary_namespace
    live = settings.claude_dir / "projects" / primary_namespace() / "memory" / "MEMORY.md"
    if not live.is_file():
        return False, "no primary MEMORY.md to verify against"
    with tempfile.TemporaryDirectory(prefix="noirdeck-vault-verify-") as td:
        p = _restic("restore", snapshot, "--target", td,
                    "--include", str(live), timeout=600)
        if p.returncode != 0:
            return False, f"restore failed: {(p.stderr or '')[-200:]}"
        restored = Path(td) / live.relative_to("/")
        if not restored.is_file():
            return False, "restored tree missing the sample file"
        same = (hashlib.sha256(restored.read_bytes()).digest()
                == hashlib.sha256(live.read_bytes()).digest())
        return same, "restored MEMORY.md matches live byte-for-byte" if same else \
            "restored MEMORY.md DIFFERS from live (snapshot may predate an edit — investigate)"


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
        cur = conn.execute(
            "INSERT INTO vault_runs (started_at, status) VALUES (?, 'running')", (started,))
        run_id = cur.lastrowid
        conn.commit()
        with tempfile.TemporaryDirectory(prefix="noirdeck-vault-bundles-") as td:
            staging = Path(td)
            bundles = _bundle_unpushed(settings.projects_dir, staging)
            p = _restic("backup", "--exclude", "*.jsonl",
                        *_backup_paths(settings, staging), timeout=3600)
        # second pass without excludes for the one .jsonl we DO want
        hist = settings.claude_dir / "history.jsonl"
        if p.returncode == 0 and hist.exists():
            p2 = _restic("backup", str(hist), timeout=600)
            if p2.returncode != 0:
                p = p2
        if p.returncode != 0:
            detail = (p.stderr or "restic backup failed")[-300:]
            conn.execute("UPDATE vault_runs SET status='failed', finished_at=?, detail=? "
                         "WHERE id=?", (utcnow(), detail, run_id))
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
        _restic("forget", "--keep-daily", "14", "--keep-weekly", "8",
                "--keep-monthly", "6", "--prune", timeout=1800)
        verified, verify_note = _restore_test(
            settings, summary.get("snapshot_id") or "latest")
        detail = json.dumps({
            "snapshot": summary.get("snapshot_id", "")[:10],
            "added_bytes": summary.get("data_added"),
            "files": summary.get("total_files_processed"),
            "bundles": bundles, "verify": verify_note,
        })[:2000]
        conn.execute(
            "UPDATE vault_runs SET status=?, finished_at=?, restore_verified=?, detail=? "
            "WHERE id=?",
            ("ok" if verified else "unverified", utcnow(), int(verified), detail, run_id))
        conn.commit()
        audit(conn, "vault", "backup_" + ("ok" if verified else "unverified"),
              f"run={run_id} snapshot={summary.get('snapshot_id', '')[:10]}")
        result = {"status": "ok" if verified else "unverified",
                  "snapshot": summary.get("snapshot_id", "")[:10],
                  "restore_verified": verified, "verify": verify_note,
                  "bundles": bundles}
        return result
    except Exception as exc:  # noqa: BLE001 — a crashed backup must be recorded, not lost
        detail = f"{type(exc).__name__}: {exc}"[:300]
        try:
            conn.execute("UPDATE vault_runs SET status='failed', finished_at=?, detail=? "
                         "WHERE status='running'", (utcnow(), detail))
            conn.commit()
        except Exception:  # noqa: BLE001
            pass
        return {"status": "failed", "detail": detail}
    finally:
        conn.close()
        _RUN_LOCK.release()


def status(conn) -> dict:
    ok, why = configured()
    rows = [dict(r) for r in conn.execute(
        "SELECT * FROM vault_runs ORDER BY id DESC LIMIT 10").fetchall()]
    last_ok = next((r for r in rows if r["status"] == "ok"), None)
    return {"configured": ok, "reason": None if ok else why,
            "repo": repo_url() or None,
            "last_runs": rows, "last_verified": last_ok["finished_at"] if last_ok else None}


if __name__ == "__main__":
    s = Settings.load()
    init_db(s.db_path)
    print(json.dumps(run_backup(s)))
