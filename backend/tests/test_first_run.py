"""First run on a machine that has never seen Claude Code.

THE 2026-08-19 LAUNCH BLOCKER (B4). `Settings.load()` raised when `~/.claude`
was absent, so a brand-new install exited 1 instead of starting a product: for
ANY runner, while the website advertises Codex, "Ollama, fully local" and "bring
your own CLI", none of which need a Claude directory. The error also named
`doctor` as the remedy, and doctor can only diagnose.

The rule these tests pin: a missing workspace is never fatal, and it is never
silent either: "no skills and no memories" and "no workspace at all" must be
distinguishable, or the empty console reads as an empty estate.
"""

from __future__ import annotations

import os

import pytest

from noirdeck.config import Settings


@pytest.fixture
def virgin_home(tmp_path, monkeypatch):
    """A home directory with no .claude, and no env pointing elsewhere."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("NOIRDECK_CLAUDE_DIR", raising=False)
    monkeypatch.delenv("NOIRDECK_PROJECTS_DIR", raising=False)
    monkeypatch.setenv("NOIRDECK_DB_PATH", str(tmp_path / "d.db"))
    return tmp_path


def test_a_brand_new_install_starts(virgin_home):
    """The whole blocker in one assertion: this used to raise ConfigError."""
    s = Settings.load()
    assert s.claude_dir == virgin_home / ".claude"
    assert s.claude_dir_ready is True, "the default location should have been created"
    assert s.claude_dir.is_dir()


def test_an_empty_workspace_is_usable(virgin_home):
    """An empty directory is a working state, which is why absence need not be
    fatal: proven against the real readers, not asserted."""
    from noirdeck.readers.memories import list_memories
    from noirdeck.readers.skills import list_agents, list_skills

    s = Settings.load()
    assert list_skills(s.claude_dir) == []
    assert list_agents(s.claude_dir) == []
    assert list_memories(s.claude_dir) == []


def test_an_explicit_directory_is_never_fabricated(tmp_path, monkeypatch):
    """If someone names a directory and it is not there, that is probably a typo.
    Creating it would hide their mistake: so it is reported, not invented, and
    still not fatal."""
    missing = tmp_path / "somewhere" / "else"
    monkeypatch.setenv("NOIRDECK_CLAUDE_DIR", str(missing))
    monkeypatch.setenv("NOIRDECK_DB_PATH", str(tmp_path / "d.db"))

    s = Settings.load()  # must not raise
    assert s.claude_dir == missing
    assert not missing.exists(), "an explicitly-named directory must not be created"
    assert s.claude_dir_ready is False, "and the caller must be able to tell"


def test_missing_is_distinguishable_from_empty(virgin_home, tmp_path, monkeypatch):
    """The reason claude_dir_ready exists. Both states produce zero skills and
    zero memories; only this flag separates 'you have nothing yet' from 'I cannot
    see your workspace'."""
    empty = Settings.load()
    assert empty.claude_dir_ready is True

    monkeypatch.setenv("NOIRDECK_CLAUDE_DIR", str(tmp_path / "nope"))
    absent = Settings.load()
    assert absent.claude_dir_ready is False


def test_health_reports_readiness():
    """The UI cannot warn about something the API does not report."""
    from noirdeck.main import health

    body = health()
    assert "claude_dir_ready" in body


def test_doctor_does_not_fail_on_a_virgin_home(virgin_home, capsys):
    """doctor must warn, not FAIL: and must not tell the user to run doctor."""
    import argparse

    from noirdeck.cli import doctor

    rc = doctor(argparse.Namespace())
    out = capsys.readouterr().out
    assert rc == 0, f"a virgin home is not a broken install:\n{out}"
    assert "FAIL  config" not in out


def test_the_old_error_message_is_gone():
    """It pointed at `doctor`, which cannot fix it. If this string comes back,
    so has the dead-end instruction."""
    from pathlib import Path

    import noirdeck.config as cfg

    src = Path(cfg.__file__).read_text()
    assert "does not exist" not in src or 'raise ConfigError(f"NOIRDECK_CLAUDE_DIR does not exist' not in src


def test_env_isolation_holds(virgin_home):
    """Guards the fixture itself: if HOME leaked, these tests would be testing the
    developer's real workspace and would pass for the wrong reason."""
    assert os.environ["HOME"] == str(virgin_home)
    assert Settings.load().claude_dir.is_relative_to(virgin_home)
