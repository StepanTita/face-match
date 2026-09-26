"""Durable, resumable checkpoint of which candidates have already been processed.

Backed by SQLite (single writer: the main process, which is also the sole
writer of matches.csv/progress.json, so there's no multi-process write
contention here - workers only ever return small result dicts over IPC).
Every result is committed to disk immediately as it arrives, so a crash or
kill -9 loses at most the handful of items that were mid-flight in workers at
that instant, never previously-committed work.

Keys are content-derived, not just paths, so a changed/replaced file at the
same path is correctly treated as new work rather than silently skipped:
  - zip entry:  zip::<archive_path>::<entry_name>::<size>::<crc32>
  - loose file: file::<path>::<size>::<mtime_int>
"""
from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

DONE_STATUSES = {"matched", "below_threshold", "no_face", "error"}


class Checkpoint:
    def __init__(self, db_path: str | Path):
        self.db_path = str(db_path)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self.conn.execute(
            """CREATE TABLE IF NOT EXISTS checkpoint (
                key TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                score REAL,
                detail TEXT,
                ts REAL
            )"""
        )
        self.conn.commit()
        # Full key->status map cached in memory so the producer can do an
        # O(1) "already done?" check per candidate without a DB round trip
        # for every single file discovered (there can be hundreds of
        # thousands during the full scan).
        self._cache: dict[str, str] = {}
        for key, status in self.conn.execute("SELECT key, status FROM checkpoint"):
            self._cache[key] = status

    def __len__(self):
        return len(self._cache)

    def is_done(self, key: str, retry_errors: bool = False) -> bool:
        status = self._cache.get(key)
        if status is None:
            return False
        if status == "error" and retry_errors:
            return False
        return True

    def cached_status(self, key: str) -> str | None:
        return self._cache.get(key)

    def record(self, key: str, status: str, score: float | None = None, detail: dict | None = None):
        assert status in DONE_STATUSES, f"unknown status {status!r}"
        self.conn.execute(
            "INSERT OR REPLACE INTO checkpoint(key, status, score, detail, ts) VALUES (?,?,?,?,?)",
            (key, status, score, json.dumps(detail) if detail is not None else None, time.time()),
        )
        self.conn.commit()  # immediate durable write per result, per requirement
        self._cache[key] = status

    def close(self):
        self.conn.close()
