"""Memory/skill hygiene — dedupe and tidy candidates, optimised for Claude use.
Zero-egress: pure heuristics over ~/.claude, no LLM calls. Findings are
read-only; the ONLY write path is a consolidation proposal through the
existing propose→approve spine (the operator approves, nothing is auto-rewritten,
originals are never deleted by this module)."""
from __future__ import annotations

import hashlib
import re
import sqlite3
from difflib import SequenceMatcher
from pathlib import Path

from .config import primary_namespace
from .db import audit, utcnow

# near-dup pairwise comparison is O(n^2) per namespace — skip monsters
MAX_NS_FILES = 500
NEAR_DUP_RATIO = 0.85
BIG_FILE_BYTES = 8_000  # token-diet: memory files this size crowd the recall window
TINY_FILE_BYTES = 80
_LINK_RE = re.compile(r"\[\[([a-z0-9_\-]+)\]\]", re.I)


def _norm(text: str) -> str:
    """Normalise for similarity: strip frontmatter, whitespace runs, case."""
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            text = text[end + 4:]
    return re.sub(r"\s+", " ", text).strip().lower()


def _read(f: Path) -> str | None:
    try:
        return f.read_text(errors="replace")
    except OSError:
        return None


def scan_namespace(mem_dir: Path) -> dict:
    """All hygiene findings for one memory namespace directory."""
    files = sorted(p for p in mem_dir.glob("*.md") if p.name != "MEMORY.md" and p.is_file())
    skipped = None
    if len(files) > MAX_NS_FILES:
        skipped = f"{len(files)} files > {MAX_NS_FILES} cap — near-dup pass skipped"
        files = files[:MAX_NS_FILES]

    texts: dict[str, str] = {}
    by_hash: dict[str, list[str]] = {}
    tiny, big, names = [], [], set()
    for f in files:
        raw = _read(f)
        if raw is None:
            continue
        names.add(f.stem)
        texts[f.name] = raw
        digest = hashlib.sha256(_norm(raw).encode()).hexdigest()
        by_hash.setdefault(digest, []).append(f.name)
        size = f.stat().st_size
        if size < TINY_FILE_BYTES:
            tiny.append({"file": f.name, "size": size})
        elif size > BIG_FILE_BYTES:
            big.append({"file": f.name, "size": size})

    exact_dupes = [sorted(v) for v in by_hash.values() if len(v) > 1]

    near_dupes = []
    if skipped is None:
        # SequenceMatcher over full texts is O(n^2 * len^2) — unusable on a real
        # namespace. Prefilter with token-set Jaccard (fast set ops), confirm with
        # ratio() on capped text so worst case stays bounded.
        CMP_CAP = 2000
        items = []
        for n, t in texts.items():
            norm = _norm(t)
            if len(norm) > TINY_FILE_BYTES:
                items.append((n, norm[:CMP_CAP], frozenset(re.findall(r"[a-z0-9]{3,}", norm))))
        flagged: set[frozenset] = {frozenset(g) for g in exact_dupes}
        for i in range(len(items)):
            na, ta, wa = items[i]
            for j in range(i + 1, len(items)):
                nb, tb, wb = items[j]
                if frozenset((na, nb)) in flagged:
                    continue
                if not wa or not wb:
                    continue
                inter = len(wa & wb)
                if inter / (len(wa) + len(wb) - inter) < 0.7:
                    continue  # token overlap too low to be a near-dupe
                ratio = SequenceMatcher(None, ta, tb).ratio()
                if ratio >= NEAR_DUP_RATIO:
                    near_dupes.append({"a": na, "b": nb, "ratio": round(ratio, 3)})

    dangling = []
    for fname, text in texts.items():
        missing = sorted({m for m in _LINK_RE.findall(text) if m not in names})
        if missing:
            dangling.append({"file": fname, "links": missing})

    # MEMORY.md index drift — entries pointing nowhere / files never indexed
    index_missing_files, unindexed = [], []
    index = mem_dir / "MEMORY.md"
    if index.is_file():
        idx_text = _read(index) or ""
        referenced = set(re.findall(r"\(([\w\-.]+\.md)\)", idx_text))
        mentioned = set(re.findall(r"[\w\-]+", idx_text))
        index_missing_files = sorted(r for r in referenced if not (mem_dir / r).exists())
        unindexed = sorted(
            f.name for f in files
            if f.name not in referenced and f.stem not in mentioned
            and f.stem.removeprefix("feedback_") not in mentioned
            and ("fb_" + f.stem.removeprefix("feedback_")) not in mentioned
        )

    return {
        "namespace": mem_dir.parent.name,
        "files": len(files),
        "skipped": skipped,
        "exact_dupes": exact_dupes,
        "near_dupes": sorted(near_dupes, key=lambda d: -d["ratio"])[:40],
        "tiny": tiny,
        "oversized": sorted(big, key=lambda d: -d["size"])[:20],
        "dangling_links": dangling[:40],
        "index_missing_files": index_missing_files,
        "unindexed": unindexed[:40],
    }


def scan_skills(claude_dir: Path) -> list[dict]:
    """Skills whose normalised bodies exactly duplicate each other."""
    skills_dir = claude_dir / "skills"
    if not skills_dir.is_dir():
        return []
    by_hash: dict[str, list[str]] = {}
    for d in sorted(skills_dir.iterdir()):
        f = d / "SKILL.md"
        if not f.is_file():
            continue
        raw = _read(f)
        if raw is None:
            continue
        digest = hashlib.sha256(_norm(raw).encode()).hexdigest()
        by_hash.setdefault(digest, []).append(d.name)
    return [sorted(v) for v in by_hash.values() if len(v) > 1]


_cache: dict[tuple[str, str], tuple[float, dict]] = {}
_TTL = 120  # near-dup pass is O(n^2) per namespace — never per SSE bump


def report(claude_dir: Path, namespace: str | None = None) -> dict:
    """Hygiene report. Default scope: the primary namespace (the only one
    proposals may write to); pass namespace to scan any other single one."""
    import time
    ns = namespace or primary_namespace()
    # ns is caller input used as a path component — single segment, direct
    # child of projects/ only (same escape class as the files API fix)
    if "/" in ns or "\\" in ns or ns in ("", ".", ".."):
        raise ValueError(f"bad namespace {ns!r}")
    # deliberately NOT resolved: worktree namespaces symlink their memory dir
    # to the canonical project's (§25 cwtlink) and must stay scannable
    projects = claude_dir / "projects"
    mem = projects / ns / "memory"
    key = (str(claude_dir), ns)
    hit = _cache.get(key)
    if hit and time.monotonic() - hit[0] < _TTL:
        return hit[1]
    out = {
        "generated_at": utcnow(),
        "namespace": ns,
        "primary_namespace": primary_namespace(),
        "namespace_report": scan_namespace(mem) if mem.is_dir() else None,
        "skill_dupes": scan_skills(claude_dir),
        "available_namespaces": sorted(
            p.parent.name for p in projects.glob("*/memory") if p.is_dir()
        ) if projects.is_dir() else [],
    }
    findings = 0
    nr = out["namespace_report"]
    if nr:
        findings = (len(nr["exact_dupes"]) + len(nr["near_dupes"]) + len(nr["tiny"])
                    + len(nr["dangling_links"]) + len(nr["index_missing_files"]))
    out["finding_count"] = findings + len(out["skill_dupes"])
    _cache[key] = (time.monotonic(), out)
    return out


def propose_merge(conn: sqlite3.Connection, claude_dir: Path, namespace: str | None,
                  files: list[str]) -> dict:
    """Draft ONE consolidation proposal from 2+ memory files. The proposal
    targets a NEW merged file; originals are untouched — the proposal body
    tells the operator which files it supersedes so deletion stays a human act."""
    if len(files) < 2:
        raise ValueError("need at least two files to merge")
    namespace = namespace or primary_namespace()
    if namespace != primary_namespace():
        raise ValueError("proposals may only target the primary namespace")
    mem = claude_dir / "projects" / namespace / "memory"
    parts, slugs = [], []
    for fname in files:
        if "/" in fname or "\\" in fname or not fname.endswith(".md"):
            raise ValueError(f"bad filename {fname}")
        f = mem / fname
        raw = _read(f) if f.is_file() else None
        if raw is None:
            raise ValueError(f"unreadable {fname}")
        slugs.append(f.stem)
        parts.append(f"<!-- from {fname} -->\n{raw.strip()}\n")

    stem = min(slugs, key=len)
    merged_name = f"{stem}_merged.md"
    body = (
        f"---\nname: {stem}_merged\n"
        f"description: \"Consolidated from {len(files)} overlapping memories: "
        f"{', '.join(slugs)}. TIDY the duplicated sections before/after approving.\"\n"
        "metadata:\n  type: reference\n---\n\n"
        "> DRAFT MERGE — sections below are concatenated sources. Deduplicate by hand\n"
        f"> or in a session, then delete the superseded originals: {', '.join(files)}\n\n"
        + "\n---\n\n".join(parts)
    )
    cur = conn.execute(
        "INSERT INTO proposals (kind,title,body,target_path,status,created_at) VALUES (?,?,?,?,'proposed',?)",
        ("memory_merge", f"Merge {len(files)} overlapping memories → {merged_name}",
         body, f"projects/{namespace}/memory/{merged_name}", utcnow()),
    )
    conn.commit()
    audit(conn, "operator", "hygiene_merge_proposed",
          f"id={cur.lastrowid} files={','.join(files)[:120]}")
    return {"proposal_id": cur.lastrowid, "target": merged_name}
