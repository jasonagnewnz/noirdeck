"""Design Studio: propose → mock quickly → apply deliberately.

- Propose: N parallel headless Claude runs, each committed to a DIFFERENT aesthetic
  direction and (optionally) a different UI library, each producing one fast,
  self-contained single-file HTML mock in a STAGING dir — never the repo.
- Apply: the chosen mock's design language is applied to the target repo's real
  frontend by a headless session (local commits, code-ready, never deployed).
- The design doctrine below is distilled from the estate frontend-design skill;
  sessions are also pointed at the full skill file on disk.
"""
from __future__ import annotations

import json
import subprocess
import threading
import time
from pathlib import Path

from .config import Settings, model as _model
from .db import audit, connect, utcnow
from .overnight import _parse_verdict, parse_cli_json
from .workspace import validate_cwd

DOCTRINE = """
DESIGN DOCTRINE (non-negotiable):
- Commit to ONE bold, coherent aesthetic direction and execute it precisely.
- Typography: distinctive, characterful pairings. NEVER Arial/Inter/Roboto/system-default look.
- Color: CSS variables; dominant ground + sharp accent beats timid even palettes.
- Space: intentional composition — asymmetry, generous negative space OR controlled density.
- Depth & atmosphere: gradients, grain, layered translucency, decisive shadows — never flat default white.
- Motion: a few high-impact moments (staggered load reveal, surprising hover) over scattered effects.
- Enterprise-grade: information-dense where it matters, accessible contrast, real content hierarchy.
- ABSOLUTELY NO generic AI-slop: no purple-gradient-on-white, no cookie-cutter cards, no lorem-ipsum energy.
The full skill lives at ~/.claude/skills/frontend-design/SKILL.md — read it if present.
"""

DIRECTIONS = [
    ("instrument", "terminal instrument-panel: mono-dominant type, hairline grids, signal-color accents on graphite"),
    ("editorial", "luxury editorial: oversized serif display type, magazine grid, restrained ink palette, one metallic accent"),
    ("aurora", "aurora glass: deep-space ground, layered translucent panels, soft neon gradients used sparingly"),
    ("brutalist", "refined brutalism: raw blocks, exposed structure, huge type, stark contrast, one shock color"),
    ("botanical", "organic calm: warm paper tones, botanical accents, soft shadows, humanist type, unhurried spacing"),
    ("neo-material", "soft neo-material: tactile surfaces, gentle elevation, rounded geometry, muted confident color"),
    ("swiss", "swiss international: strict grid, flat planes of color, perfect typographic rhythm, zero ornament"),
    ("deco", "art-deco geometric: stepped forms, brass-on-ink palette, symmetrical luxury, patterned details"),
]

LIBRARIES = {
    "bespoke": "No component library — fully bespoke CSS, hand-crafted components.",
    "fluent": "Microsoft Fluent 2 design language: its type ramp, elevation, acrylic/mica surfaces, corner radii, and interaction states. Emulate faithfully in the mock; the real build would use @fluentui/react-components.",
    "material": "Google Material 3: dynamic-color token system, tonal surfaces, state layers, M3 shape scale. Emulate in the mock; the real build would use @mui/material or material-web.",
    "carbon": "IBM Carbon: productive enterprise density, 2x grid, sharp corners, IBM Plex type. Emulate in the mock; the real build would use @carbon/react.",
    "antd": "Ant Design 5: its token system, compact enterprise tables/forms, subtle motion. Emulate in the mock; the real build would use antd.",
    "shadcn": "shadcn/ui + Radix aesthetics: neutral sophistication, crisp borders, keyboard-first affordances, tasteful dark mode. Emulate in the mock; the real build would use shadcn/ui + Tailwind.",
}

MOCK_TIMEOUT_S = 600
APPLY_TIMEOUT_S = 2400

MOCK_GUARDRAILS = """
RULES: Write EXACTLY ONE self-contained file at the path given — inline CSS, no external
resources, no build step, realistic example content (never lorem ipsum), desktop-first but
not broken on mobile. Do not touch ANY other file. End with:
VERDICT: {"status":"done","summary":"<one line: the direction you executed>"}
"""

APPLY_GUARDRAILS = """
RULES: Work only inside this repository. NEVER git push, deploy, publish, or call external
services. Local commits at sensible points. Never weaken tests. Preserve all behavior —
this is a redesign, not a rewrite. End with:
VERDICT: {"status":"done"|"blocked","summary":"<2 sentences>","question":"<only if blocked>"}
"""


class DesignStudio:
    # variant threads race a read-modify-write on the shared variants column;
    # single process, so a process lock is the whole fix (found by the test suite)
    _variants_lock = threading.Lock()

    def __init__(self, settings: Settings, claude_argv_base: list[str] | None = None):
        self.settings = settings
        self.claude_argv_base = claude_argv_base  # tests only
        self.staging_root = settings.db_path.parent / "design"
        self.staging_root.mkdir(parents=True, exist_ok=True)

    def _db(self):
        return connect(self.settings.db_path)

    def _update_variant(self, round_id: int, key: str, **fields) -> None:
        with self._variants_lock:
            self._update_variant_locked(round_id, key, **fields)

    def _update_variant_locked(self, round_id: int, key: str, **fields) -> None:
        conn = self._db()
        try:
            row = conn.execute("SELECT variants FROM design_rounds WHERE id=?", (round_id,)).fetchone()
            variants = json.loads(row["variants"])
            for v in variants:
                if v["key"] == key:
                    v.update(fields)
            done = all(v["status"] in ("done", "failed") for v in variants)
            conn.execute("UPDATE design_rounds SET variants=?, status=? WHERE id=?",
                         (json.dumps(variants),
                          "ready" if done else "proposing", round_id))
            conn.commit()
        finally:
            conn.close()

    def _run_claude(self, prompt: str, cwd: Path, model: str, max_turns: int,
                    timeout: int, env_extra: dict | None = None) -> dict:
        import os

        from .workspace import claude_bin
        if self.claude_argv_base is not None:
            argv = self.claude_argv_base + [prompt]
        else:
            from .guard import guard_settings_args
            argv = [claude_bin(), "-p", prompt, "--output-format", "json", "--model", model,
                    "--max-turns", str(max_turns), "--permission-mode", "acceptEdits",
                    *guard_settings_args()]
        env = dict(os.environ, **(env_extra or {}))
        try:
            proc = subprocess.run(argv, cwd=str(cwd), capture_output=True, text=True,
                                  timeout=timeout, env=env)
        except subprocess.TimeoutExpired:
            return {"status": "blocked", "summary": "timed out"}
        if proc.returncode != 0:
            return {"status": "blocked", "summary": (proc.stderr or "exited nonzero")[-300:]}
        try:
            result_text, _, _ = parse_cli_json(proc.stdout)
            return _parse_verdict(result_text)
        except json.JSONDecodeError:
            return _parse_verdict(proc.stdout)

    # --- propose ---
    def propose(self, project: str, brief: str, library: str = "mix", n: int = 3) -> int:
        validate_cwd(self.settings.projects_dir, project)  # target must be real
        if library != "mix" and library not in LIBRARIES:
            raise ValueError(f"unknown library {library}")
        conn = self._db()
        try:
            cur = conn.execute(
                "INSERT INTO design_rounds (project,brief,library,status,variants,created_at) "
                "VALUES (?,?,?,'proposing','[]',?)", (project, brief, library, utcnow()))
            round_id = cur.lastrowid
            # rotate direction pairing by round id so consecutive rounds differ
            libs = list(LIBRARIES) if library == "mix" else [library]
            variants = []
            for i in range(n):
                d_key, d_desc = DIRECTIONS[(round_id * 3 + i) % len(DIRECTIONS)]
                l_key = libs[(round_id + i) % len(libs)] if library == "mix" else library
                variants.append({"key": f"v{i + 1}", "direction": d_key, "library": l_key,
                                 "status": "running", "summary": ""})
            conn.execute("UPDATE design_rounds SET variants=? WHERE id=?",
                         (json.dumps(variants), round_id))
            audit(conn, "operator", "design_proposed", f"round={round_id} project={project} lib={library}")
            conn.commit()
        finally:
            conn.close()
        stage = self.staging_root / str(round_id)
        stage.mkdir(parents=True, exist_ok=True)
        for v in variants:
            threading.Thread(target=self._make_mock,
                             args=(round_id, project, brief, v, stage), daemon=True).start()
        return round_id

    def _make_mock(self, round_id: int, project: str, brief: str, v: dict, stage: Path) -> None:
        # crash-net parity with builds: a dead thread must not strand the round
        try:
            self._make_mock_inner(round_id, project, brief, v, stage)
        except Exception as exc:  # noqa: BLE001
            self._update_variant(round_id, v["key"], status="failed",
                                 summary=f"{type(exc).__name__}: {exc}"[:300])

    def _make_mock_inner(self, round_id: int, project: str, brief: str, v: dict, stage: Path) -> None:
        out = stage / f"{v['key']}.html"
        d_desc = dict(DIRECTIONS)[v["direction"]]
        prompt = (
            f"You are one of {3} parallel designers each mocking the SAME surface in a "
            f"DIFFERENT direction. Surface: {brief} (for the project '{project}').\n"
            f"YOUR aesthetic direction: {v['direction']} — {d_desc}.\n"
            f"UI system: {LIBRARIES[v['library']]}\n"
            f"{DOCTRINE}\n"
            f"Write the mock to exactly this path: {out}\n"
            f"(The same path is in $DESIGN_OUT.)\n"
            f"{MOCK_GUARDRAILS}")
        verdict = self._run_claude(prompt, stage, _model("build"), 8, MOCK_TIMEOUT_S,
                                   env_extra={"DESIGN_OUT": str(out)})
        ok = verdict.get("status") == "done" and out.is_file()
        self._update_variant(round_id, v["key"],
                             status="done" if ok else "failed",
                             summary=str(verdict.get("summary", ""))[:300])

    # --- apply ---
    def apply(self, round_id: int, variant_key: str) -> None:
        conn = self._db()
        try:
            row = conn.execute("SELECT * FROM design_rounds WHERE id=?", (round_id,)).fetchone()
            if not row:
                raise ValueError(f"no design round {round_id}")
            variants = json.loads(row["variants"])
            v = next((x for x in variants if x["key"] == variant_key), None)
            if not v or v["status"] != "done":
                raise ValueError("variant not ready")
            conn.execute("UPDATE design_rounds SET status='applying', applied_variant=? WHERE id=?",
                         (variant_key, round_id))
            audit(conn, "operator", "design_applied", f"round={round_id} variant={variant_key}")
            conn.commit()
            project, brief = row["project"], row["brief"]
        finally:
            conn.close()
        threading.Thread(target=self._apply_worker,
                         args=(round_id, project, brief, v), daemon=True).start()

    def requeue_stale(self) -> None:
        """Server restart kills variant threads — mark their rounds honestly."""
        conn = self._db()
        try:
            rows = conn.execute(
                "SELECT id, variants FROM design_rounds WHERE status IN ('proposing','applying')"
            ).fetchall()
            for r in rows:
                variants = json.loads(r["variants"])
                for v in variants:
                    if v["status"] == "running":
                        v["status"] = "failed"
                        v["summary"] = "server restarted mid-generation — propose again"
                conn.execute("UPDATE design_rounds SET variants=?, status='ready' WHERE id=?",
                             (json.dumps(variants), r["id"]))
            conn.commit()
        finally:
            conn.close()

    def _apply_worker(self, round_id: int, project: str, brief: str, v: dict) -> None:
        repo = validate_cwd(self.settings.projects_dir, project)
        mock = self.staging_root / str(round_id) / f"{v['key']}.html"
        prompt = (
            f"The operator approved a design direction for: {brief}.\n"
            f"The approved mock is at: {mock} — read it. Apply ITS design language "
            f"(type, palette, spacing, components, atmosphere) to this project's real "
            f"frontend.\n"
            f"UI system for the real implementation: {LIBRARIES[v['library']]} "
            f"Install and use the real library packages where that is the natural fit; "
            f"otherwise translate the language into the project's existing stack.\n"
            f"{DOCTRINE}\n{APPLY_GUARDRAILS}")
        verdict = self._run_claude(prompt, repo, _model("build"), 60, APPLY_TIMEOUT_S)
        conn = self._db()
        try:
            status = "applied" if verdict.get("status") == "done" else "apply-blocked"
            conn.execute("UPDATE design_rounds SET status=?, apply_summary=? WHERE id=?",
                         (status, str(verdict.get("summary", ""))[:500], round_id))
            audit(conn, "design", "design_apply_finished", f"round={round_id} status={status}")
            conn.commit()
        finally:
            conn.close()

    def mock_path(self, round_id: int, variant_key: str) -> Path:
        import re
        if not re.fullmatch(r"v[0-9]{1,2}", variant_key):
            raise ValueError("bad variant key")
        path = (self.staging_root / str(int(round_id)) / f"{variant_key}.html").resolve()
        if self.staging_root.resolve() not in path.parents:
            raise ValueError("path escape")
        return path
