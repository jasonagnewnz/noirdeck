import subprocess

import pytest

from app import vault
from app.config import Settings
from app.db import connect, init_db


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


def test_detects_tampered_restore(vault_env, claude_dir):
    out = vault.run_backup(vault_env)
    assert out["status"] == "ok"
    # live file changes AFTER the snapshot — verify must FAIL loudly, not lie
    mem = claude_dir / "projects" / "-home-user" / "memory" / "MEMORY.md"
    mem.write_text(mem.read_text() + "\nedited after snapshot\n")
    ok, note = vault._restore_test(vault_env, out["snapshot"])
    assert not ok and "DIFFERS" in note
