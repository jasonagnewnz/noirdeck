import asyncio
import subprocess

import pytest

from noirdeck.workspace import TermSession, WorkspaceError, WorkspaceManager, init_repo, takeover_prompt, validate_cwd


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
        for _ in range(20):  # signal delivery is async: poll up to 2s
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

    from noirdeck.workspace import latest_transcript_session_id

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
    import noirdeck.workspace as ws

    captured = {}

    class FakeTerm:
        def __init__(self, project, cwd, argv, runner="claude", model=None):
            captured["argv"] = argv
            self.project, self.cwd, self.argv = project, cwd, argv
            self.runner, self.model = runner, model
            self.id = "fake"

        def start(self):
            pass

    monkeypatch.setattr(ws, "TermSession", FakeTerm)
    monkeypatch.setattr("noirdeck.ai_runtime.require_runner_bin", lambda spec: spec.bin_name)
    mgr = WorkspaceManager(projects)
    mgr.start("demo", continue_last=True)
    assert captured["argv"] == ["claude", "--continue"]


def test_codex_live_session_uses_fixed_runner_argv(projects, monkeypatch):
    import noirdeck.workspace as ws

    captured = {}

    class FakeTerm:
        def __init__(self, project, cwd, argv, runner="claude", model=None):
            captured["argv"] = argv
            captured["runner"] = runner
            captured["model"] = model
            self.project, self.cwd, self.argv = project, cwd, argv
            self.runner, self.model = runner, model
            self.id = "fake"

        def start(self):
            pass

    monkeypatch.setattr(ws, "TermSession", FakeTerm)
    monkeypatch.setattr("noirdeck.ai_runtime.require_runner_bin", lambda spec: spec.bin_name)
    mgr = WorkspaceManager(projects)
    mgr.start("demo", runner_id="codex", model="gpt-5-codex", initial_prompt="orient")
    assert captured == {
        "argv": ["codex", "--model", "gpt-5-codex", "--no-alt-screen", "orient"],
        "runner": "codex",
        "model": "gpt-5-codex",
    }


def test_claude_picker_offers_the_current_model_line():
    """A retired id 404s at spawn time and reads as a dead session, not an error,
    so the picker must carry the line as it ships today."""
    from noirdeck import ai_runtime

    choices = ai_runtime.model_choices("claude")
    assert choices[:4] == ["claude-fable-5", "claude-opus-5", "claude-sonnet-5", "claude-haiku-4-5"]
    # every pipeline role must be offerable, or a queued build pins a model the
    # operator cannot select by hand
    for role in ("think", "build", "review"):
        assert ai_runtime.role_model(role) in choices


def test_model_id_rejects_shell_fragments(projects, monkeypatch):
    monkeypatch.setattr("noirdeck.ai_runtime.require_runner_bin", lambda spec: spec.bin_name)
    mgr = WorkspaceManager(projects)
    with pytest.raises(WorkspaceError, match="model id"):
        mgr.start("demo", model="sonnet; rm -rf /", argv_override=None)


def test_ollama_live_session_uses_local_model_runner(projects, monkeypatch):
    import noirdeck.workspace as ws

    captured = {}

    class FakeTerm:
        def __init__(self, project, cwd, argv, runner="claude", model=None):
            captured["argv"] = argv
            captured["runner"] = runner
            captured["model"] = model
            self.project, self.cwd, self.argv = project, cwd, argv
            self.runner, self.model = runner, model
            self.id = "fake"

        def start(self):
            pass

    monkeypatch.setattr(ws, "TermSession", FakeTerm)
    monkeypatch.setattr("noirdeck.ai_runtime.require_runner_bin", lambda spec: spec.bin_name)
    mgr = WorkspaceManager(projects)
    mgr.start("demo", runner_id="ollama", model="qwen2.5-coder:7b", initial_prompt="orient")
    assert captured == {
        "argv": ["ollama", "run", "qwen2.5-coder:7b", "orient"],
        "runner": "ollama",
        "model": "qwen2.5-coder:7b",
    }


def test_takeover_prompt_uses_clean_terminal_tail(projects):
    cwd = validate_cwd(projects, "demo")
    term = TermSession("demo", cwd, ["codex"], runner="codex", model="gpt-5-codex")
    term.scrollback.append(b"\x1b[?25l\x1b[1;1HWorking...\r\nDone with step one\r\n\x1b[31mNeed tests\x1b[0m\r\n")
    prompt = takeover_prompt(term, "claude", "claude-sonnet-5")
    assert "SESSION TAKEOVER BRIEF" in prompt
    assert "Source runtime: codex / gpt-5-codex" in prompt
    assert "Target runtime: claude / claude-sonnet-5" in prompt
    assert "Done with step one" in prompt
    assert "Need tests" in prompt
    assert "\x1b" not in prompt
