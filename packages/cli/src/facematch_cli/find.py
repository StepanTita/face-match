"""`facematch find` - scan an archive for matches against your reference photos.

Parallel, resumable, and able to run detached in the background.

Architecture:
    - Main process enumerates candidates (walks directories / streams zip
      listings) and feeds them, one at a time, into a multiprocessing.Pool
      via imap_unordered. This is the "producer" - it never extracts or
      decodes anything itself, just lists what needs doing. Anything already
      recorded in checkpoint.sqlite3 (see facematch_core.checkpoint) is
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
      process, which is the sole writer of matches.csv and checkpoint.sqlite3
      - avoiding any multi-process file-write races on those.
    - Every result is committed to checkpoint.sqlite3 as it arrives (not
      batched), so a crash/kill loses at most a few in-flight items. Re-running
      the same command afterwards resumes: already-checkpointed items are
      skipped, matches.csv/matched/ are appended to (never wiped).
    - `--background` re-invokes this same command as a detached child process
      (see runstate.py) instead of a second execution mode bolted on here;
      the child is just a normal `find` run with a `--_run-id` it uses to
      write status.json instead of drawing a tqdm bar. `find status` and
      `find restart` (below) are the other two pieces of that job-control
      story.
"""
from __future__ import annotations

import argparse
import csv
import multiprocessing
import os
import subprocess
import sys
import time
from pathlib import Path
from textwrap import dedent

import numpy as np
from tqdm import tqdm

from facematch_core.checkpoint import Checkpoint
from facematch_core.decode import ffmpeg_available
from facematch_core.events import ProgressTracker
from facematch_core.match import DEFAULT_THRESHOLD
from facematch_core.sources import enumerate_source
from facematch_core.worker import init_worker, process_candidate

from . import paths, runstate
from .config import get_default_sources


def load_reference_embeddings() -> dict[str, np.ndarray]:
    """Returns person-label -> stacked [Ni, 512] reference embeddings.

    Classic (non-named) reference sets - and any pre-existing
    reference_embeddings.npz written before multi-person support existed,
    which has no "persons" array at all - come back as {"": embeddings}.
    Named mode (references/<person>/ subfolders) comes back with one entry
    per person. See build_references.py and facematch_core.worker.
    """
    path = paths.reference_embeddings_path()
    if not path.exists():
        print("ERROR: reference_embeddings.npz not found. Run `facematch build-references` first.")
        sys.exit(1)
    data = np.load(path)
    embeddings = data["embeddings"]
    persons = data["persons"] if "persons" in data.files else np.array([""] * len(embeddings))

    grouped: dict[str, list] = {}
    for emb, person in zip(embeddings, persons):
        grouped.setdefault(str(person), []).append(emb)
    return {name: np.stack(embs).astype(np.float32) for name, embs in grouped.items()}


def is_named_mode(refs: dict[str, np.ndarray]) -> bool:
    return any(person != "" for person in refs)


def _status_to_kind(status: str) -> str:
    if status == "matched":
        return "matched"
    if status == "error":
        return "errored"
    return "rejected"  # "no_face" or "below_threshold"


def candidate_generator(sources: list[str], scratch_root: str, tracker: ProgressTracker,
                         checkpoint: Checkpoint, retry_errors: bool, log):
    """The producer: enumerates all sources lazily. Every candidate counts as
    'discovered' immediately. Anything already checkpointed is tallied from
    its cached status and skipped without ever reaching a worker; everything
    else is yielded on to the pool."""
    skipped = 0
    for source in sources:
        if not os.path.exists(source):
            log(f"[warn] source not found, skipping: {source}")
            continue
        tracker.set_current_source(f"[enumerating] {source}")
        log(f"=== Scanning source: {source} ===")
        for cand in enumerate_source(source, scratch_root):
            tracker.add_discovered()
            if checkpoint.is_done(cand.key, retry_errors=retry_errors):
                status = checkpoint.cached_status(cand.key)
                tracker.record_processed(_status_to_kind(status))
                skipped += 1
                continue
            yield cand
    tracker.set_total_known()
    if skipped:
        log(f"[resume] skipped {skipped} already-checkpointed items")


# ---------------------------------------------------------------------------
# argparse wiring: `facematch find [run flags]`, plus two nested actions,
# `facematch find status` and `facematch find restart`.
# ---------------------------------------------------------------------------

def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.formatter_class = argparse.RawDescriptionHelpFormatter
    parser.description = "Scan a source (folder or zip) for files matching your reference photos."
    parser.epilog = dedent("""\
        examples:
          facematch find                                   run in the foreground; shows a live progress bar
          facematch find --sources ~/Photos a.zip           scan specific paths instead of sources.local.json
          facematch find --threshold 0.45 --workers 4       stricter match, fewer worker processes
          facematch find --limit 20                         stop after 20 newly-processed files (for a quick test)
          facematch find --background                       start the same scan detached; prints a run id
          facematch find status                              check on the most recent run (background or not)
          facematch find status --watch                      keep watching a background run until it finishes
          facematch find restart                              wipe checkpoint + match log, then run again fresh
          facematch find --no-dedupe                          skip the automatic post-scan dedupe pass

        want to find several people in one pass instead of one at a time? put each
        person's photos in their own references/<person>/ subfolder (see
        `facematch build-references --help`) - find matches an archive against all
        of them in a single scan, copying results into matched/<person>/ instead of
        matched/ (a file with more than one of them in it lands in every relevant
        person's folder, same as `facematch group`).

        by default, a run RESUMES: anything already recorded in checkpoint.sqlite3
        is skipped instantly. use `facematch find restart` when you want to
        re-scan everything from zero instead.

        when the scan finishes, `facematch dedupe` runs automatically on matched/ -
        the same photo often exists more than once across overlapping backup
        sources, so this collapses exact and near-duplicate copies for you (see
        `facematch dedupe --help`). pass --no-dedupe to skip this and inspect the
        raw, undeduplicated output instead.
        """)
    parser.add_argument(
        "--sources", nargs="+", default=None,
        help="Paths/zips to scan. Defaults to the 'sources' list in sources.local.json "
             "(see sources.example.json) if omitted.",
    )
    parser.add_argument(
        "--threshold", type=float, default=DEFAULT_THRESHOLD,
        help=f"Cosine similarity cutoff for a match, 0-1 (default: {DEFAULT_THRESHOLD}, tuned for recall - "
             "lower catches more true matches at the cost of more false positives).",
    )
    parser.add_argument(
        "--limit", type=int, default=None,
        help="Stop after N newly-processed candidates. Handy for a quick test run before committing to a full scan.",
    )
    parser.add_argument(
        "--workers", type=int, default=max(1, (os.cpu_count() or 2) - 1),
        help="Worker process count (default: cpu_count - 1, leaving one core free).",
    )
    parser.add_argument(
        "--retry-errors", action="store_true",
        help="Re-attempt items previously checkpointed as 'error' instead of skipping them.",
    )
    parser.add_argument(
        "--background", action="store_true",
        help="Start this same scan as a detached background process and return immediately. "
             "Check on it with `facematch find status`.",
    )
    parser.add_argument(
        "--no-dedupe", action="store_true",
        help="Skip the automatic `facematch dedupe` pass this command normally runs on matched/ "
             "when it finishes, so you see the raw, undeduplicated output instead.",
    )
    # Internal: set automatically on the detached child process spawned by
    # --background, so it knows to write status.json instead of drawing a
    # tqdm bar. Not meant to be passed by hand.
    parser.add_argument("--_run-id", dest="_run_id", default=None, help=argparse.SUPPRESS)

    nested = parser.add_subparsers(dest="find_action")

    status_p = nested.add_parser(
        "status",
        help="Show the progress of a background (or the most recent) find run",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=dedent("""\
            examples:
              facematch find status                  show the most recent run's progress
              facematch find status --run-id 20260926T101500-a1b2c3
              facematch find status --watch          keep refreshing until the run finishes
            """),
    )
    status_p.add_argument("--run-id", default=None, help="Which run to inspect (default: the most recent one).")
    status_p.add_argument("--watch", action="store_true", help="Poll and re-print the status until the run ends.")

    restart_p = nested.add_parser(
        "restart",
        help="Delete the checkpoint DB and match log so the next find re-scans everything from scratch",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=dedent("""\
            examples:
              facematch find restart          asks for confirmation, then resets
              facematch find restart --yes    resets without asking

            this removes checkpoint.sqlite3 and matched/matches.csv (so every file
            looks unprocessed again on the next `facematch find`). files already
            copied into matched/ are left in place - re-scanning will just find and
            re-log them again, not duplicate them.
            """),
    )
    restart_p.add_argument("--yes", action="store_true", help="Skip the confirmation prompt.")


def run(args: argparse.Namespace) -> None:
    action = getattr(args, "find_action", None)
    if action == "status":
        return run_status(args)
    if action == "restart":
        return run_restart(args)
    return run_scan(args)


# ---------------------------------------------------------------------------
# `facematch find` (default action): run the scan, foreground or background.
# ---------------------------------------------------------------------------

def run_scan(args: argparse.Namespace) -> None:
    sources = args.sources or get_default_sources()
    if not sources:
        print("ERROR: no sources given. Pass --sources, or create sources.local.json (see sources.example.json).")
        sys.exit(1)

    if not ffmpeg_available():
        print(
            "WARNING: ffmpeg/ffprobe not found on PATH. Video files in your "
            "sources will fail with an error; images are unaffected. Install "
            "ffmpeg (e.g. `brew install ffmpeg` on macOS) to support video.",
            file=sys.stderr,
        )

    if args.background and not args._run_id:
        _start_background(args)
        return

    is_background_child = bool(args._run_id)
    state = runstate.RunState("find", args._run_id) if is_background_child else None

    if state is not None:
        log = print  # stdout is already redirected to the run's log.txt by the parent
        on_update = lambda snap: state.write_status(snap)  # noqa: E731
        pbar = None
    else:
        pbar = tqdm(unit="file", dynamic_ncols=True, desc="find")
        log = tqdm.write

        def on_update(snap):
            if snap.total_known:
                pbar.total = snap.total_discovered
            pbar.n = snap.processed
            pbar.set_postfix(matched=snap.matched, rejected=snap.rejected, errored=snap.errored, refresh=False)
            pbar.refresh()

    matched_dir = paths.matched_dir()
    thumbs_dir = paths.thumbs_dir()
    scratch_root = paths.scratch_root("scan")
    log_path = paths.matches_csv()
    checkpoint_path = paths.checkpoint_path()

    matched_dir.mkdir(parents=True, exist_ok=True)
    thumbs_dir.mkdir(parents=True, exist_ok=True)
    scratch_root.mkdir(parents=True, exist_ok=True)

    refs = load_reference_embeddings()
    named = is_named_mode(refs)
    checkpoint = Checkpoint(checkpoint_path)
    if named:
        breakdown = ", ".join(f"{person} ({refs[person].shape[0]})" for person in refs)
        log(f"Loaded references for {len(refs)} people: {breakdown}. "
            f"Threshold={args.threshold}. Workers={args.workers}")
    else:
        log(f"Loaded {refs[''].shape[0]} reference embeddings. Threshold={args.threshold}. Workers={args.workers}")
    log(f"Checkpoint: {len(checkpoint)} items already recorded in {checkpoint_path}")

    tracker = ProgressTracker(on_update=on_update)
    tracker.set_phase("processing")

    log_is_new = not log_path.exists()

    # One intra-op thread per worker process: with N worker PROCESSES already
    # providing parallelism across cores, letting each process's ONNX Runtime
    # session ALSO spin up its own multi-core thread pool would oversubscribe
    # the machine N-fold. See facematch_core.model.get_face_app's docstring.
    intra_op_threads = 1

    exit_status = "finished"
    try:
        with open(log_path, "a", newline="") as logf, \
             multiprocessing.Pool(
                 processes=args.workers,
                 initializer=init_worker,
                 initargs=(refs, args.threshold, str(scratch_root), str(matched_dir), str(thumbs_dir), intra_op_threads),
             ) as pool:
            csv_writer = csv.writer(logf)
            if log_is_new:
                csv_writer.writerow(["source", "status", "score", "detail"])

            gen = candidate_generator(sources, str(scratch_root), tracker, checkpoint, args.retry_errors, log)
            count = 0
            for result in pool.imap_unordered(process_candidate, gen, chunksize=1):
                status = result["status"]
                key = result["key"]
                tracker.set_current_source(result["display_name"])

                if status == "matched" and not named:
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
                elif status == "matched" and named:
                    matches = result["matches"]
                    detail = {
                        "type": result.get("kind", "image"),
                        "source": result["display_name"],
                        "thumb": result.get("thumb", ""),
                        "persons": {p: round(m["score"], 3) for p, m in matches.items()},
                    }
                    tracker.record_processed("matched", detail)
                    for person, m in matches.items():
                        csv_writer.writerow([
                            result["display_name"], "matched", f"{m['score']:.4f}", m["dest_path"],
                        ])
                    checkpoint.record(key, "matched", max(m["score"] for m in matches.values()), {
                        "matches": matches,
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
                    log(f"[limit reached] stopping after {count} newly-processed candidates")
                    break
    except BaseException as e:
        exit_status = "crashed"
        if state is not None:
            state.write_meta(exit_status="crashed", error=str(e), ended_at=time.time())
        raise
    finally:
        tracker.finish()
        checkpoint.close()
        if pbar is not None:
            pbar.close()
        if state is not None and exit_status == "finished":
            state.write_meta(exit_status="finished", ended_at=time.time())

    log("Find complete.")

    if not args.no_dedupe:
        from . import dedupe as dedupe_module
        try:
            if named:
                log(f"Deduplicating each folder under {matched_dir} independently ...")
                subdirs = sorted(
                    p for p in matched_dir.iterdir()
                    if p.is_dir() and p.name not in dedupe_module._RESERVED_SUBDIR_NAMES
                )
                for sub in subdirs:
                    dedupe_module.dedupe_directory(sub, log=log)
            else:
                log("Deduplicating matched/ ...")
                dedupe_module.dedupe_directory(matched_dir, log=log)
        except Exception as e:
            log(f"[warn] automatic dedupe failed (matched/ is untouched, your results are fine): {e}")


def _child_argv(args: argparse.Namespace, run_id: str) -> list[str]:
    argv = ["find"]
    if args.sources:
        argv += ["--sources", *args.sources]
    argv += ["--threshold", str(args.threshold)]
    if args.limit is not None:
        argv += ["--limit", str(args.limit)]
    argv += ["--workers", str(args.workers)]
    if args.retry_errors:
        argv.append("--retry-errors")
    if args.no_dedupe:
        argv.append("--no-dedupe")
    argv += ["--_run-id", run_id]
    return argv


def _start_background(args: argparse.Namespace) -> None:
    run_id = runstate.new_run_id()
    state = runstate.RunState("find", run_id)
    state.dir.mkdir(parents=True, exist_ok=True)
    state.write_meta(
        run_id=run_id,
        command="find",
        args={
            "sources": args.sources,
            "threshold": args.threshold,
            "limit": args.limit,
            "workers": args.workers,
            "retry_errors": args.retry_errors,
            "no_dedupe": args.no_dedupe,
        },
        started_at=time.time(),
        cwd=str(paths.project_dir()),
        pid=None,
        exit_status=None,
    )

    child_argv = _child_argv(args, run_id)
    with open(state.log_path, "wb") as logf:
        proc = subprocess.Popen(
            [sys.executable, "-m", "facematch_cli", *child_argv],
            stdout=logf,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            cwd=str(paths.project_dir()),
            start_new_session=True,  # detach from this terminal/session entirely
        )
    state.write_meta(pid=proc.pid)

    print(f"Started find in the background (run id: {run_id}, pid {proc.pid}).")
    print(f"  facematch find status                check its progress")
    print(f"  facematch find status --watch         follow it live")
    print(f"  log: {state.log_path}")


# ---------------------------------------------------------------------------
# `facematch find status`
# ---------------------------------------------------------------------------

def _format_status_line(run_id: str, meta: dict, status: dict, state_label: str) -> str:
    processed = status.get("processed", 0)
    total = status.get("total_discovered", 0)
    total_known = status.get("total_known", False)
    matched = status.get("matched", 0)
    rejected = status.get("rejected", 0)
    errored = status.get("errored", 0)
    rate = status.get("rate_per_min", 0.0)
    elapsed = status.get("elapsed_seconds", 0.0)
    phase = status.get("phase", "starting")

    progress = f"{processed}/{total}" if total_known else f"{processed} (still enumerating)"
    eta = ""
    if total_known and rate > 0 and total > processed:
        remaining_min = (total - processed) / rate
        eta = f", ETA ~{remaining_min:.1f} min"

    lines = [
        f"run {run_id}  [{state_label}]",
        f"  phase: {phase}",
        f"  processed: {progress}{eta}",
        f"  matched: {matched}   rejected: {rejected}   errored: {errored}",
        f"  rate: {rate:.1f}/min   elapsed: {elapsed:.0f}s",
    ]
    if meta.get("error"):
        lines.append(f"  error: {meta['error']}")
    return "\n".join(lines)


def run_status(args: argparse.Namespace) -> None:
    run_id = args.run_id or paths.latest_run_id("find")
    if run_id is None:
        print("No find runs recorded yet. Start one with `facematch find --background`.")
        sys.exit(1)

    state = runstate.RunState("find", run_id)
    if not state.dir.exists():
        print(f"ERROR: no run '{run_id}' found under {paths.runs_root('find')}")
        sys.exit(1)

    try:
        while True:
            meta = state.read_meta()
            status = state.read_status()
            alive = runstate.pid_alive(meta.get("pid"))
            label = runstate.run_state_label(meta, alive)
            print(_format_status_line(run_id, meta, status, label))
            if not args.watch or label != "running":
                if label == "crashed":
                    sys.exit(1)
                return
            print("-" * 40)
            time.sleep(2.0)
    except KeyboardInterrupt:
        print("\n[stopped watching - the run itself keeps going in the background]")


# ---------------------------------------------------------------------------
# `facematch find restart`
# ---------------------------------------------------------------------------

def run_restart(args: argparse.Namespace) -> None:
    checkpoint_path = paths.checkpoint_path()
    to_remove = [
        checkpoint_path,
        checkpoint_path.with_name(checkpoint_path.name + "-wal"),
        checkpoint_path.with_name(checkpoint_path.name + "-shm"),
        paths.matches_csv(),
    ]
    existing = [p for p in to_remove if p.exists()]

    if not existing:
        print("Nothing to reset - no previous find run found here.")
        return

    if not args.yes:
        print("This will delete:")
        for p in existing:
            print(f"  - {p}")
        print("Files already copied into matched/ are NOT deleted - only the checkpoint/log "
              "that tracks what's already been scanned.")
        reply = input("Continue? [y/N] ").strip().lower()
        if reply not in ("y", "yes"):
            print("Aborted.")
            return

    for p in existing:
        p.unlink()
    print(f"Removed {len(existing)} file(s). Ready for a fresh `facematch find`.")
