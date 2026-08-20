"""Consult tests.

These pin the three properties the feature promises, because each is a promise
that would fail silently if it broke: advisory-only, redacted-first, and quiet
unless it has something to say.
"""

import subprocess

import pytest

from noirdeck import consult


def test_detects_signals_worth_interrupting_for():
    assert consult.detect_signal("Traceback (most recent call last):") == "traceback"
    assert consult.detect_signal("FAILED tests/test_x.py::test_y") == "test-failure"
    assert consult.detect_signal("ValueError: bad input") == "python-error"


def test_stays_quiet_on_ordinary_output():
    """A consultant that fires on normal output is noise, and noise gets the
    feature switched off. Silence is the default, not the exception."""
    for line in (
        "32 passed in 3.4s",
        "building frontend...",
        "$ git status",
        "Compiled successfully.",
    ):
        assert consult.detect_signal(line) is None, line


def test_context_is_redacted_before_the_model_sees_it():
    ctx, _counts = consult._context("DB_PASSWORD=hunter2xyz and AWS_SECRET_ACCESS_KEY=abcdef123456789")
    assert "hunter2xyz" not in ctx
    assert "abcdef123456789" not in ctx
    assert "REDACTED" in ctx


def test_redaction_runs_before_the_tail_is_cut():
    """Trimming first could slice a secret in half and leave a fragment that no
    longer matches its own pattern — so the whole text is scrubbed, then cut."""
    secret = "DB_PASSWORD=supersecretvalue123"
    padding = "x" * (consult.CONTEXT_CHARS * 2)
    ctx, _ = consult._context(secret + "\n" + padding)
    assert "supersecretvalue123" not in ctx


def test_consultant_is_spawned_read_only(monkeypatch):
    """readonly=True is what makes this advisory rather than a second writer.
    If someone flips it, this test is the thing that notices."""
    seen = {}

    def fake_queue_argv(runner_id, model, max_turns, prompt, readonly=False):
        seen["readonly"] = readonly
        return ["/bin/true"]

    monkeypatch.setattr(consult, "queue_argv", fake_queue_argv)

    class _Settings:
        projects_dir = "/tmp"

    consult._invoke(_Settings(), "ollama", "m", "prompt")
    assert seen["readonly"] is True


def test_cooldown_prevents_a_storm():
    """One failing build writes hundreds of lines. Without a cooldown that is
    hundreds of consultations."""
    sid = "cooldown-session"
    consult._last_ambient.pop(sid, None)
    assert consult.cooled_down(sid) is True
    consult._last_ambient[sid] = consult._now()
    assert consult.cooled_down(sid) is False


def test_nothing_to_add_becomes_quiet_not_noise(monkeypatch):
    monkeypatch.setattr(
        consult,
        "_invoke",
        lambda *a, **k: subprocess.CompletedProcess(args=[], returncode=0, stdout="NOTHING TO ADD", stderr=""),
    )

    class _Settings:
        projects_dir = "/tmp"

    job = consult.submit(_Settings(), project="p", scrollback="clean output", runner="ollama")
    for _ in range(100):
        out = consult.get(job["id"])
        if out.get("status") != "running":
            break
        import time

        time.sleep(0.02)
    assert consult.get(job["id"])["status"] == "quiet"
    assert consult.get(job["id"])["answer"] == ""


def test_unknown_runner_is_rejected():
    class _Settings:
        projects_dir = "/tmp"

    with pytest.raises(Exception):
        consult.submit(_Settings(), project="p", scrollback="x", runner="definitely-not-a-runner")


def test_answer_survives_a_message_list_response():
    """A CLI returning a message LIST rather than an object has burned this
    codebase before — the answer must not be lost to a shape change."""
    assert consult._answer_text('[{"type":"result","result":"use a worktree"}]') == "use a worktree"
    assert consult._answer_text('{"result":"check the logs"}') == "check the logs"
    assert consult._answer_text("plain text answer") == "plain text answer"
