"""Progress tracking: periodically writes progress.json for progress.html to poll."""
from __future__ import annotations

import base64
import json
import threading
import time
from collections import deque
from pathlib import Path

PROGRESS_PATH = Path(__file__).parent.parent.parent / "progress.json"


class ProgressTracker:
    def __init__(self, write_interval_s: float = 2.0, path: Path = PROGRESS_PATH):
        self.path = path
        self.write_interval_s = write_interval_s
        self.lock = threading.Lock()
        self.start_time = time.time()
        self.phase = "enumerating"  # "enumerating" | "processing" | "done"
        self.current_source = ""
        self.total_discovered = 0
        self.total_known = False  # whether "total_discovered" is the final total
        self.processed = 0
        self.matched = 0
        self.rejected = 0
        self.errored = 0
        self.recent_matches = deque(maxlen=12)
        self._last_write = 0.0

    def set_phase(self, phase: str):
        with self.lock:
            self.phase = phase
        self._maybe_write(force=True)

    def set_current_source(self, source: str):
        with self.lock:
            self.current_source = source
        self._maybe_write()

    def add_discovered(self, n: int = 1):
        with self.lock:
            self.total_discovered += n
        self._maybe_write()

    def set_total_known(self, known: bool = True):
        with self.lock:
            self.total_known = known
        self._maybe_write(force=True)

    def record_processed(self, kind: str, detail: dict | None = None):
        """kind: 'matched' | 'rejected' | 'errored'"""
        with self.lock:
            self.processed += 1
            if kind == "matched":
                self.matched += 1
                if detail:
                    self.recent_matches.appendleft(detail)
            elif kind == "rejected":
                self.rejected += 1
            elif kind == "errored":
                self.errored += 1
        self._maybe_write()

    def _maybe_write(self, force: bool = False):
        now = time.time()
        if not force and (now - self._last_write) < self.write_interval_s:
            return
        self._last_write = now
        self._write()

    def _write(self):
        with self.lock:
            elapsed = time.time() - self.start_time
            rate = self.processed / elapsed * 60 if elapsed > 0 else 0.0
            data = {
                "phase": self.phase,
                "current_source": self.current_source,
                "total_discovered": self.total_discovered,
                "total_known": self.total_known,
                "processed": self.processed,
                "matched": self.matched,
                "rejected": self.rejected,
                "errored": self.errored,
                "elapsed_seconds": round(elapsed, 1),
                "rate_per_min": round(rate, 1),
                "recent_matches": list(self.recent_matches),
                "updated_at": time.time(),
            }
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, indent=2))
        tmp.replace(self.path)

    def finish(self):
        with self.lock:
            self.phase = "done"
        self._write()


def thumbnail_data_uri(img_bgr, max_size: int = 160) -> str:
    import cv2

    h, w = img_bgr.shape[:2]
    scale = max_size / max(h, w)
    if scale < 1:
        img_bgr = cv2.resize(img_bgr, (int(w * scale), int(h * scale)))
    ok, buf = cv2.imencode(".jpg", img_bgr, [cv2.IMWRITE_JPEG_QUALITY, 70])
    if not ok:
        return ""
    b64 = base64.b64encode(buf.tobytes()).decode("ascii")
    return f"data:image/jpeg;base64,{b64}"
