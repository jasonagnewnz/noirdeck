import subprocess

from app.readers.commits import follow_on_flags, recent_commits


def _repo(tmp_path):
    repo = tmp_path / "r"
    repo.mkdir()
    for args in (["init", "-q"], ["config", "user.email", "t@t"], ["config", "user.name", "t"]):
        subprocess.run(["git", "-C", str(repo), *args], check=True)
    return repo


def _commit(repo, msg, *files):
    for name, content in files:
        p = repo / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", msg], check=True)


def test_recent_commits_and_follow_on(tmp_path):
    repo = _repo(tmp_path)
    _commit(repo, "add schema", ("migrations/001_init.py", "x"))
    _commit(repo, "WIP checkpoint", ("a.txt", "y"))
    _commit(repo, "change env contract", (".env.example", "K=v"))
    _commit(repo, "schema with tests", ("migrations/002.py", "x"), ("tests/test_m.py", "def test_a(): pass"))

    commits = recent_commits(repo)
    assert len(commits) == 4
    assert commits[0]["subject"] == "schema with tests"

    kinds = {(f["kind"], f["subject"]) for f in follow_on_flags(repo)}
    assert ("schema-no-tests", "add schema") in kinds
    assert ("wip-commit", "WIP checkpoint") in kinds
    assert ("env-contract", "change env contract") in kinds
    # schema WITH tests must not be flagged
    assert not any(k == "schema-no-tests" and s == "schema with tests" for k, s in kinds)
