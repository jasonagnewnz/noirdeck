import subprocess

from noirdeck.overnight import route_agent, route_model
from noirdeck.qa import evaluate_project


def _git_repo(tmp_path):
    repo = tmp_path / "proj"
    repo.mkdir()
    subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "t@t"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "t"], check=True)
    return repo


def test_qa_flags_tracked_env_as_blocker(tmp_path):
    repo = _git_repo(tmp_path)
    (repo / ".env").write_text("SECRET=x")
    subprocess.run(["git", "-C", str(repo), "add", ".env"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "x"], check=True)
    result = evaluate_project(repo)
    assert result["overall"] == "BLOCKER"
    gate = next(g for g in result["gates"] if g["id"] == "env-tracked")
    assert gate["verdict"] == "BLOCKER"


def test_qa_passes_hygienic_repo(tmp_path):
    repo = _git_repo(tmp_path)
    (repo / ".gitignore").write_text(".env\n")
    (repo / "README.md").write_text("hi")
    (repo / "tests").mkdir()
    (repo / "tests" / "test_x.py").write_text("def test_a(): pass")
    (repo / "docs").mkdir()
    (repo / "docs" / "DEPLOYMENT.md").write_text("deploy + verify")
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "x"], check=True)
    result = evaluate_project(repo)
    assert result["overall"] != "BLOCKER"
    verdicts = {g["id"]: g["verdict"] for g in result["gates"]}
    assert verdicts["secret-shapes"] == "PASS"
    assert verdicts["tests"] == "PASS"
    # local-only branch is correctly a GAP (work-loss risk), not a pass
    assert verdicts["pushed"] == "GAP"


def test_model_routing_pins_explicit_ids():
    assert route_model("review the auth middleware for security") == "claude-opus-5"
    assert route_model("why does the sync fail — root cause the design") == "claude-fable-5"
    assert route_model("add a button to the settings page") == "claude-sonnet-5"


def test_agent_routing_matches_description(claude_dir):
    got = route_agent("verify backups restore correctly across the fleet", claude_dir)
    assert got == "backup-operator"
    assert route_agent("totally unrelated words qqq zzz", claude_dir) is None
