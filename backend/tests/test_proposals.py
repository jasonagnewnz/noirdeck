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
        "VALUES ('skill','t','BODY',?, 'proposed',?)",
        (target, utcnow()),
    )
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


# --- universal undo -----------------------------------------------------------

from app.proposals import revert  # noqa: E402


def test_revert_restores_overwritten_content(conn, claude_dir):
    target = "skills/deploy-wazuh/SKILL.md"  # exists in fixture
    original = (claude_dir / target).read_text()
    pid = _insert(conn, target)
    approve(conn, claude_dir, pid, overwrite=True)
    assert (claude_dir / target).read_text() == "BODY"

    out = revert(conn, claude_dir, pid)
    assert out["outcome"] == "restored previous content"
    assert (claude_dir / target).read_text() == original
    assert list_proposals(conn, "reverted")[0]["id"] == pid


def test_revert_removes_created_file(conn, claude_dir):
    target = "skills/brand-new/SKILL.md"
    pid = _insert(conn, target)
    approve(conn, claude_dir, pid)
    assert (claude_dir / target).exists()
    out = revert(conn, claude_dir, pid)
    assert out["outcome"] == "removed the file this approval created"
    assert not (claude_dir / target).exists()


def test_revert_refuses_when_file_drifted(conn, claude_dir):
    target = "skills/drift/SKILL.md"
    pid = _insert(conn, target)
    approve(conn, claude_dir, pid)
    (claude_dir / target).write_text("hand-edited since apply")
    with pytest.raises(ProposalError, match="changed since"):
        revert(conn, claude_dir, pid)
    # explicit overwrite reverts anyway (file was created by us -> removed)
    revert(conn, claude_dir, pid, overwrite=True)
    assert not (claude_dir / target).exists()


def test_revert_guards(conn, claude_dir):
    # not approved
    pid = _insert(conn, "skills/x/SKILL.md")
    with pytest.raises(ProposalError, match="not approved"):
        revert(conn, claude_dir, pid)
    # no target
    pid2 = _insert(conn, None)
    conn.execute("UPDATE proposals SET status='approved', prior_existed=0 WHERE id=?", (pid2,))
    conn.commit()
    with pytest.raises(ProposalError, match="nothing to revert"):
        revert(conn, claude_dir, pid2)
    # double revert
    pid3 = _insert(conn, "skills/twice/SKILL.md")
    approve(conn, claude_dir, pid3)
    revert(conn, claude_dir, pid3)
    with pytest.raises(ProposalError):
        revert(conn, claude_dir, pid3)
    # pre-migration row (no snapshot) refuses rather than guessing
    pid4 = _insert(conn, "skills/old/SKILL.md")
    (claude_dir / "skills/old").mkdir(parents=True)
    (claude_dir / "skills/old/SKILL.md").write_text("BODY")
    conn.execute("UPDATE proposals SET status='approved', prior_existed=NULL WHERE id=?", (pid4,))
    conn.commit()
    with pytest.raises(ProposalError, match="predates undo"):
        revert(conn, claude_dir, pid4)
