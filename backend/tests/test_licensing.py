"""Licence key tests.

The asymmetry is the point, so it is what gets pinned: a key that is
definitively bad must be refused, and a key that merely could not be refreshed
must NOT be. Getting that backwards locks paying users out of their own work
during an outage on our side.
"""

import base64
import json
from datetime import datetime, timedelta, timezone

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from noirdeck import licensing


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _keypair():
    priv = Ed25519PrivateKey.generate()
    pub = priv.public_key().public_bytes(encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw)
    return priv, _b64(pub)


def _issue(priv, *, days=365, email="a@b.com"):
    now = datetime.now(timezone.utc)
    claims = {
        "email": email,
        "name": "A B",
        "company": "B Ltd",
        "plan": "free",
        "iat": now.isoformat(),
        "exp": (now + timedelta(days=days)).isoformat(),
    }
    payload = json.dumps(claims, separators=(",", ":"), sort_keys=True).encode()
    return f"noirdeck-{_b64(payload)}.{_b64(priv.sign(payload))}"


@pytest.fixture
def issuer(monkeypatch):
    priv, pub = _keypair()
    monkeypatch.setattr(licensing, "ISSUER_PUBLIC_KEY_B64", pub)
    return priv


def test_valid_key_verifies(issuer):
    lic = licensing.parse(_issue(issuer))
    assert lic.email == "a@b.com"
    assert lic.company == "B Ltd"
    assert not lic.expired and not lic.dead


def test_tampered_key_is_rejected(issuer):
    key = _issue(issuer)
    with pytest.raises(licensing.LicenseError, match="not genuine"):
        licensing.parse(key[:-4] + "AAAA")


def test_key_from_a_different_issuer_is_rejected(issuer):
    """The one that actually matters: anyone can generate a keypair and mint a
    structurally perfect key. Only OUR signature may be accepted."""
    forger, _pub = _keypair()
    with pytest.raises(licensing.LicenseError, match="not genuine"):
        licensing.parse(_issue(forger))


def test_claims_cannot_be_edited_without_breaking_the_signature(issuer):
    """Swapping the payload for a longer expiry must not verify."""
    key = _issue(issuer, days=1)
    _, sig = key.removeprefix("noirdeck-").split(".")
    forged_claims = {
        "email": "a@b.com",
        "exp": (datetime.now(timezone.utc) + timedelta(days=99999)).isoformat(),
        "iat": datetime.now(timezone.utc).isoformat(),
    }
    forged = _b64(json.dumps(forged_claims, separators=(",", ":"), sort_keys=True).encode())
    with pytest.raises(licensing.LicenseError):
        licensing.parse(f"noirdeck-{forged}.{sig}")


def test_expired_but_within_grace_still_works(issuer, monkeypatch, tmp_path):
    """Grace exists so a refresh problem does not stop someone working."""
    key = _issue(issuer, days=-1)  # expired yesterday
    monkeypatch.setattr(licensing, "key_path", lambda: tmp_path / "license.key")
    licensing.save(key)
    lic = licensing.load()
    assert lic.expired and lic.in_grace and not lic.dead
    allowed, _reason = licensing.allows("consult")
    assert allowed is True


def test_expired_past_grace_is_denied(issuer, monkeypatch, tmp_path):
    key = _issue(issuer, days=-(licensing.GRACE_DAYS + 5))
    monkeypatch.setattr(licensing, "key_path", lambda: tmp_path / "license.key")
    licensing.save(key)
    assert licensing.load().dead is True
    allowed, reason = licensing.allows("consult")
    assert allowed is False
    assert "expired" in reason


def test_ungated_features_never_need_a_key(issuer, monkeypatch, tmp_path):
    """The console itself must stay reachable unlicensed: otherwise a licence
    problem hides the very screen used to fix it."""
    monkeypatch.setattr(licensing, "key_path", lambda: tmp_path / "nothing.key")
    for feature in ("overview", "files", "settings", "memories"):
        allowed, _ = licensing.allows(feature)
        assert allowed is True, feature


def test_gated_features_denied_without_any_key(issuer, monkeypatch, tmp_path):
    monkeypatch.setattr(licensing, "key_path", lambda: tmp_path / "nothing.key")
    for feature in sorted(licensing.GATED_FEATURES):
        allowed, _ = licensing.allows(feature)
        assert allowed is False, feature


def test_unreleased_build_has_no_licensing_at_all(monkeypatch, tmp_path):
    """A source checkout ships no issuer key, so nothing is gated. Someone
    working on noirdeck itself must not need a key to run it, and the test
    suite must not need a keypair to exercise a route."""
    monkeypatch.setattr(licensing, "ISSUER_PUBLIC_KEY_B64", "")
    monkeypatch.setattr(licensing, "key_path", lambda: tmp_path / "nothing.key")
    for feature in sorted(licensing.GATED_FEATURES):
        allowed, reason = licensing.allows(feature)
        assert allowed is True, feature
        assert "inactive" in reason
    assert licensing.status()["state"] == "inactive"


def test_save_refuses_a_key_it_cannot_verify(issuer, monkeypatch, tmp_path):
    """Never persist an unreadable key: the failure would resurface at startup,
    detached from the paste that caused it."""
    path = tmp_path / "license.key"
    monkeypatch.setattr(licensing, "key_path", lambda: path)
    with pytest.raises(licensing.LicenseError):
        licensing.save("noirdeck-garbage.garbage")
    assert not path.exists()


def test_status_never_raises(issuer, monkeypatch, tmp_path):
    """status() backs the screen someone opens to fix their licence. It must not
    be the thing that breaks it."""
    monkeypatch.setattr(licensing, "key_path", lambda: tmp_path / "nothing.key")
    out = licensing.status()
    assert out["licensed"] is False and out["state"] == "unlicensed"

    # A stored key that cannot be verified must REPORT, not explode: this is
    # the exact path that broke the first time it was written.
    (tmp_path / "bad.key").write_text("noirdeck-nonsense.nonsense")
    monkeypatch.setattr(licensing, "key_path", lambda: tmp_path / "bad.key")
    bad = licensing.status()
    assert bad["licensed"] is False and bad["state"] == "invalid"
    assert "could not be verified" in bad["detail"]


def test_every_gated_feature_has_a_human_label():
    """A gate list of bare feature names is not interpretable by the person paying.
    'mining' in particular reads as "mining is unavailable" when the free local pass
    works and only the model pass is paid."""
    from noirdeck.licensing import GATED_FEATURES, GATED_LABELS

    assert set(GATED_LABELS) == set(GATED_FEATURES), "labels and gates have drifted apart"
    for feature, label in GATED_LABELS.items():
        assert len(label) > 10, f"{feature} has no useful description"
        assert label == label.lower() or "(" in label, f"{feature} label should read as prose"
