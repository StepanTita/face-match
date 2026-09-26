"""`facematch backfill-videos` - copy full video files for old matches that only saved a thumbnail.

Older matches.csv rows may have been recorded back when only a thumbnail was
saved for video matches (the worker now also copies the full video for
anything matched going forward, but that only takes effect the next time
`facematch find`'s worker pool is (re)started; this command covers everything
matched before then).

No face detection or ffmpeg re-sampling needed - the match (and its
confidence score) is already confirmed in matches.csv; this just locates the
original source (loose file or zip entry) and copies the whole thing into
matched/, using the same collision-free naming convention as everything else.

Safe to run alongside a live `facematch find`: read-only w.r.t.
matches.csv/checkpoint, only ever writes NEW files into matched/ (skips any
source that already has a copy there), and opens zips independently (its own
ZipFile handles).
"""
from __future__ import annotations

import argparse
import csv
import os
import shutil
import sys
import zipfile
from pathlib import Path
from textwrap import dedent

from facematch_core.decode import VIDEO_EXTS
from facematch_core.worker import safe_dest_name

from . import paths
from .config import get_default_sources, get_drive_root


def _resolve_zip_path(display_prefix: str, drive_root: str, top_level_zip_by_basename: dict[str, str]) -> str | None:
    if display_prefix in top_level_zip_by_basename:
        return top_level_zip_by_basename[display_prefix]
    candidate = os.path.join(drive_root, display_prefix)
    if os.path.exists(candidate):
        return candidate
    return None


def _is_video_source(source: str) -> bool:
    entry = source.split("::", 1)[1] if "::" in source else source
    return Path(entry).suffix.lower() in VIDEO_EXTS


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.formatter_class = argparse.RawDescriptionHelpFormatter
    parser.description = "Copy full video files for old matches that only saved a thumbnail."
    parser.epilog = dedent("""\
        examples:
          facematch backfill-videos

        requires drive_root to be set in sources.local.json, so the original
        archive zips can be located. skips any match that already has a full
        video copy in matched/; safe to re-run.
        """)


def run(args: argparse.Namespace) -> None:
    matched_dir = paths.matched_dir()
    matches_csv_path = paths.matches_csv()
    drive_root = get_drive_root() or ""
    # Known top-level configured source zips get logged in matches.csv under
    # just their basename (see sources.enumerate_source: Path(root).name for
    # a zip passed directly as a source), not a path relative to the drive
    # root, so we need the same source list (from sources.local.json) to
    # resolve those specifically.
    top_level_zip_by_basename = {
        Path(s).name: s for s in get_default_sources() if s.lower().endswith(".zip")
    }

    if not matches_csv_path.exists():
        print("ERROR: matches.csv not found.")
        sys.exit(1)

    with open(matches_csv_path, newline="") as f:
        rows = [row for row in csv.DictReader(f) if row.get("status") == "matched"]

    video_rows = [r for r in rows if _is_video_source(r["source"])]
    print(f"Found {len(video_rows)} matched-video rows in matches.csv")

    copied, skipped_existing, failed = 0, 0, 0
    for row in video_rows:
        source = row["source"]
        dest_name = safe_dest_name(source)
        dest_path = matched_dir / dest_name

        if dest_path.exists() and dest_path.stat().st_size > 0:
            skipped_existing += 1
            continue

        try:
            if "::" in source:
                prefix, entry = source.split("::", 1)
                zip_path = _resolve_zip_path(prefix, drive_root, top_level_zip_by_basename)
                if zip_path is None:
                    raise FileNotFoundError(f"could not resolve zip for prefix {prefix!r}")
                with zipfile.ZipFile(zip_path) as zf, zf.open(entry) as src, open(dest_path, "wb") as dst:
                    shutil.copyfileobj(src, dst)
            else:
                if not os.path.exists(source):
                    raise FileNotFoundError(source)
                shutil.copy2(source, dest_path)
            size = dest_path.stat().st_size
            print(f"  [ok] {source} -> {dest_name} ({size/1e6:.1f} MB, confidence={row['score']})")
            copied += 1
        except Exception as e:
            print(f"  [FAILED] {source}: {e}")
            failed += 1

    print(f"\nCopied {copied}, already present (skipped) {skipped_existing}, failed {failed}")
