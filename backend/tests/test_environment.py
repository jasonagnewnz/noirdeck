"""Platform and AI-environment detection.

The interesting case throughout is WSL, where the operator has two homes and
noirdeck reads one. Every test builds its own fake home rather than looking at
the machine running the suite: a test that passes only on the developer's laptop
is not a test.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from noirdeck import environment


@pytest.fixture(autouse=True)
def _no_cache():
    """The cache is a performance feature and a correctness hazard in tests."""
    environment._cache = None
    yield
    environment._cache = None


def _home(tmp_path: Path, *relative: str) -> Path:
    home = tmp_path / "home"
    for rel in relative:
        (home / rel).mkdir(parents=True, exist_ok=True)
    home.mkdir(parents=True, exist_ok=True)
    return home


class TestPlatform:
    def test_reports_wsl_version_and_distro(self, monkeypatch):
        monkeypatch.setattr(environment, "_osrelease", lambda: "6.18.33.2-microsoft-standard-WSL2\n")
        monkeypatch.setenv("WSL_DISTRO_NAME", "Ubuntu-24.04")
        monkeypatch.setenv("WSL_INTEROP", "/run/WSL/1_interop")
        info = environment.detect_platform()
        assert info["kind"] == "wsl"
        assert info["wsl"]["version"] == 2
        assert info["wsl"]["distro"] == "Ubuntu-24.04"
        assert info["wsl"]["interop"] is True

    def test_tells_wsl1_from_wsl2(self, monkeypatch):
        # WSL1 does not carry "WSL2" in the kernel string, and the difference
        # matters: it has no separate kernel and different filesystem behaviour.
        monkeypatch.setattr(environment, "_osrelease", lambda: "4.4.0-19041-Microsoft\n")
        monkeypatch.delenv("WSL_DISTRO_NAME", raising=False)
        info = environment.detect_platform()
        assert info["kind"] == "wsl"
        assert info["wsl"]["version"] == 1

    def test_plain_linux_has_no_windows_half(self, monkeypatch):
        monkeypatch.setattr(environment, "_osrelease", lambda: "6.8.0-generic\n")
        monkeypatch.delenv("WSL_DISTRO_NAME", raising=False)
        info = environment.detect_platform()
        assert info["kind"] == "linux"
        assert "wsl" not in info

    def test_env_var_alone_is_enough(self, monkeypatch):
        # A kernel string can be rebuilt; the distro variable is set by WSL itself.
        monkeypatch.setattr(environment, "_osrelease", lambda: "6.8.0-custom\n")
        monkeypatch.setenv("WSL_DISTRO_NAME", "Debian")
        assert environment.detect_platform()["kind"] == "wsl"

    def test_distro_survives_a_service_environment(self, monkeypatch, tmp_path):
        """A systemd user unit gets no WSL_DISTRO_NAME. It still has to answer."""
        monkeypatch.delenv("WSL_DISTRO_NAME", raising=False)
        release = tmp_path / "os-release"
        release.write_text('NAME="Ubuntu"\nPRETTY_NAME="Ubuntu 24.04.3 LTS"\n', encoding="utf-8")
        real = environment.Path

        def fake(arg):
            return release if str(arg) == "/etc/os-release" else real(arg)

        monkeypatch.setattr(environment, "Path", fake)
        assert environment._distro_name() == "Ubuntu 24.04.3 LTS"

    def test_the_env_var_still_wins_when_present(self, monkeypatch):
        monkeypatch.setenv("WSL_DISTRO_NAME", "Debian")
        assert environment._distro_name() == "Debian"

    def test_interop_is_detected_without_the_session_variable(self, monkeypatch, tmp_path):
        """WSL_INTEROP is per-session; the binfmt registration is what makes it work."""
        monkeypatch.delenv("WSL_INTEROP", raising=False)
        binfmt = tmp_path / "binfmt_misc"
        binfmt.mkdir()
        (binfmt / "WSLInterop").write_text("enabled", encoding="utf-8")
        real = environment.Path

        def fake(arg):
            return binfmt if str(arg) == "/proc/sys/fs/binfmt_misc" else real(arg)

        monkeypatch.setattr(environment, "Path", fake)
        assert environment._interop_available() is True


class TestWindowsProfiles:
    def test_skips_template_profiles_and_stray_files(self, tmp_path):
        users = tmp_path / "Users"
        for name in ("AlexMorgan", "Default", "Default User", "Public"):
            (users / name / "AppData").mkdir(parents=True)
        # /mnt/c/Users really does contain loose files, and directories with no
        # AppData. Both were matched before this was filtered.
        (users / "AgentInstall.txt").write_text("log", encoding="utf-8")
        (users / "not-a-profile").mkdir()

        assert [d.name for d in environment._windows_profiles(root=users)] == ["AlexMorgan"]

    def test_a_missing_users_directory_is_empty_not_an_error(self, tmp_path):
        assert environment._windows_profiles(root=tmp_path / "absent") == []

    def test_the_limit_holds(self, tmp_path):
        users = tmp_path / "Users"
        for i in range(6):
            (users / f"user{i}" / "AppData").mkdir(parents=True)
        assert len(environment._windows_profiles(root=users, limit=3)) == 3


class TestScan:
    def test_finds_a_config_only_environment(self, tmp_path, monkeypatch):
        """The case the module exists for: configuration with no local binary."""
        home = _home(tmp_path, ".claude", ".codex")
        monkeypatch.setattr(environment.shutil, "which", lambda _name: None)
        found = environment._scan_home(home, "windows")
        by_id = {f.id: f for f in found}
        assert set(by_id) == {"claude", "codex"}
        assert by_id["claude"].as_dict()["evidence"] == "config"
        # Nothing on the Windows side is runnable from here, whatever it is.
        assert by_id["claude"].drivable is False

    def test_a_binary_with_no_config_still_counts(self, tmp_path, monkeypatch):
        home = _home(tmp_path)
        monkeypatch.setattr(environment.shutil, "which", lambda name: "/usr/bin/aider" if name == "aider" else None)
        found = {f.id: f for f in environment._scan_home(home, "linux")}
        assert found["aider"].as_dict()["evidence"] == "binary"

    def test_only_known_runtimes_are_offered_as_drivable(self, tmp_path, monkeypatch):
        home = _home(tmp_path, ".claude", ".aider")
        monkeypatch.setattr(environment.shutil, "which", lambda name: f"/usr/bin/{name}")
        found = {f.id: f for f in environment._scan_home(home, "linux")}
        # Both are present; only the one noirdeck can actually spawn is drivable.
        assert found["claude"].drivable is True
        assert found["aider"].drivable is False

    def test_a_windows_binary_on_path_is_labelled_as_interop(self, tmp_path, monkeypatch):
        home = _home(tmp_path)
        monkeypatch.setattr(
            environment.shutil,
            "which",
            lambda name: "/mnt/c/Users/x/AppData/Local/cursor.exe" if name == "cursor" else None,
        )
        found = {f.id: f for f in environment._scan_home(home, "linux")}
        assert found["cursor"].as_dict()["via_interop"] is True

    def test_an_unreadable_home_is_not_an_error(self, tmp_path, monkeypatch):
        """A profile that cannot be statted is reported as absent, not fatal."""
        monkeypatch.setattr(environment.shutil, "which", lambda _name: None)
        assert environment._scan_home(tmp_path / "nope", "windows") == []

    def test_scan_reports_the_unread_windows_half(self, tmp_path, monkeypatch):
        linux_home = _home(tmp_path / "linux", ".claude")
        win_home = _home(tmp_path / "win", ".claude", ".codex")
        monkeypatch.setattr(
            environment,
            "detect_platform",
            lambda: {
                "kind": "wsl",
                "kernel": "test",
                "wsl": {
                    "version": 2,
                    "distro": "Ubuntu",
                    "interop": True,
                    "windows_mount": "/mnt/c",
                    "windows_profiles": [str(win_home)],
                },
            },
        )
        monkeypatch.setattr(environment.shutil, "which", lambda name: f"/usr/bin/{name}")
        out = environment.scan_ai_environments(home=linux_home)
        assert out["counts"]["windows"] == 2
        assert out["unread_windows_environments"] == ["Claude Code", "Codex CLI"]

    def test_nothing_found_is_a_real_answer(self, tmp_path, monkeypatch):
        """Empty must mean "looked and found none", never "did not look"."""
        monkeypatch.setattr(environment, "detect_platform", lambda: {"kind": "linux", "kernel": "x"})
        monkeypatch.setattr(environment.shutil, "which", lambda _name: None)
        out = environment.scan_ai_environments(home=_home(tmp_path))
        assert out["tools"] == []
        assert out["counts"] == {"total": 0, "drivable": 0, "linux": 0, "windows": 0}
        assert out["platform"]["kind"] == "linux"


class TestCache:
    def test_an_explicit_home_is_never_cached(self, tmp_path, monkeypatch):
        """Cache the machine, not an argument: a caller passing a home wants that home."""
        monkeypatch.setattr(environment, "detect_platform", lambda: {"kind": "linux", "kernel": "x"})
        monkeypatch.setattr(environment.shutil, "which", lambda _name: None)
        environment.scan_ai_environments(home=_home(tmp_path))
        assert environment._cache is None

    def test_refresh_bypasses_a_warm_cache(self, monkeypatch):
        calls = []
        monkeypatch.setattr(environment, "detect_platform", lambda: calls.append(1) or {"kind": "linux", "kernel": "x"})
        monkeypatch.setattr(environment.shutil, "which", lambda _name: None)
        environment.scan_ai_environments()
        environment.scan_ai_environments()
        assert len(calls) == 1, "second call should have been served from cache"
        environment.scan_ai_environments(refresh=True)
        assert len(calls) == 2
