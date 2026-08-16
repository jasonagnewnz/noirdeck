import asyncio
import subprocess

import pytest

from app.workspace import WorkspaceError, WorkspaceManager, init_repo, validate_cwd


@pytest.fixture
def projects(tmp_path):
    proj = tmp_path / "projects"
    proj.mkdir()
    repo = proj / "demo"
    repo.mkdir()
    subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True)
    return proj


def test_validate_cwd(projects):
    assert validate_cwd(projects, "demo").name == "demo"
    with pytest.raises(WorkspaceError):
        validate_cwd(projects, "nope")
    with pytest.raises(WorkspaceError):
        validate_cwd(projects, "../outside")


def test_pty_roundtrip_and_reap(projects):
    async def run():
        mgr = WorkspaceManager(projects)
        term = mgr.start("demo", argv_override=["bash", "-c", "echo MARKER_$((40+2)); sleep 0.1"])
        out = b""
        try:
            while True:
                chunk = await asyncio.wait_for(term.queue.get(), timeout=5)
                if chunk is None:
                    break
                out += chunk
        except asyncio.TimeoutError:
            pass
        assert b"MARKER_42" in out
        assert b"MARKER_42" in b"".join(term.scrollback)
        term.resize(120, 40)  # no crash on a finished/finishing pty is acceptable
        mgr.reap()
        assert mgr.listing() == []

    asyncio.run(run())


def test_interactive_write(projects):
    async def run():
        mgr = WorkspaceManager(projects)
        term = mgr.start("demo", argv_override=["cat"])
        term.write(b"hello-pty\n")
        out = b""
        for _ in range(10):
            try:
                chunk = await asyncio.wait_for(term.queue.get(), timeout=2)
            except asyncio.TimeoutError:
                break
            out += chunk or b""
            if out.count(b"hello-pty") >= 2:  # echo + cat output
                break
        assert b"hello-pty" in out
        mgr.stop(term.id)
        for _ in range(20):  # signal delivery is async — poll up to 2s
            if not term.alive():
                break
            await asyncio.sleep(0.1)
        assert not term.alive()

    asyncio.run(run())


def test_session_cap(projects):
    async def run():
        mgr = WorkspaceManager(projects)
        for _ in range(6):
            mgr.start("demo", argv_override=["sleep", "5"])
        with pytest.raises(WorkspaceError, match="cap"):
            mgr.start("demo", argv_override=["sleep", "5"])
        for sid in list(mgr.sessions):
            mgr.stop(sid)

    asyncio.run(run())


def test_init_repo(projects):
    target = init_repo(projects, "fresh-one")
    assert (target / ".git").is_dir()
    with pytest.raises(WorkspaceError):
        init_repo(projects, "fresh-one")  # exists
    for bad in ("../evil", "a b", ".hidden" * 20):
        with pytest.raises(WorkspaceError):
            init_repo(projects, bad)


def test_latest_transcript_session_id(tmp_path):
    import os
    import time

    from app.workspace import latest_transcript_session_id

    claude = tmp_path / "claude"
    cwd = tmp_path / "projects" / "demo"
    ns = claude / "projects" / str(cwd).replace("/", "-")
    ns.mkdir(parents=True)
    old = ns / "aaaaaaaa-1111-2222-3333-444444444444.jsonl"
    new = ns / "bbbbbbbb-1111-2222-3333-444444444444.jsonl"
    old.write_text("{}")
    new.write_text("{}")
    now = time.time()
    os.utime(old, (now - 60, now - 60))
    os.utime(new, (now, now))
    assert latest_transcript_session_id(claude, cwd) == new.stem
    # newest file with a non-session-id name means "unknown", never a bad argv
    weird = ns / "not a session id!.jsonl"
    weird.write_text("{}")
    os.utime(weird, (now + 60, now + 60))
    assert latest_transcript_session_id(claude, cwd) is None
    assert latest_transcript_session_id(claude, tmp_path / "nowhere") is None


def test_continue_last_builds_continue_argv(projects, monkeypatch):
    import app.workspace as ws

    captured = {}

    class FakeTerm:
        def __init__(self, project, cwd, argv):
            captured["argv"] = argv
            self.project, self.cwd, self.argv = project, cwd, argv
            self.id = "fake"

        def start(self):
            pass

    monkeypatch.setattr(ws, "TermSession", FakeTerm)
    monkeypatch.setattr(ws, "claude_bin", lambda: "claude")
    mgr = WorkspaceManager(projects)
    mgr.start("demo", continue_last=True)
    assert captured["argv"] == ["claude", "--continue"]
