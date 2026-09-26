"""Main face-matching scan over a personal photo/video archive - PARALLEL + RESUMABLE.

Usage:
    uv run scan.py --sources "/path/a" "/path/b/archive.zip" [--threshold 0.38] [--workers 9] [--limit 200] [--retry-errors]
    # or, with sources.local.json in place (see sources.example.json):
    uv run scan.py [--threshold 0.38] [--workers 9] [--limit 200] [--retry-errors]

Architecture:
    - Main process enumerates candidates (walks directories / streams zip
      listings) and feeds them, one at a time, into a multiprocessing.Pool
      via imap_unordered. This is the "producer" - it never extracts or
      decodes anything itself, just lists what needs doing. Anything already
      recorded in checkpoint.sqlite3 (see facematch/checkpoint.py) is
      immediately tallied from its cached outcome and skipped, without ever
      touching a worker - this is what makes a resumed run fast for the part
      it already did.
    - A pool of worker PROCESSES (default: cpu_count - 1) each load their own
      InsightFace model once (ONNX Runtime sessions cannot be shared across
      processes) and pull candidates from the pool's internal task queue.
      Each worker extracts its own single entry to a dedicated per-worker
      scratch subdirectory (keyed by PID, so concurrent workers never collide
      on temp filenames), decodes it, runs detection+embedding+matching, does
      its own file copy for matches (dest filenames are derived from the
      unique source path, so concurrent writers never collide either), then
      deletes the temp file immediately - the "stream, don't fully extract"
      constraint is preserved per-worker.
    - Only small JSON-able result dicts (a base64 thumbnail for genuine
      matches, no raw image/video bytes) cross back over IPC to the main
      process, which is the sole writer of matches.csv, checkpoint.sqlite3 and
      progress.json - avoiding any multi-process file-write races on those.
    - Every result is committed to checkpoint.sqlite3 as it arrives (not
      batched), so a crash/kill loses at most a few in-flight items. Re-running
      the same command afterwards resumes: already-checkpointed items are
      skipped, matches.csv/matched/ are appended to (never wiped), and
      progress.json's counters reflect the full re-walk (fast-skips count
      instantly, so a resumed run's progress bar catches up to where it left
      off almost immediately, then continues at normal processing speed).
"""
from __future__ import annotations

import argparse
import csv
import multiprocessing
import os
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent / "src"))
from facematch.checkpoint import Checkpoint  # noqa: E402
from facematch.config import get_default_sources  # noqa: E402
from facematch.core import DEFAULT_THRESHOLD  # noqa: E402
from facematch.progress import ProgressTracker  # noqa: E402
from facematch.sources import enumerate_source  # noqa: E402
from facematch.worker import init_worker, process_candidate  # noqa: E402

PROJECT_DIR = Path(__file__).parent
MATCHED_DIR = PROJECT_DIR / "matched"
THUMBS_DIR = MATCHED_DIR / "video_thumbnails"
SCRATCH_ROOT = PROJECT_DIR / "scratch" / "scan"
LOG_PATH = MATCHED_DIR / "matches.csv"
CHECKPOINT_PATH = PROJECT_DIR / "checkpoint.sqlite3"


def load_reference_embeddings() -> np.ndarray:
    path = PROJECT_DIR / "reference_embeddings.npz"
    if not path.exists():
        print("ERROR: reference_embeddings.npz not found. Run build_references.py first.")
        sys.exit(1)
    data = np.load(path)
    return data["embeddings"]


def _status_to_kind(status: str) -> str:
    if status == "matched":
        return "matched"
    if status == "error":
        return "errored"
    return "rejected"  # "no_face" or "below_threshold"


def candidate_generator(sources: list[str], scratch_root: str, tracker: ProgressTracker,
                         checkpoint: Checkpoint, retry_errors: bool):
    """The producer: enumerates all sources lazily. Every candidate counts as
    'discovered' immediately. Anything already checkpointed is tallied from
    its cached status and skipped without ever reaching a worker; everything
    else is yielded on to the pool."""
    skipped = 0
    for source in sources:
        if not os.path.exists(source):
            print(f"[warn] source not found, skipping: {source}")
            continue
        tracker.set_current_source(f"[enumerating] {source}")
        print(f"\n=== Scanning source: {source} ===")
        for cand in enumerate_source(source, scratch_root):
            tracker.add_discovered()
            if checkpoint.is_done(cand.key, retry_errors=retry_errors):
                status = checkpoint.cached_status(cand.key)
                tracker.record_processed(_status_to_kind(status))
                skipped += 1
                continue
            yield cand
    if skipped:
        print(f"\n[resume] skipped {skipped} already-checkpointed items")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--sources", nargs="+", default=None,
        help="Paths/zips to scan. Defaults to the 'sources' list in sources.local.json "
             "(see sources.example.json) if omitted.",
    )
    parser.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD)
    parser.add_argument("--limit", type=int, default=None, help="Stop after N NEWLY processed candidates (testing)")
    parser.add_argument(
        "--workers", type=int, default=max(1, (os.cpu_count() or 2) - 1),
        help="Worker process count (default: cpu_count - 1, leaving one core free)",
    )
    parser.add_argument(
        "--retry-errors", action="store_true",
        help="Re-attempt items previously checkpointed as 'error' instead of skipping them",
    )
    args = parser.parse_args()

    sources = args.sources or get_default_sources()
    if not sources:
        print("ERROR: no sources given. Pass --sources, or create sources.local.json (see sources.example.json).")
        sys.exit(1)
    MATCHED_DIR.mkdir(parents=True, exist_ok=True)
    THUMBS_DIR.mkdir(parents=True, exist_ok=True)
    SCRATCH_ROOT.mkdir(parents=True, exist_ok=True)

    refs = load_reference_embeddings()
    checkpoint = Checkpoint(CHECKPOINT_PATH)
    print(f"Loaded {refs.shape[0]} reference embeddings. Threshold={args.threshold}. Workers={args.workers}")
    print(f"Checkpoint: {len(checkpoint)} items already recorded in {CHECKPOINT_PATH}")

    tracker = ProgressTracker()
    tracker.set_phase("processing")

    log_is_new = not LOG_PATH.exists()

    # One intra-op thread per worker process: with N worker PROCESSES already
    # providing parallelism across cores, letting each process's ONNX Runtime
    # session ALSO spin up its own multi-core thread pool would oversubscribe
    # the machine N-fold. See core.get_face_app's docstring for the reasoning.
    intra_op_threads = 1

    try:
        with open(LOG_PATH, "a", newline="") as logf, \
             multiprocessing.Pool(
                 processes=args.workers,
                 initializer=init_worker,
                 initargs=(refs, args.threshold, str(SCRATCH_ROOT), str(MATCHED_DIR), str(THUMBS_DIR), intra_op_threads),
             ) as pool:
            csv_writer = csv.writer(logf)
            if log_is_new:
                csv_writer.writerow(["source", "status", "score", "detail"])

            gen = candidate_generator(sources, str(SCRATCH_ROOT), tracker, checkpoint, args.retry_errors)
            count = 0
            for result in pool.imap_unordered(process_candidate, gen, chunksize=1):
                status = result["status"]
                key = result["key"]
                tracker.set_current_source(result["display_name"])

                if status == "matched":
                    detail = {
                        "type": result.get("kind", "image"),
                        "name": Path(result["dest_path"]).name,
                        "confidence": round(result["score"], 3),
                        "source": result["display_name"],
                        "thumb": result.get("thumb", ""),
                    }
                    if "timestamps" in result:
                        detail["timestamps"] = result["timestamps"]
                    tracker.record_processed("matched", detail)
                    csv_writer.writerow([
                        result["display_name"], "matched", f"{result['score']:.4f}", result["dest_path"],
                    ])
                    checkpoint.record(key, "matched", result["score"], {
                        "dest_path": result["dest_path"],
                        "timestamps": result.get("timestamps"),
                    })
                elif status == "error":
                    tracker.record_processed("errored")
                    err = result.get("error", "")
                    csv_writer.writerow([result["display_name"], "error", "", err])
                    checkpoint.record(key, "error", None, {"error": err})
                else:
                    # "no_face" or "below_threshold"
                    tracker.record_processed("rejected")
                    score = result.get("score", "")
                    score_str = f"{score:.4f}" if isinstance(score, float) else ""
                    csv_writer.writerow([result["display_name"], status, score_str, ""])
                    checkpoint.record(key, status, result.get("score"))

                count += 1
                if count % 20 == 0:
                    logf.flush()
                if args.limit and count >= args.limit:
                    print(f"\n[limit reached] stopping after {count} newly-processed candidates")
                    break
    finally:
        tracker.finish()
        checkpoint.close()

    print("\nScan complete.")


if __name__ == "__main__":
    main()
