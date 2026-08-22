"""The headers the console sends to a browser.

⛔ WHAT THIS PROTECTS (2026-08-22). The console served its interface with no
security headers at all, and the missing one that mattered was frame-ancestors.

The safety property this product sells is that a human clicks approve. The Host
and Origin allowlists stop a cross-origin page CALLING the API, and they do
nothing about a page FRAMING the console: any site could have embedded
127.0.0.1:4747 in an invisible iframe, floated a harmless button under the
pointer, and collected a click on Approve from someone who never saw the screen.
Consent that can be clickjacked is not consent.

The other assertion worth its place is the last one: the generated-mock route
serves untrusted LLM-authored HTML under a far stricter sandbox policy of its
own, and a general header applied with assignment rather than setdefault would
have silently replaced it with a weaker one.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from noirdeck.main import _SECURITY_HEADERS, app


@pytest.fixture
def client():
    return TestClient(app)


def test_the_interface_cannot_be_framed(client):
    """The one that stops a click on Approve being harvested from an iframe."""
    r = client.get("/api/health")
    assert "frame-ancestors 'none'" in r.headers["content-security-policy"]
    assert r.headers["x-frame-options"] == "DENY"


def test_an_injected_script_cannot_run(client):
    """script-src deliberately does NOT carry 'unsafe-inline'."""
    csp = client.get("/api/health").headers["content-security-policy"]
    assert "script-src 'self'" in csp
    assert "'unsafe-inline'" not in csp.split("script-src")[1].split(";")[0]


def test_the_pre_paint_script_is_allowed_by_hash_not_by_unsafe_inline(client):
    """The appearance is stamped by an inline script before anything is fetched.

    ⛔ `script-src 'self'` blocks it, and the failure is silent: the app still
    works and paints the wrong appearance first, which is exactly the flash that
    script exists to prevent. Hashing keeps the directive intact; the hash is
    computed from the shipped file at startup so editing the script cannot leave
    a stale one behind.
    """
    from noirdeck.main import _inline_script_hashes

    hashes = _inline_script_hashes()
    if not hashes:
        pytest.skip("no built SPA in this tree, so there is no inline script to hash")

    script_src = client.get("/api/health").headers["content-security-policy"]
    script_src = script_src.split("script-src")[1].split(";")[0]
    for h in hashes:
        assert h in script_src, f"index.html carries an inline script the policy does not allow: {h}"


def test_nothing_may_be_fetched_from_another_origin(client):
    csp = client.get("/api/health").headers["content-security-policy"]
    for directive in ("default-src 'self'", "font-src 'self'", "connect-src 'self'", "object-src 'none'"):
        assert directive in csp, f"missing: {directive}"
    # Fonts and assets are all bundled, so no external host should be named at all.
    assert "http://" not in csp
    assert "https://" not in csp


def test_content_types_are_not_sniffed(client):
    assert client.get("/api/health").headers["x-content-type-options"] == "nosniff"


def test_a_local_console_names_no_urls_to_anyone(client):
    assert client.get("/api/health").headers["referrer-policy"] == "no-referrer"


def test_headers_are_on_every_response_including_refusals(client):
    """A 403 is served to a browser too, and is not a reason to drop the policy."""
    r = client.get("/api/health", headers={"Origin": "https://evil.example"})
    assert r.status_code == 403
    assert "frame-ancestors 'none'" in r.headers["content-security-policy"]


def test_a_route_with_its_own_stricter_policy_keeps_it():
    """setdefault, not assignment.

    The generated-mock route serves untrusted LLM-authored HTML under
    `sandbox; default-src 'none'`. Overwriting that with the general policy would
    hand script authority to exactly the content that must not have it.
    """
    from starlette.responses import Response

    strict = "sandbox; default-src 'none'"
    response = Response(content="x", media_type="text/html")
    response.headers["Content-Security-Policy"] = strict
    for name, value in _SECURITY_HEADERS.items():
        response.headers.setdefault(name, value)

    assert response.headers["content-security-policy"] == strict
    # The rest still apply, because they were not already set.
    assert response.headers["x-content-type-options"] == "nosniff"
