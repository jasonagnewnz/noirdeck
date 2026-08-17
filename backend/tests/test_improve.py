import subprocess

import pytest

from noirdeck import improve
from noirdeck.config import Settings
from noirdeck.db import connect, init_db

SRC = """def add(a, b):
    return a + b

def sub(a, b):
    return a - b

def mul(a, b):
    return a * b
"""
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
    subprocess.run(["git", "-C", str(repo), "-c", "user.email=t@t", "-c", "user.name=t", "add", "-A"], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "init"], check=True
    )
    monkeypatch.setenv("NOIRDECK_CLAUDE_DIR", str(claude_dir))
    monkeypatch.setenv("NOIRDECK_PROJECTS_DIR", str(proj))
    monkeypatch.setenv("NOIRDECK_DB_PATH", str(tmp_path / "i.db"))
    s = Settings.load()
    init_db(s.db_path)
    conn = connect(s.db_path)
    conn.execute("INSERT INTO improve_repos (project, enabled, created_at) VALUES ('tidy-me', 1, '2026-01-01')")
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
    monkeypatch.setattr(improve, "_generate", lambda p, m: (WITH_DOCS + "<<<END>>>", None))
    before = (repo / "calc.py").read_text()
    out = improve.improve_one(s, conn, "tidy-me")
    assert out and "proposed" in out, out
    assert (repo / "calc.py").read_text() == before  # real tree untouched
    branches = subprocess.run(
        ["git", "-C", str(repo), "branch", "--list", "improve/*"], capture_output=True, text=True
    ).stdout
    assert "improve/" in branches
    row = conn.execute("SELECT * FROM improve_changes ORDER BY id DESC").fetchone()
    assert row["status"] == "proposed" and "docstring" in row["kind"]
    assert '"""' in row["diff"]


def test_improve_one_rejects_logic_change(env, monkeypatch):
    s, conn, repo = env
    evil = WITH_DOCS.replace("return a + b", "return a - b")
    monkeypatch.setattr(improve, "_generate", lambda p, m: (evil + "<<<END>>>", None))
    out = improve.improve_one(s, conn, "tidy-me")
    assert out and out.get("skipped") and "rejected" in out["reason"]
    assert conn.execute("SELECT COUNT(*) c FROM improve_changes").fetchone()["c"] == 0
    branches = subprocess.run(
        ["git", "-C", str(repo), "branch", "--list", "improve/*"], capture_output=True, text=True
    ).stdout
    assert branches.strip() == ""  # rejected branch cleaned up


def test_run_improver_fail_closed(env, monkeypatch):
    s, _, _ = env
    monkeypatch.delenv("NOIRDECK_IMPROVER_ARMED", raising=False)
    assert "fail-closed" in improve.run_improver(s)["reason"]
    monkeypatch.setenv("NOIRDECK_IMPROVER_ARMED", "true")
    monkeypatch.setattr(improve, "available_models", lambda: ["qwen2.5-coder:7b"])
    out = improve.run_improver(s)  # armed but NO contract → halted before any work
    assert out.get("halted") and "no arming contract" in out["halted"]


def test_per_repo_model_reaches_generate_and_change_row(env, monkeypatch):
    s, conn, repo = env
    seen = []

    def fake_gen(prompt, model):
        seen.append(model)
        return WITH_DOCS + "<<<END>>>", None

    monkeypatch.setattr(improve, "_generate", fake_gen)
    out = improve.improve_one(s, conn, "tidy-me", model="muse-glimmer:30b")
    assert out and "proposed" in out
    assert seen == ["muse-glimmer:30b"]
    row = conn.execute("SELECT model FROM improve_changes ORDER BY id DESC").fetchone()
    assert row["model"] == "muse-glimmer:30b"


def test_run_improver_skips_unpulled_repo_model(env, monkeypatch):
    s, conn, _ = env
    conn.execute("UPDATE improve_repos SET model='muse-glimmer:30b' WHERE project='tidy-me'")
    conn.commit()
    monkeypatch.setenv("NOIRDECK_IMPROVER_ARMED", "true")
    monkeypatch.setattr(improve, "available_models", lambda: ["qwen2.5-coder:7b"])
    from noirdeck.arming import arm

    arm(conn, "improver", hours=1, max_tasks=5)
    out = improve.run_improver(s)
    assert out["proposed"] == 0 and out["skipped"] == 1
    detail = conn.execute("SELECT detail FROM audit_log WHERE action='change_skipped' ORDER BY id DESC").fetchone()[
        "detail"
    ]
    assert "not pulled locally" in detail


def test_decide_merge_and_discard(env, monkeypatch):
    s, conn, repo = env
    monkeypatch.setattr(improve, "_generate", lambda p, m: (WITH_DOCS + "<<<END>>>", None))
    improve.improve_one(s, conn, "tidy-me")
    row = conn.execute("SELECT * FROM improve_changes ORDER BY id DESC").fetchone()
    out = improve.decide(s, conn, row["id"], "merge")
    assert out["status"] == "merged"
    assert '"""' in (repo / "calc.py").read_text()  # change landed via human act
    with pytest.raises(ValueError):
        improve.decide(s, conn, row["id"], "merge")  # already decided


def test_generate_failure_reason_reaches_the_skip(env, monkeypatch):
    s, conn, _ = env
    monkeypatch.setattr(improve, "_generate", lambda p, m: (None, "muse-glimmer:30b timed out after 1800s"))
    out = improve.improve_one(s, conn, "tidy-me")
    assert out["skipped"] and "timed out" in out["reason"]


def test_worktree_add_failure_is_an_audited_skip_not_none(env, monkeypatch):
    s, conn, repo = env
    monkeypatch.setattr(improve, "_generate", lambda p, m: (WITH_DOCS + "<<<END>>>", None))
    # pre-create the branch the run would use, so worktree add fails
    cand = improve.candidates(repo)[0]
    branch = f"improve/{improve.utcnow()[:10]}-{cand['kind']}-{cand['file']}"
    subprocess.run(["git", "-C", str(repo), "branch", branch], check=True)
    out = improve.improve_one(s, conn, "tidy-me")
    assert out and out.get("skipped") and "worktree add failed" in out["reason"]


def _seed_decision(conn, branch, kind, status, project="tidy-me", model="m"):
    conn.execute(
        "INSERT INTO improve_changes (project,branch,kind,target_file,summary,diff,"
        "tests,model,status,created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (project, branch, kind, "calc.py", "", "", "", model, status, "2026-01-01"),
    )


def test_decision_learning_mutes_reranks_and_unmutes(env):
    s, conn, repo = env
    for i in range(3):
        _seed_decision(conn, f"b{i}", "docstrings", "discarded")
    conn.commit()
    stats = improve.decision_stats(conn)
    assert "tidy-me/docstrings" in stats["muted"]
    cands, muted = improve._apply_decisions(stats, "tidy-me", improve.candidates(repo))
    assert muted == ["docstrings"] and cands == []
    out = improve.improve_one(s, conn, "tidy-me")
    assert out["skipped"] and "muted" in out["reason"]
    # merging one of that kind un-mutes it
    conn.execute("UPDATE improve_changes SET status='merged' WHERE branch='b0'")
    conn.commit()
    assert improve.decision_stats(conn)["muted"] == []


def test_decision_learning_weights_prefer_merged_kinds():
    stats = {
        "kinds": {"docstrings": {"merged": 0, "discarded": 4}, "comment_tidy": {"merged": 4, "discarded": 0}},
        "repo_kinds": {},
        "models": {},
        "muted": [],
    }
    cands = [
        {"kind": "docstrings", "file": "a.py", "score": 5, "why": ""},
        {"kind": "comment_tidy", "file": "a.py", "score": 5, "why": ""},
    ]
    ranked, muted = improve._apply_decisions(stats, "any", cands)
    assert muted == []
    assert ranked[0]["kind"] == "comment_tidy"  # merged history outranks discarded
    assert ranked[0]["weight"] > 1 > ranked[1]["weight"]


def test_safe_repo_rejects_traversal(env, tmp_path):
    s, _, _ = env
    # make the escape target itself a git repo — mirrors ~ being a repo
    subprocess.run(["git", "-C", str(tmp_path), "init", "-q"], check=True)
    for bad in ("..", ".", "", "../x", "a/b", "..\\x"):
        assert improve.safe_repo(s, bad) is None
    assert improve.safe_repo(s, "tidy-me") is not None


SKILL_MD = "---\nname: deploy-wazuh\ndescription: Deploy wazuh agents fleet-wide.\nmodel: opus\n---\n\n# body\n"


def test_safe_asset_respects_write_allowlist(env):
    s, _, _ = env
    assert improve.safe_asset(s.claude_dir, "skills/deploy-wazuh/SKILL.md") is not None
    assert improve.safe_asset(s.claude_dir, "projects/-home-user/memory/misc_note.md") is not None
    # agents are OUTSIDE the proposals allowlist — never addable
    assert improve.safe_asset(s.claude_dir, "agents/backup-operator.md") is None
    assert improve.safe_asset(s.claude_dir, "../outside.md") is None
    assert improve.safe_asset(s.claude_dir, "skills/../agents/backup-operator.md") is None


def test_asset_guards():
    orig = "---\nname: x\n---\n\nSee [[other-note]].\nSome long prose here to tidy.\n"
    assert improve._asset_ok("memory", orig, orig.replace("prose", "text")) is None
    assert "frontmatter" in improve._asset_ok("memory", orig, orig.replace("name: x", "name: y"))
    assert "links" in improve._asset_ok("memory", orig, orig.replace("[[other-note]]", "other note"))
    big = orig + "z" * (len(orig) + 300)
    assert "grew" in improve._asset_ok("memory", orig, big)
    # skills are allowed to grow (refining a draft adds structure) — same
    # addition that fails a memory tidy passes for a skill under its cap
    assert improve._asset_ok("skill", orig, orig + "z" * 100) is None


def test_improve_asset_one_proposes_via_spine_and_dedups(env, monkeypatch):
    s, conn, _ = env
    tidy = SKILL_MD.replace("# body", "# Deploy Wazuh\n\nRun the rollout.")
    monkeypatch.setattr(improve, "_generate", lambda p, m: (tidy + "<<<END>>>", None))
    conn.execute(
        "INSERT INTO improve_targets (kind, target_path, created_at) "
        "VALUES ('skill', 'skills/deploy-wazuh/SKILL.md', '2026-01-01')"
    )
    conn.commit()
    target = dict(conn.execute("SELECT * FROM improve_targets").fetchone())
    out = improve.improve_asset_one(s, conn, target)
    assert out and "proposed" in out, out
    prop = conn.execute("SELECT * FROM proposals ORDER BY id DESC").fetchone()
    assert prop["kind"] == "improve_skill" and prop["status"] == "proposed"
    assert prop["diff"] and "+# Deploy Wazuh" in prop["diff"]
    # the file itself is untouched until approval
    assert (s.claude_dir / "skills/deploy-wazuh/SKILL.md").read_text() == SKILL_MD
    # a pending proposal blocks a duplicate
    out2 = improve.improve_asset_one(s, conn, target)
    assert out2["skipped"] and "already pending" in out2["reason"]
    # approval (with overwrite — target exists) writes through the spine
    from noirdeck.proposals import approve

    approve(conn, s.claude_dir, prop["id"], overwrite=True)
    assert "Run the rollout." in (s.claude_dir / "skills/deploy-wazuh/SKILL.md").read_text()


def test_run_improver_only_touches_armed_targets(env, monkeypatch):
    s, conn, _ = env
    calls = []
    monkeypatch.setattr(improve, "_generate", lambda p, m: (calls.append(1), (None, "noop"))[1])
    monkeypatch.setenv("NOIRDECK_IMPROVER_ARMED", "true")
    monkeypatch.setattr(improve, "available_models", lambda: ["qwen2.5-coder:7b"])
    conn.execute("UPDATE improve_repos SET enabled=0")  # isolate: targets only
    conn.execute(
        "INSERT INTO improve_targets (kind, target_path, created_at) VALUES "
        "('skill', 'skills/deploy-wazuh/SKILL.md', '2026-01-01')"
    )  # DISARMED
    conn.execute(
        "INSERT INTO improve_targets (kind, target_path, armed_until, created_at) "
        "VALUES ('memory', 'projects/-home-user/memory/misc_note.md', "
        "'2099-01-01T00:00:00+00:00', '2026-01-01')"
    )  # armed
    conn.commit()
    from noirdeck.arming import arm

    arm(conn, "improver", hours=1, max_tasks=5)
    out = improve.run_improver(s)
    assert len(calls) == 1  # only the ARMED target generated
    assert out["skipped"] == 1  # its noop skip was audited, disarmed one untouched
