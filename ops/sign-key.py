#!/usr/bin/env python3
"""Issue a noirdeck licence key.

This is the reference implementation of the issuing side. The real issuer (the
signup service) does exactly this: build the claims, sign the payload bytes with
the Ed25519 PRIVATE key, hand the token to the customer. Everything else about
licensing happens offline in the client.

    # once, to create an issuing keypair
    python ops/sign-key.py keygen

    # per customer
    NOIRDECK_ISSUER_PRIVKEY=<b64> python ops/sign-key.py issue \
        --email a@b.com --name "A B" --company "B Ltd" --days 365

⛔ The PRIVATE key is the whole system. Anyone holding it can mint keys, and
rotating it invalidates every key already issued. It belongs in a secrets
manager, never in this repo, never in an .env that gets backed up in the clear.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
from datetime import datetime, timedelta, timezone

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


def b64(raw: bytes) -> str:
    """urlsafe, unpadded — keys get pasted into terminals and emails, and '='
    has a habit of being eaten on the way."""
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def cmd_keygen(_args: argparse.Namespace) -> int:
    priv = Ed25519PrivateKey.generate()
    from cryptography.hazmat.primitives import serialization

    raw_priv = priv.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    )
    raw_pub = priv.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    print("PRIVATE (issuer only — secrets manager, never this repo):")
    print(f"  NOIRDECK_ISSUER_PRIVKEY={b64(raw_priv)}")
    print()
    print("PUBLIC (safe to ship inside the wheel):")
    print(f"  NOIRDECK_ISSUER_PUBKEY={b64(raw_pub)}")
    return 0


def cmd_issue(args: argparse.Namespace) -> int:
    secret = os.environ.get("NOIRDECK_ISSUER_PRIVKEY", "")
    if not secret:
        print("NOIRDECK_ISSUER_PRIVKEY is not set — refusing to issue", file=sys.stderr)
        return 2
    priv = Ed25519PrivateKey.from_private_bytes(base64.urlsafe_b64decode(secret + "=" * (-len(secret) % 4)))

    now = datetime.now(timezone.utc)
    claims = {
        "email": args.email,
        "name": args.name,
        "company": args.company,
        "plan": args.plan,
        "iat": now.isoformat(),
        "exp": (now + timedelta(days=args.days)).isoformat(),
    }
    # Sign the exact bytes that travel. Signing re-serialised JSON would break
    # verification on any key-order or whitespace difference.
    payload = json.dumps(claims, separators=(",", ":"), sort_keys=True).encode()
    token = f"{b64(payload)}.{b64(priv.sign(payload))}"
    print(f"noirdeck-{token}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("keygen", help="create a new issuing keypair").set_defaults(fn=cmd_keygen)

    issue = sub.add_parser("issue", help="sign a key for one customer")
    issue.add_argument("--email", required=True)
    issue.add_argument("--name", default="")
    issue.add_argument("--company", default="")
    issue.add_argument("--plan", default="personal", choices=["personal", "commercial"])
    issue.add_argument("--days", type=int, default=365)
    issue.set_defaults(fn=cmd_issue)

    args = ap.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
