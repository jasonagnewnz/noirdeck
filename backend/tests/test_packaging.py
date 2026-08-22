"""The two ways noirdeck runs: from a checkout, and from an installed wheel.

Installed mode has no repo, so anything resolved relative to the source tree
(the SPA, the database) has to come from somewhere else. These pin that.
"""

import importlib.util
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
#: with CI green throughout, because every test imported noirdeck.* directly.
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
    assert hasattr(mod, attr), f"{target} is not importable: uvicorn would fail to boot"


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


def test_the_pipeline_guard_ships_inside_the_package():
    """THE 2026-08-19 SHIPPING DEFECT. The guard lived in ops/, pyproject
    packages only backend/noirdeck, so it was absent from every wheel and
    guard_settings_args() returned [] for every paying customer: unattended
    sessions ran with acceptEdits and no hook at all. It passed every test,
    because every test ran in a checkout where ops/ exists.

    The guard must therefore be importable AS PART OF THE PACKAGE, and the module
    file must sit under the packaged directory.
    """
    from noirdeck.guard import GUARD_SCRIPT, guard_available

    assert guard_available(), f"the guard is missing at {GUARD_SCRIPT}: it will not ship"
    guard_file = GUARD_SCRIPT.resolve()
    packaged = (paths.REPO_ROOT / "backend" / "noirdeck").resolve()
    assert packaged in guard_file.parents or guard_file.parent == packaged, (
        f"the guard lives at {guard_file}, outside the packaged tree {packaged}: it will not be in the wheel"
    )


def test_wheel_packages_the_directory_the_guard_lives_in():
    """Pins the packaging config itself, so moving the guard back out, or
    narrowing `packages`, fails here rather than in a customer's install."""
    import tomllib

    cfg = tomllib.loads((paths.REPO_ROOT / "pyproject.toml").read_text())
    packaged = cfg["tool"]["hatch"]["build"]["targets"]["wheel"]["packages"]
    assert "backend/noirdeck" in packaged
    assert (paths.REPO_ROOT / "backend" / "noirdeck" / "pipeline_guard.py").is_file()


def test_guard_fails_closed_when_it_cannot_be_found(monkeypatch):
    """A missing guard used to warn to stderr and return []: in a background
    process that is an inert control with a fast path. No boundary, no pipeline."""
    from noirdeck import guard

    monkeypatch.setattr(guard, "guard_available", lambda: False)
    with pytest.raises(guard.GuardUnavailable):
        guard.guard_settings_args()


# ── the headless path ───────────────────────────────────────────────────────
# `do` and `status` are the whole reason to have a CLI: a task from a terminal
# with no browser and no clicks. They must stay wired, and `do` must keep reusing
# the queue's own task path rather than growing a second implementation.


def test_the_headless_commands_are_reachable():
    parser = build_parser()
    for argv, expect in [
        (["do", "add a retry"], {"task": "add a retry", "later": False}),
        (["do", "x", "--later"], {"later": True}),
        (["do", "x", "--project", "demo"], {"project": "demo"}),
        (["do", "x", "--depth", "heavy"], {"depth": "heavy"}),
        (["status"], {"json": False}),
        (["status", "--json"], {"json": True}),
    ]:
        ns = parser.parse_args(argv)
        for k, v in expect.items():
            assert getattr(ns, k) == v, f"{argv}: {k}"


def test_do_reuses_the_queue_task_path_rather_than_reimplementing_it():
    """A second task implementation would drift from the console's within a week
    and lose the context pack, the guardrails, the guard and the staged plan/check.
    Pin that `do` calls run_task."""
    import inspect

    from noirdeck import cli

    src = inspect.getsource(cli.do)
    assert "run_task" in src, "do must delegate to overnight.run_task"
    assert "INSERT INTO queue" in src, "and the task must exist as a queue row, so it is auditable"


def test_do_respects_the_licence_gate():
    import inspect

    from noirdeck import cli

    src = inspect.getsource(cli.do)
    assert "allows(" in src and "overnight" in src, "the terminal must not be a way around the gate"


def test_do_arms_but_never_widens_an_existing_contract():
    import inspect

    from noirdeck import cli

    src = inspect.getsource(cli.do)
    assert 'status(conn).get("overnight"' in src and "live" in src, (
        "must only arm when nothing is live: silently widening an operator's budget is what arming exists to prevent"
    )


def test_project_resolution_prefers_cwd_and_refuses_outside_the_projects_dir(tmp_path, monkeypatch):
    """Standing in a repo and being made to name it is the friction that makes a CLI
    feel slower than clicking. But a repo OUTSIDE the projects dir must be refused,
    not silently worked in."""
    import subprocess

    from noirdeck import cli
    from noirdeck.config import Settings

    projects = tmp_path / "projects"
    inside = projects / "demo"
    inside.mkdir(parents=True)
    subprocess.run(["git", "-C", str(inside), "init", "-q"], check=True)
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    subprocess.run(["git", "-C", str(outside), "init", "-q"], check=True)

    settings = Settings(
        claude_dir=tmp_path / ".claude",
        projects_dir=projects,
        db_path=tmp_path / "d.db",
        port=1,
        mining_armed=False,
        overnight_armed=False,
        mine_max_batches=1,
    )

    monkeypatch.chdir(inside)
    name, repo = cli._resolve_project(settings, None)
    assert name == "demo" and repo == inside.resolve()

    monkeypatch.chdir(outside)
    name, repo = cli._resolve_project(settings, None)
    assert name is None, "a repo outside the projects dir must be refused, not assumed"

    name, repo = cli._resolve_project(settings, "nope")
    assert name is None, "a named project that does not exist must be refused"
