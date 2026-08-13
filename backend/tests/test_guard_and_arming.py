import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from app.arming import ArmingError, arm, check, consume, revoke, status
from app.db import init_db
from app.guard import GUARD_SCRIPT, guard_settings_args

REPO = Path(__file__).resolve().parents[2]


def _guard(payload) -> subprocess.CompletedProcess:
    raw = payload if isinstance(payload, str) else json.dumps(payload)
    return subprocess.run([sys.executable, str(GUARD_SCRIPT)], input=raw,
                          capture_output=True, text=True, timeout=10)


def _bash(cmd: str):
    return {"tool_name": "Bash", "tool_input": {"command": cmd}}


DENIED = [
    "git push origin main",
    "git -C /x commit -m ok && git push",
    "gh pr create --title x",
    "gh release create v1",
    "npm publish",
    "docker push registry/img",
    "flyctl deploy",
    "wrangler deploy",
    "kubectl apply -f x.yml",
    "terraform apply",
    "ssh root@server 'ls'",
    "rsync -a dist/ user@host:/var/www",
    "systemctl restart nginx",
    "systemctl --user restart noirdeck",
    "pkill -f uvicorn",
]
ALLOWED = [
    "git commit -m 'work'",
    "git status && git log --oneline",
    "npm run build",
    "python -m pytest -q",
    "curl -s http://127.0.0.1:8000/health",
    "systemctl --user status noirdeck",
    "grep -r 'push' src/",   # word inside other text, not a git push
]


def test_guard_denies_outward_mutation():
    for cmd in DENIED:
        p = _guard(_bash(cmd))
        assert p.returncode == 2, f"should deny: {cmd}"
        assert "pipeline-guard DENIED" in p.stderr


def test_guard_allows_normal_work():
    for cmd in ALLOWED:
        p = _guard(_bash(cmd))
        assert p.returncode == 0, f"should allow: {cmd} ({p.stderr})"


def test_guard_ignores_other_tools_and_fails_closed_on_garbage():
    assert _guard({"tool_name": "Read", "tool_input": {"file_path": "/x"}}).returncode == 0
    p = _guard("not json at all")
    assert p.returncode == 2 and "fail-closed" in p.stderr


def test_guard_settings_args_wire():
    args = guard_settings_args()
    assert args[0] == "--settings"
    cfg = json.loads(args[1])
    hook = cfg["hooks"]["PreToolUse"][0]
    assert hook["matcher"] == "Bash"
    assert str(GUARD_SCRIPT) in hook["hooks"][0]["command"]


@pytest.fixture
def conn(tmp_path):
    db = tmp_path / "a.db"
    init_db(db)
    c = sqlite3.connect(db)
    c.row_factory = sqlite3.Row
    yield c
    c.close()


def test_contract_lifecycle(conn):
    ok, reason = check(conn, "overnight")
    assert not ok and "no arming contract" in reason
    arm(conn, "overnight", hours=1, max_tasks=2, max_tokens=50_000)
    assert check(conn, "overnight")[0]
    consume(conn, "overnight", tasks=1, tokens=10_000)
    assert check(conn, "overnight")[0]
    consume(conn, "overnight", tasks=1, tokens=10_000)
    ok, reason = check(conn, "overnight")
    assert not ok and "budget exhausted" in reason
    # re-arming replaces the spent contract
    arm(conn, "overnight", hours=1)
    assert check(conn, "overnight")[0]
    assert revoke(conn, "overnight") is True
    assert not check(conn, "overnight")[0]


def test_contract_expiry_and_token_cap(conn):
    arm(conn, "mining", hours=1, max_tokens=5000)
    consume(conn, "mining", tasks=1, tokens=6000)
    ok, reason = check(conn, "mining")
    assert not ok and "budget exhausted" in reason
    arm(conn, "mining", hours=1)
    conn.execute("UPDATE arm_contracts SET armed_until='2020-01-01T00:00:00+00:00' "
                 "WHERE revoked_at IS NULL AND subsystem='mining'")
    conn.commit()
    ok, reason = check(conn, "mining")
    assert not ok and "expired" in reason
    st = status(conn)
    assert st["mining"]["live"] is False


def test_arm_validation(conn):
    with pytest.raises(ArmingError):
        arm(conn, "warp-drive", hours=1)
    with pytest.raises(ArmingError):
        arm(conn, "overnight", hours=0)
    with pytest.raises(ArmingError):
        arm(conn, "overnight", hours=9999)
    with pytest.raises(ArmingError):
        arm(conn, "overnight", hours=1, max_tasks=0)


def test_run_queue_halts_without_contract(tmp_path, monkeypatch, claude_dir):
    from app import overnight
    from app.config import Settings
    db = tmp_path / "q.db"
    init_db(db)
    c = sqlite3.connect(db)
    c.execute("INSERT INTO queue (project,title,prompt,status,created_at) "
              "VALUES ('/x','t','p','queued','2026-01-01')")
    c.commit(); c.close()
    settings = Settings(claude_dir=claude_dir, projects_dir=tmp_path, db_path=db,
                        port=1, mining_armed=False, overnight_armed=True, mine_max_batches=1)
    ran = []
    monkeypatch.setattr(overnight, "run_task", lambda *a, **k: ran.append(1))
    out = overnight.run_queue(settings, 0.01, once=True)
    assert out.get("halted") and "no arming contract" in out["halted"]
    assert not ran  # contract gate fired BEFORE any task ran
