"""What machine is this, and which AI environments are on it.

Two questions that turn out to be one. noirdeck assumes a single home directory
holding a single set of assistant configuration, and on WSL that assumption is
simply wrong: the operator has a Linux home AND a Windows profile, each with its
own `.claude`, its own `.codex`, its own history. Reading only one of them
reports half an estate and calls it the whole thing.

So this module answers both:

  detect_platform()        native Linux, macOS, or WSL, and if WSL then which
                           version, which distro, and where the Windows profile is
  scan_ai_environments()   every assistant runtime it can find, on both sides,
                           by binary and by configuration directory

Two rules it follows, because both were nearly broken while writing it:

⛔ It never walks a filesystem. `/mnt/c` is a 9p mount and a walk over it is
   slow enough to hang a request. Every path here is a direct stat of a
   candidate, and the candidate list is finite.

⛔ It never executes anything it finds. Reporting that a binary exists is a
   read; running an unknown binary to ask its version is not, and "scan the
   machine for AI tools" is not a licence to execute whatever turns up.
"""

from __future__ import annotations

import os
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path

# Every stat against /mnt/c crosses a 9p mount, and a full scan measured 937ms on
# a real machine: too slow to sit in a request that renders a screen. The answer
# changes when someone installs a tool, so a short cache costs nothing and
# removes the cost entirely.
_CACHE_TTL_SEC = 120
_cache: tuple[float, dict] | None = None

# Windows ships template profiles that look exactly like real ones, AppData and
# all. They never hold anybody's assistant configuration, and listing them makes
# a real finding harder to see.
_TEMPLATE_PROFILES = {"default", "default user", "public", "all users", "defaultuser0"}

# Runtimes worth looking for, by the name they install as and the directory they
# keep state in. A runtime is reported when EITHER is found: a binary with no
# config is an install nobody has used, and a config with no binary is an
# environment that exists on the other side of a WSL boundary, which is exactly
# the case this module was written for.
#
# `drivable` marks the ones noirdeck can actually run a session with (see
# ai_runtime.RUNNERS). The rest are reported so the picture is honest, and are
# not offered as somewhere to send work.


@dataclass(frozen=True)
class AiTool:
    id: str
    label: str
    bins: tuple[str, ...] = ()
    config_dirs: tuple[str, ...] = ()
    drivable: bool = False


CATALOGUE: tuple[AiTool, ...] = (
    AiTool("claude", "Claude Code", ("claude",), (".claude",), drivable=True),
    AiTool("codex", "Codex CLI", ("codex",), (".codex",), drivable=True),
    AiTool("ollama", "Ollama", ("ollama",), (".ollama",), drivable=True),
    AiTool("grok", "Grok CLI", ("grok",), (".grok",), drivable=True),
    AiTool("gemini", "Gemini CLI", ("gemini",), (".gemini",)),
    AiTool("cursor", "Cursor", ("cursor", "cursor-agent"), (".cursor",)),
    AiTool("aider", "Aider", ("aider",), (".aider", ".aider.conf.yml")),
    AiTool("goose", "Goose", ("goose",), (".goose", ".config/goose")),
    AiTool("opencode", "opencode", ("opencode",), (".opencode", ".config/opencode")),
    AiTool("amp", "Amp", ("amp",), (".amp",)),
    AiTool("llm", "llm", ("llm",), (".config/io.datasette.llm",)),
    AiTool("qwen", "Qwen Code", ("qwen",), (".qwen",)),
    AiTool("crush", "Crush", ("crush",), (".config/crush",)),
    AiTool("copilot", "GitHub Copilot CLI", ("copilot",), (".config/github-copilot",)),
    AiTool("continue", "Continue", (), (".continue",)),
    AiTool("windsurf", "Windsurf", ("windsurf",), (".codeium", ".windsurf")),
)


@dataclass
class Found:
    id: str
    label: str
    host: str  # "linux" | "windows"
    drivable: bool
    bin_path: str | None = None
    config_paths: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "label": self.label,
            "host": self.host,
            "drivable": self.drivable,
            "bin": self.bin_path,
            # A binary on PATH that resolves under the interop mount is a Windows
            # program, not a Linux one. It runs, slowly, and it does not share the
            # Linux home, so calling it a local install would be misleading.
            "via_interop": bool(self.bin_path and self.bin_path.startswith("/mnt/")),
            "config": self.config_paths,
            # What the evidence actually was. "config only" is the interesting
            # case: an environment that exists but cannot be run from here.
            "evidence": "binary+config"
            if self.bin_path and self.config_paths
            else ("binary" if self.bin_path else "config"),
        }


def _osrelease() -> str:
    try:
        return Path("/proc/sys/kernel/osrelease").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


WINDOWS_USERS = Path("/mnt/c/Users")


def _windows_profiles(root: Path | None = None, limit: int = 12) -> list[Path]:
    """Windows user profiles reachable through the interop mount.

    /mnt/c/Users holds more than user profiles: installer logs and stray files
    live there too. A real profile has an AppData directory, so that is the test
    rather than "is a directory", which on this machine matches a dozen files
    that are not profiles at all.
    """
    users = root or WINDOWS_USERS
    try:
        entries = sorted(users.iterdir())
    except OSError:
        return []
    out: list[Path] = []
    for entry in entries:
        if len(out) >= limit:
            break
        try:
            if entry.name.lower() in _TEMPLATE_PROFILES:
                continue
            if entry.is_dir() and (entry / "AppData").is_dir():
                out.append(entry)
        except OSError:
            # A profile we cannot stat is one we cannot read either.
            continue
    return out


def _distro_name() -> str | None:
    """The distribution, from the environment if it is there and the system if not.

    WSL_DISTRO_NAME is the obvious source and is absent exactly where this
    matters: a systemd user unit gets a minimal environment, so noirdeck running
    as a service reported no distro while the same code in a shell reported one.
    /etc/os-release is always present and is the better answer anyway.
    """
    name = os.environ.get("WSL_DISTRO_NAME")
    if name:
        return name
    try:
        fields = dict(
            line.split("=", 1)
            for line in Path("/etc/os-release").read_text(encoding="utf-8").splitlines()
            if "=" in line
        )
    except OSError:
        return None
    pretty = (fields.get("PRETTY_NAME") or fields.get("NAME") or "").strip().strip('"')
    return pretty or None


def _interop_available() -> bool:
    """Whether Windows programs can actually be launched from here.

    WSL_INTEROP is per-session and does not survive into a service, so relying on
    it alone reported interop as unavailable on a machine where it plainly works.
    The binfmt registration is what actually makes a .exe runnable, and /run/WSL
    is present whenever the interop server is.
    """
    if os.environ.get("WSL_INTEROP"):
        return True
    binfmt = Path("/proc/sys/fs/binfmt_misc")
    if (binfmt / "WSLInterop").exists() or (binfmt / "WSLInterop-late").exists():
        return True
    return Path("/run/WSL").is_dir()


def detect_platform() -> dict:
    """Which machine this is, and on WSL, where the other half of it lives."""
    osrel = _osrelease()
    lowered = osrel.lower()
    is_wsl = "microsoft" in lowered or "wsl" in lowered or bool(os.environ.get("WSL_DISTRO_NAME"))

    info: dict = {
        "kind": "wsl" if is_wsl else ("macos" if os.uname().sysname == "Darwin" else "linux"),
        "kernel": osrel.strip(),
    }
    if not is_wsl:
        return info

    info["wsl"] = {
        # WSL1 shares the Windows kernel and reports differently; the string is
        # the only reliable way to tell them apart from inside.
        "version": 2 if "wsl2" in lowered else 1,
        "distro": _distro_name(),
        "interop": _interop_available(),
        "windows_mount": "/mnt/c" if Path("/mnt/c").is_dir() else None,
        "windows_profiles": [str(p) for p in _windows_profiles()],
    }
    return info


def _scan_home(home: Path, host: str) -> list[Found]:
    found: list[Found] = []
    for tool in CATALOGUE:
        configs = []
        for rel in tool.config_dirs:
            candidate = home / rel
            try:
                if candidate.exists():
                    configs.append(str(candidate))
            except OSError:
                continue
        # PATH lookup only describes the machine noirdeck is running on. A
        # Windows profile is evidence of an environment, not of a runnable one.
        binary = None
        if host == "linux":
            for name in tool.bins:
                binary = shutil.which(name)
                if binary:
                    break
        if binary or configs:
            found.append(
                Found(
                    id=tool.id,
                    label=tool.label,
                    host=host,
                    drivable=tool.drivable and host == "linux" and bool(binary),
                    bin_path=binary,
                    config_paths=configs,
                )
            )
    return found


def scan_ai_environments(home: Path | None = None, refresh: bool = False) -> dict:
    """Every assistant environment this machine can see, on either side.

    Bounded by construction: a finite list of direct stats, no walk, and nothing
    is executed. Cached briefly because the Windows half is not cheap.
    """
    global _cache
    if home is None and not refresh and _cache and (time.monotonic() - _cache[0]) < _CACHE_TTL_SEC:
        return _cache[1]

    platform = detect_platform()
    here = home or Path.home()
    results = _scan_home(here, "linux")

    windows: list[Found] = []
    for profile in platform.get("wsl", {}).get("windows_profiles", []):
        windows.extend(_scan_home(Path(profile), "windows"))
    results.extend(windows)

    drivable = [f for f in results if f.drivable]
    out = {
        "platform": platform,
        "tools": [f.as_dict() for f in results],
        "counts": {
            "total": len(results),
            "drivable": len(drivable),
            "linux": sum(1 for f in results if f.host == "linux"),
            "windows": len(windows),
        },
        # The finding worth surfacing rather than burying in a list: assistant
        # configuration on the Windows side that noirdeck is not reading.
        "unread_windows_environments": sorted({f.label for f in windows if f.config_paths}),
    }
    if home is None:
        _cache = (time.monotonic(), out)
    return out
