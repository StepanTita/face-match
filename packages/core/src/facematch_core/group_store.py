"""Durable, resumable store of face detections for `facematch group`.

Distinct from Checkpoint (used by `find`): find checkpoints one row per FILE
(matched / rejected / error), because it's testing each file against an
already-known set of references. `group` doesn't know who anyone is yet - it
has to remember every individual detected FACE (its embedding, its bounding
box, which file it came from) so a second, cheap clustering pass can run over
everything collected so far without re-running detection. Resumability still
works at file granularity: a file already recorded in `files` is skipped on
restart, regardless of how many faces it contained.

Backed by SQLite, single writer (the main process - workers only return
result dicts over IPC, exactly as in worker.py), every file's result
committed immediately, same durability story as checkpoint.py.
"""
from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

import numpy as np

DONE_STATUSES = {"done", "no_face", "error"}


class GroupStore:
    def __init__(self, db_path: str | Path):
        self.db_path = str(db_path)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS files (
                file_key TEXT PRIMARY KEY,
                display_name TEXT NOT NULL,
                kind TEXT NOT NULL,
                status TEXT NOT NULL,
                error TEXT,
                loose_path TEXT,
                zip_path TEXT,
                zip_entry TEXT,
                ts REAL
            );
            CREATE TABLE IF NOT EXISTS faces (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                file_key TEXT NOT NULL,
                face_index INTEGER NOT NULL,
                embedding BLOB NOT NULL,
                bbox TEXT,
                det_score REAL,
                video_ts REAL
            );
            CREATE INDEX IF NOT EXISTS idx_faces_file_key ON faces(file_key);
            """
        )
        self.conn.commit()
        # Full file_key->status map cached in memory, same reasoning as
        # Checkpoint._cache: an O(1) "already done?" check per candidate
        # without a DB round trip for every file discovered.
        self._done_cache: dict[str, str] = {}
        for key, status in self.conn.execute("SELECT file_key, status FROM files"):
            self._done_cache[key] = status

    def __len__(self) -> int:
        return len(self._done_cache)

    def is_done(self, file_key: str, retry_errors: bool = False) -> bool:
        status = self._done_cache.get(file_key)
        if status is None:
            return False
        if status == "error" and retry_errors:
            return False
        return True

    def cached_status(self, file_key: str) -> str | None:
        return self._done_cache.get(file_key)

    def record_file(
        self,
        file_key: str,
        display_name: str,
        kind: str,
        status: str,
        error: str | None = None,
        loose_path: str | None = None,
        zip_path: str | None = None,
        zip_entry: str | None = None,
        faces: list[dict] | None = None,
    ) -> None:
        assert status in DONE_STATUSES, f"unknown status {status!r}"
        self.conn.execute(
            """INSERT OR REPLACE INTO files
               (file_key, display_name, kind, status, error, loose_path, zip_path, zip_entry, ts)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (file_key, display_name, kind, status, error, loose_path, zip_path, zip_entry, time.time()),
        )
        # A re-processed file (e.g. after --retry-errors) would leave its old
        # faces behind on a fresh record if we didn't clear them first - a
        # file is never allowed to contribute duplicate face rows.
        self.conn.execute("DELETE FROM faces WHERE file_key = ?", (file_key,))
        for i, face in enumerate(faces or []):
            emb: np.ndarray = np.asarray(face["embedding"], dtype=np.float32)
            self.conn.execute(
                "INSERT INTO faces (file_key, face_index, embedding, bbox, det_score, video_ts) "
                "VALUES (?,?,?,?,?,?)",
                (
                    file_key,
                    i,
                    emb.tobytes(),
                    json.dumps(face.get("bbox")),
                    face.get("det_score"),
                    face.get("video_ts"),
                ),
            )
        self.conn.commit()  # immediate durable write per file, per Checkpoint's contract
        self._done_cache[file_key] = status

    def iter_faces(self):
        """Yield (file_key, embedding: np.ndarray[float32]) for every recorded face."""
        cur = self.conn.execute("SELECT file_key, embedding FROM faces")
        for file_key, blob in cur:
            yield file_key, np.frombuffer(blob, dtype=np.float32)

    def file_info(self, file_key: str) -> dict | None:
        row = self.conn.execute(
            "SELECT display_name, kind, status, loose_path, zip_path, zip_entry FROM files WHERE file_key = ?",
            (file_key,),
        ).fetchone()
        if row is None:
            return None
        display_name, kind, status, loose_path, zip_path, zip_entry = row
        return {
            "display_name": display_name,
            "kind": kind,
            "status": status,
            "loose_path": loose_path,
            "zip_path": zip_path,
            "zip_entry": zip_entry,
        }

    def stats(self) -> dict:
        total_faces = self.conn.execute("SELECT COUNT(*) FROM faces").fetchone()[0]
        return {"files": len(self._done_cache), "faces": total_faces}

    def close(self):
        self.conn.close()
