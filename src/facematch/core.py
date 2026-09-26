"""Shared utilities: face model loading, image decoding, embedding/matching helpers."""
from __future__ import annotations

import io
import os
import subprocess
import tempfile
from pathlib import Path

import cv2
import numpy as np

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".heic", ".heif", ".bmp", ".tiff", ".tif", ".webp"}
VIDEO_EXTS = {".mov", ".mp4", ".m4v", ".avi", ".mkv", ".3gp"}

# Cosine-similarity accept threshold for ArcFace (buffalo_l) embeddings.
# The "confident" threshold most ArcFace-based pipelines use is ~0.6, tuned for
# precision (e.g. access control). For a personal recall-biased archive search
# across a ~40 year age range and poor old-photo quality, we deliberately use a
# much lower default so borderline true positives aren't silently dropped -
# the user said they'd rather manually reject false positives than miss a
# real photo. 0.38 sits in the high-recall part of the commonly cited
# 0.35-0.45 range for this use case.
DEFAULT_THRESHOLD = 0.38

_APP = None


def get_face_app(intra_op_threads: int | None = None):
    """Lazily load & cache the InsightFace FaceAnalysis app (buffalo_l, CPU).

    intra_op_threads: when running one worker PROCESS per CPU core (our
    scan.py design), each ONNX Runtime session should use a SINGLE intra-op
    thread. Left at ORT's default (which sizes its intra-op pool to all
    physical cores), N worker processes would each spin up an N-core-wide
    threadpool, causing massive oversubscription and context-switch thrashing
    once N > 1. Pinning threads=1 here and getting parallelism from the
    process pool instead scales far better for many small, independent
    single-image inferences (each call is cheap, so per-call thread-pool
    scheduling overhead in the multi-threaded case dominates anyway).
    """
    global _APP
    if _APP is None:
        import onnxruntime as ort
        from insightface.app import FaceAnalysis

        kwargs = {"providers": ["CPUExecutionProvider"]}
        if intra_op_threads:
            sess_options = ort.SessionOptions()
            sess_options.intra_op_num_threads = intra_op_threads
            sess_options.inter_op_num_threads = 1
            kwargs["sess_options"] = sess_options

        _APP = FaceAnalysis(name="buffalo_l", **kwargs)
        _APP.prepare(ctx_id=0, det_size=(640, 640))
    return _APP


def register_heif_opener():
    import pillow_heif

    pillow_heif.register_heif_opener()


def decode_image_bytes(data: bytes, ext: str) -> np.ndarray | None:
    """Decode raw image bytes (any supported ext, incl. HEIC) to a BGR numpy array."""
    ext = ext.lower()
    if ext in (".heic", ".heif"):
        return _decode_heic_bytes(data)
    arr = np.frombuffer(data, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    return img


def _decode_heic_bytes(data: bytes) -> np.ndarray | None:
    from PIL import Image

    register_heif_opener()
    im = Image.open(io.BytesIO(data)).convert("RGB")
    arr = np.array(im)
    return cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)


def decode_image_path(path: str) -> np.ndarray | None:
    ext = Path(path).suffix.lower()
    if ext in (".heic", ".heif"):
        from PIL import Image

        register_heif_opener()
        im = Image.open(path).convert("RGB")
        arr = np.array(im)
        return cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)
    return cv2.imread(path, cv2.IMREAD_COLOR)


def largest_face_embedding(img_bgr: np.ndarray):
    """Return (embedding, bbox, det_score) of the largest-bbox face, or None."""
    if img_bgr is None:
        return None
    app = get_face_app()
    faces = app.get(img_bgr)
    if not faces:
        return None
    faces.sort(key=lambda f: (f.bbox[2] - f.bbox[0]) * (f.bbox[3] - f.bbox[1]), reverse=True)
    f = faces[0]
    return f.normed_embedding, f.bbox, f.det_score


def all_face_embeddings(img_bgr: np.ndarray):
    """Return list of (embedding, bbox, det_score) for every detected face."""
    if img_bgr is None:
        return []
    app = get_face_app()
    faces = app.get(img_bgr)
    return [(f.normed_embedding, f.bbox, f.det_score) for f in faces]


def cosine_sim(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.dot(a, b))


def best_match_score(embedding: np.ndarray, reference_embeddings: np.ndarray) -> float:
    """Max cosine similarity between embedding and any row of reference_embeddings."""
    sims = reference_embeddings @ embedding
    return float(np.max(sims))


def extract_frames_ffmpeg(video_path: str, out_dir: str, fps: float = 0.7, max_frames: int | None = None) -> list[str]:
    """Sample frames from a video at ~fps frames/sec using ffmpeg. Returns list of jpg paths."""
    os.makedirs(out_dir, exist_ok=True)
    pattern = os.path.join(out_dir, "frame_%05d.jpg")
    cmd = [
        # -threads 1: see the note in extract_video_timestamps_ffmpeg - ffmpeg
        # defaults to using all cores per invocation, which would oversubscribe
        # the machine once many worker processes each shell out to it.
        "ffmpeg", "-y", "-threads", "1", "-i", video_path,
        "-vf", f"fps={fps}",
        "-qscale:v", "2",
        pattern,
    ]
    if max_frames:
        cmd = cmd[:1] + ["-frames:v", str(max_frames)] + cmd[1:]
    subprocess.run(cmd, capture_output=True, check=False, timeout=600)
    frames = sorted(Path(out_dir).glob("frame_*.jpg"))
    return [str(p) for p in frames]


def extract_video_timestamps_ffmpeg(video_path: str, out_dir: str, n_samples: int = 8) -> list[tuple[str, float]]:
    """Sample n_samples frames evenly spread through the video's duration.
    Returns list of (jpg_path, timestamp_seconds)."""
    os.makedirs(out_dir, exist_ok=True)
    duration = get_video_duration(video_path)
    if duration is None or duration <= 0:
        # fallback: just grab a handful of frames via fps sampling
        paths = extract_frames_ffmpeg(video_path, out_dir, fps=1.0, max_frames=n_samples)
        return [(p, float(i)) for i, p in enumerate(paths)]
    timestamps = [duration * (i + 1) / (n_samples + 1) for i in range(n_samples)]
    results = []
    for i, ts in enumerate(timestamps):
        out_path = os.path.join(out_dir, f"ts_{i:03d}.jpg")
        cmd = [
            "ffmpeg", "-y", "-threads", "1", "-ss", f"{ts:.2f}", "-i", video_path,
            "-frames:v", "1", "-qscale:v", "2", out_path,
        ]
        subprocess.run(cmd, capture_output=True, check=False, timeout=60)
        if os.path.exists(out_path):
            results.append((out_path, ts))
    return results


def get_video_duration(video_path: str) -> float | None:
    cmd = [
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", video_path,
    ]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=30, check=False)
        return float(out.stdout.strip())
    except Exception:
        return None
