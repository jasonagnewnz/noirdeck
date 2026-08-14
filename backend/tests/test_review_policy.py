import subprocess

import pytest

from app.review_policy import diff_since, head, review_needed


def test_small_clean_change_skips():
    needed, reason = review_needed(12, ["src/util.py"], "PASS", [])
    assert not needed and "deterministic rule" in reason


def test_substantial_change_reviews():
    needed, reason = review_needed(300, ["src/util.py"], "PASS", [])
    assert needed and "300 lines" in reason


def test_security_path_always_reviews_even_tiny():
    for f in ("app/auth.py", "backend/app/proposals.py", "lib/token_store.js",
              "ops/pipeline-guard.py", "app/arming.py"):
        needed, reason = review_needed(1, [f], "PASS", [])
        assert needed, f
        assert "security-flagged" in reason


def test_gate_blocker_reviews():
    needed, reason = review_needed(3, ["readme.md"], "BLOCKER", [])
    assert needed and "BLOCKER" in reason


def test_untracked_files_review_fail_safe():
    needed, reason = review_needed(0, [], "PASS", ["mystery.py"])
    assert needed and "untracked" in reason


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "r"
    r.mkdir()
    def git(*a):
        subprocess.run(["git", "-C", str(r), "-c", "user.name=t", "-c", "user.email=t@t", *a],
                       check=True, capture_output=True)
    git("init", "-q", "-b", "main")
    (r / "a.py").write_text("one\ntwo\n")
    git("add", "-A")
    git("commit", "-qm", "base")
    return r


def test_diff_since_counts_committed_and_working_changes(repo):
    baseline = head(repo)
    (repo / "a.py").write_text("one\ntwo\nthree\nfour\n")
    subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t",
                    "commit", "-aqm", "grow"], check=True, capture_output=True)
    (repo / "a.py").write_text("one\ntwo\nthree\nfour\nfive\n")  # uncommitted on top
    stats = diff_since(repo, baseline)
    assert stats["files"] == ["a.py"]
    assert stats["lines"] == 3  # both committed and working-tree additions counted
    assert stats["untracked"] == []


def test_diff_since_reports_untracked(repo):
    (repo / "new.py").write_text("x\n")
    stats = diff_since(repo, head(repo))
    assert stats["lines"] == 0
    assert stats["untracked"] == ["new.py"]


def test_unmeasurable_returns_none(tmp_path):
    assert diff_since(tmp_path, "deadbeef") is None
    assert head(tmp_path) is None
