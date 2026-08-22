"""Sharing what happened in a session.

A TRANSCRIPT IS A DISCLOSURE CHANNEL. This estate found a sudo password inside a
generated skill file and 125 distinct secrets across its workspace: all from text that
was "just" printed once. So the export must redact, must SAY what it removed, and must
re-scan its own output so the guarantee is checkable rather than asserted.

The other thing pinned here is what Stage 0 deliberately is NOT: no socket, no invite,
no relay, no bind beyond loopback. docs/SECURITY.md requires an auth layer before any
exposure of the workspace, and sharing a file bypasses none of it.
"""

from __future__ import annotations

from noirdeck.share import MAX_CHARS, build_export

# Assembled at runtime so this file is not itself a credential a future scan flags.
AWS = "AKIA" + "IOSFODNN7" + "EXAMPL9"
GH = "ghp_" + "a1B2c3D4e5F6g7H8i9J0" + "kLmNoPqRsTuVwXyZ1234"
ANTHROPIC = "sk-ant-" + "api03" + "-" + "x" * 40


def export(text: str, **kw):
    return build_export(scrollback=text, project=kw.pop("project", "storefront"), **kw)


# --- the secrets must not travel ------------------------------------------


def test_a_key_in_the_transcript_is_removed():
    out = export(f"$ deploy\nusing AWS_ACCESS_KEY_ID={AWS}\ndone\n")
    assert AWS not in out["markdown"], "the credential travelled in the export"
    assert out["secrets_removed"] >= 1
    assert out["redactions"], "and it must say WHAT it removed, not just that it did"


def test_several_shapes_are_all_removed():
    out = export(f"token {GH}\nkey {ANTHROPIC}\nid {AWS}\n")
    for secret in (GH, ANTHROPIC, AWS):
        assert secret not in out["markdown"]
    assert out["secrets_removed"] >= 3


def test_not_even_a_prefix_of_the_secret_survives():
    """Partial redaction is not redaction: a usable prefix in a shared file is a leak
    with a smaller font."""
    out = export(f"AWS_ACCESS_KEY_ID={AWS}\n")
    assert AWS[:12] not in out["markdown"]


def test_the_count_is_reported_so_redaction_is_visible():
    """A guarantee you cannot see is one you are taking on trust."""
    out = export(f"key {GH}\n")
    assert f"**{out['secrets_removed']}**" in out["markdown"]


# --- it checks its own work -----------------------------------------------


def test_the_export_rescans_itself_and_reports_what_survived():
    """The load-bearing check. Redaction matches shapes; if the scanner still finds
    something in the REDACTED text, the operator must be told before sending it."""
    out = export("nothing interesting here\n")
    assert "residual_findings" in out
    assert isinstance(out["residual_detectors"], list)
    assert out["safe_to_send"] is (out["residual_findings"] == 0)


def test_a_residual_finding_produces_a_loud_warning_in_the_document():
    # a prose password: redaction matches VALUE shapes, so this is exactly the case
    # that gets past it and must therefore be flagged
    out = export("the password is Dd" + "onald" + "01!\n")
    if out["residual_findings"]:
        assert out["safe_to_send"] is False
        assert "CHECK BEFORE SENDING" in out["markdown"]


def test_it_never_claims_to_be_clean():
    """Redaction is shape-matching. The document must say so rather than implying the
    transcript is safe."""
    out = export("plain output\n")
    assert "looks like an ordinary word is not removed" in out["markdown"]


# --- the document is useful to a human who was not there ------------------


def test_the_header_says_what_this_is_and_where_it_came_from():
    out = export("hello\n", project="ledger-api", runner="claude", model="claude-opus-5")
    md = out["markdown"]
    assert md.startswith("# noirdeck session: ledger-api")
    assert "claude" in md and "claude-opus-5" in md
    assert "Exported:" in md


def test_the_transcript_is_fenced_so_it_pastes_anywhere():
    out = export("$ ls\nfile.txt\n")
    assert "```text" in out["markdown"] and "file.txt" in out["markdown"]


def test_an_empty_session_says_so_rather_than_producing_a_blank_block():
    out = export("")
    assert "(no terminal output captured)" in out["markdown"]


def test_an_optional_note_is_carried_and_bounded():
    out = export("x\n", note="look at line 40" + "!" * 900)
    assert "look at line 40" in out["markdown"]
    assert len(out["markdown"]) < MAX_CHARS, "a note must not be able to bloat the export"


# --- the filename cannot surprise anything --------------------------------


def test_the_filename_cannot_escape_a_directory_or_a_shell():
    for hostile in ("../../etc/passwd", "a; rm -rf /", "..", "$(whoami)", "with spaces"):
        name = export("x\n", project=hostile)["filename"]
        assert "/" not in name and ".." not in name
        assert " " not in name and ";" not in name and "$" not in name
        assert name.startswith("noirdeck-") and name.endswith(".md")


# --- what Stage 0 deliberately is not ------------------------------------


def test_sharing_opens_no_socket_and_needs_no_identity():
    """docs/SECURITY.md: an auth layer MUST exist before the workspace is exposed.
    Stage 0 must therefore open no socket and serve nothing.

    Checked by PARSING the module, not by grepping it: the first version of this test
    searched the text for "socket" and failed on share.py's own docstring, which says
    there is no socket. A test that reads documentation instead of code is testing the
    wrong artifact.
    """
    import ast
    import inspect

    from noirdeck import share

    tree = ast.parse(inspect.getsource(share))
    imported: set[str] = set()
    called: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
        elif isinstance(node, ast.Call):
            fn = node.func
            called.add(fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", ""))

    networky = {"socket", "socketserver", "http", "asyncio", "websockets", "uvicorn", "ssl", "urllib", "requests"}
    assert not (imported & networky), f"share.py must not import {sorted(imported & networky)}: that is Stage 1+"
    for forbidden in {"bind", "listen", "accept", "connect", "serve_forever"}:
        assert forbidden not in called, f"share.py must not call {forbidden}(): Stage 0 opens nothing"


def test_very_long_scrollback_is_bounded():
    out = export("x" * (MAX_CHARS * 3))
    assert out["chars"] <= MAX_CHARS
