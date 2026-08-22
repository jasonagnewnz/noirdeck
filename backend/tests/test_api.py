import importlib
import subprocess
from datetime import datetime


def test_api_smoke(tmp_path, monkeypatch, claude_dir):
    monkeypatch.setenv("NOIRDECK_CLAUDE_DIR", str(claude_dir))
    monkeypatch.setenv("NOIRDECK_DB_PATH", str(tmp_path / "api.db"))
    monkeypatch.setenv("NOIRDECK_PROJECTS_DIR", str(tmp_path / "projects"))
    (tmp_path / "projects").mkdir()

    import noirdeck.main as main

    importlib.reload(main)
    from fastapi.testclient import TestClient

    client = TestClient(main.app)

    health = client.get("/api/health").json()
    assert health["status"] == "ok"
    assert health["version"]
    assert datetime.fromisoformat(health["server_started_at"])
    assert datetime.fromisoformat(health["server_now"])
    assert health["frontend_dir"]
    assert health["mining_armed"] is False  # fail-closed default

    ov = client.get("/api/overview").json()
    assert ov["skills"] == 1
    assert ov["history"]["total_prompts"] == 6

    # The local pass stages the builder profile and NOTHING else. It must not
    # invent skill drafts from repeated wording: the fixture history contains a
    # prompt repeated 4x, which the old vocabulary heuristic would have turned
    # into a skill proposal. Proposals for the operator's knowledge now require a
    # model to have read the evidence (miner/runner.py + miner/evidence.py).
    mined = client.post("/api/mine").json()
    assert mined["proposals_created"] >= 1
    assert mined["skill_candidates"] == 0
    props = client.get("/api/proposals", params={"status": "proposed"}).json()
    assert not [p for p in props if p["kind"] == "skill"], "string matching must never stage a skill draft"
    profile = [p for p in props if p["kind"] == "profile_doc"]
    assert profile, "expected the builder profile to be staged"
    pid = profile[0]["id"]
    ok = client.post(f"/api/proposals/{pid}/approve", json={}).json()
    assert ok["written_to"] and "builder-profile-noirdeck-" in ok["written_to"]

    # create-only: re-approving the same target now that the file exists is refused
    mined2 = client.post("/api/mine").json()
    assert mined2["proposals_created"] == 0, "same-day profile must not be re-staged"

    # LLM mining refuses when unarmed
    llm = client.post("/api/mine/llm").json()
    assert llm.get("skipped") is True

    assert client.get("/api/history/search", params={"q": "sentinelone"}).json()

    # browser-boundary hardening: foreign Host (DNS rebinding) and foreign Origin
    # (cross-site request) are both rejected on every route
    assert client.get("/api/health", headers={"host": "evil.example"}).status_code == 403
    assert (
        client.post("/api/workspace", headers={"origin": "https://evil.example"}, json={"project": "x"}).status_code
        == 403
    )
    assert client.get("/api/health", headers={"origin": "http://localhost:4747"}).status_code == 200


def test_workspace_runtime_defaults_knowledge_and_detached_queue(tmp_path, monkeypatch, claude_dir):
    monkeypatch.setenv("NOIRDECK_CLAUDE_DIR", str(claude_dir))
    monkeypatch.setenv("NOIRDECK_DB_PATH", str(tmp_path / "runtime.db"))
    monkeypatch.setenv("NOIRDECK_PROJECTS_DIR", str(tmp_path / "projects"))
    projects = tmp_path / "projects"
    repo = projects / "demo"
    repo.mkdir(parents=True)
    subprocess.run(["git", "-C", str(repo), "init", "-q", "-b", "main"], check=True)
    (repo / "README.md").write_text("# demo\n")

    import noirdeck.main as main

    importlib.reload(main)
    runtimes = main.workspace_runtimes()
    assert {r["id"] for r in runtimes["runners"]} >= {"claude", "codex"}

    prefs = main.workspace_defaults(
        main.WorkspaceDefaultsBody(
            runner="codex",
            model="gpt-5-codex",
            knowledge_source_runner="claude",
            knowledge_source_model="claude-sonnet-5",
            method_advisor=True,
        )
    )
    assert prefs["runner"] == "codex"
    assert prefs["model"] == "gpt-5-codex"
    assert prefs["method_advisor"] is True

    pack = main.workspace_knowledge(
        main.WorkspaceKnowledgeBody(
            project="demo",
            source_runner="claude",
            source_model="claude-sonnet-5",
            target_runner="codex",
            target_model="gpt-5-codex",
        )
    )
    assert "AI Workspace Transfer Pack" in pack["body"]
    assert "Target runtime: Codex / gpt-5-codex" in pack["body"]

    queued = main.queue_add(
        main.TaskBody(
            project="demo",
            title="Use the selected runtime",
            prompt="Make a tiny README improvement.",
            knowledge_pack_id=pack["id"],
        )
    )
    assert queued["runner"] == "codex"
    assert queued["model"] == "gpt-5-codex"
    task = main.queue_list()[0]
    assert task["runner"] == "codex"
    assert task["model"] == "gpt-5-codex"
    assert "AI Workspace Transfer Pack" in task["prompt"]

    suggestion = main.workspace_method(
        main.WorkspaceMethodBody(project="demo", prompt="Make a tiny README improvement.")
    )
    assert suggestion["runner"] == "codex"
    assert suggestion["model"] == "gpt-5-codex"
    assert suggestion["use_handoff"] is True
    assert suggestion["memory_hints"]
    assert any("last queued" in reason for reason in suggestion["reasons"])


def test_design_capture_api(tmp_path, monkeypatch, claude_dir):
    monkeypatch.setenv("NOIRDECK_CLAUDE_DIR", str(claude_dir))
    monkeypatch.setenv("NOIRDECK_DB_PATH", str(tmp_path / "design-api.db"))
    monkeypatch.setenv("NOIRDECK_PROJECTS_DIR", str(tmp_path / "projects"))
    repo = tmp_path / "projects" / "demo"
    repo.mkdir(parents=True)
    subprocess.run(["git", "-C", str(repo), "init", "-q", "-b", "main"], check=True)
    (repo / "package.json").write_text('{"dependencies":{"react":"latest","tailwindcss":"latest"}}')
    (repo / "src").mkdir()
    (repo / "src" / "App.jsx").write_text(
        '<main className="dashboard grid gap-4 bg-zinc-950 text-white"><section>metric chart table status</section></main>'
    )

    import noirdeck.main as main

    importlib.reload(main)
    from fastapi.testclient import TestClient

    client = TestClient(main.app)
    captured = client.post("/api/design/capture", json={"project": "demo"}).json()
    assert captured["suggested_kit"] == "dashboard"
    assert "Capture the existing UI language" in captured["brief"]


def test_queuing_a_task_arms_it_so_run_later_actually_runs(tmp_path, monkeypatch, claude_dir):
    """Pressing "run later" used to accept the task and then never run it: the
    runner needs a contract, and creating one was a separate screen with three
    numbers to invent. Queuing IS the intent to run, so it arms with defaults."""
    monkeypatch.setenv("NOIRDECK_CLAUDE_DIR", str(claude_dir))
    monkeypatch.setenv("NOIRDECK_DB_PATH", str(tmp_path / "arm.db"))
    monkeypatch.setenv("NOIRDECK_PROJECTS_DIR", str(tmp_path / "projects"))
    repo = tmp_path / "projects" / "demo"
    repo.mkdir(parents=True)
    subprocess.run(["git", "-C", str(repo), "init", "-q", "-b", "main"], check=True)

    import noirdeck.main as main

    importlib.reload(main)
    from fastapi.testclient import TestClient

    client = TestClient(main.app)

    before = client.get("/api/arming").json()["contracts"].get("overnight")
    assert not (before and before.get("live")), "precondition: nothing armed"

    out = client.post("/api/queue", json={"project": "demo", "title": "tidy the readme", "prompt": "do it"}).json()
    assert out.get("id")
    assert out.get("armed"), "the response must say what it armed, so it is visible and revocable"
    assert out["armed"]["max_tasks"] and out["armed"]["max_tokens"], "a real budget, not an absent one"

    after = client.get("/api/arming").json()["contracts"]["overnight"]
    assert after["live"] is True

    # queuing a SECOND task must not widen the contract the first one created
    client.post("/api/queue", json={"project": "demo", "title": "second", "prompt": "do it"})
    again = client.get("/api/arming").json()["contracts"]["overnight"]
    assert again["max_tasks"] == after["max_tasks"], "an existing budget must never be topped up"
    assert again["id"] == after["id"], "and must not be replaced"
