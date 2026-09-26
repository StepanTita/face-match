"""Loads user-specific archive locations from a local, gitignored config file
(sources.local.json) in the current project directory, so no personal paths
ever need to live in tracked code. See sources.example.json for the expected
shape."""
from __future__ import annotations

import json

from .paths import project_dir


def load_sources_config() -> dict:
    path = project_dir() / "sources.local.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text())


def get_default_sources() -> list[str]:
    return load_sources_config().get("sources", [])


def get_drive_root() -> str | None:
    return load_sources_config().get("drive_root")
