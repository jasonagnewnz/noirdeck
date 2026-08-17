"""The staged (heavy) queue path: plan → do → conditional check, with fallback.
The _execute seam is monkeypatched — no real claude sessions run here."""

import subprocess

import pytest

from noirdeck import overnight
from noirdeck.config import Settings
from noirdeck.db import connect, init_db, utcnow
from noirdeck.overnight import route_weight

# --- weight routing -----------------------------------------------------------


def test_route_weight_heuristics():
    assert route_weight("tidy the README", "fix a typo in the readme") == "light"
    assert route_weight("Redesign the sync", "architect a new approach") == "heavy"
    assert route_weight("Migrate config", "move to pydantic settings") == "heavy"
    assert route_weight("small task", "x" * 1000) == "heavy"  # long brief = heavy
    assert route_weight("add retry", "wrap the fetch in a retry loop") == "light"


# --- staged execution ---------------------------------------------------------


@pytest.fixture
def env(tmp_path, claude_dir, monkeypatch):
    proj = tmp_path / "proj"
    proj.mkdir()

    def git(*a):
        subprocess.run(
            ["git", "-C", str(proj), "-c", "user.name=t", "-c", "user.email=t@t", *a], check=True, capture_output=True
        )

    git("init", "-q", "-b", "main")
    (proj / "app.py").write_text("x = 1\n")
    git("add", "-A")
    git("commit", "-qm", "base")

    db = tmp_path / "q.db"
    init_db(db)
    conn = connect(db)
    settings = Settings(
        claude_dir=claude_dir,
        projects_dir=tmp_path,
        db_path=db,
        port=1,
        mining_armed=False,
        overnight_armed=True,
        mine_max_batches=1,
    )
    monkeypatch.setattr("noirdeck.ai_runtime.require_runner_bin", lambda spec: spec.bin_name)
    yield conn, settings, proj
    conn.close()


def _queue(conn, proj, weight=None):
    cur = conn.execute(
        "INSERT INTO queue (project,title,prompt,weight,status,created_at) VALUES (?,?,?,?,'queued',?)",
        (str(proj), "task", "do the thing", weight, utcnow()),
    )
    conn.commit()
    return conn.execute("SELECT * FROM queue WHERE id=?", (cur.lastrowid,)).fetchone()


def _row(conn, tid):
    return conn.execute("SELECT * FROM queue WHERE id=?", (tid,)).fetchone()


def test_heavy_runs_plan_then_do_and_skips_clean_small_check(env, monkeypatch):
    conn, settings, proj = env
    calls = []

    def fake_execute(argv, cwd, timeout=3600):
        calls.append(argv)
        if len(calls) == 1:  # plan
            return True, "GOAL: do the thing\nSTEPS: 1. edit app.py", None, 111, ""
        return True, 'VERDICT: {"status":"done","summary":"did it"}', 5, 222, ""

    monkeypatch.setattr(overnight, "_execute", fake_execute)
    task = _queue(conn, proj, weight="heavy")
    overnight.run_task(conn, settings, task)

    assert len(calls) == 2  # plan + do; check skipped (no change on disk)
    plan_argv, do_argv = calls
    assert "--tools" in plan_argv and plan_argv[plan_argv.index("--tools") + 1 :] == ["Read", "Grep", "Glob"]
    assert overnight._model("think") in plan_argv
    do_prompt = do_argv[2]
    assert "EXECUTION BRIEF" in do_prompt and "GOAL: do the thing" in do_prompt
    assert "PROJECT CONTEXT PACK" in do_prompt  # harness research injected

    row = _row(conn, task["id"])
    assert row["status"] == "done"
    assert row["weight"] == "heavy"
    assert row["tokens_out"] == 333  # summed across stages
    assert "check skipped" in row["verdict"]


def test_heavy_check_runs_on_substantial_change_and_can_block(env, monkeypatch):
    conn, settings, proj = env
    calls = []

    def fake_execute(argv, cwd, timeout=3600):
        calls.append(argv)
        if len(calls) == 1:
            return True, "the brief", None, 10, ""
        if len(calls) == 2:  # do: makes a real 60-line committed change
            (proj / "big.py").write_text("line\n" * 60)
            subprocess.run(
                ["git", "-C", str(proj), "-c", "user.name=t", "-c", "user.email=t@t", "add", "-A"],
                check=True,
                capture_output=True,
            )
            subprocess.run(
                ["git", "-C", str(proj), "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "big"],
                check=True,
                capture_output=True,
            )
            return True, 'VERDICT: {"status":"done","summary":"built big"}', 5, 20, ""
        return (
            True,
            ('VERDICT: {"status":"blocked","summary":"found a real bug","question":"fix the off-by-one?"}'),
            None,
            30,
            "",
        )

    monkeypatch.setattr(overnight, "_execute", fake_execute)
    task = _queue(conn, proj, weight="heavy")
    overnight.run_task(conn, settings, task)

    assert len(calls) == 3
    assert overnight._model("review") in calls[2]
    row = _row(conn, task["id"])
    assert row["status"] == "blocked"
    assert "found a real bug" in row["verdict"]
    assert "fix the off-by-one" in row["question"]
    assert row["tokens_out"] == 60


def test_heavy_plan_failure_falls_back_to_single_session(env, monkeypatch):
    conn, settings, proj = env
    calls = []

    def fake_execute(argv, cwd, timeout=3600):
        calls.append(argv)
        if len(calls) == 1:
            return False, "", None, 0, "rc=1; stderr: boom"
        return True, 'VERDICT: {"status":"done","summary":"did it anyway"}', None, 40, ""

    monkeypatch.setattr(overnight, "_execute", fake_execute)
    task = _queue(conn, proj, weight="heavy")
    overnight.run_task(conn, settings, task)

    assert len(calls) == 2  # plan attempt + do; NO check (fell back to light)
    row = _row(conn, task["id"])
    assert row["status"] == "done"
    assert "fell back to single-session" in row["verdict"]


def test_light_stays_single_session(env, monkeypatch):
    conn, settings, proj = env
    calls = []

    def fake_execute(argv, cwd, timeout=3600):
        calls.append(argv)
        return True, 'VERDICT: {"status":"done","summary":"ok"}', 1, 50, ""

    monkeypatch.setattr(overnight, "_execute", fake_execute)
    task = _queue(conn, proj)  # weight NULL -> auto -> light for this tiny prompt
    overnight.run_task(conn, settings, task)

    assert len(calls) == 1
    assert "--permission-mode" in calls[0]
    row = _row(conn, task["id"])
    assert row["weight"] == "light" and row["status"] == "done"
