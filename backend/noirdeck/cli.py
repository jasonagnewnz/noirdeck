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
        _check("claude dir", True, str(settings.claude_dir))
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
    if not _check("claude cli", claude is not None, claude or "not found — sessions/builds unavailable"):
        print("        install: https://claude.com/claude-code")

    git = shutil.which("git")
    _check("git", git is not None, git or "not found — repo views unavailable")

    restic = shutil.which("restic") or (Path.home() / ".local/bin/restic").exists()
    _check("restic", bool(restic), "found" if restic else "not found — vault backups unavailable")

    ollama = os.environ.get("NOIRDECK_OLLAMA_URL", "http://127.0.0.1:11434")
    try:
        import urllib.request

        with urllib.request.urlopen(f"{ollama}/api/tags", timeout=2):
            _check("ollama", True, f"reachable at {ollama}")
    except Exception:  # noqa: BLE001 — unreachable is a normal, reportable state
        _check("ollama", False, f"unreachable at {ollama} — improver unavailable")

    from . import scheduler

    _check("scheduler", True, f"{'on' if scheduler.enabled() else 'off'} — {scheduler.mode()}")

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
            f"noirdeck: port {settings.port} is already in use — "
            f"another instance may be running. Try `noirdeck serve --port <n>`.",
            file=sys.stderr,
        )
        return 1

    url = f"http://{BIND_HOST}:{settings.port}"
    print(f"noirdeck {VERSION} → {url}   (local only; Ctrl-C to stop)")
    if web_dir() is None:
        print("  note: web UI not built — serving the API only")

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

    p_run = sub.add_parser("run", help="run one recurring job now")
    p_run.add_argument("job", choices=["mine", "vault", "overnight", "improve"])
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
