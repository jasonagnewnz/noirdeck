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

import fcntl
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
MAX_FILE_LINES = 400  # only small files — small model, small blast radius
GEN_TIMEOUT_S = int(os.environ.get("NOIRDECK_GEN_TIMEOUT_S", "1800"))
# CPU inference is slow (muse-glimmer:30b measured ~1-2 tok/s + ~100s cold load);
# the timeout covers load + prompt eval + generation in one urlopen.
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


def available_models() -> list[str]:
    """Tags actually pulled into the local Ollama — the only models the
    improver may ever use (zero-egress by design, never a cloud model)."""
    try:
        with urllib.request.urlopen(f"{OLLAMA}/api/tags", timeout=5) as r:
            tags = json.load(r)
        return sorted(m["name"] for m in tags.get("models", []) if m.get("name"))
    except OSError:
        return []


def _model_in(model: str, avail: list[str]) -> bool:
    # exact tag match only — a loose prefix match let "muse-glimmer:30b" pass
    # when only muse-glimmer:7b was pulled, failing later with a vague reason.
    # An untagged name resolves to :latest, mirroring ollama itself.
    return model in avail or (":" not in model and f"{model}:latest" in avail)


def model_available(model: str | None = None) -> bool:
    return _model_in(model or local_model(), available_models())


def _generate(prompt: str, model: str) -> tuple[str | None, str | None]:
    """(text, None) on success, (None, reason) on failure — one reason string
    per distinct failure so the audit trail diagnoses itself (a single vague
    reason previously covered timeout, missing model, AND cap rejections).
    think:false — reasoning models (muse-glimmer) otherwise burn the token
    budget in the thinking channel at CPU speeds and time out into skips;
    non-thinking models (qwen2.5-coder) ignore the field. Verified on 0.32.9."""
    body = json.dumps(
        {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "think": False,
            "keep_alive": "30m",
            "options": {"temperature": 0.2, "num_predict": 4096},
        }
    ).encode()
    req = urllib.request.Request(f"{OLLAMA}/api/generate", data=body, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=GEN_TIMEOUT_S) as r:
            resp = json.load(r).get("response")
        if not resp:
            return None, f"{model} returned empty output"
        return resp, None
    except TimeoutError:
        return None, f"{model} timed out after {GEN_TIMEOUT_S}s"
    except urllib.error.HTTPError as e:
        return None, f"ollama rejected the request: HTTP {e.code}"
    except OSError as e:
        return None, f"ollama unreachable: {type(e).__name__}"


# ── estate targets: manually-armed assets under ~/.claude ───────────────────
# Beyond repos: skills and memory notes become improvement targets, but ONLY
# while individually armed (fail-closed expiry). Output never touches disk
# here — it lands in the propose→approve spine, whose allowlist is the real
# write boundary into ~/.claude.

ASSET_KINDS = ("skill", "memory")
MAX_ASSET_BYTES = 60_000

ASSET_PROMPTS = {
    "skill": (
        "Refine this Claude Code skill file. Keep the YAML frontmatter EXACTLY as "
        "it is, byte for byte. Preserve every fact, command, path and warning. "
        "Improve clarity and structure, remove repetition, fix grammar. Do NOT "
        "invent commands, tools, or facts that are not already present."
    ),
    "memory": (
        "Tidy this memory note. Keep the YAML frontmatter EXACTLY as it is, byte "
        "for byte. Preserve every fact, every warning marker, and every [[link]]. "
        "Tighten wording and structure; the result must not be longer than the "
        "original. Do NOT invent or drop facts."
    ),
}

_LINK_RE = re.compile(r"\[\[[^\]]+\]\]")


def safe_asset(claude_dir: Path, target_path: str) -> Path | None:
    """Resolve an estate target through the PROPOSALS allowlist — the same
    boundary approval enforces, so nothing addable here is unwritable there."""
    from .proposals import ProposalError, _resolve_target

    try:
        p = _resolve_target(claude_dir, target_path)
    except ProposalError:
        return None
    return p if p.is_file() and p.suffix == ".md" else None


def _frontmatter_block(text: str) -> str | None:
    if not text.startswith("---\n"):
        return None
    end = text.find("\n---", 4)
    return text[: end + 4] if end >= 0 else None


def _asset_ok(kind: str, original: str, new: str) -> str | None:
    """None when structurally safe, else the reason. Structure guards only —
    factual fidelity is the human's call in the proposal diff. Growth is
    kind-aware: refining a draft skill legitimately adds structure; a memory
    tidy must not add bulk. +200 bytes of headroom keeps tiny files workable."""
    fm = _frontmatter_block(original)
    if fm and not new.startswith(fm):
        return "frontmatter was altered — rejected"
    growth = 1.5 if kind == "skill" else 1.1
    if len(new) > len(original) * growth + 200:
        return f"result grew beyond the {kind} cap — too much added bulk"
    if len(new) < len(original) * 0.5:
        return "result lost >50% of the file — too aggressive"
    missing = set(_LINK_RE.findall(original)) - set(_LINK_RE.findall(new))
    if missing:
        return "dropped [[links]]: " + ", ".join(sorted(missing)[:4])
    return None


def improve_asset_one(settings: Settings, conn, target: dict, model: str | None = None) -> dict | None:
    model = model or local_model()
    label = {"kind": target["kind"], "file": target["target_path"]}
    path = safe_asset(settings.claude_dir, target["target_path"])
    if path is None:
        return {"skipped": label, "reason": "target missing or outside the write allowlist"}
    if conn.execute(
        "SELECT 1 FROM proposals WHERE target_path=? AND status='proposed'", (target["target_path"],)
    ).fetchone():
        return {"skipped": label, "reason": "a proposal for this target is already pending"}
    original = path.read_text(errors="replace")
    if len(original) > MAX_ASSET_BYTES:
        return {"skipped": label, "reason": f"file too large ({len(original)} > {MAX_ASSET_BYTES} bytes)"}
    prompt = (
        f"{ASSET_PROMPTS[target['kind']]}\n\n"
        f"Return the COMPLETE new file content between the markers, nothing else.\n"
        f"<<<FILE>>>\n{original}\n<<<END>>>\n\nNew file content:\n<<<FILE>>>\n"
    )
    resp, why_not = _generate(prompt, model)
    if not resp:
        return {"skipped": label, "reason": why_not}
    m = re.search(r"(.*?)<<<END>>>", resp, re.S)
    content = (m.group(1) if m else resp).strip("\n") + "\n"
    content = content.replace("<<<FILE>>>", "").lstrip("\n")
    if not content.strip():
        return {"skipped": label, "reason": "model output was empty after unwrapping the markers"}
    if content == original:
        return {"skipped": label, "reason": "model proposed no changes"}
    bad = _asset_ok(target["kind"], original, content)
    if bad:
        return {"skipped": label, "reason": bad}
    import difflib

    diff = "".join(
        difflib.unified_diff(
            original.splitlines(keepends=True),
            content.splitlines(keepends=True),
            fromfile=target["target_path"],
            tofile=target["target_path"] + " (proposed)",
        )
    )
    cur = conn.execute(
        "INSERT INTO proposals (kind, title, body, target_path, diff, created_at) VALUES (?,?,?,?,?,?)",
        (
            f"improve_{target['kind']}",
            f"improve({target['kind']}): {target['target_path']}",
            content,
            target["target_path"],
            diff[:60_000],
            utcnow(),
        ),
    )
    conn.execute("UPDATE improve_targets SET last_proposed_at=? WHERE id=?", (utcnow(), target["id"]))
    conn.commit()
    audit(
        conn,
        "improver",
        "asset_proposed",
        f"proposal={cur.lastrowid} {target['kind']} {target['target_path']} model={model}",
    )
    return {"proposed": {"proposal_id": cur.lastrowid, **label}}


# ── decision learning: the operator's merges/discards steer future work ─────

MUTE_DISCARDS = 3  # this many discards with zero merges mutes a kind per repo


def decision_stats(conn) -> dict:
    """Tallies of the operator's own merge/discard decisions — the improver's
    only learning signal. Deterministic and fully inspectable: no model in
    the loop, and merging a previously-discarded kind un-mutes it naturally."""
    rows = conn.execute(
        "SELECT project, kind, model, status, COUNT(*) AS n FROM improve_changes "
        "WHERE status IN ('merged','discarded') "
        "GROUP BY project, kind, model, status"
    ).fetchall()
    kinds, models, repo_kinds = {}, {}, {}
    for r in rows:
        for key, bucket in ((r["kind"], kinds), (r["model"], models), (f"{r['project']}/{r['kind']}", repo_kinds)):
            if not key:
                continue
            b = bucket.setdefault(key, {"merged": 0, "discarded": 0})
            b[r["status"]] += r["n"]
    muted = sorted(k for k, b in repo_kinds.items() if b["discarded"] >= MUTE_DISCARDS and b["merged"] == 0)
    return {"kinds": kinds, "models": models, "repo_kinds": repo_kinds, "muted": muted}


def _apply_decisions(stats: dict, project: str, cands: list[dict]) -> tuple[list[dict], list[str]]:
    """Re-rank candidates by decision history and drop muted kinds.
    weight = (merged+1)/(discarded+1) — repo-specific counts at full strength,
    the global kind history at quarter strength as a prior."""
    out, muted = [], []
    for c in cands:
        key = f"{project}/{c['kind']}"
        if key in stats["muted"]:
            muted.append(c["kind"])
            continue
        rk = stats["repo_kinds"].get(key, {"merged": 0, "discarded": 0})
        gk = stats["kinds"].get(c["kind"], {"merged": 0, "discarded": 0})
        weight = (rk["merged"] + 0.25 * gk["merged"] + 1) / (rk["discarded"] + 0.25 * gk["discarded"] + 1)
        out.append({**c, "score": c["score"] * weight, "weight": round(weight, 2)})
    out.sort(key=lambda c: -c["score"])
    return out, sorted(set(muted))


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
            out.append(
                {
                    "kind": "docstrings",
                    "file": rel,
                    "score": defs - docstrings,
                    "why": f"{defs} functions, few docstrings",
                }
            )
        stale = len(re.findall(r"^\s*#\s*(TODO|FIXME|XXX|HACK)\b", text, re.M))
        commented_code = len(re.findall(r"^\s*#\s*(?:def |class |import |print\()", text, re.M))
        if stale + commented_code >= 3:
            out.append(
                {
                    "kind": "comment_tidy",
                    "file": rel,
                    "score": stale + commented_code,
                    "why": f"{stale} stale markers, {commented_code} commented-out code lines",
                }
            )
    readme = repo / "README.md"
    if readme.is_file():
        text = readme.read_text(errors="replace").lower()
        missing = [s for s in ("how to run", "install", "test") if s not in text]
        if len(missing) >= 2 and text.count("\n") < 120:
            out.append(
                {
                    "kind": "readme_gap",
                    "file": "README.md",
                    "score": len(missing),
                    "why": f"README missing: {', '.join(missing)}",
                }
            )
    out.sort(key=lambda c: -c["score"])
    return out


_PROMPTS = {
    "docstrings": (
        "Add concise, accurate docstrings to functions/classes that lack them. "
        "Do NOT change any executable code, names, signatures, imports, or logic. "
        "Do NOT add type hints. Keep existing docstrings untouched."
    ),
    "comment_tidy": (
        "Tidy the comments ONLY: delete commented-out dead code, resolve or reword stale "
        "TODO/FIXME markers into clear statements, fix comment typos. Do NOT change any "
        "executable code, names, signatures, imports, or logic."
    ),
    "readme_gap": (
        "Improve this README: keep everything true and in the same voice, and add the "
        "missing practical sections (how to install, how to run, how to test) inferred "
        "ONLY from information already present in the file. Do not invent commands."
    ),
}


def _propose_content(kind: str, path: Path, model: str) -> tuple[str | None, str | None]:
    """(content, None) when the model produced a safe change, else (None, reason)."""
    original = path.read_text(errors="replace")
    prompt = (
        f"You improve code quality with minimal, surgical edits.\n{_PROMPTS[kind]}\n\n"
        f"Return the COMPLETE new file content between the markers, nothing else.\n"
        f"<<<FILE>>>\n{original}\n<<<END>>>\n\n"
        f"New file content:\n<<<FILE>>>\n"
    )
    resp, why_not = _generate(prompt, model)
    if not resp:
        return None, why_not
    m = re.search(r"(.*?)<<<END>>>", resp, re.S)
    content = (m.group(1) if m else resp).strip("\n") + "\n"
    content = content.replace("<<<FILE>>>", "").lstrip("\n")
    if not content.strip():
        return None, "model output was empty after unwrapping the markers"
    orig_lines, new_lines = original.splitlines(), content.splitlines()
    if len(new_lines) < len(orig_lines) * 0.7:
        return None, "rewrite deleted >30% of the file — not subtle, rejected"
    changed = sum(1 for a, b in zip(orig_lines, new_lines) if a != b) + abs(len(new_lines) - len(orig_lines))
    if changed == 0:
        return None, "model proposed no changes"
    if changed > MAX_CHANGED_LINES:
        return None, f"diff too large ({changed} > {MAX_CHANGED_LINES} changed lines)"
    return content, None


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
            if (
                isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
                and node.body
                and isinstance(node.body[0], ast.Expr)
                and isinstance(node.body[0].value, ast.Constant)
                and isinstance(node.body[0].value.value, str)
            ):
                node.body = node.body[1:] or [ast.Pass()]
    return ast.dump(a) == ast.dump(b)


def _run_tests(worktree: Path) -> str:
    if (worktree / "pytest.ini").exists() or (worktree / "backend" / "tests").is_dir() or (worktree / "tests").is_dir():
        try:
            p = subprocess.run(
                ["python3", "-m", "pytest", "-q", "-x"], cwd=worktree, capture_output=True, text=True, timeout=600
            )
            tail = (p.stdout or "").strip().splitlines()[-1:] or ["no output"]
            if p.returncode == 5:  # a tests/ dir with no collectable python tests
                return "no tests collected"
            return ("pass: " if p.returncode == 0 else "FAIL: ") + tail[0][:200]
        except (OSError, subprocess.TimeoutExpired):
            return "FAIL: pytest did not complete"
    return "no tests found"


def improve_one(settings: Settings, conn, project: str, model: str | None = None) -> dict | None:
    model = model or local_model()
    repo = safe_repo(settings, project)
    if repo is None:
        # an ENABLED repo that fails the safety check is an anomaly, not a
        # quiet no-op — surface it instead of returning silently
        return {"skipped": {"kind": "-", "file": "-"}, "reason": "repo missing or failed the safety check"}
    cands = candidates(repo)
    if not cands:
        return None
    cands, muted_kinds = _apply_decisions(decision_stats(conn), project, cands)
    if not cands:
        return {
            "skipped": {"kind": ", ".join(muted_kinds), "file": "-"},
            "reason": "all candidate kinds muted by your discard history (merge one of that kind anywhere to un-mute)",
        }
    cand = cands[0]
    branch = f"improve/{utcnow()[:10]}-{cand['kind']}-{cand['file'].replace('/', '-')[:40]}"
    with tempfile.TemporaryDirectory(prefix="noirdeck-improve-") as td:
        wt = Path(td) / "wt"
        try:
            wt_add = subprocess.run(
                ["git", "-C", str(repo), "worktree", "add", "-b", branch, str(wt), "HEAD"],
                capture_output=True,
                text=True,
                timeout=60,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return {"skipped": cand, "reason": f"worktree add failed: {type(exc).__name__}"}
        if wt_add.returncode != 0:
            # e.g. the proposal branch already exists from a concurrent or
            # earlier run — an audited skip, never a silent None
            return {"skipped": cand, "reason": f"worktree add failed: {(wt_add.stderr or '').strip()[-120:]}"}
        try:
            target = wt / cand["file"]
            original = target.read_text(errors="replace")
            content, why_not = _propose_content(cand["kind"], target, model)
            if content is None:
                return {"skipped": cand, "reason": why_not or "model produced no safe content"}
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
                [
                    "git",
                    "-C",
                    str(wt),
                    "-c",
                    "user.name=noirdeck-improve",
                    "-c",
                    "user.email=improve@noirdeck.local",
                    "commit",
                    "-aqm",
                    f"improve({cand['kind']}): {cand['file']} [noirdeck local model]",
                ],
                capture_output=True,
                text=True,
                timeout=60,
            )
            if committed.returncode != 0:
                return {"skipped": cand, "reason": f"commit failed: {(committed.stderr or '')[-120:]}"}
            diff = subprocess.run(
                ["git", "-C", str(wt), "show", "--stat", "--patch", "HEAD", "--", cand["file"]],
                capture_output=True,
                text=True,
                timeout=60,
            ).stdout
            cur = conn.execute(
                "INSERT INTO improve_changes (project,branch,kind,target_file,summary,"
                "diff,tests,model,created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                (project, branch, cand["kind"], cand["file"], cand["why"], diff[:60000], tests, model, utcnow()),
            )
            conn.commit()
            audit(conn, "improver", "change_proposed", f"id={cur.lastrowid} {project} {cand['kind']} {cand['file']}")
            return {"proposed": {"id": cur.lastrowid, "project": project, **cand, "branch": branch, "tests": tests}}
        finally:
            subprocess.run(
                ["git", "-C", str(repo), "worktree", "remove", "--force", str(wt)], capture_output=True, timeout=60
            )
            # branch survives the worktree; drop it only if nothing was recorded
            kept = conn.execute("SELECT 1 FROM improve_changes WHERE branch=?", (branch,)).fetchone()
            if not kept:
                subprocess.run(["git", "-C", str(repo), "branch", "-Dq", branch], capture_output=True, timeout=30)


def run_improver(settings: Settings) -> dict:
    if not armed():
        return {"skipped": True, "reason": "NOIRDECK_IMPROVER_ARMED != true (fail-closed)"}
    avail = available_models()
    if not avail:
        return {"skipped": True, "reason": "no local models available (Ollama down?)"}
    from .arming import check, consume

    if not _RUN_LOCK.acquire(blocking=False):
        return {"skipped": True, "reason": "already running"}
    # the thread lock only covers THIS process — "Run now" lives in the API
    # service while the hourly timer is its own process, and both mutate the
    # same repos. flock is advisory but both writers are ours.
    lock_file = open(settings.db_path.parent / "improve.lock", "w")
    try:
        fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        lock_file.close()
        _RUN_LOCK.release()
        return {"skipped": True, "reason": "already running in another process"}
    conn = connect(settings.db_path)
    results = {"proposed": 0, "skipped": 0, "details": []}
    try:
        repos = [
            (r["project"], r["model"])
            for r in conn.execute(
                "SELECT project, model FROM improve_repos WHERE enabled=1 ORDER BY project"
            ).fetchall()
        ]
        for project, repo_model in repos:
            allowed, reason = check(conn, "improver")
            if not allowed:
                results["halted"] = reason
                audit(conn, "improver", "run_halted", reason)
                break
            model = repo_model or local_model()
            if not _model_in(model, avail):
                results["skipped"] += 1
                audit(conn, "improver", "change_skipped", f"{project}: model {model} not pulled locally")
                continue
            out = improve_one(settings, conn, project, model)
            if not out:
                continue
            results["details"].append(out)
            if "proposed" in out:
                results["proposed"] += 1
                consume(conn, "improver", tasks=1)
            else:
                results["skipped"] += 1
                # a silent skip is invisible in a background thread — record why
                audit(conn, "improver", "change_skipped", f"{project}: {out.get('reason', '?')[:160]}")
        # estate targets — only while manually armed and unexpired (fail-closed)
        if "halted" not in results:
            targets = [
                dict(r)
                for r in conn.execute(
                    "SELECT * FROM improve_targets WHERE armed_until IS NOT NULL AND armed_until > ? ORDER BY id",
                    (utcnow(),),
                ).fetchall()
            ]
            for t in targets:
                allowed, reason = check(conn, "improver")
                if not allowed:
                    results["halted"] = reason
                    audit(conn, "improver", "run_halted", reason)
                    break
                model = t["model"] or local_model()
                if not _model_in(model, avail):
                    results["skipped"] += 1
                    audit(conn, "improver", "change_skipped", f"{t['target_path']}: model {model} not pulled locally")
                    continue
                out = improve_asset_one(settings, conn, t, model)
                if not out:
                    continue
                results["details"].append(out)
                if "proposed" in out:
                    results["proposed"] += 1
                    consume(conn, "improver", tasks=1)
                else:
                    results["skipped"] += 1
                    audit(conn, "improver", "change_skipped", f"{t['target_path']}: {out.get('reason', '?')[:160]}")
        audit(conn, "improver", "run_finished", json.dumps({k: results[k] for k in ("proposed", "skipped")}))
        return results
    finally:
        conn.close()
        lock_file.close()  # closing releases the flock
        _RUN_LOCK.release()


def decide(settings: Settings, conn, change_id: int, action: str) -> dict:
    row = conn.execute("SELECT * FROM improve_changes WHERE id=?", (change_id,)).fetchone()
    if not row or row["status"] != "proposed":
        raise ValueError(f"change {change_id} is not pending")
    repo = safe_repo(settings, row["project"])
    if repo is None:
        raise ValueError(f"unknown project {row['project']!r}")
    into = None
    if action == "merge":
        dirty = subprocess.run(
            ["git", "-C", str(repo), "status", "--porcelain"], capture_output=True, text=True, timeout=30
        ).stdout.strip()
        if dirty:
            raise ValueError("working tree has uncommitted changes — merge later")
        # the merge lands on whatever branch the repo has checked out — say so
        # honestly everywhere instead of claiming "main"
        into = (
            subprocess.run(
                ["git", "-C", str(repo), "rev-parse", "--abbrev-ref", "HEAD"],
                capture_output=True,
                text=True,
                timeout=30,
            ).stdout.strip()
            or "?"
        )
        p = subprocess.run(
            [
                "git",
                "-C",
                str(repo),
                "-c",
                "user.name=noirdeck-improve",
                "-c",
                "user.email=improve@noirdeck.local",
                "merge",
                "--no-ff",
                "-m",
                f"Merge {row['branch']} into {into} (noirdeck improve)",
                row["branch"],
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if p.returncode != 0:
            raise ValueError(f"merge failed: {(p.stderr or '')[-200:]}")
        subprocess.run(["git", "-C", str(repo), "branch", "-dq", row["branch"]], capture_output=True, timeout=30)
        status = "merged"
    elif action == "discard":
        subprocess.run(["git", "-C", str(repo), "branch", "-Dq", row["branch"]], capture_output=True, timeout=30)
        status = "discarded"
    else:
        raise ValueError(f"unknown action {action!r}")
    conn.execute("UPDATE improve_changes SET status=?, decided_at=? WHERE id=?", (status, utcnow(), change_id))
    conn.commit()
    audit(conn, "operator", f"improve_{status}", f"id={change_id} {row['project']}" + (f" into={into}" if into else ""))
    return {"id": change_id, "status": status, "into": into}


if __name__ == "__main__":
    s = Settings.load()
    from .db import init_db

    init_db(s.db_path)
    print(json.dumps(run_improver(s)))
