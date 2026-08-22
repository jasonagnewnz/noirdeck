import json
import subprocess
import time

import pytest

from noirdeck.config import Settings
from noirdeck.db import connect, init_db
from noirdeck.design import DesignStudio
from noirdeck.workspace import WorkspaceError

# Writes the mock file DesignStudio points at via $DESIGN_OUT, then a done verdict.
SUCCESS_STUB = [
    "bash",
    "-c",
    'echo "<html><body>mock</body></html>" > "$DESIGN_OUT"; '
    'echo \'VERDICT: {"status":"done","summary":"stub direction"}\'; #',
]

# Prints a done verdict but never touches $DESIGN_OUT: used both to simulate a
# mock-writing failure (propose) and as a harmless stand-in for the apply session
# (apply never checks for a file, only the verdict).
VERDICT_ONLY_STUB = ["bash", "-c", 'echo \'VERDICT: {"status":"done","summary":"stub direction"}\'; #']


@pytest.fixture
def settings(tmp_path, monkeypatch, claude_dir):
    proj = tmp_path / "projects"
    proj.mkdir()
    monkeypatch.setenv("NOIRDECK_CLAUDE_DIR", str(claude_dir))
    monkeypatch.setenv("NOIRDECK_PROJECTS_DIR", str(proj))
    monkeypatch.setenv("NOIRDECK_DB_PATH", str(tmp_path / "d.db"))
    s = Settings.load()
    init_db(s.db_path)
    repo = proj / "demo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    return s


# The variant-thread race this suite originally found is now fixed in app/design.py
# itself (DesignStudio._variants_lock): these tests run against the real locking.


def _wait_round(db_path, round_id, want, timeout=15):
    deadline = time.monotonic() + timeout
    row = None
    while time.monotonic() < deadline:
        conn = connect(db_path)
        row = conn.execute("SELECT * FROM design_rounds WHERE id=?", (round_id,)).fetchone()
        conn.close()
        if row["status"] in want:
            return row
        time.sleep(0.2)
    raise AssertionError(f"round never reached {want}, last={row['status'] if row else None}")


def test_propose_produces_ready_round_with_distinct_variants(settings):
    studio = DesignStudio(settings, claude_argv_base=SUCCESS_STUB)
    round_id = studio.propose("demo", "a settings page", library="mix", n=3)
    row = _wait_round(settings.db_path, round_id, {"ready"})
    variants = json.loads(row["variants"])
    assert len(variants) == 3
    assert all(v["status"] == "done" for v in variants)
    assert len({v["direction"] for v in variants}) == 3
    assert {v["library"] for v in variants} <= {
        "landing",
        "dashboard",
        "booking",
        "shopfront",
        "portal",
        "portfolio",
    }

    stage = settings.db_path.parent / "design" / str(round_id)
    for i in range(1, 4):
        assert (stage / f"v{i}.html").is_file()


def test_propose_dashboard_kit_pins_every_variant(settings):
    studio = DesignStudio(settings, claude_argv_base=SUCCESS_STUB)
    round_id = studio.propose("demo", "a dashboard", library="dashboard", n=3)
    row = _wait_round(settings.db_path, round_id, {"ready"})
    variants = json.loads(row["variants"])
    assert len(variants) == 3
    assert all(v["library"] == "dashboard" for v in variants)


def test_propose_unknown_kit_raises_value_error(settings):
    studio = DesignStudio(settings, claude_argv_base=SUCCESS_STUB)
    with pytest.raises(ValueError):
        studio.propose("demo", "a dashboard", library="nope", n=3)


def test_propose_unknown_project_raises_workspace_error(settings):
    studio = DesignStudio(settings, claude_argv_base=SUCCESS_STUB)
    with pytest.raises(WorkspaceError):
        studio.propose("ghost-project", "a dashboard", library="mix", n=3)


def test_capture_design_summarizes_project_ui(settings):
    repo = settings.projects_dir / "demo"
    (repo / "package.json").write_text(
        json.dumps({"dependencies": {"react": "latest", "tailwindcss": "latest", "framer-motion": "latest"}})
    )
    (repo / "src").mkdir()
    (repo / "src" / "App.jsx").write_text(
        """
        export default function App() {
          return <main className="dashboard grid gap-6 bg-slate-950 text-white rounded-2xl shadow-xl">
            <nav>Status dashboard</nav>
            <section className="metric chart table filter status kpi">Revenue chart table</section>
          </main>
        }
        """
    )
    (repo / "src" / "style.css").write_text(
        """
        :root { --accent: #14b8a6; --panel: #111827; }
        body { font-family: "IBM Plex Sans", sans-serif; color: var(--accent); }
        .card { border-radius: 12px; background: rgba(20,184,166,.16); }
        """
    )

    capture = DesignStudio(settings, claude_argv_base=SUCCESS_STUB).capture_design("demo")

    assert capture["suggested_kit"] == "dashboard"
    assert "React" in capture["evidence"]["stack"]
    assert "Tailwind" in capture["evidence"]["stack"]
    assert "#14b8a6" in capture["evidence"]["colors"]
    assert "IBM Plex Sans" in capture["evidence"]["fonts"]
    assert "dashboard" in capture["brief"]
    assert "src/style.css" in capture["brief"]


def test_propose_failed_mocks_still_reach_ready(settings):
    # No file is ever written to $DESIGN_OUT, so every variant should end "failed"
    # even though the stub reports a "done" verdict.
    studio = DesignStudio(settings, claude_argv_base=VERDICT_ONLY_STUB)
    round_id = studio.propose("demo", "a login page", library="mix", n=2)
    row = _wait_round(settings.db_path, round_id, {"ready"})
    variants = json.loads(row["variants"])
    assert len(variants) == 2
    assert all(v["status"] == "failed" for v in variants)


def test_apply_marks_round_applied_with_chosen_variant(settings):
    propose_studio = DesignStudio(settings, claude_argv_base=SUCCESS_STUB)
    round_id = propose_studio.propose("demo", "a settings page", library="mix", n=3)
    _wait_round(settings.db_path, round_id, {"ready"})

    apply_studio = DesignStudio(settings, claude_argv_base=VERDICT_ONLY_STUB)
    apply_studio.apply(round_id, "v1")
    row = _wait_round(settings.db_path, round_id, {"applied", "apply-blocked"})
    assert row["status"] == "applied"
    assert row["applied_variant"] == "v1"


def test_apply_on_variant_not_ready_raises_value_error(settings):
    studio = DesignStudio(settings, claude_argv_base=VERDICT_ONLY_STUB)
    round_id = studio.propose("demo", "a login page", library="mix", n=2)
    _wait_round(settings.db_path, round_id, {"ready"})  # variants are "failed", not "done"

    with pytest.raises(ValueError):
        studio.apply(round_id, "v1")


def test_mock_path_resolves_under_staging_root(settings):
    studio = DesignStudio(settings, claude_argv_base=SUCCESS_STUB)
    path = studio.mock_path(7, "v1")
    assert path == (studio.staging_root / "7" / "v1.html").resolve()
    assert studio.staging_root.resolve() in path.parents


@pytest.mark.parametrize("bad_key", ["../x", "v1/../../etc", "../../../etc/passwd", "v01/../x"])
def test_mock_path_rejects_path_escape_keys(settings, bad_key):
    studio = DesignStudio(settings, claude_argv_base=SUCCESS_STUB)
    with pytest.raises(ValueError):
        studio.mock_path(1, bad_key)
