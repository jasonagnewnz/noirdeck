"""Ask-your-estate — plain-English questions answered by a READ-ONLY headless
Claude session over ~/projects and the ~/.claude memory.

The read-only cage is layered: the session's tool set is restricted to
Read/Grep/Glob (no Bash, no Write, no Edit — the tools simply don't exist in
the session), and the pipeline guard hook rides along for depth. Answers are
ephemeral (in-memory): this is a question box, not a records system."""
from __future__ import annotations

import subprocess
import threading
import time
import uuid

from .config import Settings, model, primary_namespace
from .guard import guard_settings_args
from .overnight import parse_cli_json

MAX_QUESTION = 500
TIMEOUT_S = 300
KEEP = 20

_jobs: dict[str, dict] = {}
_lock = threading.Lock()


class AskError(RuntimeError):
    pass


def _prompt(settings: Settings, question: str) -> str:
    mem_index = settings.claude_dir / "projects" / primary_namespace() / "memory" / "MEMORY.md"
    return (
        "You are answering one question about this machine's code estate for its "
        "operator, who may be non-technical. You have READ-ONLY access.\n"
        f"- Projects live under {settings.projects_dir} (each subfolder is a repo).\n"
        f"- Long-term memory notes live under {mem_index.parent} — start with the "
        "index MEMORY.md, then read only the notes that look relevant.\n"
        "Ground every claim in something you actually read; if you cannot find the "
        "answer, say so plainly rather than guessing. Answer in plain English, "
        "concisely (a short paragraph, or a few bullet lines if listing).\n\n"
        f"QUESTION: {question}"
    )


def _invoke(settings: Settings, prompt: str) -> subprocess.CompletedProcess:
    """Seam for tests. Variadic --tools is placed last so it can't swallow flags."""
    from .workspace import claude_bin
    return subprocess.run(
        [claude_bin(), "-p", prompt, "--output-format", "json",
         "--model", model("build"), "--max-turns", "15",
         *guard_settings_args(),
         "--tools", "Read", "Grep", "Glob"],
        capture_output=True, text=True, timeout=TIMEOUT_S,
        cwd=str(settings.projects_dir),
    )


def _run(settings: Settings, job_id: str) -> None:
    job = _jobs[job_id]
    t0 = time.time()
    try:
        proc = _invoke(settings, _prompt(settings, job["question"]))
        if proc.returncode == 0 and proc.stdout:
            answer, _tin, tout = parse_cli_json(proc.stdout)
            job.update(status="done", answer=(answer or "").strip() or
                       "The session returned no answer — try asking more specifically.",
                       tokens_out=tout)
        else:
            job.update(status="error",
                       answer=f"The answer session failed (rc={proc.returncode}). "
                              f"{(proc.stderr or '').strip()[-200:]}")
    except subprocess.TimeoutExpired:
        job.update(status="error",
                   answer=f"Timed out after {TIMEOUT_S // 60} minutes — try a narrower question.")
    except Exception as exc:  # a background thread must never die silently
        job.update(status="error", answer=f"{type(exc).__name__}: {exc}"[:300])
    finally:
        job["seconds"] = round(time.time() - t0)


def submit(settings: Settings, question: str) -> dict:
    question = (question or "").strip()
    if not question:
        raise AskError("ask a question first")
    if len(question) > MAX_QUESTION:
        raise AskError(f"keep the question under {MAX_QUESTION} characters")
    with _lock:
        if any(j["status"] == "running" for j in _jobs.values()):
            raise AskError("an answer is already being worked on — wait for it to finish")
        job_id = uuid.uuid4().hex[:12]
        _jobs[job_id] = {"id": job_id, "question": question, "status": "running",
                         "answer": None, "seconds": None, "tokens_out": None,
                         "started_at": time.time()}
        while len(_jobs) > KEEP:
            oldest = min(_jobs, key=lambda k: _jobs[k]["started_at"])
            del _jobs[oldest]
    threading.Thread(target=_run, args=(settings, job_id), daemon=True).start()
    return {"id": job_id}


def get(job_id: str) -> dict:
    job = _jobs.get(job_id)
    if not job:
        raise AskError(f"no such question {job_id} (answers don't survive a restart)")
    return job


def recent() -> list[dict]:
    return sorted(_jobs.values(), key=lambda j: j["started_at"], reverse=True)
