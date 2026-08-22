"""pyproject.toml [project].version and noirdeck.version.VERSION are two spellings of
one fact: this pin keeps them from drifting apart."""

import re
from pathlib import Path

from noirdeck.version import VERSION


def test_pyproject_version_matches_app_version():
    pyproject = Path(__file__).resolve().parents[2] / "pyproject.toml"
    m = re.search(r'^version = "([^"]+)"$', pyproject.read_text(), re.M)
    assert m, "no version field in pyproject.toml"
    assert m.group(1) == VERSION
