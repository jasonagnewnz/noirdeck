import subprocess
import tarfile
from pathlib import Path

import pytest

from noirdeck import vault
from noirdeck.config import Settings
from noirdeck.db import connect, init_db


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), "-c", "user.email=t@t", "-c", "user.name=t", *args],
        check=True,
        capture_output=True,
    )


def _pushed_repo(root: Path, name: str) -> Path:
    """A repo whose every commit is on its remote — nothing for a bundle to carry.
    This is the shape that used to vanish from the report entirely."""
    bare = root / f"{name}.git"
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True, capture_output=True)
    repo = root / name
    repo.mkdir()
    _git(repo, "init", "-q")
    (repo / "tracked.txt").write_text("v1\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "initial")
    _git(repo, "remote", "add", "origin", str(bare))
    _git(repo, "push", "-q", "-u", "origin", "HEAD")
    return repo


def _members(tar_path: Path) -> list[str]:
    with tarfile.open(tar_path) as tar:
        return tar.getnames()


@pytest.fixture
def vault_env(tmp_path, monkeypatch, claude_dir):
    if not vault.restic_bin():
        pytest.skip("restic not installed")
    proj = tmp_path / "projects"
    proj.mkdir()
    # one repo with unpushed local work, one clean-ish repo with a remote
    dirty = proj / "wip-app"
    dirty.mkdir()
    subprocess.run(["git", "-C", str(dirty), "init", "-q"], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(dirty),
            "-c",
            "user.email=t@t",
            "-c",
            "user.name=t",
            "commit",
            "-q",
            "--allow-empty",
            "-m",
            "local only",
        ],
        check=True,
    )
    repo = tmp_path / "resticrepo"
    passfile = tmp_path / "pass"
    passfile.write_text("test-passphrase\n")
    monkeypatch.setenv("NOIRDECK_VAULT_REPO", str(repo))
    monkeypatch.setenv("NOIRDECK_VAULT_PASSFILE", str(passfile))
    monkeypatch.setenv("NOIRDECK_CLAUDE_DIR", str(claude_dir))
    monkeypatch.setenv("NOIRDECK_PROJECTS_DIR", str(proj))
    monkeypatch.setenv("NOIRDECK_DB_PATH", str(tmp_path / "v.db"))
    s = Settings.load()
    init_db(s.db_path)
    subprocess.run(
        [vault.restic_bin(), "-r", str(repo), "init"],
        env={"RESTIC_PASSWORD_FILE": str(passfile), "PATH": "/usr/bin:/bin"},
        capture_output=True,
        check=True,
    )
    return s


def test_unconfigured_is_loud(monkeypatch, tmp_path, claude_dir):
    monkeypatch.delenv("NOIRDECK_VAULT_REPO", raising=False)
    monkeypatch.setenv("NOIRDECK_CLAUDE_DIR", str(claude_dir))
    monkeypatch.setenv("NOIRDECK_PROJECTS_DIR", str(tmp_path))
    monkeypatch.setenv("NOIRDECK_DB_PATH", str(tmp_path / "u.db"))
    s = Settings.load()
    out = vault.run_backup(s)
    assert out["status"] == "not_configured"
    ok, why = vault.configured()
    assert not ok and "VAULT_REPO" in why


def test_backup_verifies_restore_and_bundles_unpushed(vault_env):
    # the fixture claude tree has a primary MEMORY.md at -home-user (conftest pin)
    out = vault.run_backup(vault_env)
    assert out["status"] == "ok", out
    assert out["restore_verified"] is True
    assert "matches live byte-for-byte" in out["verify"]
    bundled = [b for b in out["bundles"] if b.get("bundled")]
    assert [b["repo"] for b in bundled] == ["wip-app"]  # unpushed repo captured
    conn = connect(vault_env.db_path)
    row = conn.execute("SELECT * FROM vault_runs ORDER BY id DESC LIMIT 1").fetchone()
    conn.close()
    assert row["status"] == "ok" and row["restore_verified"] == 1
    st_conn = connect(vault_env.db_path)
    st = vault.status(st_conn)
    st_conn.close()
    assert st["configured"] and st["last_verified"] is not None


def test_pushed_but_dirty_repo_is_captured_not_skipped(tmp_path):
    """Regression: a repo with nothing unpushed but a dirty tree was dropped
    before any entry was recorded, so unprotected work read as 'nothing to do'."""
    proj = tmp_path / "projects"
    proj.mkdir()
    repo = _pushed_repo(proj, "shipped-app")
    (repo / "tracked.txt").write_text("v2 uncommitted\n")
    (repo / "brand_new.py").write_text("print('new work')\n")
    staging = tmp_path / "staging"
    staging.mkdir()

    entry = {e["repo"]: e for e in vault._bundle_unpushed(proj, staging)}["shipped-app"]

    assert entry["bundled"] is False, "nothing unpushed, so no bundle — but still reported"
    assert entry["dirty_files"] == 2
    assert entry["tracked_patch"] is True
    assert entry["untracked_files"] == 1
    assert "v2 uncommitted" in (staging / "shipped-app.dirty.patch").read_text()
    assert _members(staging / "shipped-app.untracked.tar") == ["brand_new.py"]


def test_clean_repo_stays_out_of_the_report(tmp_path):
    proj = tmp_path / "projects"
    proj.mkdir()
    _pushed_repo(proj, "all-clean")
    staging = tmp_path / "staging"
    staging.mkdir()
    assert vault._bundle_unpushed(proj, staging) == []


def test_gitignored_secret_never_enters_the_capture(tmp_path):
    """.gitignore is the primary filter: --exclude-standard drops the secret
    before the deny-list is ever consulted, so nothing is even counted."""
    proj = tmp_path / "projects"
    proj.mkdir()
    repo = _pushed_repo(proj, "ignores-its-secrets")
    (repo / ".gitignore").write_text(".env\n")
    _git(repo, "add", ".gitignore")
    _git(repo, "commit", "-q", "-m", "ignore env")
    _git(repo, "push", "-q", "origin", "HEAD")
    (repo / ".env").write_text("API_KEY=live-value-do-not-back-up\n")
    (repo / "work.py").write_text("x = 1\n")
    staging = tmp_path / "staging"
    staging.mkdir()

    entry = {e["repo"]: e for e in vault._bundle_unpushed(proj, staging)}["ignores-its-secrets"]

    assert _members(staging / "ignores-its-secrets.untracked.tar") == ["work.py"]
    assert "secrets_skipped" not in entry, "git already excluded it; nothing to deny-list"


def test_unignored_secret_is_skipped_and_counted(tmp_path):
    """Defence in depth for a repo that never ignored its secrets. The skip is
    reported as a count so it can never pass as 'there was nothing there'."""
    proj = tmp_path / "projects"
    proj.mkdir()
    repo = _pushed_repo(proj, "sloppy-repo")
    (repo / ".env").write_text("API_KEY=live-value-do-not-back-up\n")
    (repo / "server.pem").write_text("-----BEGIN PRIVATE KEY-----\n")
    (repo / "work.py").write_text("x = 1\n")
    staging = tmp_path / "staging"
    staging.mkdir()

    entry = {e["repo"]: e for e in vault._bundle_unpushed(proj, staging)}["sloppy-repo"]

    assert entry["secrets_skipped"] == 2
    assert entry["untracked_files"] == 1
    assert _members(staging / "sloppy-repo.untracked.tar") == ["work.py"]


def test_the_cap_drops_bulk_and_keeps_source(tmp_path, monkeypatch):
    """A repo can hold megabytes of regenerable artifacts next to its work.
    Under the cap the small source files must survive and the blob must go."""
    monkeypatch.setattr(vault, "MAX_DIRTY_BYTES", 4096)
    proj = tmp_path / "projects"
    proj.mkdir()
    repo = _pushed_repo(proj, "screenshot-heavy")
    (repo / "shot.png").write_bytes(b"\x00" * 8192)  # over cap on its own
    for i in range(3):
        (repo / f"src_{i}.py").write_text(f"value = {i}\n")
    staging = tmp_path / "staging"
    staging.mkdir()

    entry = {e["repo"]: e for e in vault._bundle_unpushed(proj, staging)}["screenshot-heavy"]

    assert sorted(_members(staging / "screenshot-heavy.untracked.tar")) == [
        "src_0.py",
        "src_1.py",
        "src_2.py",
    ]
    assert entry["untracked_truncated"] is True
    assert entry["untracked_skipped"] == 1  # the blob, reported not hidden


def test_local_commits_and_dirty_tree_are_both_captured(tmp_path):
    proj = tmp_path / "projects"
    proj.mkdir()
    repo = _pushed_repo(proj, "both-at-risk")
    (repo / "tracked.txt").write_text("committed locally\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "local only commit")
    (repo / "still_dirty.py").write_text("y = 2\n")
    staging = tmp_path / "staging"
    staging.mkdir()

    entry = {e["repo"]: e for e in vault._bundle_unpushed(proj, staging)}["both-at-risk"]

    assert entry["bundled"] is True and entry["bytes"] > 0
    assert entry["dirty_files"] == 1
    assert _members(staging / "both-at-risk.untracked.tar") == ["still_dirty.py"]


def test_credentials_are_never_in_the_backup_set(tmp_path, claude_dir, monkeypatch):
    """The one file that must never be copied anywhere. Guards against someone
    later 'simplifying' the allowlist into backing up the whole claude dir."""
    (claude_dir / ".credentials.json").write_text('{"token": "live-oauth-token"}')
    (claude_dir / "settings.json").write_text("{}")
    monkeypatch.setenv("NOIRDECK_CLAUDE_DIR", str(claude_dir))
    monkeypatch.setenv("NOIRDECK_PROJECTS_DIR", str(tmp_path))
    monkeypatch.setenv("NOIRDECK_DB_PATH", str(tmp_path / "c.db"))
    s = Settings.load()
    paths = vault._backup_paths(s, tmp_path / "staging")

    assert not any(".credentials.json" in p for p in paths)
    assert any(p.endswith("settings.json") for p in paths), "settings must be protected"
    # and the claude dir must never be handed over wholesale
    assert str(claude_dir) not in paths


def test_manifest_tells_the_user_what_is_and_is_not_protected(tmp_path, claude_dir, monkeypatch):
    monkeypatch.setenv("NOIRDECK_CLAUDE_DIR", str(claude_dir))
    monkeypatch.setenv("NOIRDECK_PROJECTS_DIR", str(tmp_path))
    monkeypatch.setenv("NOIRDECK_DB_PATH", str(tmp_path / "m.db"))
    man = vault.manifest(Settings.load())

    included = {i["path"] for i in man["included"]}
    assert {"CLAUDE.md", "settings.json", "skills", "projects", "agent-memory"} <= included
    assert any(e["path"] == ".credentials.json" for e in man["excluded"])
    # every excluded entry must say WHY, or the disclosure is just a list
    assert all(e.get("why") for e in man["excluded"])


def test_manifest_matches_what_is_actually_backed_up(tmp_path, claude_dir, monkeypatch):
    """Disclosure drift is the failure here: a manifest that promises more than
    the backup set delivers is worse than no manifest."""
    for name in ("settings.json", "settings.local.json", "CLAUDE.md"):
        (claude_dir / name).write_text("{}")
    for name in ("skills", "agents", "commands", "rules", "docs", "agent-memory"):
        (claude_dir / name).mkdir(exist_ok=True)
    monkeypatch.setenv("NOIRDECK_CLAUDE_DIR", str(claude_dir))
    monkeypatch.setenv("NOIRDECK_PROJECTS_DIR", str(tmp_path))
    monkeypatch.setenv("NOIRDECK_DB_PATH", str(tmp_path / "d.db"))
    s = Settings.load()
    paths = vault._backup_paths(s, tmp_path / "staging")

    for item in vault.manifest(s)["included"]:
        if item["present"] and not item["path"].startswith(("*", "(")) and item["path"] != "history.jsonl":
            assert any(p.endswith(item["path"]) for p in paths), f"promised but not backed up: {item['path']}"


def test_detects_tampered_restore(vault_env, claude_dir):
    out = vault.run_backup(vault_env)
    assert out["status"] == "ok"
    # live file changes AFTER the snapshot — verify must FAIL loudly, not lie
    mem = claude_dir / "projects" / "-home-user" / "memory" / "MEMORY.md"
    mem.write_text(mem.read_text() + "\nedited after snapshot\n")
    ok, note = vault._restore_test(vault_env, out["snapshot"])
    assert not ok and "DIFFERS" in note
