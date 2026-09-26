"""`facematch build-references` - build reference face embeddings from files in references/.

For every image, detect faces and keep the largest (most prominent) face's
embedding. For videos, sample several frames spread through them and embed
faces found there too. All embeddings are kept as a list (not averaged)
since matching against the closest of several references handles different
ages/angles/lighting better than a single averaged vector.

Output:
    reference_embeddings.npz  (array "embeddings" of shape [N, 512], "sources" list)
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from textwrap import dedent

import numpy as np
from facematch_core.decode import IMAGE_EXTS, VIDEO_EXTS, decode_image_path, extract_video_timestamps_ffmpeg
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
        """)


def run(args: argparse.Namespace) -> None:
    references_dir = paths.references_dir()
    out_path = paths.reference_embeddings_path()
    scratch_dir = paths.scratch_root("ref_frames")

    embeddings = []
    sources = []

    if not references_dir.exists():
        print(f"ERROR: {references_dir} not found. Create it and add reference photos/videos first.")
        sys.exit(1)

    files = sorted(p for p in references_dir.iterdir() if p.is_file() and not p.name.startswith("."))
    print(f"Found {len(files)} files in {references_dir}")

    for path in tqdm(files, unit="file", desc="build-references"):
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

    if not embeddings:
        print("ERROR: no reference embeddings extracted!")
        sys.exit(1)

    emb_array = np.stack(embeddings).astype(np.float32)
    np.savez(out_path, embeddings=emb_array, sources=np.array(sources))
    print(f"\nSaved {len(embeddings)} reference embeddings to {out_path}")
