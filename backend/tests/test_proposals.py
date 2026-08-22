import pytest

from noirdeck.db import connect, init_db, utcnow
from noirdeck.proposals import ProposalError, approve, dismiss, list_proposals


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


def test_approve_is_create_only_and_has_no_escape_hatch(conn, claude_dir):
    """The operator's rule: noirdeck adds files, it never modifies one it did not
    create: and approval is not a way around that."""
    target = "skills/deploy-wazuh/SKILL.md"  # exists in fixture
    original = (claude_dir / target).read_text()
    pid = _insert(conn, target)
    with pytest.raises(ProposalError, match="create-only"):
        approve(conn, claude_dir, pid)
    assert (claude_dir / target).read_text() == original, "existing file must be untouched"
    # there is no overwrite parameter to reach for
    import inspect

    assert "overwrite" not in inspect.signature(approve).parameters
    # and the proposal stays actionable (dismissible), not silently consumed
    assert list_proposals(conn, "proposed")[0]["id"] == pid


def test_double_decision_blocked(conn, claude_dir):
    pid = _insert(conn, None)
    dismiss(conn, pid)
    with pytest.raises(ProposalError):
        dismiss(conn, pid)
    assert list_proposals(conn, "dismissed")[0]["id"] == pid


# --- universal undo -----------------------------------------------------------

from noirdeck.proposals import revert  # noqa: E402


def test_revert_restores_legacy_overwritten_content(conn, claude_dir):
    """Rows approved BEFORE create-only landed can carry prior_existed=1. Undo
    must still restore those, or an old approval becomes unrevertable."""
    target = "skills/deploy-wazuh/SKILL.md"  # exists in fixture
    original = (claude_dir / target).read_text()
    pid = _insert(conn, target)
    # simulate a pre-create-only approval that replaced the file
    (claude_dir / target).write_text("BODY")
    conn.execute(
        "UPDATE proposals SET status='approved', prior_body=?, prior_existed=1 WHERE id=?",
        (original, pid),
    )

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
