"""One-off backfill: copy full video files for matches.csv rows that were
recorded back when only a thumbnail was saved for video matches (see
worker.py's _process_video - it now also copies the full video for anything
matched going forward, but that only takes effect the next time scan.py's
worker pool is (re)started; this script covers everything matched before then).

No face detection or ffmpeg re-sampling needed - the match (and its
confidence score) is already confirmed in matches.csv; this just locates the
original source (loose file or zip entry) and copies the whole thing into
matched/, using the same collision-free naming convention as everything else.

Safe to run alongside the live scan: read-only w.r.t. matches.csv/checkpoint,
only ever writes NEW files into matched/ (skips any source that already has
a copy there), and opens zips independently (its own ZipFile handles).

Usage:
    uv run backfill_videos.py
"""
from __future__ import annotations

import csv
import os
import shutil
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))
from facematch.config import get_default_sources, get_drive_root  # noqa: E402
from facematch.core import VIDEO_EXTS  # noqa: E402
from facematch.worker import _safe_dest_name  # noqa: E402

PROJECT_DIR = Path(__file__).parent
MATCHED_DIR = PROJECT_DIR / "matched"
MATCHES_CSV = MATCHED_DIR / "matches.csv"
DRIVE_ROOT = get_drive_root() or ""

# Known top-level configured source zips get logged in matches.csv under just
# their basename (see sources.enumerate_source: Path(root).name for a zip
# passed directly as a source), not a path relative to the drive root, so we
# need the same source list (from sources.local.json) to resolve those
# specifically.
_TOP_LEVEL_ZIP_BY_BASENAME = {
    Path(s).name: s for s in get_default_sources() if s.lower().endswith(".zip")
}


def resolve_zip_path(display_prefix: str) -> str | None:
    if display_prefix in _TOP_LEVEL_ZIP_BY_BASENAME:
        return _TOP_LEVEL_ZIP_BY_BASENAME[display_prefix]
    candidate = os.path.join(DRIVE_ROOT, display_prefix)
    if os.path.exists(candidate):
        return candidate
    return None


def is_video_source(source: str) -> bool:
    entry = source.split("::", 1)[1] if "::" in source else source
    return Path(entry).suffix.lower() in VIDEO_EXTS


def main():
    if not MATCHES_CSV.exists():
        print("ERROR: matches.csv not found.")
        sys.exit(1)

    with open(MATCHES_CSV, newline="") as f:
        rows = [row for row in csv.DictReader(f) if row.get("status") == "matched"]

    video_rows = [r for r in rows if is_video_source(r["source"])]
    print(f"Found {len(video_rows)} matched-video rows in matches.csv")

    copied, skipped_existing, failed = 0, 0, 0
    for row in video_rows:
        source = row["source"]
        dest_name = _safe_dest_name(source)
        dest_path = MATCHED_DIR / dest_name

        if dest_path.exists() and dest_path.stat().st_size > 0:
            skipped_existing += 1
            continue

        try:
            if "::" in source:
                prefix, entry = source.split("::", 1)
                zip_path = resolve_zip_path(prefix)
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


if __name__ == "__main__":
    main()
