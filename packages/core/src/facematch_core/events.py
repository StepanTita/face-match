"""In-process progress accounting for a running scan.

This module used to write a `progress.json` file for a browser-based viewer
to poll. That viewer is gone: `ProgressTracker` now only accumulates counters
in memory and (optionally, throttled) hands a snapshot to a caller-supplied
`on_update` callback. Front ends decide what to do with it - the CLI renders
a live `tqdm` bar for a foreground run, or writes a small status file for a
`--background` one. A future GUI can plug in the same way.
"""
from __future__ import annotations

import dataclasses
import threading
import time
from collections import deque


@dataclasses.dataclass
class ProgressSnapshot:
    phase: str
    current_source: str
    total_discovered: int
    total_known: bool
    processed: int
    matched: int
    rejected: int
    errored: int
    elapsed_seconds: float
    rate_per_min: float
    recent_matches: list


class ProgressTracker:
    def __init__(self, on_update=None, update_interval_s: float = 1.0):
        self.on_update = on_update
        self.update_interval_s = update_interval_s
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
        self.recent_matches: deque = deque(maxlen=12)
        self._last_notify = 0.0

    def set_phase(self, phase: str):
        with self.lock:
            self.phase = phase
        self._maybe_notify(force=True)

    def set_current_source(self, source: str):
        with self.lock:
            self.current_source = source
        self._maybe_notify()

    def add_discovered(self, n: int = 1):
        with self.lock:
            self.total_discovered += n
        self._maybe_notify()

    def set_total_known(self, known: bool = True):
        with self.lock:
            self.total_known = known
        self._maybe_notify(force=True)

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
        self._maybe_notify()

    def snapshot(self) -> ProgressSnapshot:
        with self.lock:
            elapsed = time.time() - self.start_time
            rate = self.processed / elapsed * 60 if elapsed > 0 else 0.0
            return ProgressSnapshot(
                phase=self.phase,
                current_source=self.current_source,
                total_discovered=self.total_discovered,
                total_known=self.total_known,
                processed=self.processed,
                matched=self.matched,
                rejected=self.rejected,
                errored=self.errored,
                elapsed_seconds=round(elapsed, 1),
                rate_per_min=round(rate, 1),
                recent_matches=list(self.recent_matches),
            )

    def _maybe_notify(self, force: bool = False):
        if self.on_update is None:
            return
        now = time.time()
        if not force and (now - self._last_notify) < self.update_interval_s:
            return
        self._last_notify = now
        self.on_update(self.snapshot())

    def finish(self):
        with self.lock:
            self.phase = "done"
        self._maybe_notify(force=True)


def thumbnail_data_uri(img_bgr, max_size: int = 160) -> str:
    import cv2

    h, w = img_bgr.shape[:2]
    scale = max_size / max(h, w)
    if scale < 1:
        img_bgr = cv2.resize(img_bgr, (int(w * scale), int(h * scale)))
    ok, buf = cv2.imencode(".jpg", img_bgr, [cv2.IMWRITE_JPEG_QUALITY, 70])
    if not ok:
        return ""
    import base64

    b64 = base64.b64encode(buf.tobytes()).decode("ascii")
    return f"data:image/jpeg;base64,{b64}"
