from app.miner.redact import redact


def test_redacts_key_shapes():
    text = (
        "aws AKIAABCDEFGHIJKLMNOP here, gh ghp_" + "a" * 36 +
        " ant sk-ant-api03-" + "x" * 24 +
        " password=hunter2secret and Bearer abcdefghijklmnopqrstuvwx"
    )
    clean, counts = redact(text)
    assert "AKIA" not in clean
    assert "ghp_" not in clean
    assert "sk-ant-" not in clean
    assert "hunter2secret" not in clean
    assert counts["aws_access_key"] == 1
    assert counts["kv_secret"] >= 1


def test_redacts_private_key_block_and_jwt():
    text = ("-----BEGIN RSA PRIVATE KEY-----\nMIIabc\n-----END RSA PRIVATE KEY-----\n"
            "jwt eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.abcde12345")
    clean, counts = redact(text)
    assert "MIIabc" not in clean
    assert "eyJhbGci" not in clean
    assert counts["private_key_block"] == 1


def test_plain_text_untouched():
    clean, counts = redact("deploy the invoice sync to staging and run tests")
    assert clean == "deploy the invoice sync to staging and run tests"
    assert counts == {}
