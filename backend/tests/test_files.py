import subprocess

import pytest

from app.readers.files import FilesError, list_dir, read_file


@pytest.fixture
def projects(tmp_path):
    proj = tmp_path / "projects"
    repo = proj / "demo"
    (repo / "src").mkdir(parents=True)
    subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True)
    (repo / "README.md").write_text("hello")
    (repo / "src" / "app.py").write_text("print('x')\n")
    (repo / "node_modules").mkdir()
    (repo / "blob.bin").write_bytes(b"\x00\x01\x02")
    return proj


def test_list_skips_heavy_dirs_and_sorts(projects):
    entries = list_dir(projects, "demo")
    names = [e["name"] for e in entries]
    assert "node_modules" not in names and ".git" not in names
    assert names.index("src") < names.index("README.md")  # dirs first


def test_read_file_and_binary_guard(projects):
    out = read_file(projects, "demo", "src/app.py")
    assert out["content"].startswith("print")
    with pytest.raises(FilesError, match="binary"):
        read_file(projects, "demo", "blob.bin")


def test_path_escapes_rejected(projects):
    for bad in ("../", "../../etc/passwd", "src/../../demo2"):
        with pytest.raises(FilesError):
            list_dir(projects, "demo", bad)
    # normalizing back inside the project is safe and allowed
    assert read_file(projects, "demo", "src/../README.md")["content"] == "hello"
    with pytest.raises(FilesError):
        read_file(projects, "demo", "../outside.txt")
    with pytest.raises(FilesError):
        list_dir(projects, "nope", "")


def test_project_segment_cannot_escape(projects, tmp_path):
    # tmp_path's parent isn't a git repo, so make the escape target one —
    # mirrors the real box where ~ itself is a git repo.
    subprocess.run(["git", "-C", str(tmp_path), "init", "-q"], check=True)
    (tmp_path / "loot.txt").write_text("secret")
    for bad in ("..", ".", "", "../", "..\\", "a/b", "../demo", "demo/.."):
        with pytest.raises(FilesError):
            list_dir(projects, bad)
    with pytest.raises(FilesError):
        read_file(projects, "..", "loot.txt")
