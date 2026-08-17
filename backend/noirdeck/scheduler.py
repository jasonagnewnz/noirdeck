"""In-process scheduler for the recurring jobs.

A source checkout drives these from systemd user timers (ops/*.timer). An
installed copy has no systemd — and may not be on Linux at all — so the server
runs them itself. Both modes must never be active at once or every job fires
twice, which is why the default follows the install mode and the env var
NOIRDECK_SCHEDULER can force either way.

Nothing here decides whether work is allowed to happen: every job is already
fail-closed behind its own arming contract, so a scheduler tick on an unarmed
subsystem is a no-op by design.
"""

from __future__ import annotations

import threading
import traceback
from datetime import datetime, timedelta

from .config import Settings
from .db import audit, connect, init_db
from .paths import is_repo_checkout

# name -> (callable(settings) -> dict, schedule spec)
# "HH:MM" = daily at that local time; "hourly" = every hour on the hour.
JOBS: dict[str, str] = {
    "mine": "02:30",
    "vault": "02:34",
    "overnight": "23:30",
    "improve": "hourly",
}

TICK_SECONDS = 60


def enabled() -> bool:
    """Off in a checkout (systemd timers own the schedule there), on when installed."""
    raw = (__import__("os").environ.get("NOIRDECK_SCHEDULER") or "").strip().lower()
    if raw in {"1", "on", "true", "yes"}:
        return True
    if raw in {"0", "off", "false", "no"}:
        return False
    return not is_repo_checkout()


def mode() -> str:
    """Which mechanism owns the recurring jobs in this install."""
    return "checkout (systemd timers)" if is_repo_checkout() else "installed (in-process)"


def _run_job(name: str, settings: Settings) -> dict:
    """Import inside the call: these modules pull in heavy readers, and a job
    that is never due should never cost startup time."""
    if name == "mine":
        from .miner.heuristics import run_heuristics

        conn = connect(settings.db_path)
        try:
            return {"heuristics": run_heuristics(conn, settings.claude_dir)}
        finally:
            conn.close()
    if name == "vault":
        from .vault import run_backup

        return run_backup(settings)
    if name == "overnight":
        from .overnight import run_queue

        return run_queue(settings, 6.0, False)
    if name == "improve":
        from .improve import run_improver

        return run_improver(settings)
    raise ValueError(f"unknown job {name!r}")


def next_due(spec: str, after: datetime) -> datetime:
    """First moment STRICTLY after `after` that matches the schedule.

    Strict matters at both ends: seeding at exactly 09:00 must not make an
    hourly job instantly due on a fresh install, and re-arming a job that just
    ran must not hand it back its own due time.
    """
    if spec == "hourly":
        top = after.replace(minute=0, second=0, microsecond=0)
        return top + timedelta(hours=1) if top <= after else top
    hh, mm = (int(p) for p in spec.split(":"))
    today = after.replace(hour=hh, minute=mm, second=0, microsecond=0)
    return today + timedelta(days=1) if today <= after else today


class Scheduler:
    """Wakes once a minute, runs whatever came due, records the outcome.

    Due times are persisted so a restart neither re-runs a job it already did
    nor silently swallows one — the same property Persistent=true gives a timer.
    """

    def __init__(self, settings: Settings):
        self.settings = settings
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # --- persistence -----------------------------------------------------
    def _due_table(self, conn) -> dict[str, datetime]:
        rows = conn.execute("SELECT name, due_at FROM scheduler_state").fetchall()
        return {r["name"]: datetime.fromisoformat(r["due_at"]) for r in rows}

    def _set_due(self, conn, name: str, due: datetime) -> None:
        conn.execute(
            "INSERT INTO scheduler_state (name, due_at) VALUES (?, ?) "
            "ON CONFLICT(name) DO UPDATE SET due_at=excluded.due_at",
            (name, due.isoformat(timespec="seconds")),
        )
        conn.commit()

    def seed(self, now: datetime | None = None) -> None:
        """Give every job a due time without running anything on first boot."""
        now = now or datetime.now()
        conn = connect(self.settings.db_path)
        try:
            known = self._due_table(conn)
            for name, spec in JOBS.items():
                if name not in known:
                    self._set_due(conn, name, next_due(spec, now))
        finally:
            conn.close()

    # --- the loop --------------------------------------------------------
    def tick(self, now: datetime | None = None) -> list[str]:
        """Run every job that is due. Returns the names that ran."""
        now = now or datetime.now()
        conn = connect(self.settings.db_path)
        try:
            due = self._due_table(conn)
        finally:
            conn.close()

        ran: list[str] = []
        for name, spec in JOBS.items():
            when = due.get(name)
            if when is None or when > now:
                continue
            # Re-arm BEFORE running: a job that throws must not retry every
            # tick for the rest of the day.
            conn = connect(self.settings.db_path)
            try:
                self._set_due(conn, name, next_due(spec, now))
                try:
                    result = _run_job(name, self.settings)
                    audit(conn, "scheduler", f"ran:{name}", str(result)[:400])
                except Exception as exc:  # noqa: BLE001 — one bad job must not stop the rest
                    # A silent skip in a background thread is how the improver's
                    # first two defects stayed hidden; always leave a record,
                    # and name the exception class (a bare message is not triage-able).
                    audit(
                        conn,
                        "scheduler",
                        f"failed:{name}",
                        f"{type(exc).__name__}: {exc}\n{traceback.format_exc()[-600:]}",
                    )
                conn.commit()
            finally:
                conn.close()
            ran.append(name)
        return ran

    def _loop(self) -> None:
        while not self._stop.wait(TICK_SECONDS):
            try:
                self.tick()
            except Exception:  # noqa: BLE001 — the loop itself must survive anything
                pass

    def start(self) -> None:
        init_db(self.settings.db_path)
        self.seed()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="noirdeck-scheduler")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def status(self) -> dict:
        conn = connect(self.settings.db_path)
        try:
            due = self._due_table(conn)
        finally:
            conn.close()
        return {
            "enabled": enabled(),
            "mode": mode(),
            "jobs": [
                {"name": n, "schedule": s, "next_due": due.get(n).isoformat() if due.get(n) else None}
                for n, s in JOBS.items()
            ],
        }
