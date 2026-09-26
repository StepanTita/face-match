"""Build the reference face-embedding set from files in references/.

For every image, detect faces and keep the largest (most prominent) face's
embedding. For the .MOV video, sample several frames spread through it and
embed faces found there too. All embeddings are kept as a list (not
averaged) since matching against the closest of several references handles
different ages/angles/lighting better than a single averaged vector.

Usage:
    uv run build_references.py
Output:
    reference_embeddings.npz  (array "embeddings" of shape [N, 512], "sources" list)
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent / "src"))
from facematch.core import (  # noqa: E402
    IMAGE_EXTS,
    VIDEO_EXTS,
    decode_image_path,
    extract_video_timestamps_ffmpeg,
    largest_face_embedding,
)

REFERENCES_DIR = Path(__file__).parent / "references"
OUT_PATH = Path(__file__).parent / "reference_embeddings.npz"
SCRATCH_DIR = Path(__file__).parent / "scratch" / "ref_frames"


def main():
    embeddings = []
    sources = []

    files = sorted(p for p in REFERENCES_DIR.iterdir() if p.is_file() and not p.name.startswith("."))
    print(f"Found {len(files)} files in {REFERENCES_DIR}")

    for path in files:
        ext = path.suffix.lower()
        if ext in IMAGE_EXTS:
            img = decode_image_path(str(path))
            if img is None:
                print(f"  [skip] could not decode {path.name}")
                continue
            result = largest_face_embedding(img)
            if result is None:
                print(f"  [no face] {path.name}")
                continue
            emb, bbox, score = result
            embeddings.append(emb)
            sources.append(f"{path.name}")
            print(f"  [ok] {path.name} det_score={score:.3f}")
        elif ext in VIDEO_EXTS:
            print(f"  Sampling frames from video {path.name} ...")
            frames = extract_video_timestamps_ffmpeg(str(path), str(SCRATCH_DIR), n_samples=8)
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
            print(f"  [ok] {path.name}: {found}/{len(frames)} sampled frames had a face")
        else:
            print(f"  [skip] unsupported extension {path.name}")

    if not embeddings:
        print("ERROR: no reference embeddings extracted!")
        sys.exit(1)

    emb_array = np.stack(embeddings).astype(np.float32)
    np.savez(OUT_PATH, embeddings=emb_array, sources=np.array(sources))
    print(f"\nSaved {len(embeddings)} reference embeddings to {OUT_PATH}")


if __name__ == "__main__":
    main()
