"""Bookkeeping for `--background` runs: a small on-disk record per run under
`.facematch/runs/<run_id>/`, so `facematch find status` (or a later session
entirely) can find out how a detached run is doing, or how it ended.

    meta.json    run id, command, args, pid, start/end time, exit_status
    status.json  the latest ProgressSnapshot, written periodically
    log.txt      the run's stdout/stderr (argparse errors, per-file prints)

No daemon/service manager involved: "is it still running" is answered with
a liveness check on the recorded pid (os.kill(pid, 0)), which is the
simplest thing that works for a single-machine personal-use tool.
"""
from __future__ import annotations

import dataclasses
import json
import os
import time
import uuid
from pathlib import Path

from . import paths


def new_run_id() -> str:
    return f"{time.strftime('%Y%m%dT%H%M%S')}-{uuid.uuid4().hex[:6]}"


def _atomic_write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, default=str))
    tmp.replace(path)


def _read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


class RunState:
    def __init__(self, run_id: str):
        self.run_id = run_id
        self.dir = paths.run_dir(run_id)
        self.meta_path = self.dir / "meta.json"
        self.status_path = self.dir / "status.json"
        self.log_path = self.dir / "log.txt"

    def write_meta(self, **fields) -> None:
        meta = _read_json(self.meta_path)
        meta.update(fields)
        _atomic_write_json(self.meta_path, meta)

    def read_meta(self) -> dict:
        return _read_json(self.meta_path)

    def write_status(self, snapshot) -> None:
        _atomic_write_json(self.status_path, dataclasses.asdict(snapshot))

    def read_status(self) -> dict:
        return _read_json(self.status_path)


def pid_alive(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # Exists, just owned by someone else (or elevated) - treat as alive.
        return True
    except OSError:
        return False
    return True


def run_state_label(meta: dict, alive: bool) -> str:
    """One of 'running', 'finished', 'crashed'."""
    exit_status = meta.get("exit_status")
    if exit_status == "finished":
        return "finished"
    if exit_status == "crashed":
        return "crashed"
    if alive:
        return "running"
    # Process is gone but never recorded an exit status: killed, or crashed
    # hard enough to skip the finally block (e.g. SIGKILL).
    return "crashed"
