import pytest

from app.config import Settings
from app.preview import PreviewError, info, preview_root, resolve_file


@pytest.fixture
def settings(tmp_path, claude_dir):
    projects = tmp_path / "projects"
    web = projects / "webapp" / "dist"
    web.mkdir(parents=True)
    (web / "index.html").write_text("<h1>hi</h1>")
    (web / "app.css").write_text("body{}")
    (projects / "webapp" / "secret.txt").write_text("not under dist")
    cli = projects / "cliapp"
    cli.mkdir()
    (cli / "main.py").write_text("print('no web here')")
    (projects / "rootsite").mkdir()
    (projects / "rootsite" / "index.html").write_text("<p>root-level site</p>")
    return Settings(
        claude_dir=claude_dir,
        projects_dir=projects,
        db_path=tmp_path / "t.db",
        port=1,
        mining_armed=False,
        overnight_armed=False,
        mine_max_batches=1,
    )


def test_info_finds_dist_and_root_entry_points(settings):
    assert info(settings, "webapp") == {"available": True, "entry": "dist"}
    assert info(settings, "rootsite") == {"available": True, "entry": "."}
    assert info(settings, "cliapp") == {"available": False, "entry": None}


def test_resolve_serves_index_and_assets_with_types(settings):
    f, media = resolve_file(settings, "webapp", "")
    assert f.name == "index.html" and media == "text/html"
    f, media = resolve_file(settings, "webapp", "app.css")
    assert media == "text/css"


def test_no_web_entry_is_a_clear_error(settings):
    with pytest.raises(PreviewError, match="no web preview"):
        resolve_file(settings, "cliapp", "")


def test_traversal_and_project_escapes_refused(settings):
    for bad_project in ("..", ".", "", "a/b", "a\\b", "..%2F"):
        with pytest.raises(PreviewError):
            preview_root(settings, bad_project)
    for bad_path in ("../secret.txt", "a/../../secret.txt", "/etc/passwd", "\\x"):
        with pytest.raises(PreviewError):
            resolve_file(settings, "webapp", bad_path)
    # file exists but sits outside the preview root
    with pytest.raises(PreviewError):
        resolve_file(settings, "webapp", "secret.txt")


def test_size_cap(settings, monkeypatch):
    monkeypatch.setattr("app.preview._MAX_BYTES", 3)
    with pytest.raises(PreviewError, match="too large"):
        resolve_file(settings, "webapp", "index.html")
