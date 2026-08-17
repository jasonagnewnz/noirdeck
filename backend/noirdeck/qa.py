"""Commercial-readiness gates per project: BLOCKER / GAP / PASS with evidence.
Read-only: inspects the working tree and git state, never modifies anything."""

from __future__ import annotations

import subprocess
from pathlib import Path

SECRET_GREP = r"AKIA[0-9A-Z]\{16\}\|ghp_[A-Za-z0-9]\{36\}\|sk-ant-\|github_pat_\|BEGIN [A-Z ]*PRIVATE KEY"


def _git(repo: Path, *args: str, timeout: int = 10) -> tuple[int, str]:
    try:
        r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout.strip()
    except (subprocess.TimeoutExpired, OSError):
        return 1, ""


def evaluate_project(repo: Path, light: bool = False) -> dict:
    """light=True skips the git-grep secret scan (the expensive gate) for fleet-wide
    boards; the full scan runs in per-project views."""
    gates: list[dict] = []

    def gate(gid: str, title: str, verdict: str, evidence: str) -> None:
        gates.append({"id": gid, "title": title, "verdict": verdict, "evidence": evidence})

    # --- secrets ---
    rc, tracked_env = _git(repo, "ls-files", ".env", ".env.*", "*.env")
    tracked_env_files = [f for f in tracked_env.splitlines() if not f.endswith(".example")]
    gate(
        "env-tracked",
        "No .env files tracked in git",
        "BLOCKER" if tracked_env_files else "PASS",
        ", ".join(tracked_env_files) or "clean",
    )

    gi = repo / ".gitignore"
    gi_text = gi.read_text(errors="replace") if gi.is_file() else ""
    covers = ".env" in gi_text
    gate(
        "gitignore-env",
        ".gitignore covers .env",
        "PASS" if covers else ("BLOCKER" if (repo / ".env").exists() else "GAP"),
        ".gitignore has .env rule" if covers else "no .env rule in .gitignore",
    )

    if not light:
        rc, hits = _git(repo, "grep", "-I", "-l", "-e", SECRET_GREP, "--", ".", timeout=20)
        hit_files = hits.splitlines() if rc == 0 and hits else []
        gate(
            "secret-shapes",
            "No secret-shaped values in tracked files",
            "BLOCKER" if hit_files else "PASS",
            "; ".join(hit_files[:5]) or "no matches",
        )

    # --- engineering hygiene ---
    has_tests = any(repo.glob("**/test_*.py")) or (repo / "tests").is_dir() or any(repo.glob("**/*.test.*"))
    gate(
        "tests", "Tests present", "PASS" if has_tests else "GAP", "found" if has_tests else "no tests/ or test_* files"
    )

    gate("readme", "README exists", "PASS" if (repo / "README.md").is_file() else "GAP", "")

    has_deploy_doc = (
        (repo / "docs" / "DEPLOYMENT.md").is_file() or any(repo.glob("DEPLOY*.md")) or any(repo.glob("docs/DEPLOY*"))
    )
    gate(
        "deploy-doc",
        "Deploy + verify procedure documented",
        "PASS" if has_deploy_doc else "GAP",
        "" if has_deploy_doc else "no docs/DEPLOYMENT.md",
    )

    # --- work-loss risk ---
    rc, status = _git(repo, "status", "--porcelain")
    dirty = len(status.splitlines()) if status else 0
    gate(
        "clean-tree",
        "No uncommitted work",
        "PASS" if dirty == 0 else "GAP",
        f"{dirty} dirty file(s)" if dirty else "clean",
    )

    rc, unpushed = _git(repo, "rev-list", "--count", "@{u}..HEAD")
    if rc != 0:
        gate("pushed", "Work exists off-box", "GAP", "branch has no upstream (local-only)")
    else:
        n = int(unpushed) if unpushed.isdigit() else 0
        gate(
            "pushed", "Work exists off-box", "PASS" if n == 0 else "GAP", f"{n} unpushed commit(s)" if n else "in sync"
        )

    order = {"BLOCKER": 0, "GAP": 1, "PASS": 2}
    overall = min((g["verdict"] for g in gates), key=lambda v: order[v])
    return {"project": repo.name, "path": str(repo), "overall": overall, "gates": gates}


_fleet_cache: dict = {"ts": 0.0, "data": None}
_FLEET_TTL = 300  # seconds


def evaluate_fleet(projects_dir: Path) -> list[dict]:
    import time

    if _fleet_cache["data"] is not None and time.monotonic() - _fleet_cache["ts"] < _FLEET_TTL:
        return _fleet_cache["data"]
    out = []
    if projects_dir.is_dir():
        for child in sorted(projects_dir.iterdir()):
            if child.is_dir() and (child / ".git").exists():
                out.append(evaluate_project(child, light=True))
    _fleet_cache.update(ts=time.monotonic(), data=out)
    return out
