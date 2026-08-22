"""Gated LLM mining pass: headless `claude -p` over REDACTED transcript excerpts.

Fail-closed: refuses unless NOIRDECK_MINING_ARMED=true. Dedup via mined_files
(path+mtime) so no transcript version is ever mined twice: dry-run cost runaways
are an estate-documented failure mode. Batches are capped per run.
"""

from __future__ import annotations

import json
import sqlite3
import subprocess
from pathlib import Path

from ..config import Settings
from ..db import audit, utcnow
from ..miner.evidence import admissible
from ..miner.redact import redact
from ..readers.sessions import _iter_json, _text_of  # bounded readers

_BATCH_CHARS = 20000
_PROMPT = """You are analysing REDACTED excerpts of a developer's own Claude Code session
transcripts (their machine, their data). Extract, as strict JSON only:
{"skill_candidates":[{"slug":"...","evidence":"...","draft_description":"...","occurrences":N}],
 "methodology_notes":["..."],
 "memory_notes":["..."]}

skill_candidates = a PROCEDURE this developer has repeated, which could be packaged
as a reusable skill. The bar is high and you must show your work:
- slug: hyphenated, 2-5 words, naming what the procedure DOES (e.g.
  "rotate-wazuh-agent-key"). Never a filesystem path, filename, username,
  credential field, id, date, or a fragment of the prompt's wording.
- evidence: quote the actual repeated request(s) and say what the steps were.
  At least 80 characters. If you cannot quote it, do not claim it.
- draft_description: a trigger phrased "Use when ..." so the skill can fire
  correctly. At least 40 characters.
- occurrences: how many distinct times you SAW it in these excerpts.
Return an EMPTY list unless a genuine repeated procedure is present. A prompt that
merely recurs is not a procedure; a one-off request is not a procedure; a pasted
path or a "please continue" is not a procedure. An empty list is the correct and
expected answer for most batches.

methodology_notes = observations about HOW this developer likes work done (style, gates, order).
memory_notes = durable facts/landmines worth a memory file. No prose outside the JSON.

EXCERPTS:
"""


def _existing_slugs(claude_dir: Path) -> set[str]:
    d = claude_dir / "skills"
    if not d.is_dir():
        return set()
    return {p.name.lower() for p in d.iterdir() if p.is_dir()}


def _draft_skill_body(cand: dict, source: str) -> str:
    """A draft that carries its own evidence, so the reviewer can judge it without
    going back to the transcript: and so an unjustified one is obvious on sight."""
    return f"""---
name: {cand["slug"]}
description: {cand["draft_description"]}
---

# /{cand["slug"]}: DRAFT (noirdeck)

Proposed from mined session evidence. Nothing here is authoritative until you have
checked it: noirdeck saw a pattern, it did not verify the procedure works.

## Evidence this procedure is real
{cand["evidence"]}

Source transcript: `{source}`{f" · seen {cand['occurrences']}x in this batch" if cand.get("occurrences") else ""}

## Before this is a real skill
- Confirm the steps above are what actually worked, and correct them.
- Add the landmines hit along the way.
- Tighten the description into a precise trigger.
"""


def _propose_skill(conn: sqlite3.Connection, cand: dict, source: str) -> bool:
    """Stage an admissible candidate. Returns False if one is already pending."""
    target = f"skills/{cand['slug']}/SKILL.md"
    if conn.execute("SELECT 1 FROM proposals WHERE target_path=? AND status='proposed'", (target,)).fetchone():
        return False
    conn.execute(
        "INSERT INTO proposals (kind,title,body,target_path,status,created_at) VALUES (?,?,?,?,'proposed',?)",
        (
            "skill",
            f"Draft skill: /{cand['slug']}",
            _draft_skill_body(cand, source),
            target,
            utcnow(),
        ),
    )
    return True


def _user_texts(path: Path, cap: int = 40) -> list[str]:
    texts: list[str] = []
    try:
        with open(path, errors="replace") as fh:
            for rec in _iter_json(fh.readlines()[:2000]):
                if rec.get("type") == "user":
                    t = _text_of(rec).strip()
                    if t and not t.startswith("<"):
                        texts.append(t[:1500])
                        if len(texts) >= cap:
                            break
    except OSError:
        pass
    return texts


def pick_unmined(conn: sqlite3.Connection, claude_dir: Path, max_files: int) -> list[Path]:
    projects = claude_dir / "projects"
    if not projects.is_dir():
        return []
    all_files = sorted(
        (p for ns in projects.iterdir() if ns.is_dir() for p in ns.glob("*.jsonl")),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    picked: list[Path] = []
    for p in all_files:
        row = conn.execute("SELECT mtime FROM mined_files WHERE path=?", (str(p),)).fetchone()
        if row and row["mtime"] == p.stat().st_mtime:
            continue
        picked.append(p)
        if len(picked) >= max_files:
            break
    return picked


def run_llm_mining(conn: sqlite3.Connection, settings: Settings) -> dict:
    if not settings.mining_armed:
        return {"skipped": True, "reason": "NOIRDECK_MINING_ARMED != true (fail-closed)"}
    from ..arming import check, consume

    files = pick_unmined(conn, settings.claude_dir, settings.mine_max_batches)
    results = {"batches": 0, "insights": 0, "redactions": 0, "skill_proposals": 0, "candidates_rejected": 0}
    for path in files:
        allowed, reason = check(conn, "mining")
        if not allowed:
            results["halted"] = reason
            break
        texts = _user_texts(path)
        if not texts:
            conn.execute(
                "INSERT OR REPLACE INTO mined_files (path,mtime,mined_at) VALUES (?,?,?)",
                (str(path), path.stat().st_mtime, utcnow()),
            )
            conn.commit()
            continue
        blob = "\n---\n".join(texts)[:_BATCH_CHARS]
        clean, counts = redact(blob)
        results["redactions"] += sum(counts.values())
        try:
            from ..config import model as _mining_model_fn
            from ..guard import guard_settings_args
            from ..overnight import parse_cli_json
            from ..workspace import claude_bin

            proc = subprocess.run(
                [
                    claude_bin(),
                    "-p",
                    _PROMPT + clean,
                    "--output-format",
                    "json",
                    "--max-turns",
                    "1",
                    "--model",
                    _mining_model_fn("build"),
                    *guard_settings_args(),
                ],
                capture_output=True,
                text=True,
                timeout=300,
            )
            result_text = parse_cli_json(proc.stdout)[0] if proc.returncode == 0 else None
        except (subprocess.TimeoutExpired, OSError, json.JSONDecodeError):
            result_text = None
        if result_text:
            try:
                start, end = result_text.find("{"), result_text.rfind("}")
                data = json.loads(result_text[start : end + 1]) if start >= 0 else {}
            except (json.JSONDecodeError, ValueError):
                data = {}
            for note in (data.get("methodology_notes") or [])[:5]:
                conn.execute(
                    "INSERT INTO insights (kind,title,body,source,created_at) VALUES (?,?,?,?,?)",
                    ("methodology", str(note)[:120], str(note), path.name, utcnow()),
                )
                results["insights"] += 1
            for note in (data.get("memory_notes") or [])[:5]:
                conn.execute(
                    "INSERT INTO insights (kind,title,body,source,created_at) VALUES (?,?,?,?,?)",
                    ("memory", str(note)[:120], str(note), path.name, utcnow()),
                )
                results["insights"] += 1
            # Skill candidates are the only thing that becomes a WRITE proposal,
            # and only after the evidence gate. Previously the model's candidates
            # were discarded here while a keyword heuristic did the proposing:
            # exactly backwards, and the reason ten junk skills reached ~/.claude.
            raw_cands = [
                {**c, "source": c.get("source") or path.name}
                for c in (data.get("skill_candidates") or [])
                if isinstance(c, dict)
            ]
            kept, dropped = admissible(raw_cands, existing_slugs=_existing_slugs(settings.claude_dir))
            for cand in kept[:3]:
                if _propose_skill(conn, cand, path.name):
                    results["skill_proposals"] += 1
            for rej in dropped:
                results["candidates_rejected"] += 1
                audit(conn, "miner", "candidate_rejected", f"{rej.slug}: {rej.reason}"[:400])
        conn.execute(
            "INSERT OR REPLACE INTO mined_files (path,mtime,mined_at) VALUES (?,?,?)",
            (str(path), path.stat().st_mtime, utcnow()),
        )
        conn.commit()
        results["batches"] += 1
        consume(conn, "mining", tasks=1)
    audit(conn, "miner", "llm_mining_run", json.dumps(results))
    return results
