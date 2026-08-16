import json
import subprocess
import time

import pytest

from app import ask
from app.config import Settings


@pytest.fixture
def settings(tmp_path, claude_dir):
    db = tmp_path / "t.db"
    return Settings(
        claude_dir=claude_dir,
        projects_dir=tmp_path,
        db_path=db,
        port=1,
        mining_armed=False,
        overnight_armed=False,
        mine_max_batches=1,
    )


@pytest.fixture(autouse=True)
def fresh_jobs():
    ask._jobs.clear()
    yield
    ask._jobs.clear()


def _cli_json(text):
    return json.dumps([{"type": "result", "result": text, "usage": {"input_tokens": 10, "output_tokens": 20}}])


def _wait_done(job_id, timeout=5):
    for _ in range(int(timeout * 100)):
        job = ask.get(job_id)
        if job["status"] != "running":
            return job
        time.sleep(0.01)
    raise AssertionError("job never finished")


def test_submit_answers_and_records_tokens(settings, monkeypatch):
    monkeypatch.setattr(
        ask,
        "_invoke",
        lambda s, p: subprocess.CompletedProcess([], 0, stdout=_cli_json("Two repos have unpushed work."), stderr=""),
    )
    out = ask.submit(settings, "which repos have unpushed work?")
    job = _wait_done(out["id"])
    assert job["status"] == "done"
    assert job["answer"] == "Two repos have unpushed work."
    assert job["tokens_out"] == 20
    assert job["seconds"] is not None


def test_failure_and_timeout_become_plain_errors(settings, monkeypatch):
    monkeypatch.setattr(ask, "_invoke", lambda s, p: subprocess.CompletedProcess([], 1, stdout="", stderr="boom"))
    job = _wait_done(ask.submit(settings, "q")["id"])
    assert job["status"] == "error"
    assert "rc=1" in job["answer"] and "boom" in job["answer"]

    def _timeout(s, p):
        raise subprocess.TimeoutExpired([], 300)

    monkeypatch.setattr(ask, "_invoke", _timeout)
    job = _wait_done(ask.submit(settings, "q2")["id"])
    assert job["status"] == "error"
    assert "Timed out" in job["answer"]


def test_one_question_at_a_time(settings, monkeypatch):
    release = []

    def _slow(s, p):
        while not release:
            time.sleep(0.01)
        return subprocess.CompletedProcess([], 0, stdout=_cli_json("ok"), stderr="")

    monkeypatch.setattr(ask, "_invoke", _slow)
    out = ask.submit(settings, "first")
    with pytest.raises(ask.AskError, match="already being worked on"):
        ask.submit(settings, "second")
    release.append(1)
    _wait_done(out["id"])


def test_question_validation(settings):
    with pytest.raises(ask.AskError):
        ask.submit(settings, "   ")
    with pytest.raises(ask.AskError, match="under"):
        ask.submit(settings, "x" * 501)


def test_readonly_cage_in_argv(settings, monkeypatch):
    """The real invoker must restrict the session's tool set to read-only tools —
    this pins the argv contract so a refactor can't quietly drop the cage."""
    seen = {}

    def fake_run(argv, **kw):
        seen["argv"] = argv
        return subprocess.CompletedProcess(argv, 0, stdout=_cli_json("ok"), stderr="")

    monkeypatch.setattr(ask.subprocess, "run", fake_run)
    monkeypatch.setattr("app.workspace.claude_bin", lambda: "claude")
    ask._invoke(settings, "prompt")
    argv = seen["argv"]
    i = argv.index("--tools")
    assert argv[i + 1 :] == ["Read", "Grep", "Glob"]  # last, so nothing is swallowed
    assert "--permission-mode" not in argv  # default (not acceptEdits) for depth


def test_get_unknown_job(settings):
    with pytest.raises(ask.AskError, match="no such question"):
        ask.get("nope")
