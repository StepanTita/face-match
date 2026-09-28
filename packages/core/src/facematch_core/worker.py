"""Per-process worker: loads its own InsightFace model once (ONNX Runtime
sessions can't be shared across processes), then does extraction + face
detection + embedding + matching for one candidate at a time.

Each worker gets a dedicated scratch subdirectory (keyed by its own PID) so
concurrent workers never race on the same temp filename, and does its own
file copy for matches (copy dest names are derived from the unique source
path, so concurrent writes never collide either). Only lightweight result
dicts (with a small base64 thumbnail for genuine matches) cross back to the
main process - large image/video bytes never go through IPC.
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path

import cv2
import numpy as np

# OpenCV spins up its own internal thread pool (independent of ONNX Runtime's
# intra-op threads) for image decode/resize ops. Left at its default, each
# worker PROCESS would also fan out across all cores internally, causing the
# same oversubscription problem discussed in model.get_face_app - just from a
# different library. Pin it to 1 so all parallelism comes from the process
# pool, not from nested thread pools inside each process.
cv2.setNumThreads(1)

from .decode import decode_image_path, extract_frames_ffmpeg
from .events import thumbnail_data_uri
from .match import all_face_embeddings, best_match_score
from .model import get_face_app

# Set once per worker process by init_worker() (find) or init_worker_group()
# (group) - only one of the two ever runs in a given process, so sharing
# these globals between the two entry points is safe.
#
# _REFS is a dict of person-label -> reference embedding array. In classic
# (non-named) mode it's always {"": refs}. _NAMED_MODE distinguishes that
# case from genuine multi-person mode (references/<person>/ subfolders) so
# the classic single-person result shape and matched/ layout stay byte-for-
# byte identical to before multi-person support existed - see find.py.
_REFS: dict[str, np.ndarray] | None = None
_NAMED_MODE: bool = False
_THRESHOLD: float = 0.38
_SCRATCH_ROOT: Path | None = None
_MATCHED_DIR: Path | None = None
_THUMBS_DIR: Path | None = None
_WORKER_SCRATCH: Path | None = None


def init_worker(refs: dict[str, np.ndarray], threshold: float, scratch_root: str, matched_dir: str,
                 thumbs_dir: str, intra_op_threads: int):
    global _REFS, _NAMED_MODE, _THRESHOLD, _SCRATCH_ROOT, _MATCHED_DIR, _THUMBS_DIR, _WORKER_SCRATCH
    _REFS = refs
    _NAMED_MODE = any(person != "" for person in refs)
    _THRESHOLD = threshold
    _SCRATCH_ROOT = Path(scratch_root)
    _MATCHED_DIR = Path(matched_dir)
    _THUMBS_DIR = Path(thumbs_dir)
    _WORKER_SCRATCH = _SCRATCH_ROOT / f"w{os.getpid()}"
    _WORKER_SCRATCH.mkdir(parents=True, exist_ok=True)
    _MATCHED_DIR.mkdir(parents=True, exist_ok=True)
    _THUMBS_DIR.mkdir(parents=True, exist_ok=True)
    # Warm up the model now so the first real task isn't skewed by load time.
    get_face_app(intra_op_threads=intra_op_threads)


def safe_dest_name(display_name: str) -> str:
    cleaned = display_name.replace("::", "__").replace("/", "_").replace(" ", "_")
    return cleaned[-200:]


def _per_person_best_scores(faces) -> dict[str, float]:
    """Best cosine-similarity score per person across every face detected in
    one file (a file can have several faces; a person's score is the best
    any of them achieves against that person's reference set)."""
    return {
        person: max(best_match_score(emb, person_refs) for emb, _bbox, _score in faces)
        for person, person_refs in _REFS.items()
    }


def process_candidate(cand) -> dict:
    """Runs in a worker process. Returns a small JSON-able result dict."""
    result = _process_image(cand) if cand.kind == "image" else _process_video(cand)
    result["key"] = cand.key
    return result


def _process_image(cand) -> dict:
    local_path = None
    try:
        local_path = cand.extract_to(str(_WORKER_SCRATCH))
        img = decode_image_path(local_path)
        if img is None:
            return {"display_name": cand.display_name, "status": "error", "error": "could not decode"}
        faces = all_face_embeddings(img)
        if not faces:
            return {"display_name": cand.display_name, "status": "no_face"}

        per_person = _per_person_best_scores(faces)

        if not _NAMED_MODE:
            best_score = per_person[""]
            if best_score >= _THRESHOLD:
                dest_name = safe_dest_name(cand.display_name)
                dest_path = _MATCHED_DIR / dest_name
                shutil.copy2(local_path, dest_path)
                return {
                    "display_name": cand.display_name,
                    "status": "matched",
                    "kind": "image",
                    "score": best_score,
                    "dest_path": str(dest_path),
                    "thumb": thumbnail_data_uri(img),
                }
            return {"display_name": cand.display_name, "status": "below_threshold", "score": best_score}

        matched = {p: s for p, s in per_person.items() if s >= _THRESHOLD}
        if matched:
            matches = {}
            for person, score in matched.items():
                dest_dir = _MATCHED_DIR / person
                dest_dir.mkdir(parents=True, exist_ok=True)
                dest_path = dest_dir / safe_dest_name(cand.display_name)
                shutil.copy2(local_path, dest_path)
                matches[person] = {"score": score, "dest_path": str(dest_path)}
            return {
                "display_name": cand.display_name,
                "status": "matched",
                "kind": "image",
                "matches": matches,
                "thumb": thumbnail_data_uri(img),
            }
        return {"display_name": cand.display_name, "status": "below_threshold", "score": max(per_person.values())}
    except Exception as e:
        return {"display_name": cand.display_name, "status": "error", "error": str(e)}
    finally:
        if local_path and cand.loose_path is None and os.path.exists(local_path):
            os.remove(local_path)


# ---------------------------------------------------------------------------
# `facematch group` worker entry points: detect and embed EVERY face in every
# file (no reference set, no matching, no copying) - `group`'s clustering
# pass runs later, over everything this records. See group_store.py.
# ---------------------------------------------------------------------------

def init_worker_group(scratch_root: str, intra_op_threads: int):
    global _SCRATCH_ROOT, _WORKER_SCRATCH
    _SCRATCH_ROOT = Path(scratch_root)
    _WORKER_SCRATCH = _SCRATCH_ROOT / f"w{os.getpid()}"
    _WORKER_SCRATCH.mkdir(parents=True, exist_ok=True)
    get_face_app(intra_op_threads=intra_op_threads)


def process_candidate_group(cand) -> dict:
    """Runs in a worker process. Returns a small result dict: status
    'done' (faces present), 'no_face', or 'error' - never 'matched'/
    'below_threshold', since there's nothing to match against here."""
    result = _process_image_group(cand) if cand.kind == "image" else _process_video_group(cand)
    result["key"] = cand.key
    result["kind"] = cand.kind
    return result


def _process_image_group(cand) -> dict:
    local_path = None
    try:
        local_path = cand.extract_to(str(_WORKER_SCRATCH))
        img = decode_image_path(local_path)
        if img is None:
            return {"display_name": cand.display_name, "status": "error", "error": "could not decode"}
        faces = all_face_embeddings(img)
        if not faces:
            return {"display_name": cand.display_name, "status": "no_face"}
        face_dicts = [
            {"embedding": emb, "bbox": [float(x) for x in bbox], "det_score": float(score)}
            for emb, bbox, score in faces
        ]
        return {"display_name": cand.display_name, "status": "done", "faces": face_dicts}
    except Exception as e:
        return {"display_name": cand.display_name, "status": "error", "error": str(e)}
    finally:
        if local_path and cand.loose_path is None and os.path.exists(local_path):
            os.remove(local_path)


def _process_video_group(cand) -> dict:
    local_path = None
    frame_dir = str(_WORKER_SCRATCH / "frames")
    fps = 0.7
    try:
        local_path = cand.extract_to(str(_WORKER_SCRATCH))
        frames = extract_frames_ffmpeg(local_path, frame_dir, fps=fps)
        if not frames:
            return {"display_name": cand.display_name, "status": "error", "error": "no frames extracted"}
        face_dicts = []
        for i, frame_path in enumerate(frames):
            ts = i / fps
            img = decode_image_path(frame_path)
            faces = all_face_embeddings(img) if img is not None else []
            for emb, bbox, score in faces:
                face_dicts.append({
                    "embedding": emb,
                    "bbox": [float(x) for x in bbox],
                    "det_score": float(score),
                    "video_ts": round(ts, 1),
                })
            os.remove(frame_path)
        if not face_dicts:
            return {"display_name": cand.display_name, "status": "no_face"}
        return {"display_name": cand.display_name, "status": "done", "faces": face_dicts}
    except Exception as e:
        return {"display_name": cand.display_name, "status": "error", "error": str(e)}
    finally:
        if local_path and cand.loose_path is None and os.path.exists(local_path):
            os.remove(local_path)


def _process_video(cand) -> dict:
    local_path = None
    frame_dir = str(_WORKER_SCRATCH / "frames")
    fps = 0.7
    try:
        local_path = cand.extract_to(str(_WORKER_SCRATCH))
        frames = extract_frames_ffmpeg(local_path, frame_dir, fps=fps)
        if not frames:
            return {"display_name": cand.display_name, "status": "error", "error": "no frames extracted"}

        # Best score/frame/timestamps tracked per person, across every
        # sampled frame - same "best of all faces across the file" principle
        # as the image path, just accumulated frame-by-frame instead of in
        # one call.
        best_overall = {person: -1.0 for person in _REFS}
        best_frame_img = {person: None for person in _REFS}
        matched_timestamps: dict[str, list[float]] = {person: [] for person in _REFS}

        for i, frame_path in enumerate(frames):
            ts = i / fps
            img = decode_image_path(frame_path)
            faces = all_face_embeddings(img) if img is not None else []
            for emb, bbox, score in faces:
                for person, person_refs in _REFS.items():
                    sim = best_match_score(emb, person_refs)
                    if sim > best_overall[person]:
                        best_overall[person] = sim
                        best_frame_img[person] = img
                    if sim >= _THRESHOLD:
                        matched_timestamps[person].append(round(ts, 1))
            os.remove(frame_path)

        if not _NAMED_MODE:
            score = best_overall[""]
            if matched_timestamps[""]:
                return _finalize_video_match(cand, local_path, "", best_frame_img[""], score, matched_timestamps[""])
            return {"display_name": cand.display_name, "status": "below_threshold", "score": score}

        matched_people = [p for p, ts_list in matched_timestamps.items() if ts_list]
        if matched_people:
            matches = {}
            thumb = None
            for person in matched_people:
                one = _finalize_video_match(
                    cand, local_path, person, best_frame_img[person], best_overall[person], matched_timestamps[person],
                )
                matches[person] = {
                    "score": one["score"], "dest_path": one["dest_path"],
                    "thumb_path": one["thumb_path"], "timestamps": one["timestamps"],
                }
                thumb = thumb or one["thumb"]
            return {
                "display_name": cand.display_name, "status": "matched", "kind": "video",
                "matches": matches, "thumb": thumb,
            }
        return {"display_name": cand.display_name, "status": "below_threshold", "score": max(best_overall.values())}
    except Exception as e:
        return {"display_name": cand.display_name, "status": "error", "error": str(e)}
    finally:
        if local_path and cand.loose_path is None and os.path.exists(local_path):
            os.remove(local_path)


def _finalize_video_match(cand, local_path: str, person: str, best_frame_img, score: float,
                           timestamps: list[float]) -> dict:
    """Writes the thumbnail + copies the full video for one person's match,
    under _MATCHED_DIR (non-named mode) or _MATCHED_DIR/<person> (named)."""
    dest_dir = _MATCHED_DIR / person if person else _MATCHED_DIR
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_name = safe_dest_name(cand.display_name)

    thumb_name = dest_name + ".jpg"
    thumb_path = (_THUMBS_DIR / person / thumb_name) if person else (_THUMBS_DIR / thumb_name)
    thumb_path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(thumb_path), best_frame_img)

    # Full video copy, same convention as images (archive-prefixed,
    # collision-free filename). local_path already holds the whole extracted
    # file at this point (extract_to() always pulls the complete entry, not
    # just sampled frames), so this is just a copy.
    video_dest_path = dest_dir / dest_name
    shutil.copy2(local_path, video_dest_path)

    return {
        "display_name": cand.display_name,
        "status": "matched",
        "kind": "video",
        "score": score,
        "dest_path": str(video_dest_path),
        "thumb_path": str(thumb_path),
        "timestamps": timestamps,
        "thumb": thumbnail_data_uri(best_frame_img),
    }
