import pytest

from app.db import connect, init_db, utcnow
from app.proposals import ProposalError, approve, dismiss, list_proposals


@pytest.fixture
def conn(tmp_path):
    db = tmp_path / "t.db"
    init_db(db)
    c = connect(db)
    yield c
    c.close()


def _insert(conn, target):
    cur = conn.execute(
        "INSERT INTO proposals (kind,title,body,target_path,status,created_at) "
        "VALUES ('skill','t','BODY',?, 'proposed',?)", (target, utcnow()))
    conn.commit()
    return cur.lastrowid


def test_approve_writes_inside_allowlist(conn, claude_dir):
    pid = _insert(conn, "skills/newskill/SKILL.md")
    out = approve(conn, claude_dir, pid)
    assert (claude_dir / "skills" / "newskill" / "SKILL.md").read_text() == "BODY"
    assert out["written_to"].endswith("SKILL.md")


def test_approve_rejects_traversal_and_outside_roots(conn, claude_dir):
    for bad in ("skills/../settings.json", "agents/evil.md", "/etc/passwd"):
        pid = _insert(conn, bad)
        with pytest.raises(ProposalError):
            approve(conn, claude_dir, pid)


def test_approve_refuses_silent_overwrite(conn, claude_dir):
    pid = _insert(conn, "skills/deploy-wazuh/SKILL.md")  # exists in fixture
    with pytest.raises(ProposalError, match="exists"):
        approve(conn, claude_dir, pid)


def test_double_decision_blocked(conn, claude_dir):
    pid = _insert(conn, None)
    dismiss(conn, pid)
    with pytest.raises(ProposalError):
        dismiss(conn, pid)
    assert list_proposals(conn, "dismissed")[0]["id"] == pid
