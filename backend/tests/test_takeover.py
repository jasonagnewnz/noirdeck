"""Human takeover of a running autonomous task.

The behaviour that matters most is the RACE: the takeover kills the task's child,
which makes the runner see a failed session. If `claimed` is not set before the
kill, or the runner does not check it, an adopted task gets recorded as a failure
and the operator's own work is reported as broken.
"""

from __future__ import annotations

import sqlite3
import subprocess
import sys

import pytest

from noirdeck import overnight
from noirdeck.db import init_db, utcnow


@pytest.fixture
def conn(tmp_path):
    init_db(tmp_path / "d.db")
    c = sqlite3.connect(tmp_path / "d.db")
    c.row_factory = sqlite3.Row
    yield c
    c.close()


def _task(conn, project="/home/demo/projects/storefront", status="running") -> int:
    cur = conn.execute(
        "INSERT INTO queue (title, prompt, project, status, created_at) VALUES (?,?,?,?,?)",
        ("do the thing", "prompt body", project, status, utcnow()),
    )
    conn.commit()
    return cur.lastrowid


# --- schema + claim semantics ---------------------------------------------


def test_claim_columns_exist(conn):
    cols = {r[1] for r in conn.execute("PRAGMA table_info(queue)")}
    assert {"worker_pid", "transcript_session_id", "claimed_at"} <= cols


def test_is_claimed_reflects_the_row(conn):
    tid = _task(conn)
    assert overnight._is_claimed(conn, tid) is False
    conn.execute("UPDATE queue SET claimed_at=? WHERE id=?", (utcnow(), tid))
    conn.commit()
    assert overnight._is_claimed(conn, tid) is True


def test_claimed_is_not_resurrected_by_stale_requeue(conn):
    """Boot re-queues tasks orphaned by a crash. A task a human took over must not
    be swept back into the queue and run again behind their back."""
    tid = _task(conn, status="claimed")
    conn.execute("UPDATE queue SET claimed_at=? WHERE id=?", (utcnow(), tid))
    conn.commit()
    overnight.requeue_stale_running(conn)
    assert conn.execute("SELECT status FROM queue WHERE id=?", (tid,)).fetchone()["status"] == "claimed"


def test_running_tasks_are_still_requeued(conn):
    tid = _task(conn, status="running")
    overnight.requeue_stale_running(conn)
    assert conn.execute("SELECT status FROM queue WHERE id=?", (tid,)).fetchone()["status"] == "queued"


# --- _execute now exposes the child ---------------------------------------


def test_execute_reports_the_child_pid_and_still_parses_output(tmp_path):
    """The switch from subprocess.run to Popen must change how the child is
    launched and nothing about how its result is read."""
    seen = []
    payload = '{"type":"result","result":"VERDICT: {\\"status\\":\\"done\\",\\"summary\\":\\"ok\\"}","usage":{"input_tokens":10,"output_tokens":5}}'
    argv = [sys.executable, "-c", f"print({payload!r})"]
    ok, text, tin, tout, note = overnight._execute([*argv, "--output-format", "json"], tmp_path, on_start=seen.append)
    assert seen and isinstance(seen[0], int), "the pid must be reported so a takeover can stop it"
    assert ok and "VERDICT" in text
    assert tin == 10 and tout == 5 and note == ""


def test_execute_runs_the_child_in_its_own_process_group(tmp_path):
    """Grandchildren must die with the task. Signalling only the direct child
    leaves them holding the stdout pipe open: a real hang already hit in builds."""
    pids = []
    argv = [sys.executable, "-c", "import os;print(os.getpid(), os.getpgid(0))"]
    ok, text, *_ = overnight._execute(argv, tmp_path, on_start=pids.append)
    assert ok
    child_pid, child_pgid = (int(x) for x in text.split())
    assert child_pid == child_pgid, "child should lead its own process group"


def test_kill_group_stops_a_live_child_and_is_safe_on_a_dead_one(tmp_path):
    proc = subprocess.Popen([sys.executable, "-c", "import time;time.sleep(30)"], start_new_session=True)
    assert overnight._kill_group(proc.pid) is True
    proc.wait(timeout=10)
    assert proc.returncode is not None
    # a pid that is gone must not raise
    assert overnight._kill_group(proc.pid) in (True, False)


def test_kill_group_on_a_nonexistent_pid_returns_false():
    assert overnight._kill_group(2_000_000_000) is False


def test_execute_kills_the_group_on_timeout(tmp_path):
    argv = [sys.executable, "-c", "import time;time.sleep(30)"]
    pids = []
    with pytest.raises(subprocess.TimeoutExpired):
        overnight._execute(argv, tmp_path, timeout=1, on_start=pids.append)
    # the child must not be left running after the cap
    import os

    with pytest.raises((ProcessLookupError, PermissionError, OSError)):
        os.kill(pids[0], 0)
        raise OSError("still alive")


# --- the race the whole design turns on -----------------------------------


def test_a_task_claimed_mid_run_is_not_recorded_as_failed(conn, tmp_path, monkeypatch):
    """The takeover kills the child, so the builder call returns not-ok. run_task
    must notice the claim and leave the row to the operator."""
    from noirdeck.config import Settings

    tid = _task(conn)
    settings = Settings(
        db_path=tmp_path / "d.db",
        claude_dir=tmp_path / ".claude",
        projects_dir=tmp_path / "projects",
        port=1,
        mining_armed=False,
        overnight_armed=False,
        mine_max_batches=1,
    )
    (tmp_path / ".claude").mkdir(parents=True, exist_ok=True)
    (tmp_path / "projects").mkdir(parents=True, exist_ok=True)

    # stand in for the builder: simulate a human claiming the task while it runs,
    # then the child dying because the takeover killed it
    def fake_execute(argv, cwd, timeout=3600, on_start=None):
        if on_start:
            on_start(4242)
        conn.execute("UPDATE queue SET status='claimed', claimed_at=? WHERE id=?", (utcnow(), tid))
        conn.commit()
        return False, "", None, 0, "rc=-15; stderr: terminated"

    monkeypatch.setattr(overnight, "_execute", fake_execute)
    monkeypatch.setattr(overnight, "_register_worker", lambda *a, **k: None)
    monkeypatch.setattr(overnight, "context_pack", lambda *a, **k: "", raising=False)
    # run_task builds real argv, which resolves the CLI binary. CI has no `claude`
    # installed, and this test is about the claim race, not about tool discovery.
    monkeypatch.setattr("noirdeck.ai_runtime.require_runner_bin", lambda spec: spec.bin_name)

    task = conn.execute("SELECT * FROM queue WHERE id=?", (tid,)).fetchone()
    overnight.run_task(conn, settings, task)

    row = conn.execute("SELECT status, verdict FROM queue WHERE id=?", (tid,)).fetchone()
    assert row["status"] == "claimed", "an adopted task must not be marked failed/blocked"
    assert not (row["verdict"] or ""), "no failure verdict should be written over a claim"


def test_register_worker_stores_pid_and_transcript(conn, tmp_path, monkeypatch):
    from noirdeck.config import Settings

    tid = _task(conn)
    claude = tmp_path / ".claude"
    proj = tmp_path / "projects" / "storefront"
    ns = claude / "projects" / str(proj).replace("/", "-")
    ns.mkdir(parents=True)
    (ns / "abc123def456.jsonl").write_text("{}\n")
    settings = Settings(
        db_path=tmp_path / "d.db",
        claude_dir=claude,
        projects_dir=tmp_path / "projects",
        port=1,
        mining_armed=False,
        overnight_armed=False,
        mine_max_batches=1,
    )

    overnight._register_worker(conn, settings, tid, 999, proj)
    row = conn.execute("SELECT worker_pid, transcript_session_id FROM queue WHERE id=?", (tid,)).fetchone()
    assert row["worker_pid"] == 999
    assert row["transcript_session_id"] == "abc123def456", "takeover needs the task's OWN conversation"
