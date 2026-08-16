import pytest

from app.db import connect, init_db, utcnow
from app.digest import compose


@pytest.fixture
def conn(tmp_path):
    db = tmp_path / "t.db"
    init_db(db)
    c = connect(db)
    yield c
    c.close()


def test_empty_estate_is_all_quiet(conn):
    out = compose(conn)
    assert out["attention"] == 0
    assert out["lines"] == ["All quiet. Nothing needs you right now."]


def test_attention_items_lead_and_are_counted(conn):
    conn.execute(
        "INSERT INTO proposals (kind,title,body,status,created_at) VALUES ('skill','t','b','proposed',?)", (utcnow(),)
    )
    conn.execute(
        "INSERT INTO builds (name,path,prompt,status,created_at) VALUES ('site','/x','p','awaiting_plan',?)",
        (utcnow(),),
    )
    conn.execute(
        "INSERT INTO queue (project,title,prompt,status,created_at,finished_at) VALUES ('/x','t','p','blocked',?,?)",
        (utcnow(), utcnow()),
    )
    conn.execute(
        "INSERT INTO queue (project,title,prompt,status,created_at,finished_at) VALUES ('/x','t2','p','done',?,?)",
        (utcnow(), utcnow()),
    )
    conn.commit()
    out = compose(conn)
    text = " ".join(out["lines"])
    assert "1 proposal is waiting for your decision." in text
    assert "Build #1 (site) is waiting for you to approve its plan." in text
    assert "1 overnight task got stuck" in text
    assert "1 overnight task finished" in text
    assert out["attention"] == 3
    # attention lines come before informational ones
    assert out["lines"].index("1 overnight task finished while you were away.") > out["lines"].index(
        "1 proposal is waiting for your decision."
    )


def test_old_queue_activity_outside_24h_ignored(conn):
    conn.execute(
        "INSERT INTO queue (project,title,prompt,status,created_at,finished_at) "
        "VALUES ('/x','t','p','done',?, '2020-01-01T00:00:00+00:00')",
        (utcnow(),),
    )
    conn.commit()
    assert compose(conn)["lines"] == ["All quiet. Nothing needs you right now."]


def test_vault_verified_is_info_unverified_is_attention(conn):
    conn.execute(
        "INSERT INTO vault_runs (started_at,finished_at,status,restore_verified) VALUES (?,?, 'done', 0)",
        (utcnow(), utcnow()),
    )
    conn.commit()
    out = compose(conn)
    assert "No offsite backup has passed a restore test yet." in out["lines"]
    assert out["attention"] == 1

    conn.execute(
        "INSERT INTO vault_runs (started_at,finished_at,status,restore_verified) VALUES (?,?, 'done', 1)",
        (utcnow(), utcnow()),
    )
    conn.commit()
    out = compose(conn)
    assert out["attention"] == 0
    assert any("last verified offsite backup was under an hour ago" in line for line in out["lines"])


def test_token_spend_line(conn):
    conn.execute(
        "INSERT INTO queue (project,title,prompt,status,created_at,finished_at,tokens_out) "
        "VALUES ('/x','t','p','done',?,?,150000)",
        (utcnow(), utcnow()),
    )
    conn.execute(
        "INSERT INTO builds (name,path,prompt,status,created_at,finished_at,tokens_out) "
        "VALUES ('b','/x','p','done',?,?,60000)",
        (utcnow(), utcnow()),
    )
    conn.commit()
    out = compose(conn)
    assert any("spent 210k output tokens across 2 jobs" in line for line in out["lines"])
    # spend is information, not attention
    assert out["attention"] == 0
