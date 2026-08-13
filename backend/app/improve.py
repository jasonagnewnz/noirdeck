"""Improve — mapped repos that a small LOCAL model quietly improves.

The trust design does the heavy lifting, not the model:
- every change happens in a TEMPORARY git worktree (the real working tree is
  never touched — sessions may be editing it right now)
- on its own branch, one small change per repo per run
- syntax-gated (py_compile), diff-capped, test-gated when tests exist
- recorded as a PROPOSED change with the full diff; merge is a human click
- fail-closed: needs NOIRDECK_IMPROVER_ARMED=true AND a live arming contract,
  and does nothing at all when the local model isn't reachable

Zero-egress: the model is Ollama on 127.0.0.1. Candidate selection is
deterministic (readiness-gate style scans); the model only writes prose-level
improvements — docstrings, comment tidy, README gaps — the change classes a
7B model does well and a diff cap keeps honest."""
from __future__ import annotations

import json
import os
import py_compile
import re
import subprocess
import tempfile
import threading
import urllib.request
from pathlib import Path

from .config import Settings
from .db import audit, connect, utcnow

OLLAMA = os.environ.get("NOIRDECK_OLLAMA_URL", "http://127.0.0.1:11434")
MAX_CHANGED_LINES = 120
MAX_FILE_LINES = 400          # only small files — small model, small blast radius
GEN_TIMEOUT_S = 900           # CPU inference is slow; overnight doesn't care
_RUN_LOCK = threading.Lock()


def safe_repo(settings: Settings, project: str) -> Path | None:
    """project must be a single path segment naming a direct child of the
    projects dir — ~ is itself a git repo, so ".." would pass a .git check
    (same escape class fixed in the files and hygiene APIs)."""
    if "/" in project or "\\" in project or project in ("", ".", ".."):
        return None
    base = settings.projects_dir.resolve()
    repo = (base / project).resolve()
    if repo.parent != base or not (repo / ".git").exists():
        return None
    return repo


def armed() -> bool:
    return os.environ.get("NOIRDECK_IMPROVER_ARMED", "") == "true"


def local_model() -> str:
    return os.environ.get("NOIRDECK_LOCAL_MODEL", "qwen2.5-coder:7b")


def model_available() -> bool:
    try:
        with urllib.request.urlopen(f"{OLLAMA}/api/tags", timeout=5) as r:
            tags = json.load(r)
        want = local_model().split(":")[0]
        return any(want in (m.get("name") or "") for m in tags.get("models", []))
    except OSError:
        return False


def _generate(prompt: str) -> str | None:
    body = json.dumps({"model": local_model(), "prompt": prompt, "stream": False,
                       "options": {"temperature": 0.2, "num_predict": 4096}}).encode()
    req = urllib.request.Request(f"{OLLAMA}/api/generate", data=body,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=GEN_TIMEOUT_S) as r:
            return json.load(r).get("response")
    except OSError:
        return None


# ── candidates: deterministic scans, smallest-safe-change first ─────────────

def _py_files(repo: Path) -> list[Path]:
    skip = {".git", "node_modules", ".venv", "venv", "dist", "__pycache__", "build"}
    out = []
    for p in repo.rglob("*.py"):
        if not any(part in skip for part in p.parts):
            out.append(p)
    return out


def candidates(repo: Path) -> list[dict]:
    out = []
    for f in _py_files(repo):
        try:
            text = f.read_text(errors="replace")
        except OSError:
            continue
        lines = text.count("\n") + 1
        if lines > MAX_FILE_LINES:
            continue
        rel = str(f.relative_to(repo))
        defs = len(re.findall(r"^\s*def \w+", text, re.M))
        docstrings = len(re.findall(r'^\s*(?:"""|\'\'\')', text, re.M))
        if defs >= 3 and docstrings < defs // 2:
            out.append({"kind": "docstrings", "file": rel, "score": defs - docstrings,
                        "why": f"{defs} functions, few docstrings"})
        stale = len(re.findall(r"^\s*#\s*(TODO|FIXME|XXX|HACK)\b", text, re.M))
        commented_code = len(re.findall(r"^\s*#\s*(?:def |class |import |print\()", text, re.M))
        if stale + commented_code >= 3:
            out.append({"kind": "comment_tidy", "file": rel, "score": stale + commented_code,
                        "why": f"{stale} stale markers, {commented_code} commented-out code lines"})
    readme = repo / "README.md"
    if readme.is_file():
        text = readme.read_text(errors="replace").lower()
        missing = [s for s in ("how to run", "install", "test") if s not in text]
        if len(missing) >= 2 and text.count("\n") < 120:
            out.append({"kind": "readme_gap", "file": "README.md", "score": len(missing),
                        "why": f"README missing: {', '.join(missing)}"})
    out.sort(key=lambda c: -c["score"])
    return out


_PROMPTS = {
    "docstrings": (
        "Add concise, accurate docstrings to functions/classes that lack them. "
        "Do NOT change any executable code, names, signatures, imports, or logic. "
        "Do NOT add type hints. Keep existing docstrings untouched."),
    "comment_tidy": (
        "Tidy the comments ONLY: delete commented-out dead code, resolve or reword stale "
        "TODO/FIXME markers into clear statements, fix comment typos. Do NOT change any "
        "executable code, names, signatures, imports, or logic."),
    "readme_gap": (
        "Improve this README: keep everything true and in the same voice, and add the "
        "missing practical sections (how to install, how to run, how to test) inferred "
        "ONLY from information already present in the file. Do not invent commands."),
}


def _propose_content(kind: str, path: Path) -> str | None:
    original = path.read_text(errors="replace")
    prompt = (
        f"You improve code quality with minimal, surgical edits.\n{_PROMPTS[kind]}\n\n"
        f"Return the COMPLETE new file content between the markers, nothing else.\n"
        f"<<<FILE>>>\n{original}\n<<<END>>>\n\n"
        f"New file content:\n<<<FILE>>>\n")
    resp = _generate(prompt)
    if not resp:
        return None
    m = re.search(r"(.*?)<<<END>>>", resp, re.S)
    content = (m.group(1) if m else resp).strip("\n") + "\n"
    content = content.replace("<<<FILE>>>", "").lstrip("\n")
    if not content.strip():
        return None
    orig_lines, new_lines = original.splitlines(), content.splitlines()
    if len(new_lines) < len(orig_lines) * 0.7:
        return None  # a "tidy" that deletes 30% of the file is not subtle
    changed = sum(1 for a, b in zip(orig_lines, new_lines) if a != b) \
        + abs(len(new_lines) - len(orig_lines))
    if changed == 0 or changed > MAX_CHANGED_LINES:
        return None
    return content


def _code_unchanged(kind: str, original: str, new: str) -> bool:
    """For python edits: the executable structure must be identical —
    docstrings/comments are the ONLY thing a small model is trusted to touch."""
    if kind == "readme_gap":
        return True
    import ast
    try:
        a, b = ast.parse(original), ast.parse(new)
    except SyntaxError:
        return False
    for tree in (a, b):
        for node in ast.walk(tree):
            # strip docstrings so they don't participate in the comparison
            if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef,
                                 ast.ClassDef)) and node.body and \
               isinstance(node.body[0], ast.Expr) and \
               isinstance(node.body[0].value, ast.Constant) and \
               isinstance(node.body[0].value.value, str):
                node.body = node.body[1:] or [ast.Pass()]
    return ast.dump(a) == ast.dump(b)


def _run_tests(worktree: Path) -> str:
    if (worktree / "pytest.ini").exists() or (worktree / "backend" / "tests").is_dir() \
            or (worktree / "tests").is_dir():
        try:
            p = subprocess.run(["python3", "-m", "pytest", "-q", "-x"], cwd=worktree,
                               capture_output=True, text=True, timeout=600)
            tail = (p.stdout or "").strip().splitlines()[-1:] or ["no output"]
            if p.returncode == 5:  # a tests/ dir with no collectable python tests
                return "no tests collected"
            return ("pass: " if p.returncode == 0 else "FAIL: ") + tail[0][:200]
        except (OSError, subprocess.TimeoutExpired):
            return "FAIL: pytest did not complete"
    return "no tests found"


def improve_one(settings: Settings, conn, project: str) -> dict | None:
    repo = safe_repo(settings, project)
    if repo is None:
        return None
    cands = candidates(repo)
    if not cands:
        return None
    cand = cands[0]
    branch = f"improve/{utcnow()[:10]}-{cand['kind']}-{cand['file'].replace('/', '-')[:40]}"
    with tempfile.TemporaryDirectory(prefix="noirdeck-improve-") as td:
        wt = Path(td) / "wt"
        try:
            subprocess.run(["git", "-C", str(repo), "worktree", "add", "-b", branch,
                            str(wt), "HEAD"], capture_output=True, text=True,
                           timeout=60, check=True)
        except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
            return None
        try:
            target = wt / cand["file"]
            original = target.read_text(errors="replace")
            content = _propose_content(cand["kind"], target)
            if content is None:
                return {"skipped": cand, "reason": "model produced no safe content"}
            target.write_text(content)
            if target.suffix == ".py":
                try:
                    py_compile.compile(str(target), doraise=True)
                except py_compile.PyCompileError:
                    return {"skipped": cand, "reason": "result does not compile"}
                if not _code_unchanged(cand["kind"], original, content):
                    return {"skipped": cand, "reason": "executable code changed — rejected"}
            tests = _run_tests(wt)
            if tests.startswith("FAIL"):
                return {"skipped": cand, "reason": tests}
            committed = subprocess.run(
                ["git", "-C", str(wt), "-c", "user.name=noirdeck-improve",
                 "-c", "user.email=improve@noirdeck.local", "commit", "-aqm",
                 f"improve({cand['kind']}): {cand['file']} [noirdeck local model]"],
                capture_output=True, text=True, timeout=60)
            if committed.returncode != 0:
                return {"skipped": cand,
                        "reason": f"commit failed: {(committed.stderr or '')[-120:]}"}
            diff = subprocess.run(["git", "-C", str(wt), "show", "--stat", "--patch",
                                   "HEAD", "--", cand["file"]],
                                  capture_output=True, text=True, timeout=60).stdout
            cur = conn.execute(
                "INSERT INTO improve_changes (project,branch,kind,target_file,summary,"
                "diff,tests,model,created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                (project, branch, cand["kind"], cand["file"], cand["why"],
                 diff[:60000], tests, local_model(), utcnow()))
            conn.commit()
            audit(conn, "improver", "change_proposed",
                  f"id={cur.lastrowid} {project} {cand['kind']} {cand['file']}")
            return {"proposed": {"id": cur.lastrowid, "project": project, **cand,
                                 "branch": branch, "tests": tests}}
        finally:
            subprocess.run(["git", "-C", str(repo), "worktree", "remove", "--force",
                            str(wt)], capture_output=True, timeout=60)
            # branch survives the worktree; drop it only if nothing was recorded
            kept = conn.execute("SELECT 1 FROM improve_changes WHERE branch=?",
                                (branch,)).fetchone()
            if not kept:
                subprocess.run(["git", "-C", str(repo), "branch", "-Dq", branch],
                               capture_output=True, timeout=30)


def run_improver(settings: Settings) -> dict:
    if not armed():
        return {"skipped": True, "reason": "NOIRDECK_IMPROVER_ARMED != true (fail-closed)"}
    if not model_available():
        return {"skipped": True, "reason": f"local model {local_model()} not available"}
    from .arming import check, consume
    if not _RUN_LOCK.acquire(blocking=False):
        return {"skipped": True, "reason": "already running"}
    conn = connect(settings.db_path)
    results = {"proposed": 0, "skipped": 0, "details": []}
    try:
        repos = [r["project"] for r in conn.execute(
            "SELECT project FROM improve_repos WHERE enabled=1 ORDER BY project").fetchall()]
        for project in repos:
            allowed, reason = check(conn, "improver")
            if not allowed:
                results["halted"] = reason
                audit(conn, "improver", "run_halted", reason)
                break
            out = improve_one(settings, conn, project)
            if not out:
                continue
            results["details"].append(out)
            if "proposed" in out:
                results["proposed"] += 1
                consume(conn, "improver", tasks=1)
            else:
                results["skipped"] += 1
                # a silent skip is invisible in a background thread — record why
                audit(conn, "improver", "change_skipped",
                      f"{project}: {out.get('reason', '?')[:160]}")
        audit(conn, "improver", "run_finished", json.dumps(
            {k: results[k] for k in ("proposed", "skipped")}))
        return results
    finally:
        conn.close()
        _RUN_LOCK.release()


def decide(settings: Settings, conn, change_id: int, action: str) -> dict:
    row = conn.execute("SELECT * FROM improve_changes WHERE id=?", (change_id,)).fetchone()
    if not row or row["status"] != "proposed":
        raise ValueError(f"change {change_id} is not pending")
    repo = safe_repo(settings, row["project"])
    if repo is None:
        raise ValueError(f"unknown project {row['project']!r}")
    if action == "merge":
        dirty = subprocess.run(["git", "-C", str(repo), "status", "--porcelain"],
                               capture_output=True, text=True, timeout=30).stdout.strip()
        if dirty:
            raise ValueError("working tree has uncommitted changes — merge later")
        p = subprocess.run(["git", "-C", str(repo), "-c", "user.name=noirdeck-improve",
                            "-c", "user.email=improve@noirdeck.local", "merge", "--no-ff",
                            "-m", f"Merge {row['branch']} (noirdeck improve)", row["branch"]],
                           capture_output=True, text=True, timeout=60)
        if p.returncode != 0:
            raise ValueError(f"merge failed: {(p.stderr or '')[-200:]}")
        subprocess.run(["git", "-C", str(repo), "branch", "-dq", row["branch"]],
                       capture_output=True, timeout=30)
        status = "merged"
    elif action == "discard":
        subprocess.run(["git", "-C", str(repo), "branch", "-Dq", row["branch"]],
                       capture_output=True, timeout=30)
        status = "discarded"
    else:
        raise ValueError(f"unknown action {action!r}")
    conn.execute("UPDATE improve_changes SET status=?, decided_at=? WHERE id=?",
                 (status, utcnow(), change_id))
    conn.commit()
    audit(conn, "operator", f"improve_{status}", f"id={change_id} {row['project']}")
    return {"id": change_id, "status": status}


if __name__ == "__main__":
    s = Settings.load()
    from .db import init_db
    init_db(s.db_path)
    print(json.dumps(run_improver(s)))
