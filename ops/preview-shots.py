#!/usr/bin/env python3
"""Deterministic screenshots of the noirdeck SPA, with synthetic data.

Two problems this solves at once.

1. **Headless chromium hangs against the live app.** The SPA opens a persistent
   `EventSource('/api/events')`, so the page never reaches network idle and
   `--virtual-time-budget` never settles: every screenshot attempt times out.
   Here `EventSource` is stubbed out before the app bundle runs.

2. **Screenshots must not contain real data.** The live console shows real
   project names, real session history and real credential findings. None of that
   may end up in documentation or on a marketing site. Every response below is
   synthetic and obviously so.

Mechanism: serve `frontend/dist` and inject an inline CLASSIC script into
`index.html`. Inline classic scripts run in document order, and the app bundle is
a `type="module"` (deferred), so the stubs are always installed first.

Usage:
    python3 ops/preview-shots.py --out ~/noirdeck-shots
    python3 ops/preview-shots.py --out ~/noirdeck-shots --views overview,secrets
"""

from __future__ import annotations

import argparse
import functools
import http.server
import json
import socketserver
import subprocess
import threading
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DIST = REPO / "frontend" / "dist"
CHROMIUM = "/snap/bin/chromium"  # snap build is the only working one on WSL

# ── synthetic fixtures ───────────────────────────────────────────────────────
# Invented projects and findings. Deliberately generic so a screenshot can be
# published without disclosing anything about real work.
FIXTURES: dict[str, object] = {
    "/api/health": {
        "status": "ok",
        "version": "0.26.0",
        "server_started_at": "2026-08-19T09:00:00+00:00",
        "server_now": "2026-08-19T09:42:00+00:00",
        "frontend_dir": "/opt/noirdeck/web",
        "claude_dir": "/home/demo/.claude",
        "mining_armed": True,
        "overnight_armed": True,
    },
    "/api/overview": {
        "skills": 34,
        "agents": 9,
        "memories": {
            "total": 412,
            "by_type": {"project": 180, "feedback": 121, "reference": 74, "user": 37},
            "namespaces": 12,
            "top_namespaces": [["storefront", 96], ["ledger-api", 71]],
        },
        "history": {
            "total_prompts": 8412,
            "avg_prompt_chars": 148,
            "by_hour": [2, 1, 0, 0, 0, 0, 3, 18, 44, 91, 130, 122, 88, 140, 165, 158, 120, 74, 40, 33, 28, 21, 12, 6],
            "top_projects": [["storefront", 1840], ["ledger-api", 1522], ["fleet-console", 980], ["docs-site", 610]],
            "top_slash": [["/review", 142], ["/ship", 96], ["/plan", 71], ["/test", 55]],
        },
        "recent_sessions": [
            {
                "project": "storefront",
                "started": "2026-08-19T08:10:00+00:00",
                "prompts": 24,
                "open_loop": True,
                "summary": "checkout retry logic",
                "id": "s1",
            },
            {
                "project": "ledger-api",
                "started": "2026-08-19T07:02:00+00:00",
                "prompts": 11,
                "open_loop": False,
                "summary": "pagination fix",
                "id": "s2",
            },
        ],
        "open_loops": [
            {"project": "storefront", "summary": "checkout retry logic", "open_loop": True, "id": "s1"},
        ],
        "fleet_attention": [
            {
                "name": "docs-site",
                "path": "/home/demo/projects/docs-site",
                "branch": "main",
                "dirty_files": 2,
                "has_upstream": True,
                "unpushed_commits": 3,
                "last_commit_ts": 1787000000,
                "reasons": ["3 unpushed commit(s)", "2 uncommitted file(s)"],
            },
            {
                "name": "fleet-console",
                "path": "/home/demo/projects/fleet-console",
                "branch": "main",
                "dirty_files": 7,
                "has_upstream": True,
                "unpushed_commits": 0,
                "last_commit_ts": 1786900000,
                "reasons": ["7 uncommitted file(s)"],
            },
        ],
        "proposals_pending": 3,
        "queue": {"queued": 4, "done": 26, "failed": 1},
        "secrets_open": 2,
    },
    "/api/secrets": {
        "counts": {"open": 2, "acknowledged": 5, "quarantined": 1},
        "last_scan": {
            "ts": "2026-08-19T02:00:04+00:00",
            "detail": "scanned=1204 findings=8 new=2 open=2 transcripts=False truncated=False",
        },
        "findings": [
            {
                "id": 1,
                "detector": "assigned_secret",
                "confidence": "high",
                "path": "projects/ledger-api/memory/deploy-notes.md",
                "line": 34,
                "fingerprint": "4c1de9a77b02",
                "context": "staging env: `SERVICE_API_TOKEN=[REDACTED:40 chars]`",
                "status": "open",
                "note": None,
                "first_seen_at": "2026-08-19T02:00:04+00:00",
                "last_seen_at": "2026-08-19T02:00:04+00:00",
            },
            {
                "id": 2,
                "detector": "sudo_prose",
                "confidence": "medium",
                "path": "skills/reset-test-db/SKILL.md",
                "line": 12,
                "fingerprint": "9ab30f5c14de",
                "context": "> [REDACTED:11 chars] is sudo on the box",
                "status": "open",
                "note": None,
                "first_seen_at": "2026-08-19T02:00:04+00:00",
                "last_seen_at": "2026-08-19T02:00:04+00:00",
            },
        ],
    },
    "/api/proposals": [
        {
            "id": 11,
            "kind": "skill",
            "title": "Draft skill: /rotate-service-token",
            "body": "---\nname: rotate-service-token\n---\n# draft\n",
            "target_path": "skills/rotate-service-token/SKILL.md",
            "status": "proposed",
            "diff": None,
            "created_at": "2026-08-19T02:31:00+00:00",
            "prior_existed": None,
        },
        {
            "id": 12,
            "kind": "improve_skill",
            "title": "improve(skill): skills/deploy-preview/SKILL.md",
            "body": "improved body",
            "target_path": "skills/deploy-preview/SKILL.noirdeck-proposed.md",
            "status": "proposed",
            "diff": "--- skills/deploy-preview/SKILL.md\n+++ (proposed)\n@@ -4,3 +4,5 @@\n-Run the deploy.\n+Run the deploy, then verify the served asset over http.\n+Never trust the build log.\n",
            "created_at": "2026-08-19T02:32:00+00:00",
            "prior_existed": None,
        },
    ],
    "/api/fleet": [
        {
            "name": "storefront",
            "path": "/home/demo/projects/storefront",
            "branch": "main",
            "dirty": 0,
            "ahead": 0,
            "last_commit": "2026-08-19T08:40:00+00:00",
            "clean": True,
        },
        {
            "name": "ledger-api",
            "path": "/home/demo/projects/ledger-api",
            "branch": "main",
            "dirty": 0,
            "ahead": 0,
            "last_commit": "2026-08-19T07:10:00+00:00",
            "clean": True,
        },
        {
            "name": "fleet-console",
            "path": "/home/demo/projects/fleet-console",
            "branch": "main",
            "dirty": 7,
            "ahead": 0,
            "last_commit": "2026-08-18T16:00:00+00:00",
            "clean": False,
        },
        {
            "name": "docs-site",
            "path": "/home/demo/projects/docs-site",
            "branch": "main",
            "dirty": 2,
            "ahead": 3,
            "last_commit": "2026-08-18T11:00:00+00:00",
            "clean": False,
        },
    ],
    "/api/commits": {
        "feed": [
            {
                "repo": "storefront",
                "sha": "a1b2c3d",
                "ts": 1787100000,
                "author": "you",
                "subject": "retry checkout on 5xx",
            },
            {
                "repo": "ledger-api",
                "sha": "e4f5a6b",
                "ts": 1787090000,
                "author": "you",
                "subject": "paginate the statements endpoint",
            },
        ],
        "flags": [],
    },
    "/api/digest": {
        "generated_at": "2026-08-19T09:00:00+00:00",
        "attention": 2,
        "lines": [
            "2 credential findings are unresolved in your workspace",
            "docs-site has 3 commits that were never pushed",
            "26 background tasks finished overnight",
            "3 reviews are waiting for you",
        ],
    },
    "/api/arming": {
        "contracts": {
            "overnight": {
                "id": 1,
                "subsystem": "overnight",
                "armed_until": "2026-08-20T09:00:00+00:00",
                "max_tasks": 10,
                "used_tasks": 4,
                "max_tokens": 600000,
                "used_tokens": 128400,
                "created_at": "2026-08-19T09:00:00+00:00",
                "revoked_at": None,
                "live": True,
            },
            "mining": {
                "id": 2,
                "subsystem": "mining",
                "armed_until": "2026-08-19T21:00:00+00:00",
                "max_tasks": 8,
                "used_tasks": 2,
                "max_tokens": None,
                "used_tokens": 0,
                "created_at": "2026-08-19T09:00:00+00:00",
                "revoked_at": None,
                "live": True,
            },
        }
    },
    "/api/improve": {
        "armed": False,
        "model": "local-model",
        "model_available": False,
        "model_note": "not pulled",
        "repos": [],
        "targets": [],
        "assets": {"skill": [], "memory": []},
        "changes": [],
    },
    "/api/builds": [],
    "/api/design": [],
    "/api/qa": {"projects": [], "overall": None},
    "/api/vault": {"configured": False, "reason": "not set up in this demo", "repo": None, "runs": []},
    "/api/workspace/runtimes": {
        "runners": [
            {
                "id": "claude",
                "label": "Claude Code",
                "ide_label": "Claude IDE",
                "live": True,
                "default_model": "claude-opus-5",
                "models": ["claude-opus-5", "claude-sonnet-5"],
            },
            {"id": "codex", "label": "Codex", "ide_label": "Codex", "live": False, "default_model": None, "models": []},
            {
                "id": "ollama",
                "label": "Ollama (local)",
                "ide_label": "Local model",
                "live": True,
                "default_model": "llama3",
                "models": ["llama3", "qwen2.5-coder"],
            },
        ],
        "defaults": {"runner": "claude", "model": None},
        "preferences": {},
    },
    "/api/workspace/knowledge": {"packs": []},
    "/api/guided/recipes": [
        {"id": "booking-page", "title": "A booking page", "blurb": "Customers pick a slot and pay."},
        {"id": "internal-tool", "title": "An internal tool", "blurb": "A form, a table and a report."},
    ],
    "/api/sessions": [
        {
            "session_id": "s1",
            "namespace": "-home-demo-projects-storefront",
            "project": "storefront",
            "started": "2026-08-19T08:10:00+00:00",
            "prompts": 24,
            "open_loop": True,
            "summary": "checkout retry logic",
            "last": "2026-08-19T08:52:00+00:00",
        },
    ],
    "/api/hygiene": {"skill_dupes": [], "stale": [], "untyped": []},
    "/api/insights": [
        {
            "id": 1,
            "kind": "methodology",
            "title": "Verifies against the running artifact, not CI",
            "body": "Consistently re-checks the deployed artifact rather than trusting a green pipeline.",
            "source": "session",
            "created_at": "2026-08-19T02:31:00+00:00",
        },
    ],
    "/api/queue": [
        {
            "id": 31,
            "title": "Add rate limiting to the public API",
            "prompt": "...",
            "project": "/home/demo/projects/ledger-api",
            "status": "running",
            "runner": "claude",
            "model": "claude-opus-5",
            "agent_type": None,
            "weight": "heavy",
            "tokens_out": 18400,
            "verdict": None,
            "question": None,
            "created_at": "2026-08-19T09:20:00+00:00",
            "claimed_at": None,
            "worker_pid": 5150,
            "transcript_session_id": "b7c1d2e3f4a5",
        },
        {
            "id": 30,
            "title": "Tidy the settings page copy",
            "prompt": "...",
            "project": "/home/demo/projects/storefront",
            "status": "claimed",
            "runner": "claude",
            "model": None,
            "agent_type": None,
            "weight": "light",
            "tokens_out": 3100,
            "verdict": None,
            "question": None,
            "created_at": "2026-08-19T08:00:00+00:00",
            "claimed_at": "2026-08-19T09:05:00+00:00",
            "worker_pid": None,
            "transcript_session_id": None,
        },
        {
            "id": 29,
            "title": "Write tests for the invoice exporter",
            "prompt": "...",
            "project": "/home/demo/projects/ledger-api",
            "status": "queued",
            "runner": "claude",
            "model": None,
            "agent_type": None,
            "weight": "light",
            "tokens_out": None,
            "verdict": None,
            "question": None,
            "created_at": "2026-08-19T07:40:00+00:00",
            "claimed_at": None,
            "worker_pid": None,
            "transcript_session_id": None,
        },
        {
            "id": 28,
            "title": "Move the image pipeline to a queue",
            "prompt": "...",
            "project": "/home/demo/projects/storefront",
            "status": "blocked",
            "runner": "claude",
            "model": None,
            "agent_type": None,
            "weight": "heavy",
            "tokens_out": 21200,
            "verdict": "Needs a decision on retention before I can size the queue.",
            "question": "Keep processed originals, or discard after 30 days?",
            "created_at": "2026-08-18T23:31:00+00:00",
            "claimed_at": None,
            "worker_pid": None,
            "transcript_session_id": None,
        },
    ],
    "/api/local-models": {
        "state": {
            "installed": True,
            "binary": "/home/demo/.local/bin/ollama",
            "version": "0.6.2",
            "user_local": True,
            "server_running": True,
            "models": [{"name": "qwen2.5-coder:7b", "size_gb": 4.7, "modified_at": None}],
            "models_known": True,
            "arch": "x86_64",
            "arch_supported": True,
            "api": "http://127.0.0.1:11434",
            "capacity": {
                "ram_gb": 16.0,
                "gpu_name": None,
                "gpu_vram_gb": None,
                "usable_gb": 10.0,
                "basis": "10 GB of your 16 GB of memory, keeping 6 GB free",
            },
        },
        "recommendations": {
            "work_kind": "code",
            "basis": "10 GB of your 16 GB of memory, keeping 6 GB free",
            "usable_gb": 10.0,
            "start_with": {
                "tag": "qwen2.5-coder:7b",
                "label": "Qwen Coder, standard",
                "good_for": "The sensible default for coding work.",
                "needs_gb": 8.0,
                "download_gb": 4.7,
                "kinds": ["code", "general"],
                "already_pulled": True,
                "note": "Fits: wants about 8 GB, you have 10 GB to play with.",
            },
            "fits": [
                {
                    "tag": "qwen2.5-coder:7b",
                    "label": "Qwen Coder, standard",
                    "good_for": "The sensible default for coding work: reads a file, explains it, writes a patch.",
                    "needs_gb": 8.0,
                    "download_gb": 4.7,
                    "kinds": ["code", "general"],
                    "already_pulled": True,
                    "note": "Fits: wants about 8 GB, you have 10 GB to play with.",
                },
                {
                    "tag": "qwen2.5-coder:1.5b",
                    "label": "Qwen Coder, small",
                    "good_for": "Quick code questions on a modest machine.",
                    "needs_gb": 3.0,
                    "download_gb": 1.0,
                    "kinds": ["code", "tiny"],
                    "already_pulled": False,
                    "note": "Fits: wants about 3 GB, you have 10 GB to play with.",
                },
                {
                    "tag": "llama3.1:8b",
                    "label": "Llama 3.1",
                    "good_for": "General-purpose: summarising, drafting, answering questions about text.",
                    "needs_gb": 8.0,
                    "download_gb": 4.7,
                    "kinds": ["general", "writing"],
                    "already_pulled": False,
                    "note": "Fits: wants about 8 GB, you have 10 GB to play with.",
                },
                {
                    "tag": "llama3.2:3b",
                    "label": "Llama 3.2, small",
                    "good_for": "Light general assistant.",
                    "needs_gb": 4.0,
                    "download_gb": 2.0,
                    "kinds": ["general", "writing", "tiny"],
                    "already_pulled": False,
                    "note": "Fits: wants about 4 GB, you have 10 GB.",
                },
            ],
            "out_of_reach": [
                {
                    "tag": "qwen2.5-coder:32b",
                    "label": "Qwen Coder, largest",
                    "good_for": "Closest a local model gets to a hosted one for code.",
                    "needs_gb": 32.0,
                    "download_gb": 20.0,
                    "kinds": ["code"],
                    "already_pulled": False,
                    "note": "Too big here: wants about 32 GB, you have 10 GB.",
                },
            ],
            "plain_summary": "Start with Qwen Coder, standard (qwen2.5-coder:7b).",
        },
        "install_plan": {
            "supported": True,
            "arch": "x86_64",
            "url": "https://ollama.com/download/ollama-linux-amd64.tgz",
            "target": "/home/demo/.local/bin/ollama",
            "needs_root": False,
            "steps": [],
            "manual_command": None,
            "why_not_the_official_script": "",
        },
        "next_step": {
            "action": "ready",
            "headline": "Local models are ready",
            "detail": "1 model installed. Pick one as your local helper in Build Live, or add another below.",
        },
    },
    "/api/workspace": [],
    "/api/workspace/paused": [],
    "/api/scheduler": {
        "enabled": True,
        "mode": "installed",
        "jobs": [
            {"name": "secrets", "spec": "02:00", "due": "2026-08-20T02:00:00+00:00"},
            {"name": "mine", "spec": "02:30", "due": "2026-08-20T02:30:00+00:00"},
            {"name": "improve", "spec": "hourly", "due": "2026-08-19T10:00:00+00:00"},
        ],
    },
}

# Anything not named above resolves to a shape the app can render without crashing.
DEFAULT_LIST_PREFIXES = ("/api/skills", "/api/agents", "/api/queue", "/api/builds", "/api/memories")

STUB_TEMPLATE = """<script>
// Installed before the app module runs (inline classic scripts execute in
// document order; the bundle is type="module" and therefore deferred).
(function () {
  var F = %s;
  // The SPA keeps an EventSource open forever, which stops headless chromium
  // ever reaching network idle. A no-op stub is what makes screenshots possible.
  window.EventSource = function () {
    this.close = function () {};
    this.addEventListener = function () {};
  };
  function body(path) {
    var clean = path.split('?')[0].replace(/\\/$/, '');
    if (Object.prototype.hasOwnProperty.call(F, clean)) return F[clean];
    if (/^\\/api\\/(skills|agents)$/.test(clean)) return [];
    if (clean === '/api/memories') return { stats: F['/api/overview'].memories, memories: [] };
    if (/^\\/api\\//.test(clean)) return [];  // unknown endpoint: a list is the common shape
    return {};
  }
  window.fetch = function (url) {
    var path = String(url).replace(location.origin, '');
    return Promise.resolve(new Response(JSON.stringify(body(path)), {
      status: 200, headers: { 'Content-Type': 'application/json' },
    }));
  };
})();
</script>
"""


class Handler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):  # noqa: N802 - stdlib naming
        path = self.path.split("?")[0]
        if path in ("/", "/index.html"):
            html = (DIST / "index.html").read_text()
            stub = STUB_TEMPLATE % json.dumps(FIXTURES)
            html = html.replace("<head>", "<head>" + stub, 1)
            data = html.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        return super().do_GET()

    def log_message(self, *a):  # keep the run quiet
        pass


def serve(port: int) -> socketserver.TCPServer:
    """Bind, falling back to a kernel-assigned free port.

    ⛔ A stale http.server from an earlier session may already own the requested
    port and would then serve a DIFFERENT project's files: screenshots of the
    wrong site, with no error. So: never reuse a busy port, take a fresh one.
    """
    handler = functools.partial(Handler, directory=str(DIST))
    socketserver.TCPServer.allow_reuse_address = True
    for candidate in (port, 0):
        try:
            httpd = socketserver.TCPServer(("127.0.0.1", candidate), handler)
        except OSError:
            print(f"port {candidate} busy (a stale server owns it): taking a free one")
            continue
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        return httpd
    raise OSError("could not bind a preview port")


def shoot(url: str, out: Path, width: int, height: int, budget: int = 5000) -> bool:
    argv = [
        CHROMIUM,
        "--headless=new",
        "--disable-gpu",
        "--no-sandbox",
        "--hide-scrollbars",
        f"--window-size={width},{height}",
        f"--virtual-time-budget={budget}",
        f"--screenshot={out}",
        url,
    ]
    try:
        subprocess.run(argv, capture_output=True, timeout=90)
    except subprocess.TimeoutExpired:
        return False
    return out.is_file() and out.stat().st_size > 5000


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(Path.home() / "noirdeck-shots"))
    ap.add_argument("--views", default="overview,secrets,proposals,queue,builds,sessions,help")
    ap.add_argument("--port", type=int, default=8899)
    ap.add_argument("--width", type=int, default=1600)
    ap.add_argument("--height", type=int, default=1000)
    args = ap.parse_args()

    if not (DIST / "index.html").is_file():
        print(f"no build at {DIST}: run `make frontend` first")
        return 1
    # snap confinement: chromium can only write under $HOME
    out = Path(args.out).expanduser()
    if Path.home() not in out.parents and out != Path.home():
        print(f"refusing {out}: snap chromium can only write under {Path.home()}")
        return 1
    out.mkdir(parents=True, exist_ok=True)

    httpd = serve(args.port)
    port = httpd.server_address[1]
    print(f"serving {DIST} on 127.0.0.1:{port}")
    try:
        ok = 0
        for view in [v.strip() for v in args.views.split(",") if v.strip()]:
            dest = out / f"{view}.png"
            url = f"http://127.0.0.1:{port}/#{view}"
            good = shoot(url, dest, args.width, args.height)
            size = dest.stat().st_size if dest.is_file() else 0
            print(f"{'ok  ' if good else 'FAIL'} {view:12} {size:>8} bytes  {dest}")
            ok += bool(good)
        print(f"\n{ok} of {len(args.views.split(','))} captured")
        return 0 if ok else 1
    finally:
        httpd.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
