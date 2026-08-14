import json
import time

import pytest

from app.builds import PHASES, BuildRunner
from app.config import Settings
from app.db import connect, init_db


@pytest.fixture
def settings(tmp_path, monkeypatch, claude_dir):
    proj = tmp_path / "projects"
    proj.mkdir()
    monkeypatch.setenv("NOIRDECK_CLAUDE_DIR", str(claude_dir))
    monkeypatch.setenv("NOIRDECK_PROJECTS_DIR", str(proj))
    monkeypatch.setenv("NOIRDECK_DB_PATH", str(tmp_path / "b.db"))
    s = Settings.load()
    init_db(s.db_path)
    return s


def _wait_status(db_path, build_id, want, timeout=30):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        conn = connect(db_path)
        row = conn.execute("SELECT * FROM builds WHERE id=?", (build_id,)).fetchone()
        conn.close()
        if row["status"] in want:
            return row
        time.sleep(0.2)
    raise AssertionError(f"build never reached {want}, last={row['status']}")


def test_pipeline_runs_all_phases_and_finishes(settings):
    # stub claude: every phase touches a file, commits nothing, reports done
    stub = ["bash", "-c",
            'echo "phase ran" >> phases.log; '
            'echo \'VERDICT: {"status":"done","summary":"phase ok"}\'; true; #']
    runner = BuildRunner(settings, claude_argv_base=stub)
    build_id = runner.start("myapp", "Build a tiny thing that does a thing properly with tests.")
    row = _wait_status(settings.db_path, build_id, {"done", "attention", "blocked"})
    assert row["status"] in ("done", "attention")  # attention = QA gaps in a stub repo, fine
    log = json.loads(row["log"])
    assert [e["phase"] for e in log] == [p[0] for p in PHASES]
    assert all(e["status"] == "done" for e in log)
    assert (settings.projects_dir / "myapp" / "phases.log").read_text().count("phase ran") == len(PHASES)


def test_pipeline_blocks_on_blocked_verdict(settings):
    stub = ["bash", "-c",
            'echo \'VERDICT: {"status":"blocked","summary":"cannot proceed","question":"what colour?"}\'; #']
    runner = BuildRunner(settings, claude_argv_base=stub)
    build_id = runner.start("stuck", "A build that immediately gets stuck on a decision, sadly.")
    row = _wait_status(settings.db_path, build_id, {"blocked"})
    assert row["question"] == "what colour?"
    assert json.loads(row["log"])[0]["phase"] == "plan"  # stopped in phase 1


def test_pipeline_blocks_on_garbage_output(settings):
    stub = ["bash", "-c", 'echo "no verdict line here"; #']
    runner = BuildRunner(settings, claude_argv_base=stub)
    build_id = runner.start("garbled", "A build whose phases produce no structured verdict at all.")
    row = _wait_status(settings.db_path, build_id, {"blocked"})
    assert "verdict" in row["question"].lower() or "review" in row["question"].lower()


def test_resume_continues_from_last_done_phase(settings):
    stub = ["bash", "-c",
            'echo "phase ran" >> phases.log; '
            'echo \'VERDICT: {"status":"done","summary":"phase ok"}\'; true; #']
    runner = BuildRunner(settings, claude_argv_base=stub)
    build_id = runner.start("resumer", "A build that crashes midway and is resumed by the operator.")
    _wait_status(settings.db_path, build_id, {"done", "attention"})

    # simulate a crash-parked build with only the first two phases recorded
    conn = connect(settings.db_path)
    log2 = json.dumps([{"phase": "plan", "status": "done", "summary": "p1"},
                       {"phase": "build", "status": "done", "summary": "p2"}])
    conn.execute("UPDATE builds SET status='blocked', question='crash', log=? WHERE id=?",
                 (log2, build_id))
    conn.commit()
    conn.close()
    (settings.projects_dir / "resumer" / "phases.log").write_text("")  # reset counter

    runner.resume(build_id)
    row = _wait_status(settings.db_path, build_id, {"done", "attention"})
    # only the 3 remaining phases ran
    assert (settings.projects_dir / "resumer" / "phases.log").read_text().count("phase ran") == 3
    assert [e["phase"] for e in json.loads(row["log"])] == \
        ["plan", "build", "test", "review", "finish"]
    assert row["question"] is None

    import pytest as _pytest
    with _pytest.raises(ValueError, match="not resumable"):
        runner.resume(build_id)  # done builds don't resume


def test_parse_cli_json_handles_both_shapes():
    from app.overnight import parse_cli_json
    legacy = json.dumps({"result": "VERDICT: ok", "usage": {"input_tokens": 5, "output_tokens": 9}})
    assert parse_cli_json(legacy) == ("VERDICT: ok", 5, 9)
    modern = json.dumps([
        {"type": "system"}, {"type": "assistant"},
        {"type": "result", "result": "VERDICT: ok", "usage": {"input_tokens": 7, "output_tokens": 3}},
    ])
    assert parse_cli_json(modern) == ("VERDICT: ok", 7, 3)
    assert parse_cli_json("[]") == ("", None, None)


def test_requeue_stale_marks_running_blocked(settings):
    conn = connect(settings.db_path)
    conn.execute("INSERT INTO builds (name,path,prompt,status,created_at) "
                 "VALUES ('zomb','/x','p','running','2026-01-01')")
    conn.commit()
    conn.close()
    BuildRunner(settings).requeue_stale()
    conn = connect(settings.db_path)
    row = conn.execute("SELECT * FROM builds WHERE name='zomb'").fetchone()
    conn.close()
    assert row["status"] == "blocked"
    assert "restarted" in row["question"]


def test_review_skipped_for_small_clean_change(settings):
    """Phases commit tiny changes -> by review time the measured change is small,
    tracked, and un-flagged: the deterministic policy skips the paid review pass."""
    stub = ["bash", "-c",
            'echo line >> notes.txt; git add -A; '
            'git -c user.name=t -c user.email=t@t commit -qm p; '
            'echo \'VERDICT: {"status":"done","summary":"phase ok"}\'; true; #']
    runner = BuildRunner(settings, claude_argv_base=stub)
    build_id = runner.start("tinyfix", "A very small change to one harmless file, nothing more.")
    row = _wait_status(settings.db_path, build_id, {"done", "attention", "blocked"})
    log = json.loads(row["log"])
    review = next(e for e in log if e["phase"] == "review")
    assert review["status"] == "done"
    assert review["tokens"] == 0
    assert "review skipped" in review["summary"]
    # the stub really did not run for the review phase: 5 phases, 4 executions
    assert (settings.projects_dir / "tinyfix" / "notes.txt").read_text().count("line") == 4
    # and the later finish phase still ran after the skip
    assert [e["phase"] for e in log][-1] == "finish"
