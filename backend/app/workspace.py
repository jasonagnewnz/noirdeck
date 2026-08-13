"""Workspace: real Claude Code sessions inside the platform, over a PTY.

Security shape (see docs/SECURITY.md): the browser NEVER supplies a command. The
server only spawns the fixed `claude` argv, in a cwd that must resolve under the
projects dir. Client input is keystrokes + resize events, nothing else. Localhost-only
like the rest of the app — this endpoint is shell-equivalent access by design.

Auth: sessions inherit the machine's existing Claude CLI auth (~/.claude). There is
no separate platform login; if the CLI is ever logged out, /login runs in the pane.
"""
from __future__ import annotations

import asyncio
import fcntl
import os
import pty
import re
import signal
import struct
import termios
import uuid
from collections import deque
from pathlib import Path

MAX_SESSIONS = 6
SCROLLBACK_BYTES = 200_000
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


class WorkspaceError(RuntimeError):
    pass


def claude_bin() -> str:
    """Resolve the claude CLI even under systemd, whose PATH lacks ~/.local/bin."""
    import shutil
    found = shutil.which("claude")
    if found:
        return found
    fallback = Path.home() / ".local" / "bin" / "claude"
    if fallback.is_file():
        return str(fallback)
    raise WorkspaceError("claude CLI not found on PATH or in ~/.local/bin")


def validate_cwd(projects_dir: Path, project: str) -> Path:
    repo = (projects_dir / project).resolve()
    if not (repo.is_dir() and (repo / ".git").exists()):
        raise WorkspaceError(f"unknown project repo: {project}")
    if projects_dir.resolve() not in repo.parents:
        raise WorkspaceError("cwd outside the projects dir")
    return repo


class TermSession:
    def __init__(self, project: str, cwd: Path, argv: list[str]):
        self.id = uuid.uuid4().hex[:12]
        self.project = project
        self.cwd = cwd
        self.argv = argv
        self.pid: int | None = None
        self.fd: int | None = None
        self.scrollback: deque[bytes] = deque()
        self._sb_size = 0
        self.queue: asyncio.Queue[bytes | None] = asyncio.Queue()
        self._reader_attached = False

    def start(self) -> None:
        pid, fd = pty.fork()
        if pid == 0:  # child
            try:
                os.chdir(self.cwd)
                env = dict(os.environ, TERM="xterm-256color", COLORTERM="truecolor")
                os.execvpe(self.argv[0], self.argv, env)
            finally:
                os._exit(127)
        self.pid, self.fd = pid, fd
        loop = asyncio.get_running_loop()
        loop.add_reader(fd, self._on_readable)
        self._reader_attached = True

    def _on_readable(self) -> None:
        try:
            data = os.read(self.fd, 65536)
        except OSError:
            data = b""
        if not data:
            self._detach()
            self.queue.put_nowait(None)  # EOF sentinel
            return
        self.scrollback.append(data)
        self._sb_size += len(data)
        while self._sb_size > SCROLLBACK_BYTES and len(self.scrollback) > 1:
            self._sb_size -= len(self.scrollback.popleft())
        self.queue.put_nowait(data)

    def _detach(self) -> None:
        if self._reader_attached and self.fd is not None:
            try:
                asyncio.get_running_loop().remove_reader(self.fd)
            except (RuntimeError, ValueError):
                pass
            self._reader_attached = False

    def write(self, data: bytes) -> None:
        if self.fd is not None:
            os.write(self.fd, data)

    def resize(self, cols: int, rows: int) -> None:
        if self.fd is not None and 10 <= cols <= 500 and 4 <= rows <= 200:
            fcntl.ioctl(self.fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))

    def alive(self) -> bool:
        if self.pid is None:
            return False
        try:
            done, _ = os.waitpid(self.pid, os.WNOHANG)
            return done == 0
        except ChildProcessError:
            return False

    def close(self) -> None:
        self._detach()
        if self.pid is not None:
            for sig in (signal.SIGHUP, signal.SIGTERM):
                try:
                    os.kill(self.pid, sig)
                except ProcessLookupError:
                    break
        if self.fd is not None:
            try:
                os.close(self.fd)
            except OSError:
                pass
            self.fd = None


class WorkspaceManager:
    def __init__(self, projects_dir: Path):
        self.projects_dir = projects_dir
        self.sessions: dict[str, TermSession] = {}

    def reap(self) -> None:
        for sid in [s for s, t in self.sessions.items() if not t.alive()]:
            self.sessions[sid].close()
            del self.sessions[sid]

    def start(self, project: str, initial_prompt: str | None = None,
              resume_session_id: str | None = None, continue_last: bool = False,
              argv_override: list[str] | None = None) -> TermSession:
        self.reap()
        if len(self.sessions) >= MAX_SESSIONS:
            raise WorkspaceError(f"session cap reached ({MAX_SESSIONS}) — close one first")
        cwd = validate_cwd(self.projects_dir, project)
        if argv_override:  # tests only — API callers can never reach this
            argv = argv_override
        else:
            argv = [claude_bin()]
            if resume_session_id:
                if not re.fullmatch(r"[0-9a-f-]{8,40}", resume_session_id):
                    raise WorkspaceError("bad session id")
                argv += ["--resume", resume_session_id]
            elif continue_last:
                # fallback when a paused session's transcript id is unknown —
                # resumes the cwd's most recent conversation
                argv += ["--continue"]
            elif initial_prompt:
                argv += [initial_prompt[:4000]]
        term = TermSession(project, cwd, argv)
        term.start()
        self.sessions[term.id] = term
        return term

    def get(self, sid: str) -> TermSession:
        term = self.sessions.get(sid)
        if not term:
            raise WorkspaceError(f"no such workspace session {sid}")
        return term

    def stop(self, sid: str) -> None:
        term = self.get(sid)
        term.close()
        del self.sessions[sid]

    def listing(self) -> list[dict]:
        self.reap()
        return [{
            "id": t.id, "project": t.project, "alive": t.alive(),
            "resumed": "--resume" in t.argv,
        } for t in self.sessions.values()]


def latest_transcript_session_id(claude_dir: Path, cwd: Path) -> str | None:
    """Most recent transcript session id for a cwd, captured at PAUSE time.
    Resuming later must target THIS conversation — by resume time the cwd's
    'most recent' transcript may belong to an overnight/headless run instead.
    Transcript namespaces flatten the cwd path with '/' → '-'."""
    ns = claude_dir / "projects" / str(cwd).replace("/", "-")
    try:
        files = [p for p in ns.glob("*.jsonl") if p.is_file()]
    except OSError:
        return None
    if not files:
        return None
    sid = max(files, key=lambda p: p.stat().st_mtime).stem
    return sid if re.fullmatch(r"[0-9a-f-]{8,40}", sid) else None


def init_repo(projects_dir: Path, name: str) -> Path:
    """Create + git-init a new empty repo under the projects dir."""
    import subprocess
    if not NAME_RE.match(name):
        raise WorkspaceError("repo name must be [A-Za-z0-9._-], max 64 chars")
    target = projects_dir / name
    if target.exists():
        raise WorkspaceError(f"{name} already exists")
    target.mkdir(parents=True)
    r = subprocess.run(["git", "-C", str(target), "init", "-q", "-b", "main"],
                       capture_output=True, text=True, timeout=15)
    if r.returncode != 0:
        raise WorkspaceError(f"git init failed: {r.stderr[:200]}")
    return target
