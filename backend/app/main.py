"""noirdeck API + SPA server. Binds 127.0.0.1 only (see docs/SECURITY.md)."""
from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .config import REPO_ROOT, Settings, primary_namespace
from .db import audit, connect, init_db, utcnow
from .miner.heuristics import run_heuristics
from .miner.runner import run_llm_mining
from .overnight import requeue_stale_running, route_agent, route_model
from .proposals import ProposalError, approve, dismiss, list_proposals, revert
from .qa import evaluate_fleet, evaluate_project
from .readers import history as hist
from .readers.commits import fleet_feed, fleet_flags, follow_on_flags, recent_commits
from .readers.files import FilesError, list_dir, read_file
from .readers.fleet import fleet, fleet_attention
from . import arming, ask, digest, guided, hygiene, improve, preview, vault
from .readers.memories import group_memories, list_memories, memory_stats
from .readers.sessions import namespace_display, recent_sessions
from .readers.skills import list_agents, list_skills
from .version import VERSION
from .builds import BuildRunner
from .design import DesignStudio
from .workspace import (WorkspaceError, WorkspaceManager, init_repo,
                        latest_transcript_session_id)

settings = Settings.load()
init_db(settings.db_path)
app = FastAPI(title="noirdeck", version=VERSION)

# ── browser-boundary hardening ────────────────────────────────────────────────
# Loopback binding alone does not stop the user's own BROWSER being used against
# the API: DNS rebinding defeats "it's only on 127.0.0.1" (attacker domain resolves
# to 127.0.0.1 → same-origin), and WebSockets have no same-origin policy at all —
# and this app exposes a shell-equivalent WS. Host allowlist kills rebinding;
# Origin allowlist kills cross-origin WS/CSRF. A per-session token adds nothing
# against a non-browser local attacker (same user, already has a shell).
_ALLOWED_HOSTS = {"127.0.0.1", "localhost", "testserver"}


def _hostname_ok(value: str | None) -> bool:
    if not value:
        return False
    host = value.rsplit(":", 1)[0] if not value.startswith("[") else value.split("]")[0].lstrip("[")
    return host in _ALLOWED_HOSTS


def _origin_ok(origin: str | None) -> bool:
    if not origin:
        return True  # non-browser client (curl, tests) — host check still applies
    from urllib.parse import urlparse
    return urlparse(origin).hostname in _ALLOWED_HOSTS


@app.middleware("http")
async def local_browser_boundary(request, call_next):
    if not _hostname_ok(request.headers.get("host")) or not _origin_ok(request.headers.get("origin")):
        from fastapi.responses import JSONResponse
        return JSONResponse({"detail": "forbidden origin/host"}, status_code=403)
    return await call_next(request)

# re-queue tasks orphaned by a crash mid-run
_c = connect(settings.db_path)
requeue_stale_running(_c)
_c.close()


# pre-warm the expensive caches (15k memory frontmatters, 50-repo git sweep) off-thread
# so the first page load is fast instead of ~18s
def _prewarm():
    try:
        list_memories(settings.claude_dir)
        fleet(settings.projects_dir)
    except Exception:  # noqa: BLE001 — warming must never block or kill startup
        pass


import threading  # noqa: E402

threading.Thread(target=_prewarm, daemon=True).start()


def db():
    return connect(settings.db_path)


@app.get("/api/health")
def health():
    return {"status": "ok", "version": VERSION, "claude_dir": str(settings.claude_dir),
            "mining_armed": settings.mining_armed, "overnight_armed": settings.overnight_armed}


@app.get("/api/overview")
def overview():
    records = hist.load_history(settings.claude_dir)
    stats = hist.history_stats(records)
    sessions = recent_sessions(settings.claude_dir, limit=12)
    states = fleet(settings.projects_dir)
    conn = db()
    try:
        pending = conn.execute(
            "SELECT COUNT(*) c FROM proposals WHERE status='proposed'").fetchone()["c"]
        queue_counts = {r["status"]: r["c"] for r in conn.execute(
            "SELECT status, COUNT(*) c FROM queue GROUP BY status").fetchall()}
    finally:
        conn.close()
    mems = list_memories(settings.claude_dir)
    return {
        "skills": len(list_skills(settings.claude_dir)),
        "agents": len(list_agents(settings.claude_dir)),
        "memories": memory_stats(mems),
        "history": stats,
        "recent_sessions": sessions,
        "open_loops": [s for s in sessions if s["open_loop"]][:6],
        "fleet_attention": fleet_attention(states),
        "proposals_pending": pending,
        "queue": queue_counts,
    }


@app.get("/api/skills")
def skills():
    return list_skills(settings.claude_dir)


@app.get("/api/agents")
def agents():
    return list_agents(settings.claude_dir)


@app.get("/api/memories")
def memories():
    mems = list_memories(settings.claude_dir)
    return {"stats": memory_stats(mems), "memories": mems, "groups": group_memories(mems)}


def _improve_assets() -> dict:
    """Addable estate targets for the UI dropdowns — every path offered here
    already satisfies the proposals write allowlist (skills + the primary
    memory namespace), so 'addable' and 'approvable' can never disagree."""
    ns = primary_namespace()
    skills = [{"label": s["name"], "target_path": f"skills/{s['dir']}/SKILL.md"}
              for s in list_skills(settings.claude_dir)]
    memories = [{"label": m["name"], "target_path": f"projects/{ns}/memory/{m['file']}"}
                for m in list_memories(settings.claude_dir) if m["namespace"] == ns]
    return {"skill": skills, "memory": memories}


class ImproveRepoBody(BaseModel):
    project: str
    enabled: bool = True
    # per-repo model override; "" or null clears back to the env default.
    # Absent field = leave unchanged (the enable/disable toggle omits it).
    model: str | None = None


@app.get("/api/improve")
def improve_status():
    # one tags fetch serves both fields — two sequential calls stalled the
    # panel ~10s when ollama was down (each timing out separately)
    avail = improve.available_models()
    conn = db()
    try:
        return {
            "armed": improve.armed(),
            "model": improve.local_model(),
            "model_available": improve._model_in(improve.local_model(), avail),
            "models": avail,
            "repos": [dict(r) for r in conn.execute(
                "SELECT * FROM improve_repos ORDER BY project").fetchall()],
            "changes": [dict(r) for r in conn.execute(
                "SELECT * FROM improve_changes ORDER BY id DESC LIMIT 50").fetchall()],
            "learning": improve.decision_stats(conn),
            "targets": [dict(r) | {"armed": bool(r["armed_until"] and r["armed_until"] > utcnow())}
                        for r in conn.execute(
                            "SELECT * FROM improve_targets ORDER BY kind, target_path").fetchall()],
            "assets": _improve_assets(),
        }
    finally:
        conn.close()


@app.post("/api/improve/repos")
def improve_map(body: ImproveRepoBody):
    if improve.safe_repo(settings, body.project) is None:
        raise HTTPException(404, f"no project repo {body.project}")
    model = (body.model or "").strip() or None
    if model is not None:
        avail = improve.available_models()
        if not avail:
            # can't validate against a dead ollama — refuse honestly rather
            # than claiming the model isn't pulled
            raise HTTPException(503, "Ollama is unreachable — cannot validate the model")
        if model not in avail:
            # only locally-pulled Ollama tags are assignable — never a free-form
            # string that would reach the generate call, never a cloud model
            raise HTTPException(400, f"model {model!r} is not pulled locally")
    conn = db()
    try:
        conn.execute(
            "INSERT INTO improve_repos (project, enabled, created_at) VALUES (?,?,?) "
            "ON CONFLICT(project) DO UPDATE SET enabled=excluded.enabled",
            (body.project, int(body.enabled), utcnow()))
        if "model" in body.model_fields_set:
            conn.execute("UPDATE improve_repos SET model=? WHERE project=?",
                         (model, body.project))
        conn.commit()
        audit(conn, "operator", "improve_repo_mapped",
              f"{body.project} enabled={int(body.enabled)}"
              + (f" model={model or 'default'}" if "model" in body.model_fields_set else ""))
        return {"project": body.project, "enabled": body.enabled, "model": model}
    finally:
        conn.close()


class ImproveTargetBody(BaseModel):
    kind: str
    target_path: str
    model: str | None = None


class ImproveTargetAction(BaseModel):
    action: str  # arm | disarm | remove
    hours: float = 168.0  # arm default: one week


@app.post("/api/improve/targets")
def improve_target_add(body: ImproveTargetBody):
    if body.kind not in improve.ASSET_KINDS:
        raise HTTPException(400, f"kind must be one of {improve.ASSET_KINDS}")
    if improve.safe_asset(settings.claude_dir, body.target_path) is None:
        raise HTTPException(404, "target missing or outside the write allowlist")
    model = (body.model or "").strip() or None
    if model is not None:
        avail = improve.available_models()
        if not avail:
            raise HTTPException(503, "Ollama is unreachable — cannot validate the model")
        if model not in avail:
            raise HTTPException(400, f"model {model!r} is not pulled locally")
    conn = db()
    try:
        # added DISARMED — arming is a separate, deliberate act
        conn.execute(
            "INSERT INTO improve_targets (kind, target_path, model, created_at) "
            "VALUES (?,?,?,?) ON CONFLICT(target_path) DO UPDATE SET model=excluded.model",
            (body.kind, body.target_path, model, utcnow()))
        conn.commit()
        audit(conn, "operator", "improve_target_added",
              f"{body.kind} {body.target_path} model={model or 'default'}")
        return {"kind": body.kind, "target_path": body.target_path, "armed": False}
    finally:
        conn.close()


@app.post("/api/improve/targets/{tid}")
def improve_target_action(tid: int, body: ImproveTargetAction):
    conn = db()
    try:
        row = conn.execute("SELECT * FROM improve_targets WHERE id=?", (tid,)).fetchone()
        if not row:
            raise HTTPException(404, f"no improve target {tid}")
        if body.action == "arm":
            if not 1 <= body.hours <= 24 * 90:
                raise HTTPException(400, "hours must be between 1 and 2160")
            until = (datetime.now(timezone.utc) + timedelta(hours=body.hours)).isoformat()
            conn.execute("UPDATE improve_targets SET armed_until=? WHERE id=?", (until, tid))
            detail = f"until={until}"
        elif body.action == "disarm":
            conn.execute("UPDATE improve_targets SET armed_until=NULL WHERE id=?", (tid,))
            detail = "disarmed"
        elif body.action == "remove":
            conn.execute("DELETE FROM improve_targets WHERE id=?", (tid,))
            detail = "removed"
        else:
            raise HTTPException(400, f"unknown action {body.action!r}")
        conn.commit()
        audit(conn, "operator", f"improve_target_{body.action}",
              f"id={tid} {row['target_path']} {detail}")
        return {"id": tid, "action": body.action}
    finally:
        conn.close()


@app.post("/api/improve/run")
def improve_run():
    threading.Thread(target=improve.run_improver, args=(settings,), daemon=True).start()
    return {"started": True}


class ImproveDecision(BaseModel):
    action: str  # merge | discard


@app.post("/api/improve/changes/{change_id}")
def improve_decide(change_id: int, body: ImproveDecision):
    conn = db()
    try:
        return improve.decide(settings, conn, change_id, body.action)
    except ValueError as e:
        raise HTTPException(409, str(e))
    finally:
        conn.close()


@app.get("/api/vault")
def vault_status():
    conn = db()
    try:
        return vault.status(conn)
    finally:
        conn.close()


@app.post("/api/vault/run")
def vault_run():
    ok, why = vault.configured()
    if not ok:
        raise HTTPException(409, why)
    threading.Thread(target=vault.run_backup, args=(settings,), daemon=True).start()
    return {"started": True}


@app.get("/api/arming")
def arming_status():
    conn = db()
    try:
        return {"contracts": arming.status(conn),
                "env": {"overnight": settings.overnight_armed, "mining": settings.mining_armed}}
    finally:
        conn.close()


class ArmBody(BaseModel):
    subsystem: str
    hours: float = 10.0
    max_tasks: int | None = None
    max_tokens: int | None = None


@app.post("/api/arming")
def arming_arm(body: ArmBody):
    conn = db()
    try:
        return arming.arm(conn, body.subsystem, body.hours, body.max_tasks, body.max_tokens)
    except arming.ArmingError as e:
        raise HTTPException(400, str(e))
    finally:
        conn.close()


@app.delete("/api/arming/{subsystem}")
def arming_revoke(subsystem: str):
    conn = db()
    try:
        return {"revoked": arming.revoke(conn, subsystem)}
    finally:
        conn.close()


@app.get("/api/hygiene")
def hygiene_report(namespace: str | None = None):
    try:
        return hygiene.report(settings.claude_dir, namespace)
    except ValueError as e:
        raise HTTPException(400, str(e))


class MergeBody(BaseModel):
    namespace: str | None = None
    files: list[str]


@app.post("/api/hygiene/merge")
def hygiene_merge(body: MergeBody):
    conn = db()
    try:
        return hygiene.propose_merge(conn, settings.claude_dir, body.namespace, body.files)
    except ValueError as e:
        raise HTTPException(400, str(e))
    finally:
        conn.close()


@app.get("/api/sessions")
def sessions(limit: int = Query(40, le=1000), namespace: str | None = None):
    out = recent_sessions(settings.claude_dir, limit=limit, namespace=namespace)
    for s in out:
        s["display"] = namespace_display(s["namespace"])
    return out


@app.get("/api/history/stats")
def history_stats():
    return hist.history_stats(hist.load_history(settings.claude_dir))


@app.get("/api/history/search")
def history_search(q: str):
    if len(q) < 3:
        raise HTTPException(400, "query too short")
    return hist.search_history(hist.load_history(settings.claude_dir), q)


@app.get("/api/fleet")
def fleet_route():
    return fleet(settings.projects_dir)


_commit_cache: dict = {"ts": 0.0, "data": None}


@app.get("/api/commits")
def commits_route():
    import time as _t
    if _commit_cache["data"] is not None and _t.monotonic() - _commit_cache["ts"] < 120:
        return _commit_cache["data"]
    data = {"feed": fleet_feed(settings.projects_dir),
            "follow_on": fleet_flags(settings.projects_dir)}
    _commit_cache.update(ts=_t.monotonic(), data=data)
    return data


def build_kickoff(project: str, repo, state: dict, sess: list[dict]) -> str:
    return (
        f"/operate — orient from the {project} project memory index first. "
        f"Branch '{state['branch']}'"
        + (f" has {state['dirty_files']} uncommitted file(s)" if state["dirty_files"] else "")
        + (f" and {state['unpushed_commits']} unpushed commit(s)" if state["unpushed_commits"] else "")
        + ". "
        + (f"Last session ended unfinished: \"{sess[0]['last_assistant'][-200:]}\" — pick that up first."
           if sess and sess[0]["open_loop"] else "No open loop detected in the last session.")
    )


@app.get("/api/briefing/{project}")
def briefing(project: str):
    repo = settings.projects_dir / project
    if not (repo.is_dir() and (repo / ".git").exists()):
        raise HTTPException(404, f"no project repo {project}")
    ns = str(repo).replace("/", "-")
    sess = recent_sessions(settings.claude_dir, limit=5, namespace=ns)
    mem_dir = settings.claude_dir / "projects" / ns / "memory"
    from .readers.fleet import repo_state
    state = repo_state(repo)
    kickoff = build_kickoff(project, repo, state, sess)
    return {
        "project": project,
        "git": state,
        "memory_namespace": ns if mem_dir.is_dir() else None,
        "memory_files": len(list(mem_dir.glob("*.md"))) if mem_dir.is_dir() else 0,
        "recent_sessions": sess,
        "recent_commits": recent_commits(repo, 8),
        "follow_on": follow_on_flags(repo),
        "kickoff": kickoff,
        "qa": evaluate_project(repo),
    }


# --- proposals ---

class DecisionBody(BaseModel):
    overwrite: bool = False
    note: str = ""


@app.get("/api/proposals")
def proposals_route(status: str | None = None):
    conn = db()
    try:
        return list_proposals(conn, status)
    finally:
        conn.close()


@app.post("/api/proposals/{pid}/approve")
def approve_route(pid: int, body: DecisionBody):
    conn = db()
    try:
        return approve(conn, settings.claude_dir, pid, overwrite=body.overwrite)
    except ProposalError as e:
        raise HTTPException(409, str(e))
    finally:
        conn.close()


@app.post("/api/proposals/{pid}/revert")
def revert_route(pid: int, body: DecisionBody):
    conn = db()
    try:
        return revert(conn, settings.claude_dir, pid, overwrite=body.overwrite)
    except ProposalError as e:
        raise HTTPException(409, str(e))
    finally:
        conn.close()


@app.post("/api/proposals/{pid}/dismiss")
def dismiss_route(pid: int, body: DecisionBody):
    conn = db()
    try:
        return dismiss(conn, pid, body.note)
    except ProposalError as e:
        raise HTTPException(409, str(e))
    finally:
        conn.close()


@app.post("/api/mine")
def mine_now():
    conn = db()
    try:
        return run_heuristics(conn, settings.claude_dir)
    finally:
        conn.close()


@app.post("/api/mine/llm")
def mine_llm():
    conn = db()
    try:
        return run_llm_mining(conn, settings)
    finally:
        conn.close()


@app.get("/api/insights")
def insights():
    conn = db()
    try:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM insights ORDER BY id DESC LIMIT 100").fetchall()]
    finally:
        conn.close()


# --- QA gates ---

@app.get("/api/qa")
def qa_all():
    return evaluate_fleet(settings.projects_dir)


@app.get("/api/qa/{project}")
def qa_one(project: str):
    repo = settings.projects_dir / project
    if not (repo.is_dir() and (repo / ".git").exists()):
        raise HTTPException(404, f"no project repo {project}")
    return evaluate_project(repo)


# --- overnight queue ---

class TaskBody(BaseModel):
    project: str
    title: str
    prompt: str


class AnswerBody(BaseModel):
    answer: str


@app.get("/api/queue")
def queue_list():
    conn = db()
    try:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM queue ORDER BY id DESC LIMIT 200").fetchall()]
    finally:
        conn.close()


@app.post("/api/queue")
def queue_add(body: TaskBody):
    repo = settings.projects_dir / body.project
    if not (repo.is_dir() and (repo / ".git").exists()):
        raise HTTPException(400, f"unknown project {body.project}")
    text = body.title + " " + body.prompt
    conn = db()
    try:
        cur = conn.execute(
            "INSERT INTO queue (project,title,prompt,agent_type,model,status,created_at) "
            "VALUES (?,?,?,?,?,'queued',?)",
            (str(repo), body.title, body.prompt,
             route_agent(text, settings.claude_dir), route_model(text), utcnow()))
        audit(conn, "operator", "task_queued", f"id={cur.lastrowid} title={body.title[:80]}")
        conn.commit()
        return {"id": cur.lastrowid}
    finally:
        conn.close()


@app.post("/api/queue/{tid}/answer")
def queue_answer(tid: int, body: AnswerBody):
    conn = db()
    try:
        row = conn.execute("SELECT status FROM queue WHERE id=?", (tid,)).fetchone()
        if not row:
            raise HTTPException(404, "no such task")
        if row["status"] != "blocked":
            raise HTTPException(409, f"task is {row['status']}, not blocked")
        conn.execute(
            "UPDATE queue SET answer=?, status='queued', question=NULL WHERE id=?",
            (body.answer, tid))
        audit(conn, "operator", "task_answered", f"id={tid}")
        conn.commit()
        return {"id": tid, "status": "queued"}
    finally:
        conn.close()


@app.post("/api/queue/{tid}/cancel")
def queue_cancel(tid: int):
    conn = db()
    try:
        conn.execute("UPDATE queue SET status='cancelled' WHERE id=? AND status IN ('queued','blocked')", (tid,))
        audit(conn, "operator", "task_cancelled", f"id={tid}")
        conn.commit()
        return {"id": tid}
    finally:
        conn.close()


# --- workspace: real Claude sessions over PTY ---

workspace = WorkspaceManager(settings.projects_dir)


class WorkspaceStart(BaseModel):
    project: str
    briefing: bool = False
    resume_session_id: str | None = None


class RepoBody(BaseModel):
    name: str


@app.get("/api/workspace")
async def workspace_list():
    return workspace.listing()


# async so TermSession.start() runs ON the event loop — add_reader needs it;
# a sync endpoint lands in the threadpool where get_running_loop() raises
@app.post("/api/workspace")
async def workspace_start(body: WorkspaceStart):
    initial = None
    if body.briefing and not body.resume_session_id:
        repo = settings.projects_dir / body.project
        ns = str(repo).replace("/", "-")
        from .readers.fleet import repo_state
        sess = recent_sessions(settings.claude_dir, limit=5, namespace=ns)
        initial = build_kickoff(body.project, repo, repo_state(repo), sess)
    try:
        term = workspace.start(body.project, initial_prompt=initial,
                               resume_session_id=body.resume_session_id)
    except WorkspaceError as e:
        raise HTTPException(409, str(e))
    conn = db()
    try:
        audit(conn, "operator", "workspace_started",
              f"id={term.id} project={body.project} resume={body.resume_session_id or '-'}")
    finally:
        conn.close()
    return {"id": term.id, "project": term.project}


@app.delete("/api/workspace/{sid}")
async def workspace_stop(sid: str):
    try:
        workspace.stop(sid)
    except WorkspaceError as e:
        raise HTTPException(404, str(e))
    return {"id": sid, "stopped": True}


class PauseBody(BaseModel):
    label: str | None = None


@app.get("/api/workspace/paused")
async def workspace_paused_list():
    conn = db()
    try:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM paused_sessions WHERE resumed_at IS NULL "
            "ORDER BY id DESC LIMIT 20").fetchall()]
    finally:
        conn.close()


@app.post("/api/workspace/{sid}/pause")
async def workspace_pause(sid: str, body: PauseBody):
    """Park a live session for a full shutdown: capture its claude transcript
    id NOW (later 'most recent in cwd' may be a headless run's), then stop the
    PTY — claude persists the conversation continuously, so this is safe."""
    try:
        term = workspace.get(sid)
    except WorkspaceError as e:
        raise HTTPException(404, str(e))
    claude_session = latest_transcript_session_id(settings.claude_dir, term.cwd)
    project = term.project
    workspace.stop(sid)
    conn = db()
    try:
        cur = conn.execute(
            "INSERT INTO paused_sessions (project, claude_session_id, label, paused_at) "
            "VALUES (?,?,?,?)",
            (project, claude_session, (body.label or "").strip()[:120] or None, utcnow()))
        conn.commit()
        audit(conn, "operator", "workspace_paused",
              f"id={sid} project={project} claude_session={claude_session or 'unknown'}")
        return {"paused_id": cur.lastrowid, "project": project,
                "claude_session_id": claude_session}
    finally:
        conn.close()


# async for the same add_reader reason as workspace_start
@app.post("/api/workspace/paused/{pid}/resume")
async def workspace_resume_paused(pid: int):
    conn = db()
    try:
        row = conn.execute(
            "SELECT * FROM paused_sessions WHERE id=? AND resumed_at IS NULL",
            (pid,)).fetchone()
        if not row:
            raise HTTPException(404, "no such paused session (or already resumed)")
        try:
            term = workspace.start(row["project"],
                                   resume_session_id=row["claude_session_id"],
                                   continue_last=row["claude_session_id"] is None)
        except WorkspaceError as e:
            raise HTTPException(409, str(e))
        conn.execute("UPDATE paused_sessions SET resumed_at=? WHERE id=?",
                     (utcnow(), pid))
        conn.commit()
        audit(conn, "operator", "workspace_resumed",
              f"paused={pid} project={row['project']} new={term.id}")
        return {"id": term.id, "project": row["project"]}
    finally:
        conn.close()


@app.post("/api/workspace/repo")
def workspace_repo(body: RepoBody):
    try:
        target = init_repo(settings.projects_dir, body.name)
    except WorkspaceError as e:
        raise HTTPException(409, str(e))
    conn = db()
    try:
        audit(conn, "operator", "repo_created", str(target))
    finally:
        conn.close()
    return {"name": body.name, "path": str(target)}


@app.websocket("/api/workspace/ws/{sid}")
async def workspace_ws(ws: WebSocket, sid: str):
    # WebSockets bypass same-origin policy — enforce the same boundary by hand
    if not _hostname_ok(ws.headers.get("host")) or not _origin_ok(ws.headers.get("origin")):
        await ws.close(code=4403)
        return
    await ws.accept()
    try:
        term = workspace.get(sid)
    except WorkspaceError:
        await ws.close(code=4404)
        return
    # replay scrollback so a reconnect shows the session so far
    if term.scrollback:
        await ws.send_bytes(b"".join(term.scrollback))

    async def pump_out():
        while True:
            data = await term.queue.get()
            if data is None:
                await ws.close(code=4000)
                return
            await ws.send_bytes(data)

    out_task = asyncio.create_task(pump_out())
    try:
        while True:
            msg = await ws.receive_text()
            try:
                obj = json.loads(msg)
            except json.JSONDecodeError:
                continue
            if "in" in obj:
                term.write(str(obj["in"]).encode())
            elif "resize" in obj:
                cols, rows = obj["resize"]
                term.resize(int(cols), int(rows))
    except WebSocketDisconnect:
        pass
    finally:
        out_task.cancel()


# --- Builds mode: unattended prompt → code-ready software ---

builds_runner = BuildRunner(settings)
builds_runner.requeue_stale()


class BuildStart(BaseModel):
    name: str
    prompt: str


def _build_row(r) -> dict:
    d = dict(r)
    d["log"] = json.loads(d.get("log") or "[]")
    d["prompt"] = d["prompt"][:400]
    for col in ("intake", "acceptance", "evidence"):
        d[col] = json.loads(d[col]) if d.get(col) else None
    return d


@app.get("/api/builds")
def builds_list():
    conn = db()
    try:
        return [_build_row(r) for r in conn.execute(
            "SELECT * FROM builds ORDER BY id DESC LIMIT 50").fetchall()]
    finally:
        conn.close()


@app.post("/api/builds")
def builds_start(body: BuildStart):
    if len(body.prompt.strip()) < 40:
        raise HTTPException(400, "give the FULL brief — a build prompt under 40 chars "
                                 "will not produce production-quality software")
    try:
        build_id = builds_runner.start(body.name.strip(), body.prompt)
    except WorkspaceError as e:
        raise HTTPException(409, str(e))
    return {"id": build_id, "name": body.name}


@app.get("/api/guided/questions")
def guided_questions():
    return guided.INTAKE_QUESTIONS


@app.get("/api/guided/recipes")
def guided_recipes():
    return guided.RECIPES


class GuidedStart(BaseModel):
    name: str
    answers: dict


@app.post("/api/builds/guided")
def builds_start_guided(body: GuidedStart):
    missing = guided.validate_answers(body.answers)
    if missing:
        raise HTTPException(400, f"missing answers: {', '.join(missing)}")
    try:
        build_id = builds_runner.start(
            body.name.strip(),
            guided.compose_brief(body.answers),
            gated=True,
            intake=body.answers,
            acceptance=guided.acceptance_criteria(body.answers))
    except WorkspaceError as e:
        raise HTTPException(409, str(e))
    return {"id": build_id, "name": body.name, "gated": True}


class PlanDecision(BaseModel):
    action: str  # approve | revise
    feedback: str = ""


@app.post("/api/builds/{build_id}/plan")
def builds_plan_decision(build_id: int, body: PlanDecision):
    try:
        builds_runner.decide_plan(build_id, body.action, body.feedback)
    except ValueError as e:
        raise HTTPException(409, str(e))
    return {"id": build_id, "action": body.action}


@app.post("/api/builds/{build_id}/cancel")
def builds_cancel(build_id: int):
    builds_runner.cancel(build_id)
    return {"id": build_id, "cancel_requested": True}


@app.post("/api/builds/{build_id}/resume")
def builds_resume(build_id: int):
    try:
        builds_runner.resume(build_id)
    except ValueError as e:
        raise HTTPException(409, str(e))
    return {"id": build_id, "resumed": True}


# --- morning digest + ask-your-estate (Overview) ---

@app.get("/api/digest")
def digest_route():
    conn = db()
    try:
        return digest.compose(conn)
    finally:
        conn.close()


class AskBody(BaseModel):
    question: str


@app.post("/api/ask")
def ask_submit(body: AskBody):
    try:
        out = ask.submit(settings, body.question)
    except ask.AskError as e:
        raise HTTPException(409, str(e))
    conn = db()
    try:
        audit(conn, "operator", "ask_submitted", f"id={out['id']} q={body.question[:120]}")
    finally:
        conn.close()
    return out


@app.get("/api/ask")
def ask_recent():
    return ask.recent()


@app.get("/api/ask/{job_id}")
def ask_get(job_id: str):
    try:
        return ask.get(job_id)
    except ask.AskError as e:
        raise HTTPException(404, str(e))


# --- try-it preview: a build's static web output, read-only, for a sandboxed iframe ---

@app.get("/api/preview-info/{project}")
def preview_info(project: str):
    try:
        return preview.info(settings, project)
    except preview.PreviewError as e:
        raise HTTPException(400, str(e))


@app.get("/api/preview/{project}/{path:path}")
def preview_file(project: str, path: str = ""):
    try:
        f, media = preview.resolve_file(settings, project, path)
    except preview.PreviewError as e:
        raise HTTPException(404, str(e))
    return FileResponse(f, media_type=media)


# --- project file browsing (read-only, for the IDE shell) ---

@app.get("/api/files/{project}")
def files_list(project: str, path: str = ""):
    try:
        return list_dir(settings.projects_dir, project, path)
    except FilesError as e:
        raise HTTPException(400, str(e))


@app.get("/api/file/{project}")
def file_read(project: str, path: str):
    try:
        return read_file(settings.projects_dir, project, path)
    except FilesError as e:
        raise HTTPException(400, str(e))


# --- Design Studio: propose → mock quickly → apply deliberately ---

studio = DesignStudio(settings)
studio.requeue_stale()


class DesignStart(BaseModel):
    project: str
    brief: str
    library: str = "mix"


class ApplyBody(BaseModel):
    variant: str


@app.get("/api/design")
def design_list():
    conn = db()
    try:
        rows = conn.execute("SELECT * FROM design_rounds ORDER BY id DESC LIMIT 30").fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["variants"] = json.loads(d["variants"] or "[]")
            out.append(d)
        return out
    finally:
        conn.close()


@app.post("/api/design")
def design_start(body: DesignStart):
    if len(body.brief.strip()) < 10:
        raise HTTPException(400, "describe the surface — a few words minimum")
    try:
        rid = studio.propose(body.project, body.brief.strip(), body.library)
    except (ValueError, WorkspaceError) as e:
        raise HTTPException(409, str(e))
    return {"id": rid}


@app.post("/api/design/{rid}/apply")
def design_apply(rid: int, body: ApplyBody):
    try:
        studio.apply(rid, body.variant)
    except ValueError as e:
        raise HTTPException(409, str(e))
    return {"id": rid, "variant": body.variant}


@app.delete("/api/design/{rid}")
def design_dismiss(rid: int):
    conn = db()
    try:
        conn.execute("DELETE FROM design_rounds WHERE id=? AND status != 'applying'", (rid,))
        audit(conn, "operator", "design_round_dismissed", f"round={rid}")
        conn.commit()
        return {"id": rid, "dismissed": True}
    finally:
        conn.close()


@app.get("/api/design/{rid}/mock/{variant}")
def design_mock(rid: int, variant: str):
    try:
        path = studio.mock_path(rid, variant)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if not path.is_file():
        raise HTTPException(404, "mock not generated yet")
    # LLM-generated HTML is untrusted: render with zero script authority
    return FileResponse(path, media_type="text/html", headers={
        "Content-Security-Policy":
            "sandbox; default-src 'none'; style-src 'unsafe-inline'; img-src data:; font-src data:",
    })


# --- live events (SSE) ---

@app.get("/api/events")
async def events():
    async def stream():
        try:
            from watchfiles import awatch
        except ImportError:
            yield "event: error\ndata: watchfiles missing\n\n"
            return
        watch_paths = [p for p in (
            settings.claude_dir / "skills",
            settings.claude_dir / "agents",
            settings.claude_dir / "projects" / primary_namespace() / "memory",
            settings.claude_dir / "history.jsonl",
        ) if p.exists()]
        yield f"data: {json.dumps({'type': 'hello', 'ts': time.time()})}\n\n"

        queue: asyncio.Queue = asyncio.Queue()

        async def watcher():
            # Dangling symlinks (several live in skills/ + agents/) are re-reported as
            # "changed" on EVERY poll cycle — filter to paths that exist, and rate-limit,
            # or the SPA is driven into a permanent refetch loop.
            last_emit = 0.0
            async for changes in awatch(*watch_paths):
                real = [str(p) for _, p in changes if Path(p).exists()][:10]
                now = time.monotonic()
                if real and now - last_emit >= 2.0:
                    last_emit = now
                    await queue.put(real)

        task = asyncio.create_task(watcher())
        try:
            while True:
                try:
                    changed = await asyncio.wait_for(queue.get(), timeout=25)
                    yield f"data: {json.dumps({'type': 'change', 'paths': changed})}\n\n"
                except asyncio.TimeoutError:
                    yield f"data: {json.dumps({'type': 'ping', 'ts': time.time()})}\n\n"
        finally:
            task.cancel()

    return StreamingResponse(stream(), media_type="text/event-stream")


# --- SPA ---
DIST = REPO_ROOT / "frontend" / "dist"
if DIST.is_dir():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

    @app.get("/{path:path}")
    def spa(path: str):
        target = DIST / path
        if path and target.is_file():
            return FileResponse(target)
        return FileResponse(DIST / "index.html")
