"""Enumeration of candidate image/video files from directories and zip archives,
with streaming (one-entry-at-a-time) extraction for zips - never unzip whole archives."""
from __future__ import annotations

import os
import zipfile
from dataclasses import dataclass
from pathlib import Path

from .decode import IMAGE_EXTS, VIDEO_EXTS

# Out-of-scope folder names, matched case-insensitively as a substring of any
# path component. NOTE: "takeout" is deliberately NOT in this set. It only
# belongs in the LOOSE-filesystem variant below: Google's Takeout export
# format always nests real content one level under a top-level "Takeout/"
# folder *inside each zip* (e.g. "Takeout/Google Fotky/Photos from 2018/..."),
# so applying a "takeout" substring skip to zip-internal paths as well
# silently discarded every single entry of every takeout-*.zip - the largest
# source in this archive. The loose extracted Takeout/ folder alongside the
# zips is excluded separately, only when walking real directories.
SKIP_DIR_SUBSTRINGS = {
    "lightroom", "gopro videos", "vlogs", "adobe cc", "touchpoint podcast",
}
SKIP_DIR_SUBSTRINGS_LOOSE = SKIP_DIR_SUBSTRINGS | {"takeout"}


def _is_skipped_path(path_parts: list[str], skip_set: set[str] = SKIP_DIR_SUBSTRINGS) -> bool:
    for part in path_parts:
        low = part.lower()
        if any(skip in low for skip in skip_set):
            return True
    return False


# Per-process cache of open ZipFile handles, keyed by path. Re-opening a zip
# (which re-parses its central directory) for every single entry was the
# dominant cost once many worker processes hit the same archive concurrently
# from an external drive - keeping one handle open per (worker process, zip)
# for the life of the run avoids that entirely. Bounded by the number of
# distinct zips touched by a given worker (a couple dozen at most here), so
# the open file handles are cheap to keep around.
_ZIP_HANDLE_CACHE: dict[str, zipfile.ZipFile] = {}


def _get_cached_zip(zip_path: str) -> zipfile.ZipFile:
    zf = _ZIP_HANDLE_CACHE.get(zip_path)
    if zf is None:
        zf = zipfile.ZipFile(zip_path)
        _ZIP_HANDLE_CACHE[zip_path] = zf
    return zf


@dataclass
class Candidate:
    display_name: str  # human-readable path for logging / progress / dedupe prefixing
    ext: str
    kind: str  # "image" | "video"
    key: str  # stable content-derived id used for checkpointing (see checkpoint.py)
    # exactly one of the following is set:
    loose_path: str | None = None
    zip_path: str | None = None
    zip_entry: str | None = None

    def extract_to(self, scratch_dir: str) -> str:
        """Return a real filesystem path to the file, extracting from zip if needed.
        Caller must delete the returned path if it lives under scratch_dir."""
        if self.loose_path:
            return self.loose_path
        os.makedirs(scratch_dir, exist_ok=True)
        safe_name = Path(self.zip_entry).name
        out_path = os.path.join(scratch_dir, safe_name)
        zf = _get_cached_zip(self.zip_path)
        with zf.open(self.zip_entry) as src, open(out_path, "wb") as dst:
            dst.write(src.read())
        return out_path


def _classify_ext(name: str) -> tuple[str, str] | None:
    ext = Path(name).suffix.lower()
    if ext in IMAGE_EXTS:
        return ext, "image"
    if ext in VIDEO_EXTS:
        return ext, "video"
    return None


def walk_zip(zip_path: str, display_prefix: str, scratch_dir: str):
    """Yield Candidates for entries inside a zip, recursing into nested zips
    (extracting nested zips to scratch one at a time, then deleting them)."""
    try:
        zf = zipfile.ZipFile(zip_path)
    except (zipfile.BadZipFile, OSError) as e:
        print(f"  [error] cannot open zip {zip_path}: {e}")
        return
    with zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            parts = Path(info.filename).parts
            if _is_skipped_path(parts):
                continue
            ext = Path(info.filename).suffix.lower()
            display = f"{display_prefix}::{info.filename}"
            if ext == ".zip":
                # Nested zip (zip-within-zip): not expected for this archive
                # (all target zips are flat), but handled defensively. We
                # extract it once to a stable scratch path and deliberately
                # do NOT delete it here - its entries are handed out lazily
                # to worker processes that may extract_to() from it at any
                # later time, so deleting on this generator's exit would race
                # with in-flight workers. It's cleaned up as ordinary scratch
                # data, not per-entry.
                os.makedirs(scratch_dir, exist_ok=True)
                nested_local = os.path.join(scratch_dir, f"_nested_{info.CRC:08x}_{Path(info.filename).name}")
                if not os.path.exists(nested_local):
                    try:
                        with zf.open(info) as src, open(nested_local, "wb") as dst:
                            dst.write(src.read())
                    except (zipfile.BadZipFile, OSError) as e:
                        print(f"  [error] nested zip {display}: {e}")
                        continue
                yield from walk_zip(nested_local, display, scratch_dir)
                continue
            classified = _classify_ext(info.filename)
            if classified is None:
                continue
            _, kind = classified
            key = f"zip::{zip_path}::{info.filename}::{info.file_size}::{info.CRC}"
            yield Candidate(
                display_name=display,
                ext=ext,
                kind=kind,
                key=key,
                zip_path=zip_path,
                zip_entry=info.filename,
            )


def walk_directory(root: str):
    """Yield Candidates for loose image/video files under a directory tree,
    recursing into any .zip files found along the way."""
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not _is_skipped_path([d], SKIP_DIR_SUBSTRINGS_LOOSE)]
        for fname in filenames:
            if fname.startswith("."):
                continue
            full = os.path.join(dirpath, fname)
            ext = Path(fname).suffix.lower()
            if ext == ".zip":
                yield ("zip", full)
                continue
            classified = _classify_ext(fname)
            if classified is None:
                continue
            _, kind = classified
            try:
                st = os.stat(full)
                key = f"file::{full}::{st.st_size}::{int(st.st_mtime)}"
            except OSError:
                key = f"file::{full}"
            yield ("candidate", Candidate(display_name=full, ext=ext, kind=kind, key=key, loose_path=full))


def enumerate_source(root: str, scratch_dir: str):
    """Top-level entry point: root can be a directory or a .zip file.
    Yields Candidate objects, handling directory recursion and zip streaming."""
    if root.lower().endswith(".zip"):
        yield from walk_zip(root, display_prefix=Path(root).name, scratch_dir=scratch_dir)
        return
    for kind, item in walk_directory(root):
        if kind == "zip":
            yield from walk_zip(item, display_prefix=os.path.relpath(item, start=str(Path(root).parent)), scratch_dir=scratch_dir)
        else:
            yield item
