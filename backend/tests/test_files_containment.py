"""What the file browser is allowed to reach.

`readers/files.py` backs GET /api/files and GET /api/file, which read from a
project on disk and hand the contents to the browser. Its containment was
correct when this was written, and it had no test, which is the state a
containment check is least likely to survive an edit in.

The rule it enforces, and the reason each half exists:

  * `project` must be a SINGLE path segment naming a direct child of the
    projects directory. The comment in the source names the specific trap: the
    home directory is itself a git repository, so a `..` that got through the
    segment check would satisfy the "is this a repo" test and expose the whole
    of $HOME.

  * `rel` is joined and then RESOLVED, and the resolved path must sit under the
    repository. Resolving before comparing is what defeats encoded dots and a
    symlink pointing outward; string matching on "../" does not.

Verified by attacking the live service before these were written: every payload
below was refused there too.
"""

from __future__ import annotations

import pytest

from noirdeck.readers.files import FilesError, list_dir, read_file


@pytest.fixture
def projects(tmp_path):
    """A projects dir with one real repo, a sibling repo, and a secret above both."""
    root = tmp_path / "projects"
    for name in ("alpha", "beta"):
        repo = root / name
        (repo / ".git").mkdir(parents=True)
        (repo / "README.md").write_text(f"# {name}\n", encoding="utf-8")
    (root / "alpha" / "src").mkdir()
    (root / "alpha" / "src" / "app.py").write_text("print('hi')\n", encoding="utf-8")
    # The thing an escape would be trying to reach.
    (tmp_path / "secret.txt").write_text("do-not-read\n", encoding="utf-8")
    # The home directory is a git repo too, which is the trap the source names.
    (tmp_path / ".git").mkdir()
    return root


def test_a_legitimate_read_still_works(projects):
    """A containment test that only proves refusal proves nothing."""
    assert any(e["name"] == "src" for e in list_dir(projects, "alpha"))
    assert "print" in read_file(projects, "alpha", "src/app.py")["content"]


@pytest.mark.parametrize(
    "rel",
    [
        "../../secret.txt",
        "../beta/README.md",  # a sibling repo is still outside this one
        "/etc/passwd",
        "src/../../../secret.txt",
        "src/../..",
        "./../../secret.txt",
    ],
)
def test_relative_paths_cannot_leave_the_repository(projects, rel):
    with pytest.raises(FilesError):
        read_file(projects, "alpha", rel)
    with pytest.raises(FilesError):
        list_dir(projects, "alpha", rel)


@pytest.mark.parametrize("project", ["..", ".", "", "../", "alpha/../beta", "../projects/alpha", "/etc"])
def test_project_must_be_one_segment_under_the_projects_dir(projects, project):
    """⛔ The specific trap: $HOME is itself a repo, so `..` would pass the .git
    check and hand back the whole home directory."""
    with pytest.raises(FilesError):
        list_dir(projects, project)


def test_a_symlink_pointing_outward_is_refused(projects, tmp_path):
    """String matching on '../' would miss this entirely.

    The path contains no dots at all: containment holds only because the path is
    resolved before it is compared.
    """
    (projects / "alpha" / "escape").symlink_to(tmp_path / "secret.txt")
    with pytest.raises(FilesError):
        read_file(projects, "alpha", "escape")


def test_a_directory_without_git_is_not_a_project(projects):
    (projects / "not-a-repo").mkdir()
    with pytest.raises(FilesError):
        list_dir(projects, "not-a-repo")
