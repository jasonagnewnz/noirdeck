"""Credential scanning. The load-bearing tests are (a) it catches the shape that
actually leaked: a sudo password in prose, which no KEY=value pattern matches:
and (b) a finding NEVER carries the secret, because a findings table that stores
credentials is just a credential store with extra steps."""

from __future__ import annotations

import pathlib
import sqlite3

import pytest

from noirdeck.db import init_db
from noirdeck.secrets_scan import (
    SecretScanError,
    acknowledge,
    fingerprint,
    list_findings,
    quarantine,
    record,
    scan,
    scan_text,
)

# Synthetic values only. Assembled at runtime so this file cannot itself be a
# credential that a future scan flags, and so nothing here resembles a real key.
FAKE_SUDO_PW = "Dd" + "onald" + "01!"
FAKE_AWS = "AKIA" + "IOSFODNN7" + "EXAMPL9"
FAKE_GH = "ghp_" + "a1B2c3D4e5F6g7H8i9J0" + "kLmNoPqRsTuVwXyZ1234"
FAKE_PG = "postgres://svc:" + "s3cr3t" + "P4ss@db.internal:5432/app"


def dets(findings) -> set[str]:
    return {f.detector for f in findings}


# --- the shape that actually leaked ---------------------------------------


def test_catches_a_password_stated_in_prose():
    """~/.claude/skills/ddonald01/SKILL.md held exactly this. The 2026-08-18
    redaction fix would NOT have caught it: it is not KEY=value."""
    text = f"Latest example:\n> {FAKE_SUDO_PW} is sudo\n"
    found = scan_text(text, "skills/x/SKILL.md")
    assert found, "a bare password in prose must be detected"
    assert "sudo_prose" in dets(found)


def test_catches_password_is_phrasing():
    found = scan_text(f"the password is {FAKE_SUDO_PW}", "m.md")
    assert "password_in_prose" in dets(found)


@pytest.mark.parametrize(
    "line,detector",
    [
        (f"AWS_ACCESS_KEY_ID={FAKE_AWS}", "aws_access_key_id"),
        (f"token: {FAKE_GH}", "github_pat"),
        (f"DATABASE_URL={FAKE_PG}", "connection_string_password"),
        ("-----BEGIN OPENSSH PRIVATE KEY-----", "private_key_block"),
        ("AUTOTASK_SECRET=7f3a9b2c8d1e4f6a0b5c", "assigned_secret"),
        ("EncryptionKey=Qw3rTy9zXc1vBn5m", "lowercase_assigned_secret"),
    ],
)
def test_catches_common_secret_shapes(line, detector):
    assert detector in dets(scan_text(line, "f.md"))


def test_underscore_prefixed_names_are_caught():
    """The \\b-at-underscore bug: \\bpassword\\b never matches inside DB_PASSWORD."""
    assert scan_text("DB_PASSWORD=Xk9$mQ2vLp7w", "f.md")
    assert scan_text("CIPP_API_KEY=aBcD1234eFgH5678", "f.md")


# --- a finding must never carry the secret --------------------------------


def test_finding_never_contains_the_secret():
    found = scan_text(f"SUDO_PASSWORD={FAKE_SUDO_PW}", "f.md")
    assert found
    for f in found:
        blob = f"{f.detector}{f.path}{f.fingerprint}{f.context}"
        assert FAKE_SUDO_PW not in blob, "the secret leaked into the finding"
        # and not a prefix either: partial redaction is not redaction
        assert FAKE_SUDO_PW[:4] not in f.context


def test_context_is_elided_not_truncated():
    """The surrounding words survive so the finding is actionable; only the value
    is replaced. Truncating instead would still expose a usable prefix."""
    found = scan_text("AUTOTASK_SECRET=7f3a9b2c8d1e4f6a0b5c  # prod integration", "f.md")
    ctx = found[0].context
    assert "AUTOTASK_SECRET" in ctx and "prod integration" in ctx
    assert "REDACTED" in ctx


def test_fingerprint_is_stable_and_not_reversible():
    a, b = fingerprint(FAKE_SUDO_PW), fingerprint(FAKE_SUDO_PW)
    assert a == b and len(a) == 12
    assert FAKE_SUDO_PW not in a
    assert fingerprint("other") != a


# --- false positives ------------------------------------------------------


@pytest.mark.parametrize(
    "line",
    [
        "PASSWORD=$DB_PASSWORD",
        "API_KEY=${SECRET_FROM_VAULT}",
        "password: <your-password-here>",
        "TOKEN=REDACTED",
        "api_key = xxxxxxxxxxxx",
        "SECRET=changeme",
        "password is the thing we rotated",  # prose, not a value
        "AWS_SECRET_ACCESS_KEY=example-not-a-real-key",
        "the password is documented in IT Glue",
    ],
)
def test_placeholders_and_prose_are_not_findings(line):
    assert not scan_text(line, "f.md"), f"false positive on: {line}"


def test_long_base64_lines_are_skipped_not_flagged():
    assert not scan_text("data:image/png;base64," + ("A" * 5000), "f.md")


# --- persistence + alerting ----------------------------------------------


@pytest.fixture
def conn(tmp_path):
    init_db(tmp_path / "d.db")
    c = sqlite3.connect(tmp_path / "d.db")
    c.row_factory = sqlite3.Row
    yield c
    c.close()


def _result(path="skills/x/SKILL.md"):
    return {
        "findings": [
            {
                "detector": "sudo_prose",
                "confidence": "medium",
                "path": path,
                "line": 3,
                "fingerprint": fingerprint(FAKE_SUDO_PW),
                "context": "> [REDACTED:10 chars] is sudo",
            }
        ],
        "files_scanned": 12,
        "files_unreadable": 0,
        "transcripts_included": False,
        "truncated": False,
        "distinct_secrets": 1,
    }


def test_first_scan_alerts_and_rescan_does_not(conn):
    """Re-alerting hourly on a finding already seen trains the operator to ignore
    the alert, so only NEW findings raise one."""
    first = record(conn, _result())
    assert first["new_findings"] == 1 and first["alert"] is True
    again = record(conn, _result())
    assert again["new_findings"] == 0 and again["alert"] is False
    assert again["open_findings"] == 1


def test_coverage_is_reported_so_empty_is_not_mistaken_for_clean(conn):
    out = record(conn, {**_result(), "findings": []})
    assert out["findings"] == 0
    # the answer to "did you actually look?" must be in the result
    assert out["files_scanned"] == 12
    assert out["transcripts_included"] is False
    assert out["truncated"] is False


def test_acknowledge_records_judgement_without_touching_files(tmp_path, conn):
    record(conn, _result())
    fid = list_findings(conn)[0]["id"]
    acknowledge(conn, fid, note="rotated 2026-08-19")
    assert list_findings(conn, "open") == []
    assert list_findings(conn, "acknowledged")[0]["note"] == "rotated 2026-08-19"


def test_quarantine_moves_the_file_and_says_rotation_is_still_needed(tmp_path, conn):
    claude = tmp_path / ".claude"
    (claude / "skills" / "x").mkdir(parents=True)
    leak = claude / "skills" / "x" / "SKILL.md"
    leak.write_text(f"> {FAKE_SUDO_PW} is sudo\n")
    record(conn, _result())
    fid = list_findings(conn)[0]["id"]

    out = quarantine(conn, claude, fid)
    assert not leak.exists(), "the leaking file must leave the workspace"
    assert "ROTATE" in out["next_step"], "moving a file does not un-disclose a secret"
    assert list_findings(conn, "quarantined")[0]["id"] == fid


def test_quarantine_refuses_a_path_outside_the_tree(tmp_path, conn):
    """A findings row is data. Data must not be able to address arbitrary files."""
    claude = tmp_path / ".claude"
    claude.mkdir()
    outsider = tmp_path / "important.md"
    outsider.write_text("do not move me")
    record(conn, _result(path="../important.md"))
    fid = list_findings(conn)[0]["id"]
    with pytest.raises(SecretScanError, match="outside"):
        quarantine(conn, claude, fid)
    assert outsider.exists()


def test_quarantine_is_idempotent_by_status(tmp_path, conn):
    claude = tmp_path / ".claude"
    (claude / "skills" / "x").mkdir(parents=True)
    (claude / "skills" / "x" / "SKILL.md").write_text("leak\n")
    record(conn, _result())
    fid = list_findings(conn)[0]["id"]
    quarantine(conn, claude, fid)
    with pytest.raises(SecretScanError, match="already quarantined"):
        quarantine(conn, claude, fid)


# --- end to end -----------------------------------------------------------


def test_scan_walks_a_tree_and_reports_coverage(tmp_path):
    claude = tmp_path / ".claude"
    (claude / "skills" / "leaky").mkdir(parents=True)
    (claude / "projects" / "ns" / "memory").mkdir(parents=True)
    (claude / "skills" / "leaky" / "SKILL.md").write_text(f"> {FAKE_SUDO_PW} is sudo\n")
    (claude / "projects" / "ns" / "memory" / "clean.md").write_text("nothing sensitive here\n")
    (claude / "CLAUDE.md").write_text(f"AWS_ACCESS_KEY_ID={FAKE_AWS}\n")
    # transcripts are opt-in
    (claude / "projects" / "ns" / "abc.jsonl").write_text(f'{{"text":"{FAKE_GH}"}}\n')

    out = scan(claude)
    paths = {f["path"] for f in out["findings"]}
    assert any("SKILL.md" in p for p in paths)
    assert any("CLAUDE.md" in p for p in paths)
    assert not any(p.endswith(".jsonl") for p in paths), "transcripts must be opt-in"
    assert out["transcripts_included"] is False
    assert out["files_scanned"] >= 3

    with_transcripts = scan(claude, include_transcripts=True)
    assert any(p.endswith(".jsonl") for p in {f["path"] for f in with_transcripts["findings"]})


# ── bulk move ───────────────────────────────────────────────────────────────
# The estate rule this is built around: irreversible actions are selected by
# EXPLICIT ID, never by a filter, a status or a LIMIT. So there must be no way to
# ask for "move everything", and a plan must be readable before anything moves.


def _findings(conn, claude, paths):
    from noirdeck.secrets_scan import record

    for i, rel in enumerate(paths):
        f = claude / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(f"> {FAKE_SUDO_PW} is sudo\n")
        record(
            conn,
            {
                "findings": [
                    {
                        "detector": "sudo_prose",
                        "confidence": "medium",
                        "path": rel,
                        "line": 1,
                        "fingerprint": fingerprint(FAKE_SUDO_PW + str(i)),
                        "context": "> [REDACTED:10 chars] is sudo",
                    }
                ],
                "files_scanned": 1,
                "files_unreadable": 0,
                "transcripts_included": False,
                "truncated": False,
                "distinct_secrets": 1,
            },
        )


def test_the_plan_moves_nothing(tmp_path, conn):
    from noirdeck.secrets_scan import plan_sweep

    claude = tmp_path / ".claude"
    _findings(conn, claude, ["CLAUDE.md", "skills/a/SKILL.md", "projects/-x/memory/n.md"])
    plan = plan_sweep(conn, claude)
    assert plan["files_movable"] == 3
    for rel in ("CLAUDE.md", "skills/a/SKILL.md"):
        assert (claude / rel).is_file(), "planning must not move anything"


def test_the_plan_groups_by_file_because_that_is_the_unit_of_action(tmp_path, conn):
    """Moving one finding moves the whole file, so a per-finding count misrepresents
    what is about to happen."""
    from noirdeck.secrets_scan import plan_sweep, record

    claude = tmp_path / ".claude"
    _findings(conn, claude, ["CLAUDE.md"])
    # a second finding in the SAME file
    record(
        conn,
        {
            "findings": [
                {
                    "detector": "assigned_secret",
                    "confidence": "high",
                    "path": "CLAUDE.md",
                    "line": 9,
                    "fingerprint": fingerprint("other"),
                    "context": "KEY=[REDACTED:8 chars]",
                }
            ],
            "files_scanned": 1,
            "files_unreadable": 0,
            "transcripts_included": False,
            "truncated": False,
            "distinct_secrets": 1,
        },
    )
    plan = plan_sweep(conn, claude)
    assert len(plan["files"]) == 1, "one file, not two rows"
    assert plan["files"][0]["findings"] == 2
    assert plan["files"][0]["distinct_secrets"] == 2


def test_files_that_load_into_sessions_are_listed_first(tmp_path, conn):
    from noirdeck.secrets_scan import plan_sweep

    claude = tmp_path / ".claude"
    _findings(conn, claude, ["archive/old.json", "skills/a/SKILL.md"])
    plan = plan_sweep(conn, claude)
    assert plan["files"][0]["loads_into_sessions"] is True
    assert plan["files"][0]["path"] == "skills/a/SKILL.md"


def test_there_is_no_move_everything_call(tmp_path, conn):
    """THE LANDMINE. An empty id list must refuse, not mean 'all'."""
    from noirdeck.secrets_scan import sweep

    claude = tmp_path / ".claude"
    _findings(conn, claude, ["CLAUDE.md"])
    out = sweep(conn, claude, [], confirm=True)
    assert out["performed"] is False
    assert "no ids" in out["reason"]
    assert (claude / "CLAUDE.md").is_file(), "nothing may move without explicit ids"


def test_sweep_requires_confirmation(tmp_path, conn):
    from noirdeck.secrets_scan import plan_sweep, sweep

    claude = tmp_path / ".claude"
    _findings(conn, claude, ["CLAUDE.md"])
    ids = plan_sweep(conn, claude)["confirm_ids"]
    out = sweep(conn, claude, ids, confirm=False)
    assert out["performed"] is False
    assert (claude / "CLAUDE.md").is_file()


def test_sweep_moves_each_file_once_and_records_where(tmp_path, conn):
    from noirdeck.secrets_scan import plan_sweep, sweep

    claude = tmp_path / ".claude"
    _findings(conn, claude, ["CLAUDE.md", "skills/a/SKILL.md"])
    plan = plan_sweep(conn, claude)
    out = sweep(conn, claude, plan["confirm_ids"], confirm=True)
    assert out["performed"] and out["files_moved"] == 2
    assert not (claude / "CLAUDE.md").exists()
    assert not (claude / "skills/a/SKILL.md").exists()
    for m in out["moved"]:
        assert m["moved_to"], "every move must record its destination"
        assert pathlib.Path(m["moved_to"]).is_file(), "and the file must actually be there"
    assert "rotate" in out["next_step"].lower(), "moving is not fixing"


def test_a_sweep_cannot_reach_outside_the_workspace(tmp_path, conn):
    """Bulk must not be able to do what single cannot: same containment check."""
    from noirdeck.secrets_scan import list_findings, sweep

    claude = tmp_path / ".claude"
    claude.mkdir()
    outsider = tmp_path / "important.md"
    outsider.write_text("do not move me")
    _findings(conn, claude, ["CLAUDE.md"])
    conn.execute("UPDATE secret_findings SET path='../important.md'")
    conn.commit()
    out = sweep(conn, claude, [list_findings(conn)[0]["id"]], confirm=True)
    assert out["files_moved"] == 0
    assert out["failed"] and "outside" in out["failed"][0]["why"]
    assert outsider.is_file()
