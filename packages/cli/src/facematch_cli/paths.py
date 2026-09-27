"""Shared per-project output paths, all rooted at the current working
directory - i.e. the project directory the user runs `facematch` from.
This preserves today's behavior (facematch is run from the archive-scan
project's root, where matched/, checkpoint.sqlite3 etc. already live) while
working the same way for any new project directory a user starts in."""
from __future__ import annotations

from pathlib import Path


def project_dir() -> Path:
    return Path.cwd()


def matched_dir() -> Path:
    return project_dir() / "matched"


def thumbs_dir() -> Path:
    return matched_dir() / "video_thumbnails"


def duplicates_dir() -> Path:
    return matched_dir() / "duplicates"


def matches_csv() -> Path:
    return matched_dir() / "matches.csv"


def checkpoint_path() -> Path:
    return project_dir() / "checkpoint.sqlite3"


def scratch_root(subdir: str) -> Path:
    return project_dir() / "scratch" / subdir


def runs_root(command: str) -> Path:
    """Where a command's `--background` run state (meta.json, status.json,
    log.txt) lives, one subdirectory per run id. Namespaced by command
    (`find`, `group`, ...) so `facematch group status` can never pick up a
    more-recent `find` run's id, or vice versa."""
    return project_dir() / ".facematch" / "runs" / command


def run_dir(command: str, run_id: str) -> Path:
    return runs_root(command) / run_id


def latest_run_id(command: str) -> str | None:
    root = runs_root(command)
    if not root.exists():
        return None
    run_ids = sorted(p.name for p in root.iterdir() if p.is_dir())
    return run_ids[-1] if run_ids else None


def references_dir() -> Path:
    return project_dir() / "references"


def reference_embeddings_path() -> Path:
    return project_dir() / "reference_embeddings.npz"


def group_checkpoint_path() -> Path:
    return project_dir() / "group_checkpoint.sqlite3"


def default_grouped_dir() -> Path:
    return project_dir() / "grouped"
