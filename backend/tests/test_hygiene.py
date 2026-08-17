import sqlite3

import pytest

from noirdeck.db import init_db
from noirdeck.hygiene import propose_merge, report, scan_namespace


@pytest.fixture
def mem(claude_dir):
    d = claude_dir / "projects" / "-home-user" / "memory"
    # exact dupes (frontmatter differs, body identical after normalisation)
    (d / "dup_a.md").write_text("---\nname: dup_a\n---\nSame body here. Twice.\n")
    (d / "dup_b.md").write_text("---\nname: dup_b\n---\nSame   body here.\ntwice.\n")
    # near dupe pair
    base = "The wazuh manager needs analysisd restarted after every rule change. " * 5
    (d / "near_a.md").write_text(f"---\nname: near_a\n---\n{base}\n")
    (d / "near_b.md").write_text(f"---\nname: near_b\n---\n{base}Also check the logs.\n")
    # tiny + dangling link
    (d / "tiny.md").write_text("x\n")
    (d / "linker.md").write_text("---\nname: linker\n---\nSee [[does_not_exist]] and [[dup_a]].\n")
    return d


def test_scan_finds_dupes_tiny_and_dangling(mem):
    r = scan_namespace(mem)
    assert ["dup_a.md", "dup_b.md"] in r["exact_dupes"]
    assert any({p["a"], p["b"]} == {"near_a.md", "near_b.md"} for p in r["near_dupes"])
    assert any(t["file"] == "tiny.md" for t in r["tiny"])
    assert any(dl["file"] == "linker.md" and dl["links"] == ["does_not_exist"] for dl in r["dangling_links"])
    # dup_a resolves as a real link target — must NOT be dangling
    assert all("dup_a" not in dl["links"] for dl in r["dangling_links"])


def test_report_counts_and_namespace_list(mem, claude_dir):
    r = report(claude_dir)
    assert r["finding_count"] >= 3
    assert "-home-user" in r["available_namespaces"]


def test_report_rejects_namespace_traversal(claude_dir):
    for bad in ("..", ".", "../x", "a/b", "..\\x"):
        with pytest.raises(ValueError):
            report(claude_dir, bad)
    # empty string is not traversal — it falls back to the default namespace
    assert report(claude_dir, "")["namespace_report"] is not None


def test_propose_merge_creates_proposal_and_never_touches_sources(mem, claude_dir, tmp_path):
    db_path = tmp_path / "t.db"
    init_db(db_path)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    before = (mem / "dup_a.md").read_text()
    out = propose_merge(conn, claude_dir, "-home-user", ["dup_a.md", "dup_b.md"])
    row = conn.execute("SELECT * FROM proposals WHERE id=?", (out["proposal_id"],)).fetchone()
    assert row["kind"] == "memory_merge"
    assert row["target_path"].startswith("projects/-home-user/memory/")
    assert "from dup_a.md" in row["body"] and "from dup_b.md" in row["body"]
    assert (mem / "dup_a.md").read_text() == before  # sources untouched
    # guardrails
    with pytest.raises(ValueError):
        propose_merge(conn, claude_dir, "-home-user", ["dup_a.md"])
    with pytest.raises(ValueError):
        propose_merge(conn, claude_dir, "other-ns", ["dup_a.md", "dup_b.md"])
    with pytest.raises(ValueError):
        propose_merge(conn, claude_dir, "-home-user", ["../evil.md", "dup_a.md"])
