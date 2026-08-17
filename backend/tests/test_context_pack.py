import subprocess

import pytest

from noirdeck.config import Settings
from noirdeck.context_pack import PACK_CAP_CHARS, context_pack


@pytest.fixture
def settings(tmp_path, claude_dir):
    return Settings(
        claude_dir=claude_dir,
        projects_dir=tmp_path,
        db_path=tmp_path / "t.db",
        port=1,
        mining_armed=False,
        overnight_armed=False,
        mine_max_batches=1,
    )


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "myrepo"
    (r / "tests").mkdir(parents=True)
    (r / "tests" / "test_x.py").write_text("def test_x(): pass\n")
    (r / "README.md").write_text("# myrepo\nDoes a thing.\n")
    (r / "src.py").write_text("x = 1\n")

    def git(*a):
        subprocess.run(
            ["git", "-C", str(r), "-c", "user.name=t", "-c", "user.email=t@t", *a], check=True, capture_output=True
        )

    git("init", "-q", "-b", "main")
    git("add", "-A")
    git("commit", "-qm", "first commit of myrepo")
    return r


def test_pack_contains_the_facts_sessions_rediscover(settings, repo):
    pack = context_pack(repo, settings)
    assert "PROJECT CONTEXT PACK" in pack
    assert "README.md" in pack and "tests/" in pack  # layout
    assert "pytest" in pack  # test command detected
    assert "first commit of myrepo" in pack  # recent commits
    assert "Does a thing." in pack  # README head


def test_pack_reports_uncommitted_state(settings, repo):
    (repo / "src.py").write_text("x = 2\n")
    pack = context_pack(repo, settings)
    assert "Uncommitted right now" in pack and "src.py" in pack


def test_pack_is_hard_capped(settings, repo):
    (repo / "README.md").write_text("word " * 20000)
    pack = context_pack(repo, settings)
    assert len(pack) <= PACK_CAP_CHARS


def test_empty_target_costs_nothing(settings, tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    assert context_pack(empty, settings) == ""
    assert context_pack(tmp_path / "missing", settings) == ""
