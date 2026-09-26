"""Loads user-specific archive locations from a local, gitignored config file
(sources.local.json), so no personal paths ever need to live in tracked code.
See sources.example.json for the expected shape."""
from __future__ import annotations

import json
from pathlib import Path

CONFIG_PATH = Path(__file__).parent.parent.parent / "sources.local.json"


def load_sources_config() -> dict:
    if not CONFIG_PATH.exists():
        return {}
    return json.loads(CONFIG_PATH.read_text())


def get_default_sources() -> list[str]:
    return load_sources_config().get("sources", [])


def get_drive_root() -> str | None:
    return load_sources_config().get("drive_root")
