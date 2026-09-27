"""Image/video decoding, including HEIC, and ffmpeg-based frame sampling."""
from __future__ import annotations

import io
import os
import shutil
import subprocess
from pathlib import Path

import cv2
import numpy as np

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".heic", ".heif", ".bmp", ".tiff", ".tif", ".webp"}
VIDEO_EXTS = {".mov", ".mp4", ".m4v", ".avi", ".mkv", ".3gp"}

_FFMPEG_CHECKED = False


class FFmpegNotFoundError(RuntimeError):
    """Raised when ffmpeg/ffprobe are needed (a video was encountered) but not on PATH."""


def ffmpeg_available() -> bool:
    """Cheap presence check for ffmpeg/ffprobe, no caching (safe to call once at CLI startup)."""
    return shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


def require_ffmpeg() -> None:
    """Check ffmpeg/ffprobe are on PATH, once per process. Raises a clear,
    actionable error instead of letting a missing binary fail silently deep
    inside a subprocess call (every call below already swallows subprocess
    errors so a scan doesn't die on one bad file - this is the one check
    that should NOT be swallowed, since it means every video will fail)."""
    global _FFMPEG_CHECKED
    if _FFMPEG_CHECKED:
        return
    missing = [name for name in ("ffmpeg", "ffprobe") if shutil.which(name) is None]
    if missing:
        raise FFmpegNotFoundError(
            f"{' and '.join(missing)} not found on PATH, but the archive contains "
            "video files that need it for frame sampling.\n"
            "Install it, then try again:\n"
            "  macOS:   brew install ffmpeg\n"
            "  Ubuntu/Debian: sudo apt install ffmpeg\n"
            "  Fedora:  sudo dnf install ffmpeg\n"
            "Or re-run against image files only if you don't need video support."
        )
    _FFMPEG_CHECKED = True


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


def extract_frames_ffmpeg(video_path: str, out_dir: str, fps: float = 0.7, max_frames: int | None = None) -> list[str]:
    """Sample frames from a video at ~fps frames/sec using ffmpeg. Returns list of jpg paths."""
    require_ffmpeg()
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
    require_ffmpeg()
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
