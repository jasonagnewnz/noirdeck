"""Server-owned AI runtime registry.

The browser may choose a runner id and a model id, but it never supplies a
command. Every executable and flag shape lives here so adding Codex/Grok/custom
slots does not punch a hole through the workspace shell boundary.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from .config import Settings, primary_namespace
from .config import model as role_model
from .db import utcnow

RUNNER_RE = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")
MODEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/+-]{0,127}$")


class RuntimeErrorConfig(RuntimeError):
    pass


@dataclass(frozen=True)
class RunnerSpec:
    id: str
    label: str
    ide_label: str
    description: str
    bin_name: str
    bin_env: str
    models_env: str
    default_model_env: str
    default_model: str
    live_supported: bool
    queue_supported: bool
    knowledge_supported: bool = True
    supports_resume: bool = False
    supports_inline_prompt: bool = True


RUNNERS: dict[str, RunnerSpec] = {
    "claude": RunnerSpec(
        id="claude",
        label="Claude Code",
        ide_label="Claude IDE",
        description="Existing Claude Code workspace with skills, memory and transcript resume.",
        bin_name="claude",
        bin_env="NOIRDECK_CLAUDE_BIN",
        models_env="NOIRDECK_CLAUDE_MODELS",
        default_model_env="NOIRDECK_DEFAULT_CLAUDE_MODEL",
        default_model=role_model("build"),
        live_supported=True,
        queue_supported=True,
        supports_resume=True,
    ),
    "codex": RunnerSpec(
        id="codex",
        label="Codex",
        ide_label="Codex CLI",
        description="OpenAI Codex CLI against the same repo, hydrated with the same workspace context.",
        bin_name="codex",
        bin_env="NOIRDECK_CODEX_BIN",
        models_env="NOIRDECK_CODEX_MODELS",
        default_model_env="NOIRDECK_DEFAULT_CODEX_MODEL",
        default_model="gpt-5-codex",
        live_supported=True,
        queue_supported=True,
    ),
    "grok": RunnerSpec(
        id="grok",
        label="Grok / custom CLI",
        ide_label="Grok CLI",
        description="Optional external CLI slot. Set NOIRDECK_GROK_BIN to enable live/queued runs.",
        bin_name="grok",
        bin_env="NOIRDECK_GROK_BIN",
        models_env="NOIRDECK_GROK_MODELS",
        default_model_env="NOIRDECK_DEFAULT_GROK_MODEL",
        default_model="grok-code",
        live_supported=True,
        queue_supported=True,
    ),
    "ollama": RunnerSpec(
        id="ollama",
        label="Ollama local",
        ide_label="Local model",
        description="Local Ollama model chat against an injected repo transfer pack; no cloud calls.",
        bin_name="ollama",
        bin_env="NOIRDECK_OLLAMA_BIN",
        models_env="NOIRDECK_OLLAMA_MODELS",
        default_model_env="NOIRDECK_DEFAULT_OLLAMA_MODEL",
        default_model="qwen2.5-coder:7b",
        live_supported=True,
        queue_supported=True,
    ),
}


def _csv(env: str) -> list[str]:
    return [x.strip() for x in os.environ.get(env, "").split(",") if x.strip()]


def ollama_models() -> list[str]:
    try:
        url = os.environ.get("NOIRDECK_OLLAMA_URL", "http://127.0.0.1:11434") + "/api/tags"
        with urllib.request.urlopen(url, timeout=2) as r:
            tags = json.load(r)
        return sorted(m["name"] for m in tags.get("models", []) if m.get("name"))
    except (OSError, json.JSONDecodeError, ValueError):
        return []


def runner_spec(runner_id: str | None) -> RunnerSpec:
    rid = (runner_id or "claude").strip() or "claude"
    if not RUNNER_RE.fullmatch(rid) or rid not in RUNNERS:
        raise RuntimeErrorConfig(f"unknown AI runtime {rid!r}")
    return RUNNERS[rid]


def validate_model_id(model: str | None) -> str | None:
    if model is None:
        return None
    value = model.strip()
    if not value:
        return None
    if not MODEL_RE.fullmatch(value):
        raise RuntimeErrorConfig("model id may only contain letters, numbers, . _ : / + -")
    return value


def default_model(runner_id: str | None) -> str:
    spec = runner_spec(runner_id)
    if spec.id == "ollama":
        preferred = (
            os.environ.get(spec.default_model_env) or os.environ.get("NOIRDECK_LOCAL_MODEL") or spec.default_model
        )
        available = ollama_models()
        if not available or preferred in available:
            return preferred
        if ":" not in preferred and f"{preferred}:latest" in available:
            return f"{preferred}:latest"
        return available[0]
    return os.environ.get(spec.default_model_env, spec.default_model)


# The Claude line as it ships today, most capable first. The picker offers all of
# them; the pipeline roles (think/build/review) pin three of them by default.
# Update this list at each model release: an id that has been retired 404s at
# spawn time, which surfaces as a dead session rather than a clear error.
CLAUDE_MODELS = [
    "claude-fable-5",
    "claude-opus-5",
    "claude-sonnet-5",
    "claude-haiku-4-5",
]


def model_choices(runner_id: str | None) -> list[str]:
    spec = runner_spec(runner_id)
    choices = _csv(spec.models_env)
    if spec.id == "claude":
        choices += CLAUDE_MODELS
        choices += [role_model("build"), role_model("think"), role_model("review")]
    if spec.id == "ollama":
        choices += ollama_models()
    choices.append(default_model(spec.id))
    out: list[str] = []
    for choice in choices:
        if choice and choice not in out:
            out.append(choice)
    return out


def _which(bin_name: str) -> str | None:
    found = shutil.which(bin_name)
    if found:
        return found
    fallback = Path.home() / ".local" / "bin" / bin_name
    if fallback.is_file():
        return str(fallback)
    return None


def runner_bin(spec: RunnerSpec) -> str | None:
    override = os.environ.get(spec.bin_env)
    if override:
        return str(Path(override).expanduser())
    return _which(spec.bin_name)


def require_runner_bin(spec: RunnerSpec) -> str:
    found = runner_bin(spec)
    if found:
        return found
    raise RuntimeErrorConfig(f"{spec.label} CLI not found; set {spec.bin_env} or install `{spec.bin_name}`")


def claude_bin() -> str:
    return require_runner_bin(RUNNERS["claude"])


def runner_catalog() -> list[dict]:
    out = []
    for spec in RUNNERS.values():
        path = runner_bin(spec)
        enabled = bool(path)
        out.append(
            {
                "id": spec.id,
                "label": spec.label,
                "ide_label": spec.ide_label,
                "description": spec.description,
                "available": enabled,
                "path": path,
                "live": spec.live_supported and enabled,
                "queue": spec.queue_supported,
                "queue_available": spec.queue_supported and enabled,
                "knowledge": spec.knowledge_supported,
                "supports_resume": spec.supports_resume,
                "default_model": default_model(spec.id),
                "models": model_choices(spec.id),
            }
        )
    return out


def live_argv(
    runner_id: str | None,
    model: str | None = None,
    initial_prompt: str | None = None,
    resume_session_id: str | None = None,
    continue_last: bool = False,
) -> list[str]:
    spec = runner_spec(runner_id)
    if resume_session_id and not spec.supports_resume:
        raise RuntimeErrorConfig(f"{spec.label} sessions cannot resume Claude transcript ids")
    if continue_last and not spec.supports_resume:
        raise RuntimeErrorConfig(f"{spec.label} sessions cannot continue the last Claude transcript")

    argv = [require_runner_bin(spec)]
    chosen = validate_model_id(model)
    if chosen:
        argv += ["--model", chosen]

    if spec.id == "claude":
        if resume_session_id:
            if not re.fullmatch(r"[0-9a-f-]{8,40}", resume_session_id):
                raise RuntimeErrorConfig("bad session id")
            argv += ["--resume", resume_session_id]
        elif continue_last:
            argv += ["--continue"]
        elif initial_prompt:
            argv += [initial_prompt[:4000]]
        return argv

    if spec.id == "ollama":
        chosen = chosen or default_model(spec.id)
        argv = [require_runner_bin(spec), "run", chosen]
        if initial_prompt:
            argv += [initial_prompt[:4000]]
        return argv

    if spec.id == "codex":
        argv += ["--no-alt-screen"]

    if initial_prompt and spec.supports_inline_prompt:
        argv += [initial_prompt[:4000]]
    return argv


def queue_argv(runner_id: str | None, model: str, max_turns: int, prompt: str, readonly: bool = False) -> list[str]:
    spec = runner_spec(runner_id)
    if not spec.queue_supported:
        raise RuntimeErrorConfig(f"{spec.label} does not support detached tasks")
    chosen = validate_model_id(model) or default_model(spec.id)
    exe = require_runner_bin(spec)
    if spec.id == "claude":
        from .guard import guard_settings_args

        argv = [
            exe,
            "-p",
            prompt,
            "--output-format",
            "json",
            "--model",
            chosen,
            "--max-turns",
            str(max_turns),
        ]
        if readonly:
            argv += [*guard_settings_args(), "--tools", "Read", "Grep", "Glob"]
        else:
            argv += ["--permission-mode", "acceptEdits", *guard_settings_args()]
        return argv
    if spec.id == "codex":
        argv = [exe, "exec", "--model", chosen]
        if readonly:
            argv += ["--sandbox", "read-only"]
        return argv + [prompt]
    if spec.id == "ollama":
        return [exe, "run", chosen, prompt]
    return [exe, "--model", chosen, prompt]


def workspace_preferences(conn) -> dict:
    rows = conn.execute("SELECT key, value FROM workspace_settings").fetchall()
    raw = {r["key"]: r["value"] for r in rows}
    runner = raw.get("runner") or "claude"
    try:
        runner_spec(runner)
    except RuntimeErrorConfig:
        runner = "claude"
    source_runner = raw.get("knowledge_source_runner") or "claude"
    try:
        runner_spec(source_runner)
    except RuntimeErrorConfig:
        source_runner = "claude"
    return {
        "runner": runner,
        "model": validate_model_id(raw.get("model")) or "",
        "knowledge_source_runner": source_runner,
        "knowledge_source_model": validate_model_id(raw.get("knowledge_source_model")) or "",
        "method_advisor": raw.get("method_advisor") == "1",
    }


def save_workspace_preferences(
    conn,
    runner: str | None,
    model: str | None,
    knowledge_source_runner: str | None,
    knowledge_source_model: str | None,
    method_advisor: bool = False,
) -> dict:
    rid = runner_spec(runner).id
    src = runner_spec(knowledge_source_runner or "claude").id
    values = {
        "runner": rid,
        "model": validate_model_id(model) or "",
        "knowledge_source_runner": src,
        "knowledge_source_model": validate_model_id(knowledge_source_model) or "",
        "method_advisor": "1" if method_advisor else "0",
    }
    for key, value in values.items():
        conn.execute(
            "INSERT INTO workspace_settings (key, value, updated_at) VALUES (?,?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
            (key, value, utcnow()),
        )
    conn.commit()
    return {**values, "method_advisor": values["method_advisor"] == "1"}


def build_transfer_pack(
    settings: Settings,
    project: str,
    source_runner: str,
    source_model: str | None,
    target_runner: str,
    target_model: str | None,
) -> str:
    """A model-agnostic orientation pack for switching tools on one repo."""
    from .context_pack import context_pack
    from .readers.memories import list_memories
    from .readers.sessions import recent_sessions

    source = runner_spec(source_runner)
    target = runner_spec(target_runner)
    repo = settings.projects_dir / project
    ns = str(repo).replace("/", "-")
    primary_ns = primary_namespace()

    sessions = recent_sessions(settings.claude_dir, limit=5, namespace=ns)
    mems = [m for m in list_memories(settings.claude_dir) if m["namespace"] in {ns, primary_ns}]

    lines = [
        "# AI Workspace Transfer Pack",
        "",
        f"Generated: {utcnow()}",
        f"Project: {project}",
        f"Source knowledge: {source.label}{f' / {source_model}' if source_model else ''}",
        f"Target runtime: {target.label}{f' / {target_model}' if target_model else ''}",
        "",
        "Use this as orientation before working in the repo. It transfers durable project context; it does not replace reading the files you edit.",
        "",
    ]

    pack = context_pack(repo, settings)
    if pack:
        lines += ["## Repo Context", "", pack, ""]

    if sessions:
        lines += ["## Recent Source Sessions", ""]
        for s in sessions[:5]:
            first = (s.get("first_prompt") or "").replace("\n", " ")[:220]
            last = (s.get("last_assistant") or "").replace("\n", " ")[:260]
            marker = "open-loop" if s.get("open_loop") else "closed"
            lines += [
                f"- {marker}: {first or '(no prompt captured)'}",
                f"  Last: {last or '(no assistant tail captured)'}",
            ]
        lines.append("")

    if mems:
        lines += ["## Durable Memory Notes", ""]
        for m in sorted(mems, key=lambda x: (x["namespace"] != ns, x["name"]))[:24]:
            desc = (m.get("description") or "").replace("\n", " ")[:180]
            lines.append(f"- {m['name']} ({m['namespace']}): {desc or m.get('type') or 'memory note'}")
        lines.append("")

    lines += [
        "## Shared Operating Preferences",
        "",
        "- Work only inside this repo unless the operator explicitly says otherwise.",
        "- Prefer small, reviewable changes with local verification.",
        "- Preserve existing project conventions before introducing new tools or abstractions.",
        "- If a task depends on product, legal, security, or deployment details not present here, ask instead of guessing.",
    ]
    return "\n".join(lines)[:14000]


def _project_memory_hints(settings: Settings, project: str) -> list[dict]:
    from .readers.memories import list_memories_for_namespaces

    repo = settings.projects_dir / project
    ns = str(repo).replace("/", "-")
    primary_ns = primary_namespace()
    try:
        mems = list_memories_for_namespaces(settings.claude_dir, {ns, primary_ns}, limit=6)
    except OSError:
        return []
    hints: list[dict] = []
    for m in sorted(mems, key=lambda x: (x["namespace"] != ns, x["name"]))[:6]:
        hints.append(
            {
                "name": m["name"],
                "namespace": m["namespace"],
                "description": (m.get("description") or m.get("type") or "memory note")[:180],
            }
        )
    return hints


def workspace_method_suggestion(settings: Settings, conn, project: str, prompt: str = "") -> dict:
    """Suggest a reusable work method from preferences and durable estate context.

    This is deterministic: no model call, no repo writes, no hidden automation.
    """
    repo = settings.projects_dir / project
    prefs = workspace_preferences(conn)
    project_path = str(repo)
    recent_task = conn.execute(
        "SELECT runner, model, weight, title, created_at FROM queue "
        "WHERE project IN (?,?) AND status != 'cancelled' ORDER BY id DESC LIMIT 1",
        (project, project_path),
    ).fetchone()
    paused = conn.execute(
        "SELECT runner, model, paused_at FROM paused_sessions WHERE project=? ORDER BY id DESC LIMIT 1",
        (project,),
    ).fetchone()
    pack = conn.execute(
        "SELECT id,source_runner,source_model,target_runner,target_model,created_at FROM workspace_knowledge "
        "WHERE project=? ORDER BY id DESC LIMIT 1",
        (project,),
    ).fetchone()

    runner = (
        (recent_task["runner"] if recent_task else None)
        or (paused["runner"] if paused else None)
        or (pack["target_runner"] if pack else None)
        or prefs["runner"]
        or "claude"
    )
    try:
        spec = runner_spec(runner)
    except RuntimeErrorConfig:
        spec = runner_spec(prefs["runner"] or "claude")
        runner = spec.id

    model = (
        (recent_task["model"] if recent_task else None)
        or (paused["model"] if paused else None)
        or (pack["target_model"] if pack else None)
        or (prefs["model"] if prefs["runner"] == runner else "")
        or ""
    )
    source_runner = (pack["source_runner"] if pack else None) or prefs["knowledge_source_runner"] or "claude"
    try:
        source_runner = runner_spec(source_runner).id
    except RuntimeErrorConfig:
        source_runner = "claude"
    source_model = (pack["source_model"] if pack else None) or prefs["knowledge_source_model"] or ""
    memory_hints = _project_memory_hints(settings, project)

    reasons: list[str] = []
    if recent_task:
        label = f"{spec.label}{f' / {model}' if model else ''}"
        depth = f", {recent_task['weight']} depth" if recent_task["weight"] else ""
        reasons.append(f"You last queued this repo with {label}{depth}: {recent_task['title'][:90]}.")
    if pack:
        source = runner_spec(source_runner).label
        reasons.append(f"A recent handoff pack already bridges {source} into {spec.label}.")
    if paused:
        reasons.append(f"A previous live session for this repo used {paused['runner'] or 'claude'}.")
    if memory_hints:
        reasons.append(f"{len(memory_hints)} memory note(s) are available for this repo or your workspace defaults.")
    if not reasons:
        pref_model = prefs["model"]
        reasons.append(f"Your saved default is {spec.label}{f' / {pref_model}' if pref_model else ''}.")

    confidence = "high" if recent_task or pack else "medium" if paused or memory_hints else "low"
    use_handoff = bool(memory_hints or pack or source_runner != runner)
    model_label = model or f"default {default_model(runner)}"
    title = f"Reuse your {spec.label} method?"
    if prompt.strip():
        title = f"Reuse your {spec.label} method for this task?"

    return {
        "project": project,
        "title": title,
        "question": f"You have used {spec.label} ({model_label}) here before. Reuse that method, or choose different?",
        "confidence": confidence,
        "runner": runner,
        "runner_label": spec.label,
        "model": model,
        "model_label": model_label,
        "source_runner": source_runner,
        "source_model": source_model,
        "knowledge_pack_id": pack["id"] if pack else None,
        "use_handoff": use_handoff,
        "reasons": reasons[:4],
        "memory_hints": memory_hints,
    }
