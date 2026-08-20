from noirdeck.miner.redact import redact


def test_redacts_key_shapes():
    text = (
        "aws AKIAABCDEFGHIJKLMNOP here, gh ghp_"
        + "a" * 36
        + " ant sk-ant-api03-"
        + "x" * 24
        + " password=hunter2secret and Bearer abcdefghijklmnopqrstuvwx"
    )
    clean, counts = redact(text)
    assert "AKIA" not in clean
    assert "ghp_" not in clean
    assert "sk-ant-" not in clean
    assert "hunter2secret" not in clean
    assert counts["aws_access_key"] == 1
    assert counts["kv_secret"] >= 1


def test_redacts_private_key_block_and_jwt():
    text = (
        "-----BEGIN RSA PRIVATE KEY-----\nMIIabc\n-----END RSA PRIVATE KEY-----\n"
        "jwt eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.abcde12345"
    )
    clean, counts = redact(text)
    assert "MIIabc" not in clean
    assert "eyJhbGci" not in clean
    assert counts["private_key_block"] == 1


def test_plain_text_untouched():
    clean, counts = redact("deploy the invoice sync to staging and run tests")
    assert clean == "deploy the invoice sync to staging and run tests"
    assert counts == {}


def test_redacts_env_var_shaped_secrets():
    """Regression: `\\b` never matches at an underscore, because `_` is a word
    character. `\\bpassword\\b` therefore could not match the PASSWORD inside
    DB_PASSWORD, so SCREAMING_SNAKE_CASE=value — the commonest shape a secret
    takes in terminal output and .env files — passed through unredacted."""
    for line in (
        "DB_PASSWORD=hunter2xyz",
        "AWS_SECRET_ACCESS_KEY=wJalrXUtnFEMIKEXAMPLEKEY1",
        "NOIRDECK_API_KEY=zzzzzzzzzzzz",
        "export STRIPE_SECRET_KEY=sk_live_51H8xQ2eZvKYlo2C0abcdef",
        "MY_DB_TOKEN: supersecretvalue",
    ):
        clean, counts = redact(line)
        assert counts, f"not redacted: {line}"
        assert "hunter2xyz" not in clean
        assert "wJalrXUtnFEMIKEXAMPLEKEY1" not in clean
        assert "supersecretvalue" not in clean


def test_does_not_over_redact_benign_lines():
    """Over-redaction is the safe direction, but a consultant that only ever
    sees [REDACTED] is useless — keep ordinary output readable."""
    for line in ("TOKEN_COUNT=1500", "running 32 tests, all passed"):
        clean, counts = redact(line)
        assert counts == {}, f"over-redacted: {line}"
        assert clean == line
