"""`facematch build-references` - build reference face embeddings from files in references/.

For every image, detect faces and keep the largest (most prominent) face's
embedding. For videos, sample several frames spread through them and embed
faces found there too. All embeddings are kept as a list (not averaged)
since matching against the closest of several references handles different
ages/angles/lighting better than a single averaged vector.

Multi-person mode: if references/ contains subfolders (references/mom/,
references/dad/, ...), each subfolder is treated as one person's reference
set - `facematch find` then matches an archive against all of them in a
single pass (see find.py) instead of requiring one full scan per person.
If references/ has no subfolders, it's the classic single, anonymous
reference set (unchanged from before this existed).

Output:
    reference_embeddings.npz
        embeddings  [N, 512] float32
        sources     [N] str  - which reference file each row came from
        persons     [N] str  - "" for the classic flat layout, else the
                     references/<person>/ subfolder name
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from textwrap import dedent

import numpy as np
from facematch_core.decode import (
    IMAGE_EXTS,
    VIDEO_EXTS,
    decode_image_path,
    extract_video_timestamps_ffmpeg,
    ffmpeg_available,
)
from facematch_core.match import largest_face_embedding
from tqdm import tqdm

from . import paths


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.formatter_class = argparse.RawDescriptionHelpFormatter
    parser.description = "Build reference face embeddings from the photos/videos in references/."
    parser.epilog = dedent("""\
        examples:
          facematch build-references     (run this once before your first `facematch find`)

        put a handful of clear photos (and optionally a short video) of the person
        you want to match in a `references/` folder in the current directory first.
        this writes reference_embeddings.npz, which `facematch find` reads.

        want to find several people in one scan instead of one at a time? put each
        person's photos in their own subfolder instead - references/mom/*.jpg,
        references/dad/*.jpg - and `facematch find` will match an archive against
        all of them in a single pass, copying results into matched/mom/, matched/dad/.
        """)


def _person_dirs(references_dir: Path) -> tuple[list[Path], bool]:
    """Returns (list of directories to read reference files from, named_mode).

    named_mode=True means references/ contains subfolders (one per person);
    named_mode=False means references/ itself holds loose files directly,
    exactly like before multi-person support existed.
    """
    entries = sorted(references_dir.iterdir())
    subdirs = [p for p in entries if p.is_dir() and not p.name.startswith(".")]
    if not subdirs:
        return [references_dir], False

    loose_files = [p for p in entries if p.is_file() and not p.name.startswith(".")]
    if loose_files:
        print(
            f"WARNING: ignoring {len(loose_files)} file(s) directly in {references_dir} - "
            "subfolders are present, so this is multi-person mode and only files inside "
            "references/<person>/ subfolders are used."
        )
    return subdirs, True


def _build_for_person(person_dir: Path, person_label: str, scratch_dir: Path):
    """Returns (embeddings, sources) for one person's reference directory."""
    embeddings = []
    sources = []

    files = sorted(p for p in person_dir.iterdir() if p.is_file() and not p.name.startswith("."))
    label = f" ({person_label})" if person_label else ""
    print(f"Found {len(files)} file(s){label} in {person_dir}")

    if any(p.suffix.lower() in VIDEO_EXTS for p in files) and not ffmpeg_available():
        print(
            "WARNING: ffmpeg/ffprobe not found on PATH. Video references will "
            "fail with an error; images are unaffected. Install ffmpeg (e.g. "
            "`brew install ffmpeg` on macOS) to support video references.",
            file=sys.stderr,
        )

    desc = f"build-references{label}"
    for path in tqdm(files, unit="file", desc=desc):
        ext = path.suffix.lower()
        if ext in IMAGE_EXTS:
            img = decode_image_path(str(path))
            if img is None:
                tqdm.write(f"  [skip] could not decode {path.name}")
                continue
            result = largest_face_embedding(img)
            if result is None:
                tqdm.write(f"  [no face] {path.name}")
                continue
            emb, bbox, score = result
            embeddings.append(emb)
            sources.append(f"{path.name}")
            tqdm.write(f"  [ok] {path.name} det_score={score:.3f}")
        elif ext in VIDEO_EXTS:
            tqdm.write(f"  Sampling frames from video {path.name} ...")
            frames = extract_video_timestamps_ffmpeg(str(path), str(scratch_dir), n_samples=8)
            found = 0
            for frame_path, ts in frames:
                img = decode_image_path(frame_path)
                result = largest_face_embedding(img)
                Path(frame_path).unlink(missing_ok=True)
                if result is None:
                    continue
                emb, bbox, score = result
                embeddings.append(emb)
                sources.append(f"{path.name}@{ts:.1f}s")
                found += 1
            tqdm.write(f"  [ok] {path.name}: {found}/{len(frames)} sampled frames had a face")
        else:
            tqdm.write(f"  [skip] unsupported extension {path.name}")

    return embeddings, sources


def run(args: argparse.Namespace) -> None:
    references_dir = paths.references_dir()
    out_path = paths.reference_embeddings_path()
    scratch_dir = paths.scratch_root("ref_frames")

    if not references_dir.exists():
        print(f"ERROR: {references_dir} not found. Create it and add reference photos/videos first.")
        sys.exit(1)

    person_dirs, named_mode = _person_dirs(references_dir)

    all_embeddings: list[np.ndarray] = []
    all_sources: list[str] = []
    all_persons: list[str] = []
    per_person_counts: dict[str, int] = {}

    for person_dir in person_dirs:
        person_label = person_dir.name if named_mode else ""
        embeddings, sources = _build_for_person(person_dir, person_label, scratch_dir)
        all_embeddings.extend(embeddings)
        all_sources.extend(sources)
        all_persons.extend([person_label] * len(embeddings))
        per_person_counts[person_label or "(default)"] = len(embeddings)

    if not all_embeddings:
        print("ERROR: no reference embeddings extracted!")
        sys.exit(1)

    emb_array = np.stack(all_embeddings).astype(np.float32)
    np.savez(
        out_path,
        embeddings=emb_array,
        sources=np.array(all_sources),
        persons=np.array(all_persons),
    )

    if named_mode:
        breakdown = ", ".join(f"{name} ({count})" for name, count in per_person_counts.items())
        print(f"\nSaved {len(all_embeddings)} reference embeddings for {len(per_person_counts)} "
              f"people to {out_path}: {breakdown}")
    else:
        print(f"\nSaved {len(all_embeddings)} reference embeddings to {out_path}")
