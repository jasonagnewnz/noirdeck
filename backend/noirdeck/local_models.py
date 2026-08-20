"""Local models made approachable: get Ollama running, pull something sensible,
and say in plain words which model suits the work this person actually does.

Design stance — this is the "I don't want to learn any of this" path:
- Nothing here assumes the reader knows what a quant, a context window or a GGUF
  is. Every recommendation says what the model is FOR and whether it fits.
- Recommendations are gated on MEASURED capacity, never on hope. A model that
  needs more memory than the machine has is shown as out of reach with the reason,
  because a local model that swaps is indistinguishable from a broken one.
- ⛔ Install is USER-LOCAL and needs no root. Ollama's own install script wants
  sudo (it writes /usr/local/bin and a system service), and on this estate local
  sudo cannot work at all — no tty for askpass (fb_wsl_sudo_askpass_no_tty). So we
  unpack the official tarball into ~/.local and run the server as the user. Same
  binary, no privilege, and it matches how the existing install on this box was
  actually done.
- Downloading and running a binary from the internet is never automatic. The plan
  is always shown first and `confirm=True` is required to act.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tarfile
import tempfile
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path

OLLAMA_API = os.environ.get("NOIRDECK_OLLAMA", "http://127.0.0.1:11434")
# Official static builds. Kept as a dict so an unsupported arch is reported as
# such rather than silently downloading the wrong binary.
TARBALLS = {
    "x86_64": "https://ollama.com/download/ollama-linux-amd64.tgz",
    "aarch64": "https://ollama.com/download/ollama-linux-arm64.tgz",
}
INSTALL_ROOT = Path.home() / ".local"


# ── what is true right now ───────────────────────────────────────────────────


@dataclass
class Capacity:
    ram_gb: float | None
    gpu_name: str | None
    gpu_vram_gb: float | None
    # usable_gb is what recommendations are sized against: VRAM when there is a
    # GPU, otherwise system RAM minus headroom for everything else running.
    usable_gb: float | None
    basis: str


def _ram_gb() -> float | None:
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemTotal:"):
                return round(int(line.split()[1]) / 1048576, 1)
    except (OSError, ValueError, IndexError):
        return None
    return None


def _gpu() -> tuple[str | None, float | None]:
    exe = shutil.which("nvidia-smi")
    if not exe:
        return None, None
    try:
        out = subprocess.run(
            [exe, "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if out.returncode != 0 or not out.stdout.strip():
            return None, None
        name, mem = out.stdout.strip().splitlines()[0].split(",")
        return name.strip(), round(float(mem) / 1024, 1)
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None, None


def capacity() -> Capacity:
    ram = _ram_gb()
    gpu_name, vram = _gpu()
    if vram:
        return Capacity(ram, gpu_name, vram, vram, f"{vram} GB of graphics memory on {gpu_name}")
    if ram:
        # Leave room for the editor, the browser and the OS. A model sized to the
        # full RAM figure will page to disk and feel broken rather than slow.
        usable = round(max(0.0, ram - 6.0), 1)
        return Capacity(ram, gpu_name, None, usable, f"{usable} GB of your {ram} GB of memory, keeping 6 GB free")
    return Capacity(None, gpu_name, None, None, "could not measure this machine's memory")


def _binary() -> str | None:
    found = shutil.which("ollama")
    if found:
        return found
    local = INSTALL_ROOT / "bin" / "ollama"
    return str(local) if local.is_file() and os.access(local, os.X_OK) else None


def _version(exe: str) -> str | None:
    try:
        out = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=10)
        m = re.search(r"(\d+\.\d+\.\d+)", out.stdout + out.stderr)
        return m.group(1) if m else (out.stdout.strip() or None)
    except (OSError, subprocess.TimeoutExpired):
        return None


def installed_models() -> list[dict]:
    """Models already on this machine, with human sizes. [] can mean 'none pulled'
    OR 'server not running' — the caller must use `server_running` to tell those
    apart, never treat the empty list as evidence of a clean state."""
    try:
        with urllib.request.urlopen(f"{OLLAMA_API}/api/tags", timeout=5) as r:
            payload = json.load(r)
    except (OSError, urllib.error.URLError, json.JSONDecodeError):
        return []
    out = []
    for m in payload.get("models", []):
        size = m.get("size") or 0
        out.append(
            {
                "name": m.get("name"),
                "size_gb": round(size / 1_000_000_000, 1) if size else None,
                "modified_at": m.get("modified_at"),
            }
        )
    return sorted(out, key=lambda x: x["name"] or "")


def server_running() -> bool:
    try:
        with urllib.request.urlopen(f"{OLLAMA_API}/api/tags", timeout=3):
            return True
    except (OSError, urllib.error.URLError):
        return False


def state() -> dict:
    exe = _binary()
    running = server_running()
    cap = capacity()
    return {
        "installed": bool(exe),
        "binary": exe,
        "version": _version(exe) if exe else None,
        "user_local": bool(exe and str(INSTALL_ROOT) in exe),
        "server_running": running,
        # ⛔ Only meaningful when the server is up; see installed_models().
        "models": installed_models() if running else [],
        "models_known": running,
        "capacity": asdict(cap),
        "arch": os.uname().machine,
        "arch_supported": os.uname().machine in TARBALLS,
        "api": OLLAMA_API,
    }


# ── the catalogue ────────────────────────────────────────────────────────────
# Plain-language, purpose-first. `needs_gb` is the memory a comfortable run wants,
# not the download size — the download is smaller and it is the resident footprint
# that decides whether this feels instant or unusable.


@dataclass
class Candidate:
    tag: str
    label: str
    good_for: str
    needs_gb: float
    download_gb: float
    kinds: tuple[str, ...]  # which work this suits: code / writing / general / tiny


CATALOGUE: list[Candidate] = [
    Candidate(
        "qwen2.5-coder:1.5b",
        "Qwen Coder, small",
        "Quick code questions and completions on a modest machine. Fast, and noticeably shallower than the bigger ones.",
        3.0,
        1.0,
        ("code", "tiny"),
    ),
    Candidate(
        "qwen2.5-coder:7b",
        "Qwen Coder, standard",
        "The sensible default for coding work: reads a file, explains it, writes a patch. Good balance of speed and sense.",
        8.0,
        4.7,
        ("code", "general"),
    ),
    Candidate(
        "qwen2.5-coder:14b",
        "Qwen Coder, large",
        "Better reasoning about unfamiliar code and multi-file changes. Slower per answer.",
        16.0,
        9.0,
        ("code",),
    ),
    Candidate(
        "qwen2.5-coder:32b",
        "Qwen Coder, largest",
        "Closest a local model gets to a hosted one for code. Wants a lot of memory and rewards patience.",
        32.0,
        20.0,
        ("code",),
    ),
    Candidate(
        "llama3.1:8b",
        "Llama 3.1",
        "General-purpose: summarising, drafting, answering questions about text rather than code.",
        8.0,
        4.7,
        ("general", "writing"),
    ),
    Candidate(
        "llama3.2:3b",
        "Llama 3.2, small",
        "Light general assistant for a laptop. Handy for tidying notes and short summaries.",
        4.0,
        2.0,
        ("general", "writing", "tiny"),
    ),
    Candidate(
        "gemma2:9b",
        "Gemma 2",
        "Strong at clear prose. A good pick if most of what you want is writing and explaining.",
        10.0,
        5.4,
        ("writing", "general"),
    ),
    Candidate(
        "nomic-embed-text",
        "Nomic Embed",
        "Not a chat model: it turns your notes into searchable vectors. Tiny, and only needed for local search.",
        1.0,
        0.3,
        ("utility", "tiny"),
    ),
]


def infer_work_kind(top_slash: list, top_projects: list) -> str:
    """What this person mostly does, from their own usage. Deliberately coarse:
    'code' or 'mixed'. It picks the ORDER of recommendations, nothing more, so a
    wrong guess costs a reordered list and never a bad fit."""
    signals = " ".join(str(s[0]) for s in (top_slash or [])) + " " + " ".join(str(p[0]) for p in (top_projects or []))
    if re.search(r"(review|ship|test|deploy|migrat|api|build|refactor|ui|web|app|service)", signals, re.I):
        return "code"
    return "mixed"


def recommend(work_kind: str = "code", cap: Capacity | None = None, already: list[str] | None = None) -> dict:
    """Split the catalogue into what this machine can run well, what it cannot,
    and which single one to start with."""
    cap = cap or capacity()
    # A set, not a family-keyed dict: two tags of one family (…:7b and …:14b) are
    # different downloads, and keying by family let the second silently replace the
    # first so one of them would show as not-pulled when it was.
    pulled = set(already or [])
    usable = cap.usable_gb

    fits: list[dict] = []
    too_big: list[dict] = []
    for c in CATALOGUE:
        entry = {
            **asdict(c),
            "kinds": list(c.kinds),
            # ollama resolves a bare name to :latest, so match the way it does
            "already_pulled": c.tag in pulled or (":" not in c.tag and f"{c.tag}:latest" in pulled),
        }
        if usable is None:
            entry["note"] = "Cannot tell whether this fits — memory could not be measured."
            too_big.append(entry)
        elif c.needs_gb <= usable:
            entry["note"] = f"Fits: wants about {c.needs_gb:g} GB, you have {usable:g} GB to play with."
            fits.append(entry)
        else:
            entry["note"] = f"Too big here: wants about {c.needs_gb:g} GB, you have {usable:g} GB."
            too_big.append(entry)

    preferred = "code" if work_kind == "code" else "general"

    def rank(e: dict) -> tuple:
        # matching purpose first, then the largest that still fits — bigger is
        # better locally right up to the memory line, and worthless past it
        return (0 if preferred in e["kinds"] else 1, -e["needs_gb"])

    fits.sort(key=rank)
    start_with = next((e for e in fits if "utility" not in e["kinds"]), None)
    return {
        "work_kind": work_kind,
        "basis": cap.basis,
        "usable_gb": usable,
        "start_with": start_with,
        "fits": fits,
        "out_of_reach": too_big,
        "plain_summary": (
            f"Based on {cap.basis}, start with {start_with['label']} ({start_with['tag']})."
            if start_with
            else "No model in the list fits comfortably on this machine."
        ),
    }


# ── getting it installed, without root ───────────────────────────────────────


class LocalModelError(RuntimeError):
    pass


def install_plan() -> dict:
    """Exactly what an install would do, before anything is done."""
    arch = os.uname().machine
    url = TARBALLS.get(arch)
    return {
        "supported": bool(url),
        "arch": arch,
        "url": url,
        "target": str(INSTALL_ROOT / "bin" / "ollama"),
        "needs_root": False,
        "steps": [
            f"Download the official Ollama build for {arch}" + (f" from {url}" if url else ""),
            f"Unpack it into {INSTALL_ROOT} (your own folder — no admin rights needed)",
            "Start the model server in the background",
        ]
        if url
        else [f"No official build is published for this architecture ({arch})."],
        "manual_command": (
            f"curl -fsSL {url} | tar -xz -C {INSTALL_ROOT} && {INSTALL_ROOT}/bin/ollama serve &" if url else None
        ),
        "why_not_the_official_script": (
            "Ollama's own installer writes to /usr/local/bin and registers a system service, which needs admin "
            "rights. This puts the identical binary in your home folder instead, so nothing needs elevating."
        ),
    }


def install(confirm: bool = False, timeout: int = 900) -> dict:
    """Fetch and unpack Ollama into ~/.local. Requires confirm=True: this downloads
    an executable from the internet and runs it, which is never something to do on
    a page load."""
    plan = install_plan()
    if not plan["supported"]:
        raise LocalModelError(f"no official Ollama build for {plan['arch']}")
    if not confirm:
        return {"performed": False, "plan": plan, "reason": "confirm=true is required to download and install"}
    if _binary():
        return {"performed": False, "plan": plan, "reason": "already installed", "binary": _binary()}

    (INSTALL_ROOT / "bin").mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="noirdeck-ollama-") as td:
        archive = Path(td) / "ollama.tgz"
        try:
            with urllib.request.urlopen(plan["url"], timeout=timeout) as r, open(archive, "wb") as fh:
                shutil.copyfileobj(r, fh)
        except (OSError, urllib.error.URLError) as e:
            raise LocalModelError(f"download failed: {e}") from e
        try:
            with tarfile.open(archive) as tar:
                # Refuse absolute paths and traversal: an archive is untrusted input
                # even from a trusted host, and this unpacks into the home folder.
                for member in tar.getmembers():
                    name = Path(member.name)
                    if name.is_absolute() or ".." in name.parts:
                        raise LocalModelError(f"archive contains an unsafe path: {member.name}")
                tar.extractall(INSTALL_ROOT, filter="data")
        except (tarfile.TarError, OSError) as e:
            raise LocalModelError(f"unpack failed: {e}") from e

    exe = _binary()
    if not exe:
        raise LocalModelError(f"install finished but no binary at {plan['target']}")
    return {"performed": True, "binary": exe, "version": _version(exe), "plan": plan}


def serve() -> dict:
    """Start the model server if it is installed but not answering."""
    exe = _binary()
    if not exe:
        raise LocalModelError("Ollama is not installed yet")
    if server_running():
        return {"started": False, "reason": "already running"}
    # Detached: it must outlive this request. Output goes nowhere on purpose —
    # the server is chatty and its log is not this app's to own.
    subprocess.Popen(
        [exe, "serve"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    import time

    for _ in range(20):  # up to ~10s for the socket to come up
        time.sleep(0.5)
        if server_running():
            return {"started": True}
    return {"started": False, "reason": "the server did not answer within 10 seconds"}


_TAG_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,64}(:[a-z0-9._-]{1,32})?$", re.I)


def pull(tag: str, confirm: bool = False) -> dict:
    """Download a model. Multi-gigabyte, so it runs detached and confirm is required.

    The tag is validated against a strict pattern AND must appear in the catalogue:
    it reaches a subprocess, and 'a name from the UI' is not a reason to trust it.
    """
    if not _TAG_RE.match(tag or ""):
        raise LocalModelError(f"not a valid model name: {tag!r}")
    if tag not in {c.tag for c in CATALOGUE}:
        raise LocalModelError(f"{tag} is not in the recommended catalogue — pull it with the ollama CLI if you want it")
    if not confirm:
        entry = next(c for c in CATALOGUE if c.tag == tag)
        return {
            "started": False,
            "reason": "confirm=true is required",
            "download_gb": entry.download_gb,
            "needs_gb": entry.needs_gb,
        }
    exe = _binary()
    if not exe:
        raise LocalModelError("Ollama is not installed yet")
    if not server_running():
        serve()
    proc = subprocess.Popen(
        [exe, "pull", tag],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    return {"started": True, "tag": tag, "pid": proc.pid}


def overview(top_slash: list | None = None, top_projects: list | None = None) -> dict:
    """Everything the settings panel needs in one call."""
    st = state()
    kind = infer_work_kind(top_slash or [], top_projects or [])
    recs = recommend(kind, Capacity(**st["capacity"]), [m["name"] for m in st["models"]])
    return {
        "state": st,
        "recommendations": recs,
        "install_plan": install_plan(),
        "next_step": _next_step(st, recs),
    }


def _next_step(st: dict, recs: dict) -> dict:
    """One instruction at a time, in plain words. A settings page that shows six
    possible actions at once is how people conclude this is not for them."""
    if not st["installed"]:
        return {
            "action": "install",
            "headline": "Set up local models",
            "detail": "Nothing is installed yet. This downloads Ollama into your home folder — no admin rights, "
            "and nothing leaves your machine once it is running.",
        }
    if not st["server_running"]:
        return {
            "action": "serve",
            "headline": "Start the local model server",
            "detail": "Ollama is installed but not answering. Starting it takes a second and needs nothing from you.",
        }
    if not st["models"]:
        start = recs.get("start_with")
        return {
            "action": "pull",
            "headline": f"Download your first model{f': {start["label"]}' if start else ''}",
            "detail": (
                f"{start['good_for']} About {start['download_gb']:g} GB to download, once."
                if start
                else "No model in the catalogue fits this machine comfortably."
            ),
            "tag": start["tag"] if start else None,
        }
    return {
        "action": "ready",
        "headline": "Local models are ready",
        "detail": f"{len(st['models'])} model{'s' if len(st['models']) != 1 else ''} installed. "
        "Pick one as your local helper in Build Live, or add another below.",
    }
