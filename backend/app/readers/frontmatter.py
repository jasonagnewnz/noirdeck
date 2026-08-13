"""Minimal YAML frontmatter parsing for SKILL.md / agent / memory files."""
from __future__ import annotations

from pathlib import Path

import yaml


def parse_frontmatter(path: Path, max_bytes: int = 16384) -> tuple[dict, str]:
    """Return (frontmatter dict, first bit of body). Never raises on bad files."""
    try:
        text = path.read_text(errors="replace")[:max_bytes]
    except OSError:
        return {}, ""
    if not text.startswith("---"):
        return {}, text
    parts = text.split("\n---", 2)
    if len(parts) < 2:
        return {}, text
    raw = parts[0].lstrip("-\n")
    body = parts[1] if len(parts) > 1 else ""
    try:
        data = yaml.safe_load(raw)
        if not isinstance(data, dict):
            data = {}
    except yaml.YAMLError:
        data = {}
    return data, body.strip()
