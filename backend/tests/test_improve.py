import subprocess

import pytest

from app import improve
from app.config import Settings
from app.db import connect, init_db

SRC = '''def add(a, b):
    return a + b

def sub(a, b):
    return a - b

def mul(a, b):
    return a * b
'''
WITH_DOCS = '''def add(a, b):
    """Return the sum of a and b."""
    return a + b

def sub(a, b):
    """Return a minus b."""
    return a - b

def mul(a, b):
    """Return the product of a and b."""
    return a * b
'''


@pytest.fixture
def env(tmp_path, monkeypatch, claude_dir):
    proj = tmp_path / "projects"
    repo = proj / "tidy-me"
    repo.mkdir(parents=True)
    subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True)
    (repo / "calc.py").write_text(SRC)
    subprocess.run(["git", "-C", str(repo), "-c", "user.email=t@t", "-c", "user.name=t",
                    "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(repo), "-c", "user.email=t@t", "-c", "user.name=t",
                    "commit", "-qm", "init"], check=True)
    monkeypatch.setenv("NOIRDECK_CLAUDE_DIR", str(claude_dir))
    monkeypatch.setenv("NOIRDECK_PROJECTS_DIR", str(proj))
    monkeypatch.setenv("NOIRDECK_DB_PATH", str(tmp_path / "i.db"))
    s = Settings.load()
    init_db(s.db_path)
    conn = connect(s.db_path)
    conn.execute("INSERT INTO improve_repos (project, enabled, created_at) "
                 "VALUES ('tidy-me', 1, '2026-01-01')")
    conn.commit()
    yield s, conn, repo
    conn.close()


def test_candidates_finds_docstring_gap(env):
    _, _, repo = env
    cands = improve.candidates(repo)
    assert cands and cands[0]["kind"] == "docstrings" and cands[0]["file"] == "calc.py"


def test_code_unchanged_guard():
    assert improve._code_unchanged("docstrings", SRC, WITH_DOCS)
    tampered = WITH_DOCS.replace("return a + b", "return a - b")
    assert not improve._code_unchanged("docstrings", SRC, tampered)
    assert not improve._code_unchanged("docstrings", SRC, "def broken(:")


def test_improve_one_proposes_on_branch_and_leaves_tree_alone(env, monkeypatch):
    s, conn, repo = env
    monkeypatch.setattr(improve, "_generate", lambda p: WITH_DOCS + "<<<END>>>")
    before = (repo / "calc.py").read_text()
    out = improve.improve_one(s, conn, "tidy-me")
    assert out and "proposed" in out, out
    assert (repo / "calc.py").read_text() == before  # real tree untouched
    branches = subprocess.run(["git", "-C", str(repo), "branch", "--list", "improve/*"],
                              capture_output=True, text=True).stdout
    assert "improve/" in branches
    row = conn.execute("SELECT * FROM improve_changes ORDER BY id DESC").fetchone()
    assert row["status"] == "proposed" and "docstring" in row["kind"]
    assert '"""' in row["diff"]


def test_improve_one_rejects_logic_change(env, monkeypatch):
    s, conn, repo = env
    evil = WITH_DOCS.replace("return a + b", "return a - b")
    monkeypatch.setattr(improve, "_generate", lambda p: evil + "<<<END>>>")
    out = improve.improve_one(s, conn, "tidy-me")
    assert out and out.get("skipped") and "rejected" in out["reason"]
    assert conn.execute("SELECT COUNT(*) c FROM improve_changes").fetchone()["c"] == 0
    branches = subprocess.run(["git", "-C", str(repo), "branch", "--list", "improve/*"],
                              capture_output=True, text=True).stdout
    assert branches.strip() == ""  # rejected branch cleaned up


def test_run_improver_fail_closed(env, monkeypatch):
    s, _, _ = env
    monkeypatch.delenv("NOIRDECK_IMPROVER_ARMED", raising=False)
    assert "fail-closed" in improve.run_improver(s)["reason"]
    monkeypatch.setenv("NOIRDECK_IMPROVER_ARMED", "true")
    monkeypatch.setattr(improve, "model_available", lambda: True)
    out = improve.run_improver(s)  # armed but NO contract → halted before any work
    assert out.get("halted") and "no arming contract" in out["halted"]


def test_decide_merge_and_discard(env, monkeypatch):
    s, conn, repo = env
    monkeypatch.setattr(improve, "_generate", lambda p: WITH_DOCS + "<<<END>>>")
    improve.improve_one(s, conn, "tidy-me")
    row = conn.execute("SELECT * FROM improve_changes ORDER BY id DESC").fetchone()
    out = improve.decide(s, conn, row["id"], "merge")
    assert out["status"] == "merged"
    assert '"""' in (repo / "calc.py").read_text()  # change landed via human act
    with pytest.raises(ValueError):
        improve.decide(s, conn, row["id"], "merge")  # already decided


def test_safe_repo_rejects_traversal(env, tmp_path):
    s, _, _ = env
    # make the escape target itself a git repo — mirrors ~ being a repo
    subprocess.run(["git", "-C", str(tmp_path), "init", "-q"], check=True)
    for bad in ("..", ".", "", "../x", "a/b", "..\\x"):
        assert improve.safe_repo(s, bad) is None
    assert improve.safe_repo(s, "tidy-me") is not None
