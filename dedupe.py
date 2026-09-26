"""Deduplicate matched/ results: the same real-world photo commonly exists
multiple times across overlapping backup sources (iCloud Photos, Google
Photos Takeout, Photos/, Archive.zip likely all mirror the same phone
library under different filenames), so the scan naturally re-matches it once
per source copy.

Safe to run WHILE scan.py is still writing into matched/ - read-only with
respect to matches.csv and checkpoint.sqlite3 (the running scan's state);
only ever *moves* files within matched/, never deletes.

Two-tier detection:
  1. SHA256 exact byte match - cheap, catches identical copies.
  2. Perceptual hash (imagehash.phash, images only) with a small Hamming
     distance threshold - catches the same photo re-encoded/resized
     differently by different export pipelines (e.g. HEIC vs JPEG, Google
     Photos vs iCloud compression). Videos use SHA256 only (see below).

Incremental/idempotent: a small JSON index (dedupe_state.json) remembers
every file this script has ever classified. A previously-established
canonical is NEVER moved or replaced by a later, higher-confidence match -
group formation happens once, when a SECOND file is first found to collide
with an existing lone file; every subsequent collision just adds another
duplicate to that same group. This means re-running never reshuffles a
decision already recorded in dedupe_report.csv.

Usage:
    uv run dedupe.py [--phash-threshold 5] [--mtime-safety-seconds 5]
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))
from facematch.core import decode_image_path  # noqa: E402

PROJECT_DIR = Path(__file__).parent
MATCHED_DIR = PROJECT_DIR / "matched"
THUMBS_DIR = MATCHED_DIR / "video_thumbnails"
DUPLICATES_DIR = MATCHED_DIR / "duplicates"
MATCHES_CSV = MATCHED_DIR / "matches.csv"
STATE_PATH = PROJECT_DIR / "dedupe_state.json"
REPORT_PATH = PROJECT_DIR / "dedupe_report.csv"

IMAGE_EXTS_FOR_PHASH = {".jpg", ".jpeg", ".png", ".heic", ".heif", ".bmp", ".tiff", ".tif", ".webp"}

# Hamming distance threshold for imagehash.phash (64-bit perceptual hash,
# hash_size=8, the library default). 0 = identical hash. Empirically,
# minor re-encoding/recompression (HEIC->JPEG, different JPEG quality,
# resizing by a different export pipeline) shifts a handful of bits, while
# genuinely different photos of the same person/scene typically differ by
# a much larger margin. We bias conservative (low threshold) on purpose:
# collapsing two DIFFERENT real photos of the match subject into one "duplicate" group
# would silently hide a unique photo from the user, which is worse than
# occasionally leaving a near-duplicate uncollapsed for them to notice.
DEFAULT_PHASH_THRESHOLD = 5

# Skip any file modified more recently than this - it may still be being
# written by the concurrently-running scan.
DEFAULT_MTIME_SAFETY_SECONDS = 5


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def phash_file(path: Path):
    import imagehash
    from PIL import Image

    img_bgr = decode_image_path(str(path))
    if img_bgr is None:
        return None
    import cv2
    rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
    pil_img = Image.fromarray(rgb)
    return imagehash.phash(pil_img)


def load_matches_csv() -> dict[str, dict]:
    """basename(detail/dest_path) -> {confidence, source} for status=matched rows."""
    out = {}
    if not MATCHES_CSV.exists():
        return out
    with open(MATCHES_CSV, newline="") as f:
        for row in csv.DictReader(f):
            if row.get("status") != "matched":
                continue
            detail = row.get("detail") or ""
            if not detail:
                continue
            base = Path(detail.split(" timestamps=")[0]).name if "timestamps=" in detail else Path(detail).name
            try:
                score = float(row.get("score") or 0.0)
            except ValueError:
                score = 0.0
            out[base] = {"confidence": score, "source": row.get("source", "")}
    return out


def load_state() -> dict:
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text())
    return {"files": {}, "next_group_id": 1}


def save_state(state: dict):
    tmp = STATE_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(state, indent=2))
    tmp.replace(STATE_PATH)


def snapshot_candidates(safety_seconds: int) -> list[tuple[str, Path, str]]:
    """Returns list of (relkey, abspath, kind) for files currently safe to
    consider, where relkey is a stable identifier used as the state dict key."""
    now = time.time()
    out = []
    for root, kind, glob_pat in [(MATCHED_DIR, "image", "*"), (THUMBS_DIR, "video_thumb", "*.jpg")]:
        if not root.exists():
            continue
        for p in sorted(root.glob(glob_pat)):
            if not p.is_file():
                continue
            if p.parent != root:
                continue  # don't descend into duplicates/ or other subfolders
            if root is MATCHED_DIR and p.name == "matches.csv":
                continue
            try:
                st = p.stat()
            except OSError:
                continue
            if st.st_size == 0:
                continue
            if (now - st.st_mtime) < safety_seconds:
                continue
            relkey = f"{'thumb' if kind == 'video_thumb' else 'root'}/{p.name}"
            out.append((relkey, p, kind))
    return out


def ensure_hashes(entry: dict, path: Path, kind: str, phash_needed: bool):
    """Fill in sha256 (and phash for images) on a state entry in place, if missing."""
    if "sha256" not in entry:
        entry["sha256"] = sha256_file(path)
    if phash_needed and kind == "image" and "phash" not in entry:
        ext = path.suffix.lower()
        if ext in IMAGE_EXTS_FOR_PHASH:
            try:
                ph = phash_file(path)
                entry["phash"] = str(ph) if ph is not None else None
            except Exception:
                entry["phash"] = None
        else:
            entry["phash"] = None


def hamming(hex_a: str, hex_b: str) -> int:
    import imagehash

    return imagehash.hex_to_hash(hex_a) - imagehash.hex_to_hash(hex_b)


def pick_canonical(a_key: str, a_entry: dict, b_key: str, b_entry: dict) -> tuple[str, str]:
    """Returns (canonical_key, duplicate_key). Prefer higher match confidence,
    tie-break by larger file size."""
    ca, cb = a_entry.get("confidence", 0.0), b_entry.get("confidence", 0.0)
    if ca != cb:
        return (a_key, b_key) if ca > cb else (b_key, a_key)
    sa, sb = a_entry.get("size", 0), b_entry.get("size", 0)
    return (a_key, b_key) if sa >= sb else (b_key, a_key)


def move_to_group(entry: dict, path_lookup: dict[str, Path], group_id: str):
    group_dir = DUPLICATES_DIR / group_id
    group_dir.mkdir(parents=True, exist_ok=True)
    src_path = path_lookup[entry["_key"]]
    dest = group_dir / src_path.name
    shutil.move(str(src_path), str(dest))
    entry["role"] = "duplicate"
    entry["group_id"] = group_id
    entry["moved_to"] = str(dest)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--phash-threshold", type=int, default=DEFAULT_PHASH_THRESHOLD)
    parser.add_argument("--mtime-safety-seconds", type=int, default=DEFAULT_MTIME_SAFETY_SECONDS)
    args = parser.parse_args()

    DUPLICATES_DIR.mkdir(parents=True, exist_ok=True)
    match_info = load_matches_csv()
    state = load_state()
    files_state = state["files"]

    candidates = snapshot_candidates(args.mtime_safety_seconds)
    path_lookup = {relkey: path for relkey, path, _kind in candidates}

    new_keys = [relkey for relkey, _p, _k in candidates if relkey not in files_state]
    print(f"Snapshot: {len(candidates)} eligible files in matched/ (skipping in-flight/empty). "
          f"{len(new_keys)} not yet classified.")

    # Seed state entries for brand-new files (metadata only; hashes computed lazily below).
    for relkey, path, kind in candidates:
        if relkey in files_state:
            continue
        conf_info = match_info.get(path.name, {})
        files_state[relkey] = {
            "path": str(path),
            "kind": "image" if kind == "image" else "video_thumb",
            "size": path.stat().st_size,
            "confidence": conf_info.get("confidence", 0.0),
            "source": conf_info.get("source", ""),
            "role": None,       # "canonical" | "duplicate" | None (unclassified singleton so far)
            "group_id": None,
        }

    sha_index: dict[str, str] = {}   # sha256 -> relkey of an existing representative
    phash_index: list[tuple[str, str]] = []  # (relkey, phash_hex) for existing image files

    for relkey, entry in files_state.items():
        if relkey not in path_lookup and entry.get("role") != "duplicate":
            # File vanished from its expected root location and was never
            # recorded as moved by us - skip it defensively (don't crash).
            continue
        if entry.get("sha256"):
            sha_index.setdefault(entry["sha256"], relkey)
        if entry.get("phash"):
            phash_index.append((relkey, entry["phash"]))

    exact_groups_formed = 0
    perceptual_groups_formed = 0

    for relkey in new_keys:
        entry = files_state[relkey]
        entry["_key"] = relkey
        path = path_lookup[relkey]
        kind = entry["kind"]
        ensure_hashes(entry, path, kind, phash_needed=True)
        sha = entry["sha256"]

        match_key = sha_index.get(sha)
        matched_by = "sha256" if match_key else None

        if match_key is None and kind == "image" and entry.get("phash"):
            for other_key, other_phash in phash_index:
                if other_key == relkey:
                    continue
                if hamming(entry["phash"], other_phash) <= args.phash_threshold:
                    match_key = other_key
                    matched_by = "phash"
                    break

        if match_key is None:
            # No collision yet - remains an unclassified singleton in place.
            sha_index.setdefault(sha, relkey)
            if kind == "image" and entry.get("phash"):
                phash_index.append((relkey, entry["phash"]))
            entry.pop("_key", None)
            continue

        other_entry = files_state[match_key]
        if other_entry.get("group_id"):
            # Existing group: the new file just joins it as another duplicate.
            group_id = other_entry["group_id"]
            move_to_group(entry, path_lookup, group_id)
        else:
            # First collision for `other_entry` - form a brand new group now,
            # deciding the canonical once, permanently.
            group_id = f"g{state['next_group_id']:05d}"
            state["next_group_id"] += 1
            other_entry["_key"] = match_key
            canonical_key, duplicate_key = pick_canonical(relkey, entry, match_key, other_entry)
            for k in (canonical_key, duplicate_key):
                files_state[k]["group_id"] = group_id
            files_state[canonical_key]["role"] = "canonical"
            dup_entry = files_state[duplicate_key]
            dup_entry["_key"] = duplicate_key
            # path_lookup only has NEW files plus any still-in-root existing
            # files; the "other" file (previously a singleton) is still at
            # its original recorded path since it was never moved before.
            path_lookup.setdefault(match_key, Path(other_entry["path"]))
            path_lookup.setdefault(relkey, path)
            move_to_group(dup_entry, path_lookup, group_id)
            other_entry.pop("_key", None)

        if matched_by == "sha256":
            exact_groups_formed += 1
        else:
            perceptual_groups_formed += 1
        entry.pop("_key", None)

    for entry in files_state.values():
        entry.pop("_key", None)

    save_state(state)

    # Write/refresh the audit report from the full (persisted) state, so it's
    # always a complete picture even across multiple incremental runs.
    groups: dict[str, list[str]] = {}
    for relkey, entry in files_state.items():
        gid = entry.get("group_id")
        if gid:
            groups.setdefault(gid, []).append(relkey)

    with open(REPORT_PATH, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["group_id", "role", "filename", "confidence", "source", "current_path"])
        for gid, members in sorted(groups.items()):
            members.sort(key=lambda k: 0 if files_state[k]["role"] == "canonical" else 1)
            for relkey in members:
                e = files_state[relkey]
                w.writerow([gid, e["role"], Path(e["path"]).name, e.get("confidence", ""),
                            e.get("source", ""), e.get("moved_to", e["path"])])

    total_groups = len(groups)
    total_duplicates_moved = sum(1 for e in files_state.values() if e.get("role") == "duplicate")
    print(f"\nThis run: {exact_groups_formed} new exact-hash collisions, "
          f"{perceptual_groups_formed} new perceptual-hash collisions.")
    print(f"Cumulative: {total_groups} duplicate groups, {total_duplicates_moved} files moved into "
          f"{DUPLICATES_DIR}, report at {REPORT_PATH}")


if __name__ == "__main__":
    main()
