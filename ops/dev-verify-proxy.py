"""Dev-only logging reverse proxy 127.0.0.1:8899 -> 127.0.0.1:4747 for headless
visual verification. Headless chromium screenshots capture at the LOAD EVENT, so
data-driven views screenshot empty; and --virtual-time-budget never settles while
the SSE stream is open. This proxy stubs /api/events (instant close) so
virtual-time capture works, logs every upstream call with timing, and serves
/__click<path> to open the Builds intake panel for expanded-state shots.
Usage: python3 ops/dev-verify-proxy.py &  then
  chromium --headless=new --virtual-time-budget=8000 --screenshot=out.png \
    http://127.0.0.1:8899/#builds
"""

import http.server
import sys
import time
import urllib.request

UP = "http://127.0.0.1:" + __import__("os").environ.get("NOIRDECK_VERIFY_UPSTREAM_PORT", "4747")

PROBE = b"""<!doctype html><meta charset=utf-8><title>probe</title>
<body style="background:#111;color:#eee;font:14px monospace">
<div id=out>starting</div>
<script>
const out = document.getElementById('out')
const t0 = performance.now()
fetch('/api/builds')
  .then(r => { out.textContent = 'headers ' + r.status + ' @' + Math.round(performance.now()-t0) + 'ms'; return r.json() })
  .then(j => { out.textContent += ' | json len ' + j.length + ' @' + Math.round(performance.now()-t0) + 'ms' })
  .catch(e => { out.textContent += ' | ERR ' + e.message })
</script>
"""


class H(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self):
        if self.path == "/api/events":
            # Stub the SSE stream: close immediately so headless chromium's
            # virtual-time/network-quiescence capture can settle.
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if self.path == "/__probe.html":
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(PROBE)))
            self.end_headers()
            self.wfile.write(PROBE)
            return
        t0 = time.time()
        path = self.path
        inject = b""
        if path.startswith("/__click"):
            # /__click<real-path>: serve the SPA shell with a late script that
            # opens the intake panel, so headless can capture the expanded state.
            path = "/"
            inject = (
                b"<script>setTimeout(function(){var b=document.querySelector"
                b'(".toolbar button");if(b)b.click()},1500)</script>'
            )
        req = urllib.request.Request(UP + path, headers={"Host": "127.0.0.1:4747"})
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                body = r.read()
                if inject:
                    body = body.replace(b"</body>", inject + b"</body>")
                ms = int((time.time() - t0) * 1000)
                print(f"PROXY {self.path} -> {r.status} {len(body)}b {ms}ms", file=sys.stderr, flush=True)
                self.send_response(r.status)
                for k, v in r.headers.items():
                    if k.lower() in ("content-type",):
                        self.send_header(k, v)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
        except Exception as ex:
            print(f"PROXY {self.path} -> EXC {ex}", file=sys.stderr, flush=True)
            self.send_error(502, str(ex))

    def log_message(self, *a):
        pass


http.server.ThreadingHTTPServer(("127.0.0.1", 8899), H).serve_forever()
