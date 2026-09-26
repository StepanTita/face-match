"""Face detection, embedding, and cosine-similarity matching against a set of
reference embeddings."""
from __future__ import annotations

import numpy as np

from .model import get_face_app

# Cosine-similarity accept threshold for ArcFace (buffalo_l) embeddings.
# The "confident" threshold most ArcFace-based pipelines use is ~0.6, tuned for
# precision (e.g. access control). Archive search is a different tradeoff:
# personal photo/video collections often span decades, with significant
# appearance change and low-quality old scans, so a false negative (missing a
# real match) is usually more costly than a false positive (an easy manual
# reject). We deliberately default lower, biased toward recall. 0.38 sits in
# the high-recall part of the commonly cited 0.35-0.45 range for this use case.
DEFAULT_THRESHOLD = 0.38


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
