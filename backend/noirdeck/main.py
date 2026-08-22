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

from . import (
    ai_runtime,
    arming,
    ask,
    consult,
    digest,
    environment,
    guided,
    hygiene,
    improve,
    licensing,
    local_models,
    preview,
    scheduler,
    secrets_scan,
    vault,
)
from . import (
    share as share_mod,
)
from .builds import BuildRunner
from .config import Settings, primary_namespace
from .db import audit, connect, init_db, utcnow
from .design import DesignStudio
from .miner.heuristics import run_heuristics
from .miner.runner import run_llm_mining
from .overnight import _kill_group as overnight_kill_group
from .overnight import requeue_stale_running, route_agent, route_model
from .paths import web_dir
from .proposals import ProposalError, approve, dismiss, list_proposals, revert
from .qa import evaluate_fleet, evaluate_project
from .readers import history as hist
from .readers.commits import fleet_feed, fleet_flags, follow_on_flags, recent_commits
from .readers.files import FilesError, list_dir, read_file
from .readers.fleet import cached_fleet, fleet, fleet_attention
from .readers.memories import cached_memories, list_memories, memory_stats
from .readers.sessions import namespace_display, recent_sessions
from .readers.skills import list_agents, list_skills
from .version import VERSION
from .workspace import WorkspaceError, WorkspaceManager, init_repo, latest_transcript_session_id, takeover_prompt

settings = Settings.load()
init_db(settings.db_path)
SERVER_STARTED_AT = datetime.now(timezone.utc)
app = FastAPI(title="noirdeck", version=VERSION)

# ── browser-boundary hardening ────────────────────────────────────────────────
# Loopback binding alone does not stop the user's own BROWSER being used against
# the API: DNS rebinding defeats "it's only on 127.0.0.1" (attacker domain resolves
# to 127.0.0.1 → same-origin), and WebSockets have no same-origin policy at all:
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
        return True  # non-browser client (curl, tests): host check still applies
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
    except Exception:  # noqa: BLE001 - warming must never block or kill startup
        pass


import threading  # noqa: E402

threading.Thread(target=_prewarm, daemon=True).start()

# Recurring jobs. Off in a checkout (systemd timers own them there), on when
# installed: see scheduler.enabled(). Every job is still fail-closed behind
# its own arming contract, so an enabled scheduler grants no new authority.
_scheduler = scheduler.Scheduler(settings)
if scheduler.enabled():
    _scheduler.start()


@app.get("/api/scheduler")
def scheduler_status():
    """Will unattended work actually run? Both halves of the answer, in one place.

    This used to report only whether the scheduler process was alive, while the
    arming contracts lived on a different screen. Each half is useless alone: a
    running scheduler with no contract runs nothing, and a live contract with no
    scheduler runs nothing: and both look identical to "it was a quiet night".
    Answering half a question in two places is how a user concludes the product is
    broken when it is merely off.
    """
    base = _scheduler.status()
    conn = db()
    try:
        contracts = arming.status(conn)
    finally:
        conn.close()
    live_contracts = {k: v for k, v in contracts.items() if v.get("live")}
    scheduler_on = bool(base.get("enabled"))
    return {
        **base,
        "contracts": contracts,
        # The one sentence a user needs. Computed here rather than in the UI so the
        # API and the screen can never disagree about it.
        "will_run": scheduler_on and bool(live_contracts),
        "blocked_by": (
            None
            if scheduler_on and live_contracts
            else "nothing is armed"
            if scheduler_on
            else "the scheduler is not running here"
        ),
    }


def db():
    return connect(settings.db_path)


@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "version": VERSION,
        "server_started_at": SERVER_STARTED_AT.isoformat(),
        "server_now": datetime.now(timezone.utc).isoformat(),
        "frontend_dir": str(web_dir()),
        "claude_dir": str(settings.claude_dir),
        # so a MISSING workspace is distinguishable from an EMPTY one
        "claude_dir_ready": settings.claude_dir_ready,
        "mining_armed": settings.mining_armed,
        "overnight_armed": settings.overnight_armed,
    }


@app.get("/api/overview")
def overview():
    records = hist.load_history(settings.claude_dir)
    stats = hist.history_stats(records)
    sessions = recent_sessions(settings.claude_dir, limit=12)
    states = cached_fleet(settings.projects_dir, refresh=True)
    conn = db()
    try:
        pending = conn.execute("SELECT COUNT(*) c FROM proposals WHERE status='proposed'").fetchone()["c"]
        queue_counts = {
            r["status"]: r["c"] for r in conn.execute("SELECT status, COUNT(*) c FROM queue GROUP BY status").fetchall()
        }
        secrets_open = conn.execute("SELECT COUNT(*) c FROM secret_findings WHERE status='open'").fetchone()["c"]
    finally:
        conn.close()
    mems = cached_memories(settings.claude_dir, refresh=True)
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
        # surfaced on every page load: a cleartext credential in the knowledge
        # tree is the one finding that should never wait for someone to go looking
        "secrets_open": secrets_open,
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
    # no "groups": filename-token clustering was removed (see readers/memories.py)
    return {"stats": memory_stats(mems), "memories": mems}


def _improve_assets() -> dict:
    """Addable estate targets for the UI dropdowns: every path offered here
    already satisfies the proposals write allowlist (skills + the primary
    memory namespace), so 'addable' and 'approvable' can never disagree."""
    ns = primary_namespace()
    skills = [
        {"label": s["name"], "target_path": f"skills/{s['dir']}/SKILL.md"} for s in list_skills(settings.claude_dir)
    ]
    memories = [
        {"label": m["name"], "target_path": f"projects/{ns}/memory/{m['file']}"}
        for m in list_memories(settings.claude_dir)
        if m["namespace"] == ns
    ]
    return {"skill": skills, "memory": memories}


class ImproveRepoBody(BaseModel):
    project: str
    enabled: bool = True
    # per-repo model override; "" or null clears back to the env default.
    # Absent field = leave unchanged (the enable/disable toggle omits it).
    model: str | None = None


@app.get("/api/improve")
def improve_status():
    # one tags fetch serves both fields: two sequential calls stalled the
    # panel ~10s when ollama was down (each timing out separately)
    avail = improve.available_models()
    conn = db()
    try:
        return {
            "armed": improve.armed(),
            "model": improve.local_model(),
            "model_available": improve._model_in(improve.local_model(), avail),
            "models": avail,
            "repos": [dict(r) for r in conn.execute("SELECT * FROM improve_repos ORDER BY project").fetchall()],
            "changes": [
                dict(r) for r in conn.execute("SELECT * FROM improve_changes ORDER BY id DESC LIMIT 50").fetchall()
            ],
            "learning": improve.decision_stats(conn),
            "targets": [
                dict(r) | {"armed": bool(r["armed_until"] and r["armed_until"] > utcnow())}
                for r in conn.execute("SELECT * FROM improve_targets ORDER BY kind, target_path").fetchall()
            ],
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
            # can't validate against a dead ollama: refuse honestly rather
            # than claiming the model isn't pulled
            raise HTTPException(503, "Ollama is unreachable: cannot validate the model")
        if model not in avail:
            # only locally-pulled Ollama tags are assignable: never a free-form
            # string that would reach the generate call, never a cloud model
            raise HTTPException(400, f"model {model!r} is not pulled locally")
    conn = db()
    try:
        conn.execute(
            "INSERT INTO improve_repos (project, enabled, created_at) VALUES (?,?,?) "
            "ON CONFLICT(project) DO UPDATE SET enabled=excluded.enabled",
            (body.project, int(body.enabled), utcnow()),
        )
        if "model" in body.model_fields_set:
            conn.execute("UPDATE improve_repos SET model=? WHERE project=?", (model, body.project))
        conn.commit()
        audit(
            conn,
            "operator",
            "improve_repo_mapped",
            f"{body.project} enabled={int(body.enabled)}"
            + (f" model={model or 'default'}" if "model" in body.model_fields_set else ""),
        )
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
            raise HTTPException(503, "Ollama is unreachable: cannot validate the model")
        if model not in avail:
            raise HTTPException(400, f"model {model!r} is not pulled locally")
    conn = db()
    try:
        # added DISARMED: arming is a separate, deliberate act
        conn.execute(
            "INSERT INTO improve_targets (kind, target_path, model, created_at) "
            "VALUES (?,?,?,?) ON CONFLICT(target_path) DO UPDATE SET model=excluded.model",
            (body.kind, body.target_path, model, utcnow()),
        )
        conn.commit()
        audit(conn, "operator", "improve_target_added", f"{body.kind} {body.target_path} model={model or 'default'}")
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
        audit(conn, "operator", f"improve_target_{body.action}", f"id={tid} {row['target_path']} {detail}")
        return {"id": tid, "action": body.action}
    finally:
        conn.close()


@app.post("/api/improve/run")
def improve_run():
    require_license("improve")
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
        out = vault.status(conn)
    finally:
        conn.close()
    # the disclosure travels with the status so the UI can never show one
    # without the other
    out["manifest"] = vault.manifest(settings)
    return out


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
        return {
            "contracts": arming.status(conn),
            "env": {"overnight": settings.overnight_armed, "mining": settings.mining_armed},
        }
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
    return hist.search_grouped(hist.load_history(settings.claude_dir), q)


@app.get("/api/fleet")
def fleet_route():
    return cached_fleet(settings.projects_dir, refresh=True)


_commit_cache: dict = {"ts": 0.0, "data": None}


@app.get("/api/commits")
def commits_route():
    import time as _t

    if _commit_cache["data"] is not None and _t.monotonic() - _commit_cache["ts"] < 120:
        return _commit_cache["data"]
    data = {"feed": fleet_feed(settings.projects_dir), "follow_on": fleet_flags(settings.projects_dir)}
    _commit_cache.update(ts=_t.monotonic(), data=data)
    return data


def build_kickoff(project: str, repo, state: dict, sess: list[dict]) -> str:
    return (
        f"/operate: orient from the {project} project memory index first. "
        f"Branch '{state['branch']}'"
        + (f" has {state['dirty_files']} uncommitted file(s)" if state["dirty_files"] else "")
        + (f" and {state['unpushed_commits']} unpushed commit(s)" if state["unpushed_commits"] else "")
        + ". "
        + (
            f'Last session ended unfinished: "{sess[0]["last_assistant"][-200:]}": pick that up first.'
            if sess and sess[0]["open_loop"]
            else "No open loop detected in the last session."
        )
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


# --- credential scanning ---
# Report-only. The scheduled job never edits or moves anything; quarantine is a
# human action addressed by explicit finding id (see secrets_scan.py).


class SecretScanBody(BaseModel):
    # Transcripts are tens of thousands of files, so they are opt-in per run
    # rather than silently skipped: "did not look" must not read as "clean".
    include_transcripts: bool = False


class SecretDecisionBody(BaseModel):
    note: str = ""


@app.get("/api/secrets")
def secrets_list(status: str = "open"):
    conn = db()
    try:
        findings = secrets_scan.list_findings(conn, status)
        counts = {
            r["status"]: r["c"]
            for r in conn.execute("SELECT status, COUNT(*) c FROM secret_findings GROUP BY status").fetchall()
        }
        last = conn.execute(
            "SELECT ts, detail FROM audit_log WHERE actor='secret_scan' ORDER BY id DESC LIMIT 1"
        ).fetchone()
        return {
            "findings": findings,
            "counts": counts,
            "last_scan": dict(last) if last else None,
        }
    finally:
        conn.close()


@app.post("/api/secrets/scan")
def secrets_scan_route(body: SecretScanBody):
    return secrets_scan.run_scan(settings, include_transcripts=body.include_transcripts)


@app.post("/api/secrets/{fid}/acknowledge")
def secrets_ack_route(fid: int, body: SecretDecisionBody):
    conn = db()
    try:
        return secrets_scan.acknowledge(conn, fid, body.note)
    except secrets_scan.SecretScanError as e:
        raise HTTPException(409, str(e))
    finally:
        conn.close()


class SecretSweepBody(BaseModel):
    # EXPLICIT ids, always. The estate rule is that irreversible actions are selected
    # by id and never by a filter, a time window or a LIMIT: so there is deliberately
    # no "sweep everything" shape here, and the plan endpoint is what produces the list.
    ids: list[int]
    confirm: bool = False


@app.get("/api/secrets/sweep")
def secrets_sweep_plan(ids: str | None = None):
    """What a sweep would move, grouped by file, moving nothing."""
    wanted = [int(x) for x in ids.split(",") if x.strip().isdigit()] if ids else None
    conn = db()
    try:
        return secrets_scan.plan_sweep(conn, settings.claude_dir, wanted)
    finally:
        conn.close()


@app.post("/api/secrets/sweep")
def secrets_sweep(body: SecretSweepBody):
    conn = db()
    try:
        return secrets_scan.sweep(conn, settings.claude_dir, body.ids, confirm=body.confirm)
    finally:
        conn.close()


@app.post("/api/secrets/{fid}/quarantine")
def secrets_quarantine_route(fid: int):
    conn = db()
    try:
        return secrets_scan.quarantine(conn, settings.claude_dir, fid)
    except secrets_scan.SecretScanError as e:
        raise HTTPException(409, str(e))
    finally:
        conn.close()


# --- local models (Ollama) ---
# Report-then-act: every mutating call needs confirm=true, because installing a
# binary and downloading multiple gigabytes are both things a page load must never
# start on its own.


class LocalModelBody(BaseModel):
    confirm: bool = False


class LocalPullBody(BaseModel):
    tag: str
    confirm: bool = False


@app.get("/api/local-models")
def local_models_overview():
    # the recommendation order is keyed off what this person actually works on
    stats = hist.history_stats(hist.load_history(settings.claude_dir))
    return local_models.overview(top_slash=stats.get("top_slash"), top_projects=stats.get("top_projects"))


@app.post("/api/local-models/install")
def local_models_install(body: LocalModelBody):
    try:
        return local_models.install(confirm=body.confirm)
    except local_models.LocalModelError as e:
        raise HTTPException(409, str(e))


@app.post("/api/local-models/serve")
def local_models_serve():
    try:
        return local_models.serve()
    except local_models.LocalModelError as e:
        raise HTTPException(409, str(e))


@app.post("/api/local-models/pull")
def local_models_pull(body: LocalPullBody):
    try:
        return local_models.pull(body.tag, confirm=body.confirm)
    except local_models.LocalModelError as e:
        raise HTTPException(409, str(e))


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
    # body.overwrite is deliberately NOT forwarded: approval is create-only and
    # there is no relaxation of that from the API surface (see proposals.py).
    conn = db()
    try:
        return approve(conn, settings.claude_dir, pid)
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
    require_license("mining")
    conn = db()
    try:
        return run_llm_mining(conn, settings)
    finally:
        conn.close()


@app.get("/api/insights")
def insights():
    conn = db()
    try:
        return [dict(r) for r in conn.execute("SELECT * FROM insights ORDER BY id DESC LIMIT 100").fetchall()]
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
    runner: str | None = None
    model: str | None = None
    weight: str | None = None  # None = auto-routed; 'light' | 'heavy' to override
    knowledge_pack_id: int | None = None


class AnswerBody(BaseModel):
    answer: str


@app.get("/api/queue")
def queue_list():
    conn = db()
    try:
        return [dict(r) for r in conn.execute("SELECT * FROM queue ORDER BY id DESC LIMIT 200").fetchall()]
    finally:
        conn.close()


@app.post("/api/queue")
def queue_add(body: TaskBody):
    """Queue a task for unattended work.

    Pressing this used to accept the task and then never run it, because the
    runner needs an arming contract and creating one was a separate screen with
    three numbers to invent. "Run later" that does not run later is worse than a
    refusal. Queuing IS the intent, so it arms with a default budget when nothing
    is armed. The contract is unchanged in kind: expiring, task- and token-capped,
    re-checked before every task: and the response says what was armed, so the
    operator can see and revoke it.
    """
    require_license("overnight")
    repo = settings.projects_dir / body.project
    if not (repo.is_dir() and (repo / ".git").exists()):
        raise HTTPException(400, f"unknown project {body.project}")
    if body.weight not in (None, "light", "heavy"):
        raise HTTPException(400, "weight must be light or heavy (omit for auto)")
    conn = db()
    try:
        prefs = ai_runtime.workspace_preferences(conn)
        runner = body.runner or prefs["runner"] or "claude"
        try:
            runner = ai_runtime.runner_spec(runner).id
            chosen_model = ai_runtime.validate_model_id(body.model if body.model is not None else prefs["model"])
        except ai_runtime.RuntimeErrorConfig as e:
            raise HTTPException(400, str(e))
        prompt = body.prompt
        if body.knowledge_pack_id is not None:
            pack = conn.execute("SELECT body FROM workspace_knowledge WHERE id=?", (body.knowledge_pack_id,)).fetchone()
            if not pack:
                raise HTTPException(404, "no such knowledge pack")
            prompt = f"{pack['body']}\n\nTASK:\n{body.prompt}"
        text = body.title + " " + prompt
        model = chosen_model or (route_model(text) if runner == "claude" else ai_runtime.default_model(runner))
        agent = route_agent(text, settings.claude_dir) if runner == "claude" else None
        cur = conn.execute(
            "INSERT INTO queue (project,title,prompt,agent_type,model,runner,weight,status,created_at) "
            "VALUES (?,?,?,?,?,?,?,'queued',?)",
            (
                str(repo),
                body.title,
                prompt,
                agent,
                model,
                runner,
                body.weight,
                utcnow(),
            ),
        )
        audit(
            conn,
            "operator",
            "task_queued",
            f"id={cur.lastrowid} runner={runner} model={model} title={body.title[:80]}",
        )
        # Arm with defaults if nothing is armed, so the task actually runs. Never
        # EXTEND or top up a live contract: the operator set that budget, and
        # silently widening it is exactly the kind of thing arming exists to prevent.
        armed_now = None
        if not arming.status(conn).get("overnight", {}).get("live"):
            contract = arming.arm(conn, "overnight")
            armed_now = {
                "hours": arming.DEFAULT_HOURS,
                "max_tasks": arming.DEFAULT_MAX_TASKS,
                "max_tokens": arming.DEFAULT_MAX_TOKENS,
                "armed_until": contract["armed_until"],
            }
            audit(conn, "operator", "armed_by_queueing", f"task={cur.lastrowid} defaults applied")
        conn.commit()
        return {"id": cur.lastrowid, "runner": runner, "model": model, "armed": armed_now}
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
        conn.execute("UPDATE queue SET answer=?, status='queued', question=NULL WHERE id=?", (body.answer, tid))
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


@app.post("/api/queue/{tid}/takeover")
def queue_takeover(tid: int):
    """Take a running autonomous task away from the runner and continue it yourself.

    Stops the unattended child, then opens an INTERACTIVE session resuming the same
    conversation, in the same repo, so you inherit its context instead of starting
    cold. The task is marked `claimed`: a human owns it, which is deliberately not
    done and not failed.

    Why adopt-and-resume rather than attaching to the live process: an autonomous
    task runs `claude -p`, which has no input loop: there is nothing to type into.
    Handing it over therefore means ending the headless run and resuming its
    transcript interactively. The cost is a brief gap and the loss of any turn in
    flight; the gain is that the work so far, and its conversation, carry over.
    """
    conn = db()
    try:
        row = conn.execute("SELECT * FROM queue WHERE id=?", (tid,)).fetchone()
        if not row:
            raise HTTPException(404, f"no task {tid}")
        if row["status"] != "running":
            raise HTTPException(
                409, f"task {tid} is {row['status']}, not running: only a running task can be taken over"
            )

        project_dir = Path(row["project"]).expanduser()
        # queue.project is stored as a path; the workspace addresses repos by name
        # and re-validates containment itself, so hand it the name.
        project_name = project_dir.name

        sid = row["transcript_session_id"] or latest_transcript_session_id(settings.claude_dir, project_dir)

        # Claim BEFORE killing: the runner checks claimed_at the moment its child
        # dies, and if the kill landed first it would record a failure for a task
        # that was actually adopted.
        conn.execute("UPDATE queue SET status='claimed', claimed_at=? WHERE id=?", (utcnow(), tid))
        conn.commit()

        stopped = bool(row["worker_pid"]) and overnight_kill_group(row["worker_pid"])

        try:
            term = workspace.start(project_name, resume_session_id=sid) if sid else workspace.start(project_name)
        except WorkspaceError as e:
            # The task is already claimed and its child stopped, so say plainly that
            # the handover half-happened rather than implying nothing changed.
            raise HTTPException(
                409,
                f"task {tid} was stopped and marked claimed, but a session could not be opened: {e}",
            ) from e

        audit(
            conn,
            "operator",
            "task_taken_over",
            f"task={tid} project={project_name} session={term.id} resumed={sid or 'no transcript found'} "
            f"child_stopped={stopped}",
        )
        conn.commit()
        return {
            "task_id": tid,
            "session_id": term.id,
            "project": project_name,
            "resumed_conversation": bool(sid),
            "child_stopped": stopped,
            "note": (
                "Resuming the task's own conversation."
                if sid
                else "No transcript was found for this task, so this is a fresh session in the same repo: "
                "the task's context did not carry over."
            ),
        }
    finally:
        conn.close()


class WorkspaceStart(BaseModel):
    project: str
    briefing: bool = False
    resume_session_id: str | None = None
    runner: str | None = None
    model: str | None = None
    knowledge_pack_id: int | None = None


class RepoBody(BaseModel):
    name: str


class WorkspaceDefaultsBody(BaseModel):
    runner: str = "claude"
    model: str | None = None
    knowledge_source_runner: str = "claude"
    knowledge_source_model: str | None = None
    method_advisor: bool = False


class WorkspaceKnowledgeBody(BaseModel):
    project: str
    source_runner: str = "claude"
    source_model: str | None = None
    target_runner: str = "claude"
    target_model: str | None = None


class WorkspaceMethodBody(BaseModel):
    project: str
    prompt: str = ""


class WorkspaceTakeoverBody(BaseModel):
    runner: str = "claude"
    model: str | None = None
    close_source: bool = False


@app.get("/api/workspace/runtimes")
def workspace_runtimes():
    conn = db()
    try:
        bundles = [
            dict(r)
            for r in conn.execute(
                "SELECT id,project,source_runner,source_model,target_runner,target_model,created_at "
                "FROM workspace_knowledge ORDER BY id DESC LIMIT 10"
            ).fetchall()
        ]
        return {
            "runners": ai_runtime.runner_catalog(),
            "defaults": ai_runtime.workspace_preferences(conn),
            "knowledge_bundles": bundles,
        }
    finally:
        conn.close()


@app.post("/api/workspace/defaults")
def workspace_defaults(body: WorkspaceDefaultsBody):
    conn = db()
    try:
        try:
            prefs = ai_runtime.save_workspace_preferences(
                conn,
                body.runner,
                body.model,
                body.knowledge_source_runner,
                body.knowledge_source_model,
                body.method_advisor,
            )
        except ai_runtime.RuntimeErrorConfig as e:
            raise HTTPException(400, str(e))
        audit(
            conn,
            "operator",
            "workspace_defaults_saved",
            f"runner={prefs['runner']} model={prefs['model'] or 'default'} source={prefs['knowledge_source_runner']}",
        )
        return prefs
    finally:
        conn.close()


@app.post("/api/workspace/method")
def workspace_method(body: WorkspaceMethodBody):
    repo = settings.projects_dir / body.project
    if not (repo.is_dir() and (repo / ".git").exists()):
        raise HTTPException(404, f"no project repo {body.project}")
    conn = db()
    try:
        return ai_runtime.workspace_method_suggestion(settings, conn, body.project, body.prompt)
    finally:
        conn.close()


@app.post("/api/workspace/knowledge")
def workspace_knowledge(body: WorkspaceKnowledgeBody):
    repo = settings.projects_dir / body.project
    if not (repo.is_dir() and (repo / ".git").exists()):
        raise HTTPException(404, f"no project repo {body.project}")
    try:
        source = ai_runtime.runner_spec(body.source_runner).id
        target = ai_runtime.runner_spec(body.target_runner).id
        source_model = ai_runtime.validate_model_id(body.source_model)
        target_model = ai_runtime.validate_model_id(body.target_model)
        pack = ai_runtime.build_transfer_pack(settings, body.project, source, source_model, target, target_model)
    except ai_runtime.RuntimeErrorConfig as e:
        raise HTTPException(400, str(e))
    conn = db()
    try:
        created = utcnow()
        cur = conn.execute(
            "INSERT INTO workspace_knowledge "
            "(project,source_runner,source_model,target_runner,target_model,body,created_at) VALUES (?,?,?,?,?,?,?)",
            (body.project, source, source_model, target, target_model, pack, created),
        )
        conn.commit()
        audit(
            conn,
            "operator",
            "workspace_knowledge_created",
            f"id={cur.lastrowid} project={body.project} {source}->{target}",
        )
        return {
            "id": cur.lastrowid,
            "project": body.project,
            "source_runner": source,
            "source_model": source_model,
            "target_runner": target,
            "target_model": target_model,
            "body": pack,
            "created_at": created,
        }
    finally:
        conn.close()


@app.get("/api/workspace")
async def workspace_list():
    return workspace.listing()


# async so TermSession.start() runs ON the event loop: add_reader needs it;
# a sync endpoint lands in the threadpool where get_running_loop() raises
@app.post("/api/workspace")
async def workspace_start(body: WorkspaceStart):
    require_license("builds")
    initial = None
    runner = body.runner
    model = body.model
    conn = db()
    try:
        prefs = ai_runtime.workspace_preferences(conn)
    finally:
        conn.close()
    runner = runner or prefs["runner"]
    model = model if model is not None else prefs["model"]
    if body.briefing and not body.resume_session_id:
        repo = settings.projects_dir / body.project
        ns = str(repo).replace("/", "-")
        from .readers.fleet import repo_state

        sess = recent_sessions(settings.claude_dir, limit=5, namespace=ns)
        initial = build_kickoff(body.project, repo, repo_state(repo), sess)
    if body.knowledge_pack_id is not None:
        conn = db()
        try:
            pack = conn.execute("SELECT body FROM workspace_knowledge WHERE id=?", (body.knowledge_pack_id,)).fetchone()
            if not pack:
                raise HTTPException(404, "no such knowledge pack")
            initial = f"{pack['body']}\n\n{initial or 'Open the repo and wait for the operator task.'}"
        finally:
            conn.close()
    try:
        term = workspace.start(
            body.project,
            initial_prompt=initial,
            resume_session_id=body.resume_session_id,
            runner_id=runner,
            model=model,
        )
    except WorkspaceError as e:
        raise HTTPException(409, str(e))
    conn = db()
    try:
        audit(
            conn,
            "operator",
            "workspace_started",
            f"id={term.id} project={body.project} runner={term.runner} model={term.model or '-'} "
            f"resume={body.resume_session_id or '-'}",
        )
    finally:
        conn.close()
    return {"id": term.id, "project": term.project, "runner": term.runner, "model": term.model}


@app.delete("/api/workspace/{sid}")
async def workspace_stop(sid: str):
    try:
        workspace.stop(sid)
    except WorkspaceError as e:
        raise HTTPException(404, str(e))
    return {"id": sid, "stopped": True}


@app.post("/api/workspace/{sid}/takeover")
async def workspace_takeover(sid: str, body: WorkspaceTakeoverBody):
    try:
        source = workspace.get(sid)
    except WorkspaceError as e:
        raise HTTPException(404, str(e))
    try:
        runner = ai_runtime.runner_spec(body.runner).id
        model = ai_runtime.validate_model_id(body.model)
    except ai_runtime.RuntimeErrorConfig as e:
        raise HTTPException(400, str(e))

    project = source.project
    initial = takeover_prompt(source, runner, model)
    if body.close_source:
        try:
            workspace.stop(sid)
        except WorkspaceError:
            pass
    try:
        term = workspace.start(project, initial_prompt=initial, runner_id=runner, model=model)
    except WorkspaceError as e:
        raise HTTPException(409, str(e))
    conn = db()
    try:
        audit(
            conn,
            "operator",
            "workspace_takeover",
            f"from={sid} to={term.id} project={project} runner={runner} model={model or '-'} "
            f"closed={int(body.close_source)}",
        )
    finally:
        conn.close()
    return {
        "id": term.id,
        "project": project,
        "runner": term.runner,
        "model": term.model,
        "source_id": sid,
        "closed_source": body.close_source,
    }


class ShareBody(BaseModel):
    note: str = ""


@app.post("/api/workspace/{sid}/share")
def workspace_share(sid: str, body: ShareBody):
    """Export what happened, redacted: not a live invite.

    Stage 0 of session sharing: no socket is opened, nothing binds beyond loopback and
    no second identity exists, so the auth layer docs/SECURITY.md requires before any
    exposure is not bypassed. The response includes what redaction removed AND what a
    re-scan still found, because the operator is about to send this to a person.
    """
    try:
        term = workspace.get(sid)
    except WorkspaceError as e:
        raise HTTPException(404, str(e))
    out = share_mod.build_export(
        scrollback=term.transcript_tail(max_chars=share_mod.MAX_CHARS),
        project=term.project,
        runner=term.runner,
        model=term.model,
        note=body.note,
    )
    conn = db()
    try:
        # Audited: exporting a transcript is a disclosure event, and "who shared what,
        # when" is a question that only has an answer if it was recorded at the time.
        audit(
            conn,
            "operator",
            "session_shared",
            f"session={sid} project={term.project} chars={out['chars']} "
            f"secrets_removed={out['secrets_removed']} residual={out['residual_findings']}",
        )
    finally:
        conn.close()
    return out


class PauseBody(BaseModel):
    label: str | None = None


@app.get("/api/workspace/paused")
async def workspace_paused_list():
    conn = db()
    try:
        return [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM paused_sessions WHERE resumed_at IS NULL AND discarded_at IS NULL "
                "ORDER BY id DESC LIMIT 20"
            ).fetchall()
        ]
    finally:
        conn.close()


@app.delete("/api/workspace/paused/{pid}")
async def workspace_discard_paused(pid: int):
    """Drop a paused session without resuming it.

    Discarding removes it from the list but does NOT kill anything: the process
    died at pause time. What is lost is the ability to resume that transcript,
    which is why it is an explicit act by id rather than a bulk clear.
    """
    conn = db()
    try:
        row = conn.execute(
            "SELECT * FROM paused_sessions WHERE id=? AND resumed_at IS NULL AND discarded_at IS NULL", (pid,)
        ).fetchone()
        if not row:
            raise HTTPException(404, "no such paused session (or already resumed/discarded)")
        conn.execute("UPDATE paused_sessions SET discarded_at=? WHERE id=?", (utcnow(), pid))
        conn.commit()
        audit(conn, "operator", "workspace_paused_discarded", f"id={pid} project={row['project']}")
        return {"discarded": pid, "project": row["project"]}
    finally:
        conn.close()


@app.post("/api/workspace/{sid}/pause")
async def workspace_pause(sid: str, body: PauseBody):
    """Park a live session for shutdown. Claude sessions capture their transcript
    id NOW (later 'most recent in cwd' may be a headless run's); every runtime
    stores runner/model so resume comes back through the same tool."""
    try:
        term = workspace.get(sid)
    except WorkspaceError as e:
        raise HTTPException(404, str(e))
    claude_session = latest_transcript_session_id(settings.claude_dir, term.cwd) if term.runner == "claude" else None
    project = term.project
    runner = term.runner
    model = term.model
    workspace.stop(sid)
    conn = db()
    try:
        cur = conn.execute(
            "INSERT INTO paused_sessions (project, claude_session_id, label, paused_at, runner, model) VALUES (?,?,?,?,?,?)",
            (project, claude_session, (body.label or "").strip()[:120] or None, utcnow(), runner, model),
        )
        conn.commit()
        audit(
            conn,
            "operator",
            "workspace_paused",
            f"id={sid} project={project} runner={runner} model={model or '-'} claude_session={claude_session or 'unknown'}",
        )
        return {
            "paused_id": cur.lastrowid,
            "project": project,
            "runner": runner,
            "model": model,
            "claude_session_id": claude_session,
        }
    finally:
        conn.close()


# async for the same add_reader reason as workspace_start
@app.post("/api/workspace/paused/{pid}/resume")
async def workspace_resume_paused(pid: int):
    conn = db()
    try:
        row = conn.execute("SELECT * FROM paused_sessions WHERE id=? AND resumed_at IS NULL", (pid,)).fetchone()
        if not row:
            raise HTTPException(404, "no such paused session (or already resumed)")
        runner = row["runner"] or "claude"
        try:
            term = workspace.start(
                row["project"],
                resume_session_id=row["claude_session_id"] if runner == "claude" else None,
                continue_last=runner == "claude" and row["claude_session_id"] is None,
                runner_id=runner,
                model=row["model"],
            )
        except WorkspaceError as e:
            raise HTTPException(409, str(e))
        conn.execute("UPDATE paused_sessions SET resumed_at=? WHERE id=?", (utcnow(), pid))
        conn.commit()
        audit(
            conn,
            "operator",
            "workspace_resumed",
            f"paused={pid} project={row['project']} runner={term.runner} model={term.model or '-'} new={term.id}",
        )
        return {"id": term.id, "project": row["project"], "runner": term.runner, "model": term.model}
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
    # WebSockets bypass same-origin policy: enforce the same boundary by hand
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
        return [_build_row(r) for r in conn.execute("SELECT * FROM builds ORDER BY id DESC LIMIT 50").fetchall()]
    finally:
        conn.close()


@app.post("/api/builds")
def builds_start(body: BuildStart):
    if len(body.prompt.strip()) < 40:
        raise HTTPException(
            400, "give the FULL brief: a build prompt under 40 chars will not produce production-quality software"
        )
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
            acceptance=guided.acceptance_criteria(body.answers),
        )
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
    require_license("ask")
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


# --- consult: a second model looks at the live session and offers advice ---
# Advisory only. The consultant is spawned read-only and its answer is text;
# there is deliberately no route that lets it change anything.


# --- licensing: who may use the model-backed features ---
# The console itself is never gated. Someone who installed noirdeck can always
# look around and reach the screen where a key is entered: gating the front
# door would mean a licence problem hides its own fix.


class LicenseBody(BaseModel):
    key: str


@app.get("/api/environment")
def environment_scan(refresh: bool = False):
    """What machine this is, and every assistant environment on it.

    On WSL that is two homes, not one, and the Windows half is the half noirdeck
    does not read. Cached in the module; `refresh=true` forces a re-scan after
    someone installs something.
    """
    return environment.scan_ai_environments(refresh=refresh)


@app.get("/api/license")
def license_status():
    return licensing.status()


@app.post("/api/license")
def license_save(body: LicenseBody):
    try:
        lic = licensing.save(body.key)
    except licensing.LicenseError as e:
        raise HTTPException(400, str(e))
    conn = db()
    try:
        # The key itself is never logged: only that one was accepted, for whom.
        audit(conn, "operator", "license_saved", f"email={lic.email} plan={lic.plan} exp={lic.expires_at.date()}")
    finally:
        conn.close()
    return licensing.status()


def require_license(feature: str) -> None:
    """Gate for a model-backed route. Raises 402 so the UI can tell a licence
    problem apart from a permission problem or a bug."""
    allowed, reason = licensing.allows(feature)
    if not allowed:
        raise HTTPException(402, reason)


class ConsultBody(BaseModel):
    session_id: str
    question: str = ""
    runner: str | None = None
    model: str | None = None


@app.post("/api/consult")
def consult_submit(body: ConsultBody):
    require_license("consult")
    try:
        term = workspace.get(body.session_id)
    except WorkspaceError as e:
        raise HTTPException(404, str(e))
    try:
        out = consult.submit(
            settings,
            project=term.project,
            scrollback=term.transcript_tail(consult.CONTEXT_CHARS),
            question=body.question,
            runner=body.runner,
            model=body.model,
            session_id=body.session_id,
        )
    except (ai_runtime.RuntimeErrorConfig, ValueError) as e:
        raise HTTPException(400, str(e))
    conn = db()
    try:
        # Log that a consultation happened and how much was scrubbed: never the
        # context itself, which is exactly the secret-bearing text in question.
        audit(
            conn,
            "operator",
            "consult_submitted",
            f"id={out['id']} runner={out['runner']} redactions={out['redactions']}",
        )
    finally:
        conn.close()
    return out


class ConsultWatchBody(BaseModel):
    session_id: str
    enabled: bool
    runner: str | None = None
    model: str | None = None


# Which sessions are being watched, and by whom. Off for every session until
# asked for: an observer that switched itself on would be a surprise, and a
# surprise observer of terminal output is the wrong kind of surprise.
_watching: dict[str, dict] = {}


def _watch_hook(term, chunk: bytes) -> None:
    """Called from the PTY reader for every chunk of output. Must stay cheap:
    scan only the tail, bail on the common path, and never block."""
    conf = _watching.get(term.id)
    if not conf:
        return
    signal = consult.detect_signal(chunk[-2048:].decode("utf-8", "replace"))
    if signal is None or not consult.cooled_down(term.id):
        return
    consult.submit(
        settings,
        project=term.project,
        scrollback=term.transcript_tail(consult.CONTEXT_CHARS),
        runner=conf.get("runner"),
        model=conf.get("model"),
        signal=signal,
        session_id=term.id,
    )


@app.post("/api/consult/watch")
def consult_watch(body: ConsultWatchBody):
    try:
        term = workspace.get(body.session_id)
    except WorkspaceError as e:
        raise HTTPException(404, str(e))
    if body.enabled:
        _watching[body.session_id] = {"runner": body.runner, "model": body.model}
        term.watch_hook = _watch_hook
    else:
        _watching.pop(body.session_id, None)
        term.watch_hook = None
    conn = db()
    try:
        audit(conn, "operator", "consult_watch", f"session={body.session_id} enabled={body.enabled}")
    finally:
        conn.close()
    return {"session_id": body.session_id, "watching": body.enabled}


@app.get("/api/consult")
def consult_recent():
    return consult.recent()


@app.get("/api/consult/{job_id}")
def consult_get(job_id: str):
    out = consult.get(job_id)
    if not out:
        raise HTTPException(404, f"no consultation {job_id}")
    return out


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


# --- Apply a UI: capture or brief → mock quickly → apply deliberately ---

studio = DesignStudio(settings)
studio.requeue_stale()


class DesignStart(BaseModel):
    project: str
    brief: str
    library: str = "landing"


class DesignCaptureBody(BaseModel):
    project: str


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
        raise HTTPException(400, "describe the surface: a few words minimum")
    try:
        rid = studio.propose(body.project, body.brief.strip(), body.library)
    except (ValueError, WorkspaceError) as e:
        raise HTTPException(409, str(e))
    return {"id": rid}


@app.post("/api/design/capture")
def design_capture(body: DesignCaptureBody):
    try:
        return studio.capture_design(body.project)
    except (ValueError, WorkspaceError) as e:
        raise HTTPException(409, str(e))


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
    return FileResponse(
        path,
        media_type="text/html",
        headers={
            "Content-Security-Policy": "sandbox; default-src 'none'; style-src 'unsafe-inline'; img-src data:; font-src data:",
        },
    )


# --- live events (SSE) ---


@app.get("/api/events")
async def events():
    async def stream():
        try:
            from watchfiles import awatch
        except ImportError:
            yield "event: error\ndata: watchfiles missing\n\n"
            return
        watch_paths = [
            p
            for p in (
                settings.claude_dir / "skills",
                settings.claude_dir / "agents",
                settings.claude_dir / "projects" / primary_namespace() / "memory",
                settings.claude_dir / "history.jsonl",
            )
            if p.exists()
        ]
        yield f"data: {json.dumps({'type': 'hello', 'ts': time.time()})}\n\n"

        queue: asyncio.Queue = asyncio.Queue()

        async def watcher():
            # Dangling symlinks (several live in skills/ + agents/) are re-reported as
            # "changed" on EVERY poll cycle: filter to paths that exist, and rate-limit,
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
# Bundled inside the wheel when installed, frontend/dist in a checkout.
DIST = web_dir()
if DIST is not None:
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

    @app.get("/{path:path}")
    def spa(path: str):
        target = DIST / path
        # Never serve outside the build: a crafted path must not escape it.
        if path and target.is_file() and DIST in target.resolve().parents:
            return FileResponse(target)
        return FileResponse(DIST / "index.html")
