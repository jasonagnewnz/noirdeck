import importlib


def test_api_smoke(tmp_path, monkeypatch, claude_dir):
    monkeypatch.setenv("NOIRDECK_CLAUDE_DIR", str(claude_dir))
    monkeypatch.setenv("NOIRDECK_DB_PATH", str(tmp_path / "api.db"))
    monkeypatch.setenv("NOIRDECK_PROJECTS_DIR", str(tmp_path / "projects"))
    (tmp_path / "projects").mkdir()

    import app.main as main
    importlib.reload(main)
    from fastapi.testclient import TestClient
    client = TestClient(main.app)

    health = client.get("/api/health").json()
    assert health["status"] == "ok"
    assert health["mining_armed"] is False  # fail-closed default

    ov = client.get("/api/overview").json()
    assert ov["skills"] == 1
    assert ov["history"]["total_prompts"] == 6

    # heuristic mining stages proposals; approving one writes into the fixture claude dir
    mined = client.post("/api/mine").json()
    assert mined["proposals_created"] >= 1
    props = client.get("/api/proposals", params={"status": "proposed"}).json()
    skill_props = [p for p in props if p["kind"] == "skill"]
    assert skill_props, "expected a skill-gap draft from the repeated fixture prompt"
    pid = skill_props[0]["id"]
    ok = client.post(f"/api/proposals/{pid}/approve", json={}).json()
    assert ok["written_to"] and "skills/" in ok["written_to"]

    # LLM mining refuses when unarmed
    llm = client.post("/api/mine/llm").json()
    assert llm.get("skipped") is True

    assert client.get("/api/history/search", params={"q": "sentinelone"}).json()

    # browser-boundary hardening: foreign Host (DNS rebinding) and foreign Origin
    # (cross-site request) are both rejected on every route
    assert client.get("/api/health", headers={"host": "evil.example"}).status_code == 403
    assert client.post("/api/workspace", headers={"origin": "https://evil.example"},
                       json={"project": "x"}).status_code == 403
    assert client.get("/api/health", headers={"origin": "http://localhost:4747"}).status_code == 200
