from app.readers.history import history_stats, load_history, repeated_prompts, search_history
from app.readers.memories import group_memories, list_memories, memory_stats
from app.readers.sessions import recent_sessions
from app.readers.skills import list_agents, list_skills


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


def test_sessions_open_loop(claude_dir):
    sessions = recent_sessions(claude_dir, limit=10)
    assert len(sessions) == 1
    s = sessions[0]
    assert s["first_prompt"].startswith("Build the invoice")
    assert s["open_loop"] is True
