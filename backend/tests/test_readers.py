from noirdeck.readers.history import (
    group_hits,
    history_stats,
    load_history,
    repeated_prompts,
    search_grouped,
    search_history,
)
from noirdeck.readers.memories import list_memories, memory_stats
from noirdeck.readers.sessions import recent_sessions
from noirdeck.readers.skills import list_agents, list_skills


def test_skills_and_agents(claude_dir):
    skills = list_skills(claude_dir)
    assert len(skills) == 1
    assert skills[0]["name"] == "deploy-wazuh"
    assert skills[0]["model"] == "opus"
    agents = list_agents(claude_dir)
    assert agents[0]["name"] == "backup-operator"


def test_memories_inventory(claude_dir):
    mems = list_memories(claude_dir)
    assert len(mems) == 5  # MEMORY.md excluded
    assert all(m["type"] == "feedback" for m in mems)
    stats = memory_stats(mems)
    assert stats["total"] == 5


def test_no_filename_token_clustering_exists(claude_dir):
    """Pins the 2026-08-19 removal. Clustering memories by shared filename token
    produced 96 bogus consolidation candidates against the real estate (topic
    '2026' x166). If someone reintroduces a grouper here, this fails."""
    from noirdeck.readers import memories as mod

    assert not hasattr(mod, "group_memories")
    assert not hasattr(mod, "_topic_tokens")


def test_history_stats_and_repeats(claude_dir):
    records = load_history(claude_dir)
    stats = history_stats(records)
    assert stats["total_prompts"] == 6
    assert ("/operate", 1) in stats["top_slash"]
    reps = repeated_prompts(records, min_count=3)
    assert reps and reps[0]["count"] == 4
    hits = search_history(records, "sentinelone")
    assert len(hits) == 4


def _rec(display, ts, project="/home/u/projects/a"):
    return {"display": display, "ts": ts, "project": project, "session_id": str(ts)}


def test_near_identical_prompts_collapse_into_one_group():
    """Punctuation, case and spacing differences are the same habit, not three."""
    groups = group_hits(
        [
            _rec("commit these changes", 300),
            _rec("Commit these changes.", 200, "/home/u/projects/b"),
            _rec("commit  these   changes", 100),
            _rec("deploy the website", 400, "/home/u/projects/c"),
        ]
    )
    assert len(groups) == 2
    assert groups[0]["display"] == "deploy the website"  # newest group first
    repeat = next(g for g in groups if g["count"] == 3)
    assert repeat["display"] == "commit these changes"  # newest wording shown
    assert repeat["projects"] == ["a", "b"]
    assert repeat["first_ts"] == 100 and repeat["last_ts"] == 300


def test_grouped_search_reports_how_much_it_collapsed():
    out = search_grouped([_rec("commit these changes", t) for t in (1, 2, 3)] + [_rec("other thing", 4)], "commit")
    assert out["total"] == 3 and len(out["groups"]) == 1
    assert out["collapsed"] == 2  # rows removed from the reader's view


def test_a_group_keeps_its_members_for_expansion(claude_dir):
    groups = group_hits([_rec("same prompt", t) for t in range(1, 6)])
    assert groups[0]["count"] == 5
    assert [i["ts"] for i in groups[0]["items"]] == [5, 4, 3, 2, 1]
    assert groups[0]["truncated"] is False


def test_sessions_open_loop(claude_dir):
    sessions = recent_sessions(claude_dir, limit=10)
    assert len(sessions) == 1
    s = sessions[0]
    assert s["first_prompt"].startswith("Build the invoice")
    assert s["open_loop"] is True


# ── the memory index ────────────────────────────────────────────────────────
# 44s cold on a real estate (19,308 files) became 0.44s by caching the frontmatter
# parse on disk. The risk a cache introduces is staleness, so that is what these
# pin: an edited file must be re-read, and a cache must never be able to serve a
# wrong answer just because it is fast.


def test_the_index_makes_a_second_walk_cheap_without_changing_the_answer(tmp_path, monkeypatch):
    import noirdeck.readers.memories as M

    monkeypatch.setattr(M, "_index_conn", None)
    monkeypatch.setenv("NOIRDECK_DB_PATH", str(tmp_path / "d.db"))
    monkeypatch.setenv("HOME", str(tmp_path))
    cd = tmp_path / ".claude"
    mem = cd / "projects" / "-demo" / "memory"
    mem.mkdir(parents=True)
    for i in range(5):
        (mem / f"note{i}.md").write_text(
            f"---\nname: note-{i}\ndescription: d{i}\nmetadata:\n  type: project\n---\nbody\n"
        )

    first = M.list_memories(cd)
    M._cache.clear()
    second = M.list_memories(cd)
    assert first == second, "the cached answer must be identical to the parsed one"
    assert len(first) == 5
    assert {m["name"] for m in first} == {f"note-{i}" for i in range(5)}


def test_an_edited_file_is_re_read_not_served_stale(tmp_path, monkeypatch):
    """⛔ The whole hazard of the index. Keyed on (mtime, size), so an edit must
    invalidate — otherwise the console shows a description the file no longer has."""
    import os

    import noirdeck.readers.memories as M

    monkeypatch.setattr(M, "_index_conn", None)
    monkeypatch.setenv("HOME", str(tmp_path))
    cd = tmp_path / ".claude"
    mem = cd / "projects" / "-demo" / "memory"
    mem.mkdir(parents=True)
    f = mem / "n.md"
    f.write_text("---\nname: before\ndescription: old text\n---\nbody\n")

    assert M.list_memories(cd)[0]["name"] == "before"

    f.write_text("---\nname: after\ndescription: new text and longer\n---\nbody\n")
    os.utime(f, (f.stat().st_atime + 10, f.stat().st_mtime + 10))
    M._cache.clear()

    got = M.list_memories(cd)[0]
    assert got["name"] == "after", "an edited file must not be served from the index"
    assert got["description"] == "new text and longer"


def test_a_same_mtime_edit_that_changes_length_is_caught(tmp_path, monkeypatch):
    """Why the key is (mtime, size) and not mtime alone: a tool rewriting a file can
    land inside the same mtime tick, and filesystem mtime resolution is not always
    fine enough to notice."""
    import os

    import noirdeck.readers.memories as M

    monkeypatch.setattr(M, "_index_conn", None)
    monkeypatch.setenv("HOME", str(tmp_path))
    cd = tmp_path / ".claude"
    mem = cd / "projects" / "-demo" / "memory"
    mem.mkdir(parents=True)
    f = mem / "n.md"
    f.write_text("---\nname: short\n---\nbody\n")
    st = f.stat()
    assert M.list_memories(cd)[0]["name"] == "short"

    f.write_text("---\nname: considerably-longer-name\n---\nbody\n")
    os.utime(f, (st.st_atime, st.st_mtime))  # force the SAME mtime
    M._cache.clear()

    assert M.list_memories(cd)[0]["name"] == "considerably-longer-name", "size must break the tie"


def test_the_reader_still_works_when_the_index_cannot_be_opened(tmp_path, monkeypatch):
    """A cache that can fail the feature is worse than no cache."""
    import noirdeck.readers.memories as M

    monkeypatch.setattr(M, "_index", lambda: None)
    monkeypatch.setenv("HOME", str(tmp_path))
    cd = tmp_path / ".claude"
    mem = cd / "projects" / "-demo" / "memory"
    mem.mkdir(parents=True)
    (mem / "n.md").write_text("---\nname: works-anyway\n---\nbody\n")
    M._cache.clear()
    assert M.list_memories(cd)[0]["name"] == "works-anyway"
