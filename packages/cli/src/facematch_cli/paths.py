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


def runs_root() -> Path:
    """Where `--background` run state (meta.json, status.json, log.txt) lives,
    one subdirectory per run id."""
    return project_dir() / ".facematch" / "runs"


def run_dir(run_id: str) -> Path:
    return runs_root() / run_id


def latest_run_id() -> str | None:
    root = runs_root()
    if not root.exists():
        return None
    run_ids = sorted(p.name for p in root.iterdir() if p.is_dir())
    return run_ids[-1] if run_ids else None


def references_dir() -> Path:
    return project_dir() / "references"


def reference_embeddings_path() -> Path:
    return project_dir() / "reference_embeddings.npz"


def dedupe_state_path() -> Path:
    return project_dir() / "dedupe_state.json"


def dedupe_report_path() -> Path:
    return project_dir() / "dedupe_report.csv"
