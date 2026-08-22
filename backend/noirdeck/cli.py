"""The `noirdeck` command.

Installed users get one entry point instead of a clone, a venv, a build step
and a systemd unit: `noirdeck` starts the server, opens the browser, and runs
the recurring jobs in-process.
"""

from __future__ import annotations

import argparse
import os
import shutil
import socket
import sys
import threading
import webbrowser
from pathlib import Path

from .config import ConfigError, Settings
from .paths import data_home, is_repo_checkout, web_dir
from .version import VERSION

BIND_HOST = "127.0.0.1"


def _port_free(port: int, host: str = BIND_HOST) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind((host, port))
            return True
        except OSError:
            return False


def _check(label: str, ok: bool, detail: str) -> bool:
    print(f"  {'PASS' if ok else 'WARN'}  {label:<22} {detail}")
    return ok


def doctor(_args: argparse.Namespace) -> int:
    """Report what noirdeck can and cannot do on this machine.

    Deliberately advisory: a missing optional dependency disables one feature,
    it does not stop the console being useful, so only a broken core config
    is an error.
    """
    print(f"noirdeck {VERSION}\n")
    print(f"  mode: {'source checkout' if is_repo_checkout() else 'installed'}   data: {data_home()}\n")

    fatal = False
    try:
        settings = Settings.load()
        # A missing workspace is a WARN, never a FAIL: the console is still useful
        # with Codex or a local model, and refusing to start was the old bug.
        _check(
            "claude dir",
            settings.claude_dir_ready,
            str(settings.claude_dir)
            if settings.claude_dir_ready
            else f"{settings.claude_dir} not found: skills, memories and history will be empty",
        )
        _check("database", True, str(settings.db_path))
        port_ok = _port_free(settings.port)
        _check(
            "port",
            port_ok,
            f"{settings.port} free" if port_ok else f"{settings.port} in use (noirdeck already running?)",
        )
    except ConfigError as exc:
        print(f"  FAIL  config                 {exc}")
        fatal = True

    spa = web_dir()
    if not _check("web ui", spa is not None, str(spa) if spa else "not built (API only)"):
        if is_repo_checkout():
            print("        run: make frontend")

    claude = shutil.which("claude")
    if not _check("claude cli", claude is not None, claude or "not found: sessions/builds unavailable"):
        print("        install: https://claude.com/claude-code")

    git = shutil.which("git")
    _check("git", git is not None, git or "not found: repo views unavailable")

    restic = shutil.which("restic") or (Path.home() / ".local/bin/restic").exists()
    _check("restic", bool(restic), "found" if restic else "not found: vault backups unavailable")

    ollama = os.environ.get("NOIRDECK_OLLAMA_URL", "http://127.0.0.1:11434")
    try:
        import urllib.request

        with urllib.request.urlopen(f"{ollama}/api/tags", timeout=2):
            _check("ollama", True, f"reachable at {ollama}")
    except Exception:  # noqa: BLE001 - unreachable is a normal, reportable state
        _check("ollama", False, f"unreachable at {ollama}: improver unavailable")

    from . import scheduler

    _check("scheduler", True, f"{'on' if scheduler.enabled() else 'off'}: {scheduler.mode()}")

    # What machine this is, and which assistant environments are on it. On WSL
    # there are two homes and noirdeck reads one, so the Windows half is worth
    # saying out loud rather than leaving someone to wonder why their history
    # looks short.
    from .environment import scan_ai_environments

    env = scan_ai_environments()
    platform = env["platform"]
    if platform["kind"] == "wsl":
        wsl = platform["wsl"]
        _check("platform", True, f"WSL{wsl['version']} ({wsl['distro'] or 'unknown distro'})")
    else:
        _check("platform", True, platform["kind"])

    counts = env["counts"]
    _check("ai runtimes", counts["drivable"] > 0, f"{counts['drivable']} usable of {counts['total']} found")
    for tool in env["tools"]:
        if tool["host"] != "linux":
            continue
        where = tool["bin"] or (tool["config"][0] if tool["config"] else "")
        note = " (Windows program, via interop)" if tool["via_interop"] else ""
        print(f"        {'·' if tool['drivable'] else ' '} {tool['label']:<22} {where}{note}")

    unread = env["unread_windows_environments"]
    if unread:
        print()
        print(f"  NOTE  a second AI environment exists on the Windows side: {', '.join(unread)}")
        for profile in platform["wsl"]["windows_profiles"]:
            print(f"        {profile}")
        print("        noirdeck reads this Linux home only. Nothing there is being used.")

    print("\nnot ready" if fatal else "\nready")
    return 1 if fatal else 0


def serve(args: argparse.Namespace) -> int:
    import uvicorn

    os.environ.setdefault("NOIRDECK_PORT", str(args.port))
    try:
        settings = Settings.load()
    except ConfigError as exc:
        print(f"noirdeck: {exc}", file=sys.stderr)
        print("Set NOIRDECK_CLAUDE_DIR, or run `noirdeck doctor`.", file=sys.stderr)
        return 1

    if not _port_free(settings.port):
        print(
            f"noirdeck: port {settings.port} is already in use: "
            f"another instance may be running. Try `noirdeck serve --port <n>`.",
            file=sys.stderr,
        )
        return 1

    url = f"http://{BIND_HOST}:{settings.port}"
    print(f"noirdeck {VERSION} → {url}   (local only; Ctrl-C to stop)")
    if web_dir() is None:
        print("  note: web UI not built: serving the API only")

    if args.open:
        # after a beat, so the browser lands on a server that is actually up
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()

    # import here: binding the app imports the whole reader stack
    from .main import app

    uvicorn.run(app, host=BIND_HOST, port=settings.port, log_level=args.log_level)
    return 0


def run_job(args: argparse.Namespace) -> int:
    """Run one recurring job now, in the foreground (what a timer would do)."""
    import json

    from .scheduler import _run_job

    try:
        settings = Settings.load()
    except ConfigError as exc:
        print(f"noirdeck: {exc}", file=sys.stderr)
        return 1
    from .db import init_db

    init_db(settings.db_path)
    print(json.dumps(_run_job(args.job, settings), default=str))
    return 0


def _resolve_project(settings, given: str | None) -> tuple[str, Path] | tuple[None, None]:
    """The project to work in: what was asked for, or the repo you are standing in.

    Standing in a repo and having to name it is the kind of friction that makes a CLI
    feel slower than a browser, so cwd is the default.
    """
    if given:
        repo = (settings.projects_dir / given).resolve()
        if not (repo.is_dir() and (repo / ".git").exists()):
            print(f"noirdeck: no git repo named {given!r} under {settings.projects_dir}", file=sys.stderr)
            return None, None
        return given, repo
    here = Path.cwd().resolve()
    for candidate in (here, *here.parents):
        if (candidate / ".git").exists():
            if settings.projects_dir.resolve() in candidate.parents:
                return candidate.name, candidate
            print(
                f"noirdeck: {candidate} is a git repo but not under {settings.projects_dir}; "
                "pass --project or set NOIRDECK_PROJECTS_DIR",
                file=sys.stderr,
            )
            return None, None
    print("noirdeck: not inside a git repo: pass --project NAME", file=sys.stderr)
    return None, None


def do(args: argparse.Namespace) -> int:
    """Give noirdeck a task from the terminal. No browser, no clicks.

    Two modes, and the default is the impatient one:
      noirdeck do "add retry to the sync"          -> runs now, streams, prints the verdict
      noirdeck do "..." --later                    -> queues it for the unattended runner

    Reuses the queue's own task path, so a terminal task gets exactly the same
    treatment as a queued one: the context pack, the operating guardrails, the
    PreToolUse guard, the staged plan/build/check for heavy work, and a structured
    verdict. A second implementation would drift from it within a week.
    """
    import json

    from .db import init_db

    try:
        settings = Settings.load()
    except ConfigError as exc:
        print(f"noirdeck: {exc}", file=sys.stderr)
        return 1

    name, repo = _resolve_project(settings, args.project)
    if not name:
        return 1

    init_db(settings.db_path)
    from .arming import DEFAULT_HOURS, DEFAULT_MAX_TASKS, DEFAULT_MAX_TOKENS, arm, status
    from .db import connect, utcnow
    from .licensing import allows

    ok, why = allows("overnight")
    if not ok:
        print(f"noirdeck: {why}", file=sys.stderr)
        return 2

    title = args.task if len(args.task) <= 70 else args.task[:67] + "..."
    conn = connect(settings.db_path)
    try:
        cur = conn.execute(
            "INSERT INTO queue (project,title,prompt,status,created_at,weight) VALUES (?,?,?,?,?,?)",
            (str(repo), title, args.task, "queued", utcnow(), args.depth),
        )
        task_id = cur.lastrowid
        # Same rule as the console: queuing IS the intent to run, so arm if nothing is
        # live, and never widen a contract the operator already set.
        if not status(conn).get("overnight", {}).get("live"):
            arm(conn, "overnight")
            print(
                f"armed for unattended work: {DEFAULT_HOURS:g}h, {DEFAULT_MAX_TASKS} tasks, "
                f"{DEFAULT_MAX_TOKENS:,} tokens",
                file=sys.stderr,
            )
        conn.commit()

        if args.later:
            print(json.dumps({"queued": task_id, "project": name, "title": title}))
            return 0

        print(f"noirdeck: working in {name}: {title}", file=sys.stderr)
        from .overnight import run_task

        task = conn.execute("SELECT * FROM queue WHERE id=?", (task_id,)).fetchone()
        run_task(conn, settings, task)
        row = conn.execute("SELECT status, verdict, question, tokens_out FROM queue WHERE id=?", (task_id,)).fetchone()
    finally:
        conn.close()

    print(json.dumps(dict(row), default=str, indent=2))
    # A blocked task asked you a question; that is not success, and a script should
    # be able to tell without parsing prose.
    return 0 if row["status"] == "done" else 1


def status_cmd(args: argparse.Namespace) -> int:
    """One screen of "is anything wrong", for people who live in a terminal.

    Deliberately answers the questions the console answers on its Home page, in the
    order they matter: leaked credentials first, then whether unattended work can
    actually run, then what is waiting on you.
    """
    import json

    from .db import connect, init_db

    try:
        settings = Settings.load()
    except ConfigError as exc:
        print(f"noirdeck: {exc}", file=sys.stderr)
        return 1
    init_db(settings.db_path)
    from .arming import status as arming_status
    from .licensing import status as licence_status

    conn = connect(settings.db_path)
    try:
        secrets_open = conn.execute("SELECT COUNT(*) c FROM secret_findings WHERE status='open'").fetchone()["c"]
        pending = conn.execute("SELECT COUNT(*) c FROM proposals WHERE status='proposed'").fetchone()["c"]
        queue = {r["status"]: r["c"] for r in conn.execute("SELECT status, COUNT(*) c FROM queue GROUP BY status")}
        contracts = arming_status(conn)
    finally:
        conn.close()

    live = sorted(k for k, v in contracts.items() if v.get("live"))
    report = {
        "workspace": str(settings.claude_dir) if settings.claude_dir_ready else f"{settings.claude_dir} (NOT FOUND)",
        "credential_findings_open": secrets_open,
        "armed": live,
        "reviews_waiting": pending,
        "queue": queue,
        "licensed": licence_status().get("licensed"),
    }
    if args.json:
        print(json.dumps(report, indent=2))
        return 0

    # Worst news first. A status line that buries a leaked credential under a task
    # count is a status line nobody should trust.
    if secrets_open:
        print(f"!  {secrets_open} credential finding(s) unresolved: noirdeck run secrets, then review")
    print(f"   workspace : {report['workspace']}")
    print(f"   armed     : {', '.join(live) if live else 'nothing (unattended work will not run)'}")
    print(f"   reviews   : {pending} waiting")
    print(f"   tasks     : {queue or 'none'}")
    if not report["licensed"]:
        print("   licence   : none installed (free during Early Access: request a key at noirdeck.dev)")
    return 0 if not secrets_open else 1


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="noirdeck", description="Local companion console for a Claude Code estate.")
    ap.add_argument("--version", action="version", version=f"noirdeck {VERSION}")
    sub = ap.add_subparsers(dest="cmd")

    p_serve = sub.add_parser("serve", help="run the console (default)")
    p_serve.add_argument("--port", type=int, default=int(os.environ.get("NOIRDECK_PORT", "4747")))
    p_serve.add_argument("--no-open", dest="open", action="store_false", help="do not open a browser")
    p_serve.add_argument("--log-level", default="warning")
    p_serve.set_defaults(func=serve, open=True)

    sub.add_parser("doctor", help="check this machine's setup").set_defaults(func=doctor)

    # The headless path. `do` is the whole point of having a CLI at all: a task from
    # the terminal, no browser, no clicks, same spine as the console.
    p_do = sub.add_parser("do", help="give noirdeck a task from the terminal")
    p_do.add_argument("task", help="what you want, in a sentence")
    p_do.add_argument("--project", help="repo name (default: the git repo you are standing in)")
    p_do.add_argument("--later", action="store_true", help="queue it for the unattended runner instead of now")
    p_do.add_argument("--depth", choices=["light", "heavy"], default=None, help="force staging depth")
    p_do.set_defaults(func=do)

    p_status = sub.add_parser("status", help="is anything wrong?")
    p_status.add_argument("--json", action="store_true", help="machine-readable")
    p_status.set_defaults(func=status_cmd)

    p_run = sub.add_parser("run", help="run one recurring job now")
    p_run.add_argument("job", choices=["mine", "vault", "overnight", "improve", "secrets"])
    p_run.set_defaults(func=run_job)
    return ap


def main(argv: list[str] | None = None) -> int:
    ap = build_parser()
    args = ap.parse_args(argv)
    if not getattr(args, "func", None):
        # bare `noirdeck` is the common case: just start it
        args = ap.parse_args(["serve", *(argv or [])])
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
