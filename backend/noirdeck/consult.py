"""Consult — a second model looks at what you are doing and offers advice.

Two entry points, one spine:
  * "Ask for help" — you press the button, it consults now.
  * Watch mode     — it consults itself when the session shows a signal
                     (a traceback, a failing test, a non-zero exit).

Three properties hold for both, and none of them are optional:

1. ADVISORY ONLY. The consultant is spawned read-only and its answer is rendered
   as text you can read, copy or dismiss. It has no write path, no proposals
   spine, and nothing to approve — a watcher that could act would be precisely
   the thing noirdeck promises never to do.

2. REDACTED FIRST, ALWAYS. Terminal scrollback is the most secret-bearing text
   on this machine; it is why the vault deliberately excludes transcripts. Every
   character handed to a consultant passes through the miner's secret-shape
   redaction, whether that consultant is a local model or a hosted one. Local is
   not an excuse to skip it — the model is not the only thing that sees a prompt.

3. LOCAL BY DEFAULT. The default consultant is the local Ollama runner: zero
   egress, zero cost. Hosted runners are selectable but never the default, so
   sending your terminal to someone else's server is always a deliberate act.
"""

from __future__ import annotations

import re
import subprocess
import threading
import uuid
from datetime import datetime, timezone

from .ai_runtime import default_model, queue_argv, runner_spec, validate_model_id
from .config import Settings
from .miner.redact import redact

# A consultation is a glance, not an investigation: enough tail to see what just
# happened, capped so a long session cannot quietly become a huge prompt.
CONTEXT_CHARS = 6000
TIMEOUT_S = 180
MAX_TURNS = 6

# Ambient mode must not fire on every line. One failing build writes hundreds of
# lines; without a cooldown that is hundreds of consultations.
COOLDOWN_S = 120

DEFAULT_RUNNER = "ollama"

_lock = threading.Lock()
_jobs: dict[str, dict] = {}
_last_ambient: dict[str, datetime] = {}


def _now() -> datetime:
    return datetime.now(timezone.utc)


# Signals worth interrupting someone for. Deliberately narrow: a consultant that
# chimes in on ordinary output is noise, and noise gets the feature switched off.
_SIGNALS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("traceback", re.compile(r"^Traceback \(most recent call last\)", re.M)),
    ("python-error", re.compile(r"^\w*(Error|Exception): ", re.M)),
    ("test-failure", re.compile(r"^(FAILED|=+ FAILURES|\d+ failed)", re.M)),
    ("build-failure", re.compile(r"(?i)^(error|build failed|compilation failed)\b", re.M)),
    ("command-failed", re.compile(r"(?i)\bexit(ed with)? (code )?[1-9]\d*\b")),
)


def detect_signal(text: str) -> str | None:
    """Name the first signal in `text`, or None if nothing warrants a nudge."""
    for name, pattern in _SIGNALS:
        if pattern.search(text):
            return name
    return None


def cooled_down(session_id: str) -> bool:
    """True when ambient mode may fire again for this session."""
    last = _last_ambient.get(session_id)
    if last is None:
        return True
    return (_now() - last).total_seconds() >= COOLDOWN_S


def _context(raw: str) -> tuple[str, dict[str, int]]:
    """Redact, then take the tail. Redaction runs on the WHOLE text before the
    tail is cut — trimming first could slice a secret in half and leave a
    fragment that no longer matches its own pattern."""
    clean, counts = redact(raw)
    return clean[-CONTEXT_CHARS:], counts


def _prompt(project: str, question: str, context: str, signal: str | None) -> str:
    opening = (
        f"You are a second pair of eyes on a live coding session in the project {project!r}. "
        "Another AI assistant is doing the work; you are not driving."
        if signal is None
        else (
            f"You are watching a live coding session in the project {project!r} and just noticed "
            f"a {signal}. Another AI assistant is doing the work; you are not driving."
        )
    )
    asked = f"\n\nThe operator asks: {question}" if question else ""
    return (
        f"{opening}\n\n"
        "You have READ-ONLY access to the project. Rules:\n"
        "- Be useful or be silent. If you have nothing worth saying, reply exactly: NOTHING TO ADD.\n"
        "- Lead with the single most useful thing. No preamble, no summary of what you were asked.\n"
        "- Ground advice in what you can actually read. Say plainly when you are guessing.\n"
        "- Suggest; never instruct the other assistant, and never claim you changed anything.\n"
        "- Secrets in the transcript are already redacted; treat a redaction marker as opaque.\n"
        "- Keep it short — a few sentences, or a handful of bullets at most.\n\n"
        f"Recent terminal output (redacted, tail):\n---\n{context}\n---"
        f"{asked}"
    )


def _invoke(settings: Settings, runner_id: str, model: str, prompt: str) -> subprocess.CompletedProcess:
    """Seam for tests. readonly=True is load-bearing: it is what makes the
    consultant advisory rather than an unsupervised second writer."""
    argv = queue_argv(runner_id, model, MAX_TURNS, prompt, readonly=True)
    return subprocess.run(
        argv,
        capture_output=True,
        text=True,
        timeout=TIMEOUT_S,
        cwd=str(settings.projects_dir),
    )


def _run(settings: Settings, job_id: str) -> None:
    job = _jobs[job_id]
    try:
        proc = _invoke(settings, job["runner"], job["model"], job["_prompt"])
        out = (proc.stdout or "").strip()
        if proc.returncode != 0 and not out:
            job.update(status="failed", error=(proc.stderr or "").strip()[-400:] or "consultant failed")
        else:
            answer = _answer_text(out)
            if answer.strip().upper().startswith("NOTHING TO ADD"):
                job.update(status="quiet", answer="")
            else:
                job.update(status="done", answer=answer)
    except subprocess.TimeoutExpired:
        job.update(status="failed", error=f"consultant timed out after {TIMEOUT_S}s")
    except (OSError, ValueError) as exc:
        # A missing runner binary is the common case and must read as a plain
        # message, not a stack trace in the UI.
        job.update(status="failed", error=f"{type(exc).__name__}: {exc}")
    finally:
        job.pop("_prompt", None)
        job["finished_at"] = _now().isoformat()


def _answer_text(out: str) -> str:
    """Runners disagree about output shape; a CLI that returns a message LIST
    rather than an object has already burned us once. Take text where we find
    it and fall back to the raw string rather than losing the answer."""
    import json

    try:
        parsed = json.loads(out)
    except (ValueError, TypeError):
        return out
    if isinstance(parsed, dict):
        for key in ("result", "text", "content", "response"):
            val = parsed.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()
        return out
    if isinstance(parsed, list):
        for item in reversed(parsed):
            if isinstance(item, dict):
                val = item.get("result") or item.get("text") or item.get("content")
                if isinstance(val, str) and val.strip():
                    return val.strip()
    return out


def submit(
    settings: Settings,
    *,
    project: str,
    scrollback: str,
    question: str = "",
    runner: str | None = None,
    model: str | None = None,
    signal: str | None = None,
    session_id: str | None = None,
) -> dict:
    """Start a consultation. Returns immediately; poll with get()."""
    runner_id = runner or DEFAULT_RUNNER
    spec = runner_spec(runner_id)  # raises on an unknown runner id
    chosen = validate_model_id(model) or default_model(spec.id)

    context, redactions = _context(scrollback)
    job_id = uuid.uuid4().hex[:12]
    job = {
        "id": job_id,
        "project": project,
        "runner": spec.id,
        "runner_label": spec.label,
        "model": chosen,
        "question": question,
        "signal": signal,
        "status": "running",
        "answer": "",
        "error": "",
        # Surfaced so the operator can see redaction happened, not just trust it.
        "redactions": sum(redactions.values()) if redactions else 0,
        "started_at": _now().isoformat(),
        "finished_at": "",
        "_prompt": _prompt(project, question, context, signal),
    }
    with _lock:
        _jobs[job_id] = job
        if signal and session_id:
            _last_ambient[session_id] = _now()
    threading.Thread(target=_run, args=(settings, job_id), daemon=True).start()
    return {k: v for k, v in job.items() if not k.startswith("_")}


def get(job_id: str) -> dict:
    job = _jobs.get(job_id)
    if job is None:
        return {}
    return {k: v for k, v in job.items() if not k.startswith("_")}


def recent(limit: int = 20) -> list[dict]:
    jobs = sorted(_jobs.values(), key=lambda j: j["started_at"], reverse=True)[:limit]
    return [{k: v for k, v in j.items() if not k.startswith("_")} for j in jobs]
