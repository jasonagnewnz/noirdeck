"""Apply a UI: capture or brief → mock quickly → apply deliberately.

- Propose: N parallel headless Claude runs, each committed to a DIFFERENT aesthetic
  direction inside one ready-made UI kit, each producing one fast, self-contained
  single-file HTML mock in a STAGING dir: never the repo.
- Apply: the chosen mock's design language is applied to the target repo's real
  frontend by a headless session (local commits, code-ready, never deployed).
- The design doctrine below is distilled from the estate frontend-design skill;
  sessions are also pointed at the full skill file on disk.
"""

from __future__ import annotations

import json
import re
import subprocess
import threading
from collections import Counter
from pathlib import Path

from .config import Settings
from .config import model as _model
from .db import audit, connect, utcnow
from .overnight import _parse_verdict, parse_cli_json
from .workspace import validate_cwd

DOCTRINE = """
DESIGN DOCTRINE (non-negotiable):
- Commit to ONE bold, coherent aesthetic direction and execute it precisely.
- Typography: distinctive, characterful pairings. NEVER Arial/Inter/Roboto/system-default look.
- Color: CSS variables; dominant ground + sharp accent beats timid even palettes.
- Space: intentional composition: asymmetry, generous negative space OR controlled density.
- Depth & atmosphere: gradients, grain, layered translucency, decisive shadows: never flat default white.
- Motion: a few high-impact moments (staggered load reveal, surprising hover) over scattered effects.
- Enterprise-grade: information-dense where it matters, accessible contrast, real content hierarchy.
- ABSOLUTELY NO generic AI-slop: no purple-gradient-on-white, no cookie-cutter cards, no lorem-ipsum energy.
The full skill lives at ~/.claude/skills/frontend-design/SKILL.md: read it if present.
"""

DIRECTIONS = [
    ("instrument", "terminal instrument-panel: mono-dominant type, hairline grids, signal-color accents on graphite"),
    (
        "editorial",
        "luxury editorial: oversized serif display type, magazine grid, restrained ink palette, one metallic accent",
    ),
    ("aurora", "aurora glass: deep-space ground, layered translucent panels, soft neon gradients used sparingly"),
    ("brutalist", "refined brutalism: raw blocks, exposed structure, huge type, stark contrast, one shock color"),
    ("botanical", "organic calm: warm paper tones, botanical accents, soft shadows, humanist type, unhurried spacing"),
    ("neo-material", "soft neo-material: tactile surfaces, gentle elevation, rounded geometry, muted confident color"),
    ("swiss", "swiss international: strict grid, flat planes of color, perfect typographic rhythm, zero ornament"),
    ("deco", "art-deco geometric: stepped forms, brass-on-ink palette, symmetrical luxury, patterned details"),
]

UI_KITS = {
    "landing": "Landing Page kit: hero, proof, feature sections, pricing or offer block, FAQ, and one obvious primary call to action. Use for public websites and launch pages.",
    "dashboard": "Dashboard kit: metrics, filters, tables, charts, status chips, side navigation, and dense scan-friendly layouts. Use for internal tools, SaaS apps, and operations screens.",
    "booking": "Booking Flow kit: service cards, availability picker, intake form, confirmation state, reminders, and clear next steps. Use for appointments, quotes, events, and lead capture.",
    "shopfront": "Shopfront kit: catalog grid, product/detail panel, cart summary, checkout path, trust signals, and promotional areas. Use for stores, menus, subscriptions, and paid offers.",
    "portal": "Admin Portal kit: authenticated shell, overview, records list, detail drawer, settings, user/team controls, empty states, and audit/status surfaces. Use for CRUD-heavy workspaces.",
    "portfolio": "Portfolio kit: identity header, case studies, gallery/media strip, testimonials, process/story sections, and contact CTA. Use for personal, agency, venue, and project showcase sites.",
}

LEGACY_UI_KITS = {
    "bespoke": "Legacy Bespoke CSS kit: no component library, fully bespoke CSS, hand-crafted components.",
    "fluent": "Microsoft Fluent 2 design language: its type ramp, elevation, acrylic/mica surfaces, corner radii, and interaction states. Emulate faithfully in the mock; the real build would use @fluentui/react-components.",
    "material": "Google Material 3: dynamic-color token system, tonal surfaces, state layers, M3 shape scale. Emulate in the mock; the real build would use @mui/material or material-web.",
    "carbon": "IBM Carbon: productive enterprise density, 2x grid, sharp corners, IBM Plex type. Emulate in the mock; the real build would use @carbon/react.",
    "antd": "Ant Design 5: its token system, compact enterprise tables/forms, subtle motion. Emulate in the mock; the real build would use antd.",
    "shadcn": "shadcn/ui + Radix aesthetics: neutral sophistication, crisp borders, keyboard-first affordances, tasteful dark mode. Emulate in the mock; the real build would use shadcn/ui + Tailwind.",
}
# The database column and API body are still named "library" for compatibility
# with saved design rounds from earlier versions.
LIBRARIES = {**UI_KITS, **LEGACY_UI_KITS}

MOCK_TIMEOUT_S = 600
APPLY_TIMEOUT_S = 2400
CAPTURE_EXTS = {".css", ".scss", ".sass", ".less", ".html", ".jsx", ".tsx", ".js", ".ts", ".vue", ".svelte"}
CAPTURE_SKIP_DIRS = {
    ".git",
    ".next",
    ".nuxt",
    ".svelte-kit",
    ".venv",
    "__pycache__",
    "build",
    "coverage",
    "dist",
    "node_modules",
    "venv",
}
COLOR_RE = re.compile(r"#[0-9a-fA-F]{3,8}\b|rgba?\([^)]{3,80}\)|hsla?\([^)]{3,80}\)|var\(--[A-Za-z0-9_-]+\)")
FONT_RE = re.compile(r"font-family\s*:\s*([^;}{]+)", re.I)
RADIUS_RE = re.compile(r"border-radius\s*:\s*([^;}{]+)", re.I)
CLASS_RE = re.compile(r"(?:class|className)\s*=\s*['\"]([^'\"]{2,600})['\"]")


def _top(counter: Counter[str], n: int = 8) -> list[str]:
    return [key for key, _ in counter.most_common(n)]


def _read_text(path: Path, max_bytes: int = 80_000) -> str:
    raw = path.read_bytes()[:max_bytes]
    if b"\x00" in raw[:8000]:
        return ""
    return raw.decode("utf-8", errors="replace")


def _compact(values: list[str], fallback: str) -> str:
    return ", ".join(values) if values else fallback


MOCK_GUARDRAILS = """
RULES: Write EXACTLY ONE self-contained file at the path given: inline CSS, no external
resources, no build step, realistic example content (never lorem ipsum), desktop-first but
not broken on mobile. Do not touch ANY other file. End with:
VERDICT: {"status":"done","summary":"<one line: the direction you executed>"}
"""

APPLY_GUARDRAILS = """
RULES: Work only inside this repository. NEVER git push, deploy, publish, or call external
services. Local commits at sensible points. Never weaken tests. Preserve all behavior:
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
            conn.execute(
                "UPDATE design_rounds SET variants=?, status=? WHERE id=?",
                (json.dumps(variants), "ready" if done else "proposing", round_id),
            )
            conn.commit()
        finally:
            conn.close()

    def _run_claude(
        self, prompt: str, cwd: Path, model: str, max_turns: int, timeout: int, env_extra: dict | None = None
    ) -> dict:
        import os

        from .workspace import claude_bin

        if self.claude_argv_base is not None:
            argv = self.claude_argv_base + [prompt]
        else:
            from .guard import guard_settings_args

            argv = [
                claude_bin(),
                "-p",
                prompt,
                "--output-format",
                "json",
                "--model",
                model,
                "--max-turns",
                str(max_turns),
                "--permission-mode",
                "acceptEdits",
                *guard_settings_args(),
            ]
        env = dict(os.environ, **(env_extra or {}))
        try:
            proc = subprocess.run(argv, cwd=str(cwd), capture_output=True, text=True, timeout=timeout, env=env)
        except subprocess.TimeoutExpired:
            return {"status": "blocked", "summary": "timed out"}
        if proc.returncode != 0:
            return {"status": "blocked", "summary": (proc.stderr or "exited nonzero")[-300:]}
        try:
            result_text, _, _ = parse_cli_json(proc.stdout)
            return _parse_verdict(result_text)
        except json.JSONDecodeError:
            return _parse_verdict(proc.stdout)

    def _capture_files(self, repo: Path) -> list[Path]:
        files = []
        for path in repo.rglob("*"):
            try:
                rel = path.relative_to(repo)
            except ValueError:
                continue
            if any(part in CAPTURE_SKIP_DIRS for part in rel.parts):
                continue
            if path.is_symlink() or not path.is_file() or path.suffix.lower() not in CAPTURE_EXTS:
                continue
            try:
                resolved = path.resolve()
                if repo not in resolved.parents:
                    continue
                if path.stat().st_size > 250_000:
                    continue
            except OSError:
                continue
            files.append(path)

        def score(path: Path) -> tuple[int, int, str]:
            rel = path.relative_to(repo)
            parts = set(rel.parts)
            name = path.name.lower()
            priority = 0
            if path.suffix.lower() in {".css", ".scss", ".sass", ".less"}:
                priority -= 8
            if parts & {"app", "src", "pages", "components", "styles"}:
                priority -= 4
            if name in {"app.css", "index.css", "main.css", "globals.css", "style.css", "styles.css"}:
                priority -= 6
            if name.startswith(("tailwind.config", "theme", "tokens")):
                priority -= 5
            return (priority, len(rel.parts), str(rel))

        return sorted(files, key=score)[:80]

    def _package_deps(self, repo: Path) -> set[str]:
        path = repo / "package.json"
        if not path.is_file():
            return set()
        try:
            package = json.loads(_read_text(path, 120_000))
        except json.JSONDecodeError:
            return set()
        deps = set()
        for key in ("dependencies", "devDependencies"):
            values = package.get(key)
            if isinstance(values, dict):
                deps.update(values)
        return deps

    def _detect_stack(self, deps: set[str], text: str, files: list[Path]) -> list[str]:
        lower = text.lower()
        suffixes = {p.suffix.lower() for p in files}
        stack = []
        checks = [
            ("Next.js", "next" in deps or "app/layout" in lower),
            ("React", "react" in deps or suffixes & {".jsx", ".tsx"}),
            ("Vue", "vue" in deps or ".vue" in suffixes),
            ("Svelte", "svelte" in deps or ".svelte" in suffixes),
            ("Vite", "vite" in deps),
            ("Tailwind", "tailwindcss" in deps or "tailwind.config" in lower or " bg-" in lower),
            ("Material UI", "@mui/material" in deps),
            ("Ant Design", "antd" in deps),
            ("Framer Motion", "framer-motion" in deps or "motion." in lower),
            ("shadcn/Radix", "@radix-ui/react-slot" in deps or "components/ui/" in lower),
            ("CSS modules", ".module.css" in lower or any(p.name.endswith(".module.css") for p in files)),
        ]
        for label, ok in checks:
            if ok:
                stack.append(label)
        if not stack and deps:
            stack.append("frontend package")
        return stack

    def _suggest_kit(self, corpus: str) -> str:
        lower = corpus.lower()
        buckets = {
            "shopfront": ("cart", "checkout", "product", "catalog", "price", "subscription", "order", "ecommerce"),
            "booking": ("booking", "appointment", "calendar", "schedule", "availability", "quote", "reservation"),
            "portal": ("admin", "settings", "users", "roles", "audit", "record", "detail drawer", "workspace"),
            "portfolio": ("portfolio", "case study", "gallery", "testimonial", "agency", "resume", "about"),
            "dashboard": ("dashboard", "metric", "chart", "table", "filter", "status", "kpi", "analytics"),
            "landing": ("hero", "cta", "pricing", "feature", "faq", "contact", "signup", "launch"),
        }

        def term_count(term: str) -> int:
            pattern = re.escape(term).replace(r"\ ", r"[\s_-]+")
            return len(re.findall(rf"(?<![a-z0-9]){pattern}(?![a-z0-9])", lower))

        scores = {kit: sum(term_count(term) for term in terms) for kit, terms in buckets.items()}
        best, count = max(scores.items(), key=lambda item: item[1])
        return best if count else "landing"

    def capture_design(self, project: str) -> dict:
        repo = validate_cwd(self.settings.projects_dir, project)
        files = self._capture_files(repo)
        deps = self._package_deps(repo)
        if not files and not deps:
            raise ValueError("no frontend files found to capture")

        colors: Counter[str] = Counter()
        fonts: Counter[str] = Counter()
        radii: Counter[str] = Counter()
        classes: Counter[str] = Counter()
        components: Counter[str] = Counter()
        sampled: list[str] = []
        corpus_parts = [" ".join(sorted(deps))]

        for path in files:
            rel = str(path.relative_to(repo))
            text = _read_text(path)
            if not text:
                continue
            sampled.append(rel)
            corpus_parts.append(rel)
            corpus_parts.append(text[:20_000])
            colors.update(match.group(0).lower() for match in COLOR_RE.finditer(text))
            fonts.update(font.split(",")[0].strip().strip("\"'") for font in FONT_RE.findall(text) if font.strip())
            radii.update(value.strip() for value in RADIUS_RE.findall(text) if value.strip())
            for class_match in CLASS_RE.findall(text):
                for token in class_match.split():
                    if token.startswith(("bg-", "text-", "border-", "rounded", "shadow", "grid", "flex", "gap-", "p-")):
                        classes[token] += 1
            lower = text.lower()
            for term in (
                "hero",
                "nav",
                "sidebar",
                "dashboard",
                "card",
                "table",
                "form",
                "modal",
                "drawer",
                "chart",
                "gallery",
                "pricing",
                "testimonial",
            ):
                count = lower.count(term)
                if count:
                    components[term] += count

        corpus = "\n".join(corpus_parts)
        stack = self._detect_stack(deps, corpus, files)
        suggested = self._suggest_kit(corpus)
        source_files = sampled[:12]
        summary = (
            f"Captured {project}: {_compact(stack, 'frontend surface')}; "
            f"{len(sampled)} files sampled; suggested kit {suggested}."
        )
        brief = "\n".join(
            [
                f"Capture the existing UI language from the project '{project}' and apply it to the target repo.",
                f"Detected stack: {_compact(stack, 'not obvious from files')}.",
                f"Color tokens and accents: {_compact(_top(colors), 'not obvious')}.",
                f"Typography: {_compact(_top(fonts, 5), 'not obvious')}.",
                f"Shape and radius: {_compact(_top(radii, 5), 'not obvious')}.",
                f"Layout/component signals: {_compact(_top(components), 'not obvious')}.",
                f"Utility class signals: {_compact(_top(classes, 10), 'not obvious')}.",
                f"Source files sampled: {_compact(source_files, 'package metadata only')}.",
                "Preserve the target app's behavior. Translate the captured visual language into the selected UI kit and the target project's existing stack.",
            ]
        )
        return {
            "project": project,
            "suggested_kit": suggested,
            "summary": summary,
            "brief": brief,
            "evidence": {
                "stack": stack,
                "colors": _top(colors),
                "fonts": _top(fonts, 5),
                "radii": _top(radii, 5),
                "components": _top(components),
                "classes": _top(classes, 10),
                "files": source_files,
            },
        }

    # --- propose ---
    def propose(self, project: str, brief: str, library: str = "landing", n: int = 3) -> int:
        validate_cwd(self.settings.projects_dir, project)  # target must be real
        if library != "mix" and library not in LIBRARIES:
            raise ValueError(f"unknown UI kit {library}")
        conn = self._db()
        try:
            cur = conn.execute(
                "INSERT INTO design_rounds (project,brief,library,status,variants,created_at) "
                "VALUES (?,?,?,'proposing','[]',?)",
                (project, brief, library, utcnow()),
            )
            round_id = cur.lastrowid
            # rotate direction pairing by round id so consecutive rounds differ
            libs = list(UI_KITS) if library == "mix" else [library]
            variants = []
            for i in range(n):
                d_key, d_desc = DIRECTIONS[(round_id * 3 + i) % len(DIRECTIONS)]
                l_key = libs[(round_id + i) % len(libs)] if library == "mix" else library
                variants.append(
                    {"key": f"v{i + 1}", "direction": d_key, "library": l_key, "status": "running", "summary": ""}
                )
            conn.execute("UPDATE design_rounds SET variants=? WHERE id=?", (json.dumps(variants), round_id))
            audit(conn, "operator", "design_proposed", f"round={round_id} project={project} lib={library}")
            conn.commit()
        finally:
            conn.close()
        stage = self.staging_root / str(round_id)
        stage.mkdir(parents=True, exist_ok=True)
        for v in variants:
            threading.Thread(target=self._make_mock, args=(round_id, project, brief, v, stage), daemon=True).start()
        return round_id

    def _make_mock(self, round_id: int, project: str, brief: str, v: dict, stage: Path) -> None:
        # crash-net parity with builds: a dead thread must not strand the round
        try:
            self._make_mock_inner(round_id, project, brief, v, stage)
        except Exception as exc:  # noqa: BLE001
            self._update_variant(round_id, v["key"], status="failed", summary=f"{type(exc).__name__}: {exc}"[:300])

    def _make_mock_inner(self, round_id: int, project: str, brief: str, v: dict, stage: Path) -> None:
        out = stage / f"{v['key']}.html"
        d_desc = dict(DIRECTIONS)[v["direction"]]
        prompt = (
            f"You are one of {3} parallel designers each mocking the SAME surface in a "
            f"DIFFERENT direction. Surface: {brief} (for the project '{project}').\n"
            f"YOUR aesthetic direction: {v['direction']}: {d_desc}.\n"
            f"UI kit: {LIBRARIES[v['library']]}\n"
            f"{DOCTRINE}\n"
            f"Write the mock to exactly this path: {out}\n"
            f"(The same path is in $DESIGN_OUT.)\n"
            f"{MOCK_GUARDRAILS}"
        )
        verdict = self._run_claude(
            prompt, stage, _model("build"), 8, MOCK_TIMEOUT_S, env_extra={"DESIGN_OUT": str(out)}
        )
        ok = verdict.get("status") == "done" and out.is_file()
        self._update_variant(
            round_id, v["key"], status="done" if ok else "failed", summary=str(verdict.get("summary", ""))[:300]
        )

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
            conn.execute(
                "UPDATE design_rounds SET status='applying', applied_variant=? WHERE id=?", (variant_key, round_id)
            )
            audit(conn, "operator", "design_applied", f"round={round_id} variant={variant_key}")
            conn.commit()
            project, brief = row["project"], row["brief"]
        finally:
            conn.close()
        threading.Thread(target=self._apply_worker, args=(round_id, project, brief, v), daemon=True).start()

    def requeue_stale(self) -> None:
        """Server restart kills variant threads: mark their rounds honestly."""
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
                        v["summary"] = "server restarted mid-generation: propose again"
                conn.execute(
                    "UPDATE design_rounds SET variants=?, status='ready' WHERE id=?", (json.dumps(variants), r["id"])
                )
            conn.commit()
        finally:
            conn.close()

    def _apply_worker(self, round_id: int, project: str, brief: str, v: dict) -> None:
        repo = validate_cwd(self.settings.projects_dir, project)
        mock = self.staging_root / str(round_id) / f"{v['key']}.html"
        prompt = (
            f"The operator approved a design direction for: {brief}.\n"
            f"The approved mock is at: {mock}: read it. Apply ITS design language "
            f"(type, palette, spacing, components, atmosphere) to this project's real "
            f"frontend.\n"
            f"UI kit for the real implementation: {LIBRARIES[v['library']]} "
            f"Use the project's existing stack unless adding a small, appropriate UI package "
            f"is clearly the natural fit.\n"
            f"{DOCTRINE}\n{APPLY_GUARDRAILS}"
        )
        verdict = self._run_claude(prompt, repo, _model("build"), 60, APPLY_TIMEOUT_S)
        conn = self._db()
        try:
            status = "applied" if verdict.get("status") == "done" else "apply-blocked"
            conn.execute(
                "UPDATE design_rounds SET status=?, apply_summary=? WHERE id=?",
                (status, str(verdict.get("summary", ""))[:500], round_id),
            )
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
