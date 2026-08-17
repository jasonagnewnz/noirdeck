from noirdeck.readers.history import (
    group_hits,
    history_stats,
    load_history,
    repeated_prompts,
    search_grouped,
    search_history,
)
from noirdeck.readers.memories import group_memories, list_memories, memory_stats
from noirdeck.readers.sessions import recent_sessions
from noirdeck.readers.skills import list_agents, list_skills


def test_skills_and_agents(claude_dir):
    skills = list_skills(claude_dir)
    assert len(skills) == 1
    assert skills[0]["name"] == "deploy-wazuh"
    assert skills[0]["model"] == "opus"
    agents = list_agents(claude_dir)
    assert agents[0]["name"] == "backup-operator"


def test_memories_and_grouping(claude_dir):
    mems = list_memories(claude_dir)
    assert len(mems) == 5  # MEMORY.md excluded
    assert all(m["type"] == "feedback" for m in mems)
    groups = group_memories(mems, min_group=4)
    assert any(g["topic"] == "wazuh" and g["count"] == 4 for g in groups)
    stats = memory_stats(mems)
    assert stats["total"] == 5


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
