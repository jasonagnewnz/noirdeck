"""Licence keys: who may run this copy, decided locally.

Shape: a key is a signed claim, not a password. The server signs it once at
signup with an Ed25519 private key; every noirdeck verifies it OFFLINE against
the public key baked into this file. So a running noirdeck needs no network, no
licence server and no round trip to do its job: the network is only ever needed
to *obtain* or *refresh* a key, never to use one.

THE FAILURE MODE IS THE DESIGN. Verification is deliberately ASYMMETRIC:

    transient failure (no network, server down, refresh failed)  -> ALLOW
    definitive failure (bad signature, revoked, expired past grace) -> DENY

A local developer tool that fails closed when its vendor has an outage locks
people out of their own machine, their own code and their own work: on a plane,
behind a captive portal, or because a DNS record wobbled. Our outage must never
become their outage. The trade is that blocking the refresh endpoint extends a
key's life to the end of its grace window; that is the correct thing to lose.

No custom cryptography: Ed25519 signature verification via `cryptography`.
Honest limit: this ships as readable Python. A key gate stops casual sharing and
records who accepted the terms; it does not stop someone determined, and it was
never going to. Do not build anything on the assumption that it does.
"""

from __future__ import annotations

import base64
import json
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

# The issuing key's public half, baked in at release time. EMPTY means this is
# not a released build: a source checkout or a test run: and in that case
# there is no licensing regime at all: every feature is allowed.
#
# That is deliberate, not a hole. A developer working on noirdeck itself must
# not need a key to run it, and a test suite must not need a keypair to exercise
# a route. The env override exists for that development case.
#
# It is also, of course, trivially removable by anyone reading the source: as
# stated at the top of this file, a key gate stops casual sharing, not a
# determined person. Pretending otherwise would mean designing around a
# guarantee that does not exist.
_BAKED_ISSUER_PUBLIC_KEY = ""  # ← set by the release build
ISSUER_PUBLIC_KEY_B64 = os.environ.get("NOIRDECK_ISSUER_PUBKEY", _BAKED_ISSUER_PUBLIC_KEY)

# How long past `exp` a key keeps working while a refresh keeps failing. Long on
# purpose: a fortnight of someone's working life should not depend on our uptime.
GRACE_DAYS = 14

# Features that need a valid key. The console itself does not: someone who has
# installed noirdeck can always look around, read their own estate and reach the
# place where they enter a key. Gating the front door too would mean a failed
# refresh could hide the very screen used to fix it.
GATED_FEATURES = frozenset({"builds", "consult", "mining", "overnight", "improve", "ask"})

# What each gate actually withholds, in the customer's words. Without this the
# status endpoint reports bare feature names and "mining" reads as "mining does not
# work": while the free local pass at POST /api/mine works fine and only the LLM
# pass is paid. A gate list nobody can interpret invites support tickets.
GATED_LABELS = {
    "ask": "asking questions about your estate",
    "builds": "guided builds",
    "consult": "a second model watching a session",
    "improve": "the background improvement pass",
    "mining": "the model-driven pass over your history (the instant local pass stays free)",
    "overnight": "queued unattended work",
}


class LicenseError(RuntimeError):
    pass


# The two things a key can be. "personal" is the free licence and is limited to
# one individual's own non-commercial work; "commercial" is the paid licence and
# is what any organisation, employee or paid work requires. The distinction is
# legal, not technical: both plans unlock the same features, because gating a
# paid customer's tooling differently would punish the people who paid.
PLANS = ("personal", "commercial")


@dataclass(frozen=True)
class License:
    email: str
    name: str
    company: str
    plan: str
    issued_at: datetime
    expires_at: datetime

    @property
    def expired(self) -> bool:
        return _now() > self.expires_at

    @property
    def in_grace(self) -> bool:
        return self.expired and _now() <= self.expires_at + timedelta(days=GRACE_DAYS)

    @property
    def dead(self) -> bool:
        """Past expiry AND past grace: the only expiry state that denies."""
        return _now() > self.expires_at + timedelta(days=GRACE_DAYS)


def active() -> bool:
    """True when this build has an issuer key, i.e. licensing applies at all."""
    return bool(ISSUER_PUBLIC_KEY_B64)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _b64d(raw: str) -> bytes:
    # urlsafe b64 without padding: keys get pasted into terminals and emails,
    # and '=' has a habit of being eaten on the way.
    return base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))


def key_path() -> Path:
    """Where the key lives. Follows the same install-mode split as the database:
    a checkout keeps it beside the data, an installed copy uses XDG."""
    from .paths import data_home

    return data_home() / "license.key"


def parse(key: str) -> License:
    """Verify a key's signature and decode its claims.

    Raises LicenseError for anything definitively wrong. A caller must treat that
    as DENY: but must NOT treat an exception from the refresh path the same way.
    """
    if not ISSUER_PUBLIC_KEY_B64:
        raise LicenseError("no issuer public key configured in this build")
    token = key.strip().removeprefix("noirdeck-")
    if token.count(".") != 1:
        raise LicenseError("malformed key")
    payload_b64, sig_b64 = token.split(".")
    try:
        payload_raw = _b64d(payload_b64)
        signature = _b64d(sig_b64)
    except (ValueError, TypeError) as exc:
        raise LicenseError(f"malformed key: {exc}") from exc

    try:
        pub = Ed25519PublicKey.from_public_bytes(_b64d(ISSUER_PUBLIC_KEY_B64))
        # Signed over the exact payload bytes as transmitted. Verifying the
        # re-serialised JSON instead would break on any key-order difference.
        pub.verify(signature, payload_raw)
    except InvalidSignature as exc:
        raise LicenseError("signature does not match: key is not genuine") from exc
    except (ValueError, TypeError) as exc:
        raise LicenseError(f"cannot verify key: {exc}") from exc

    try:
        claims = json.loads(payload_raw)
        return License(
            email=claims["email"],
            name=claims.get("name", ""),
            company=claims.get("company", ""),
            plan=claims.get("plan", "personal"),
            issued_at=datetime.fromisoformat(claims["iat"]),
            expires_at=datetime.fromisoformat(claims["exp"]),
        )
    except (ValueError, KeyError, TypeError) as exc:
        raise LicenseError(f"key claims are unreadable: {exc}") from exc


def load() -> License | None:
    """Read and verify the stored key. None when there is no key at all."""
    path = key_path()
    if not path.exists():
        return None
    try:
        return parse(path.read_text())
    except OSError:
        # Unreadable file is a TRANSIENT problem (permissions, a half-written
        # file), not proof of wrongdoing. Callers treat None as unlicensed.
        return None


def save(key: str) -> License:
    """Verify before storing. Never persist a key we could not read: otherwise
    the failure surfaces later, at startup, detached from the paste that caused it."""
    lic = parse(key)
    path = key_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(key.strip())
    try:
        path.chmod(0o600)
    except OSError:
        pass  # best effort; a key is not a secret worth failing a save over
    return lic


def status() -> dict:
    """What the UI shows. Never raises: a status call must not be the thing
    that breaks the screen someone opened to fix their licence."""
    if not active():
        return {
            "licensed": True,
            "state": "inactive",
            "detail": "No licence key is required for this build.",
        }
    try:
        lic = load()
    except LicenseError as exc:
        # A stored key that will not verify is definitive, but it still has to
        # be *reportable*: the operator needs to see why in order to replace it.
        return {
            "licensed": False,
            "state": "invalid",
            "detail": f"The stored key could not be verified: {exc}",
            "gated": sorted(GATED_FEATURES),
            "gated_detail": {k: GATED_LABELS[k] for k in sorted(GATED_FEATURES)},
        }
    if lic is None:
        return {
            "licensed": False,
            "state": "unlicensed",
            "detail": "No key yet. Keys are not being issued yet: request one at noirdeck.dev.",
            "gated": sorted(GATED_FEATURES),
            "gated_detail": {k: GATED_LABELS[k] for k in sorted(GATED_FEATURES)},
        }
    if lic.dead:
        return {
            "licensed": False,
            "state": "expired",
            "detail": f"Key expired {lic.expires_at.date()} and the {GRACE_DAYS}-day grace period has passed.",
            "email": lic.email,
            "gated": sorted(GATED_FEATURES),
            "gated_detail": {k: GATED_LABELS[k] for k in sorted(GATED_FEATURES)},
        }
    return {
        "licensed": True,
        "state": "grace" if lic.in_grace else "active",
        "detail": (
            f"Expired {lic.expires_at.date()}; still working for now while a refresh is retried."
            if lic.in_grace
            else f"Valid until {lic.expires_at.date()}."
        ),
        "email": lic.email,
        "name": lic.name,
        "company": lic.company,
        "plan": lic.plan,
        "plan_label": "Commercial" if lic.plan == "commercial" else "Personal (non-commercial)",
        "expires_at": lic.expires_at.isoformat(),
    }


def allows(feature: str) -> tuple[bool, str]:
    """(allowed, reason): the gate every AI feature calls.

    Ungated features always pass. Gated ones need a key that is not dead. A key
    inside its grace window PASSES: grace exists precisely so a refresh problem
    does not stop someone working.
    """
    if not active():
        return True, "unreleased build: licensing inactive"
    if feature not in GATED_FEATURES:
        return True, "not gated"
    try:
        lic = load()
    except LicenseError as exc:
        # Definitively bad key -> DENY. This is the deny side of the asymmetry;
        # a failed *refresh* must never reach here.
        return False, f"key is not valid: {exc}"
    if lic is None:
        # B3c (2026-08-19): this used to say "sign up at noirdeck.dev to get one".
        # Signup is a WAITLIST: it returns "we will email your key the day noirdeck
        # is published": so the instruction was a dead end for anyone who followed
        # it. Say what is actually true. When issuance ships (B3a/B3b in
        # PROJECT_PLAN.md) this message changes back, and not before.
        return False, (
            "noirdeck needs a key for this. Keys are not being issued yet: "
            "request one at noirdeck.dev and it arrives when noirdeck is published. "
            "Everything else keeps working without a key."
        )
    if lic.dead:
        return False, f"key expired {lic.expires_at.date()} and grace has passed: refresh it to continue"
    return True, "licensed"
