"""The two ways noirdeck runs: from a checkout, and from an installed wheel.

Installed mode has no repo, so anything resolved relative to the source tree
(the SPA, the database) has to come from somewhere else. These pin that.
"""

from datetime import datetime

import pytest

from noirdeck import paths, scheduler
from noirdeck.cli import build_parser
from noirdeck.config import Settings
from noirdeck.db import connect, init_db


# --- paths ------------------------------------------------------------------
def test_checkout_is_detected_from_the_real_tree():
    assert paths.is_repo_checkout() is True
    assert paths.web_dir() is None or paths.web_dir().name in {"web", "dist"}


def test_installed_mode_puts_state_under_the_data_home(monkeypatch, tmp_path):
    monkeypatch.setattr(paths, "is_repo_checkout", lambda: False)
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    assert paths.data_home() == tmp_path / "noirdeck"
    # never inside site-packages, which an uninstall would delete
    assert paths.default_db_path() == tmp_path / "noirdeck" / "noirdeck.db"


def test_bundled_web_wins_over_a_stale_checkout_build(monkeypatch, tmp_path):
    bundled = tmp_path / "pkg" / "web"
    bundled.mkdir(parents=True)
    (bundled / "index.html").write_text("<html></html>")
    dev = tmp_path / "repo" / "frontend" / "dist"
    dev.mkdir(parents=True)
    (dev / "index.html").write_text("<html>stale</html>")
    monkeypatch.setattr(paths, "PKG_DIR", tmp_path / "pkg")
    monkeypatch.setattr(paths, "REPO_ROOT", tmp_path / "repo")
    assert paths.web_dir() == bundled


def test_relative_db_override_never_lands_in_site_packages(monkeypatch, tmp_path, claude_dir):
    monkeypatch.setattr(paths, "is_repo_checkout", lambda: False)
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.setenv("NOIRDECK_CLAUDE_DIR", str(claude_dir))
    monkeypatch.setenv("NOIRDECK_DB_PATH", "sub/x.db")
    assert Settings.load().db_path == tmp_path / "noirdeck" / "sub" / "x.db"


# --- scheduler --------------------------------------------------------------
def test_scheduler_defers_to_systemd_in_a_checkout(monkeypatch):
    monkeypatch.delenv("NOIRDECK_SCHEDULER", raising=False)
    monkeypatch.setattr(scheduler, "is_repo_checkout", lambda: True)
    assert scheduler.enabled() is False  # timers own the schedule here
    monkeypatch.setattr(scheduler, "is_repo_checkout", lambda: False)
    assert scheduler.enabled() is True


@pytest.mark.parametrize("value,want", [("off", False), ("on", True), ("1", True), ("no", False)])
def test_scheduler_env_override(monkeypatch, value, want):
    monkeypatch.setenv("NOIRDECK_SCHEDULER", value)
    monkeypatch.setattr(scheduler, "is_repo_checkout", lambda: False)
    assert scheduler.enabled() is want


def test_next_due_is_always_in_the_future():
    now = datetime(2026, 8, 16, 9, 0)
    assert scheduler.next_due("02:30", now) == datetime(2026, 8, 17, 2, 30)
    assert scheduler.next_due("23:30", now) == datetime(2026, 8, 16, 23, 30)
    # exactly on the boundary must roll forward, or seeding fires instantly
    assert scheduler.next_due("hourly", now) == datetime(2026, 8, 16, 10, 0)
    assert scheduler.next_due("02:30", datetime(2026, 8, 16, 2, 30)) == datetime(2026, 8, 17, 2, 30)


def _settings(tmp_path, claude_dir):
    db = tmp_path / "s.db"
    init_db(db)
    return Settings(
        claude_dir=claude_dir,
        projects_dir=tmp_path,
        db_path=db,
        port=1,
        mining_armed=False,
        overnight_armed=False,
        mine_max_batches=1,
    )


def test_seeding_arms_jobs_without_running_them(tmp_path, claude_dir, monkeypatch):
    s = _settings(tmp_path, claude_dir)
    ran = []
    monkeypatch.setattr(scheduler, "_run_job", lambda n, st: ran.append(n))
    sched = scheduler.Scheduler(s)
    sched.seed(datetime(2026, 8, 16, 9, 0))
    assert not ran
    assert sched.tick(datetime(2026, 8, 16, 9, 0)) == []


def test_due_job_runs_once_then_rearms(tmp_path, claude_dir, monkeypatch):
    s = _settings(tmp_path, claude_dir)
    ran = []
    monkeypatch.setattr(scheduler, "_run_job", lambda n, st: ran.append(n) or {"ok": True})
    sched = scheduler.Scheduler(s)
    sched.seed(datetime(2026, 8, 16, 9, 0))
    at = datetime(2026, 8, 16, 10, 0)  # hourly improve is now due
    assert sched.tick(at) == ["improve"]
    # a second tick in the same minute must not re-run it
    assert sched.tick(at) == []
    assert ran == ["improve"]


def test_a_failing_job_is_audited_not_silently_skipped(tmp_path, claude_dir, monkeypatch):
    s = _settings(tmp_path, claude_dir)

    def boom(name, settings):
        raise RuntimeError("ollama unreachable")

    monkeypatch.setattr(scheduler, "_run_job", boom)
    sched = scheduler.Scheduler(s)
    sched.seed(datetime(2026, 8, 16, 9, 0))
    sched.tick(datetime(2026, 8, 16, 10, 0))
    conn = connect(s.db_path)
    try:
        rows = conn.execute("SELECT action, detail FROM audit_log WHERE actor='scheduler'").fetchall()
    finally:
        conn.close()
    assert rows and rows[0]["action"] == "failed:improve"
    # the exception CLASS must be in the record, not just its message
    assert "RuntimeError" in rows[0]["detail"]


# --- systemd units: the checkout-mode deployment contract --------------------
# Units are COPIED into ~/.config/systemd/user, not symlinked, so nothing in the
# tree can drift them back into line. Renaming the package once left all five
# invoking a module that no longer existed: the console stayed down, the hourly
# job failed in 39ms, and the nightly offsite backup would have failed silently
# — with CI green throughout, because every test imported noirdeck.* directly.
def _exec_starts() -> dict[str, str]:
    out = {}
    for unit in sorted((paths.REPO_ROOT / "ops").glob("*.service")):
        for line in unit.read_text().splitlines():
            if line.startswith("ExecStart="):
                out[unit.name] = line.split("=", 1)[1].strip()
    return out


def _module_target(exec_start: str) -> str:
    """The module a unit actually runs: '-m pkg.mod', or uvicorn's 'pkg.mod:attr'."""
    parts = exec_start.split()
    if "-m" in parts:
        after = parts[parts.index("-m") + 1]
        if after == "uvicorn":
            return next(p for p in parts if ":" in p and "/" not in p).split(":")[0]
        return after
    raise AssertionError(f"no module target in: {exec_start}")


def test_every_unit_runs_a_module_that_actually_exists():
    """The guard that was missing. Catches a package rename that CI cannot see."""
    import importlib.util

    starts = _exec_starts()
    assert starts, "no ops/*.service units found"
    for unit, exec_start in starts.items():
        module = _module_target(exec_start)
        assert module.startswith("noirdeck"), f"{unit} runs {module!r}, not the noirdeck package"
        assert importlib.util.find_spec(module) is not None, f"{unit} would die at startup: no module named {module!r}"


def test_the_server_unit_points_at_a_real_asgi_app():
    exec_start = _exec_starts()["noirdeck.service"]
    target = next(p for p in exec_start.split() if ":" in p and "/" not in p)
    module, attr = target.split(":")
    mod = __import__(module, fromlist=[attr])
    assert hasattr(mod, attr), f"{target} is not importable — uvicorn would fail to boot"


def test_unit_paths_are_internally_consistent():
    """WorkingDirectory and the interpreter must live under the same clone, or
    install-service produces units that cannot start from anywhere."""
    for unit in sorted((paths.REPO_ROOT / "ops").glob("*.service")):
        text = unit.read_text()
        workdir = next(
            (ln.split("=", 1)[1].strip() for ln in text.splitlines() if ln.startswith("WorkingDirectory=")),
            None,
        )
        exec_start = next(ln.split("=", 1)[1].strip() for ln in text.splitlines() if ln.startswith("ExecStart="))
        assert workdir, f"{unit.name} has no WorkingDirectory"
        root = workdir[: -len("/backend")] if workdir.endswith("/backend") else workdir
        assert exec_start.startswith(f"{root}/.venv/bin/python"), (
            f"{unit.name}: interpreter {exec_start.split()[0]!r} is not inside {root!r}"
        )


def test_every_scheduled_job_has_a_unit_for_checkout_mode():
    """Checkout mode runs on timers, installed mode on the in-process scheduler.
    A job that exists in only one of them silently never runs in the other."""
    units = {p.stem.replace("noirdeck-", "") for p in (paths.REPO_ROOT / "ops").glob("noirdeck-*.service")}
    assert set(scheduler.JOBS) <= units, f"scheduled jobs with no systemd unit: {set(scheduler.JOBS) - units}"


# --- cli --------------------------------------------------------------------
def test_bare_invocation_serves_and_opens():
    args = build_parser().parse_args(["serve"])
    assert args.open is True and args.port


def test_no_open_flag():
    assert build_parser().parse_args(["serve", "--no-open"]).open is False


def test_run_only_accepts_known_jobs():
    assert build_parser().parse_args(["run", "vault"]).job == "vault"
    with pytest.raises(SystemExit):
        build_parser().parse_args(["run", "rm-rf"])


def test_every_scheduled_job_is_runnable_from_the_cli():
    """A job the scheduler knows but the CLI cannot run by hand is undebuggable."""
    parser = build_parser()
    for job in scheduler.JOBS:
        assert parser.parse_args(["run", job]).job == job
