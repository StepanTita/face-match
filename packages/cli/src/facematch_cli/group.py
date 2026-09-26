"""`facematch group` - cluster every face across an archive by person, with
no reference photos required.

Two-pass design:
    Pass 1 (detection - expensive, parallel, resumable): walks all sources
    exactly like `find` does, but instead of matching each face against a
    known reference set, it detects and embeds EVERY face in EVERY file and
    records them in group_checkpoint.sqlite3 (see facematch_core.group_store)
    - one row per file (for resumability) plus one row per detected face
    (embedding + bounding box + optional video timestamp). A file already
    recorded is skipped on restart, exactly like find's checkpoint.

    Pass 2 (clustering - cheap, single-process): loads every face embedding
    collected so far, clusters them by cosine similarity into per-person
    groups via a union-find over a similarity graph (see
    facematch_core.cluster - no scikit-learn needed, this is a simple graph-
    connectivity problem), then materializes the result as `person_001/`,
    `person_002/`, ... folders under --out, each containing every file that
    person appears in (a file with several people in it is copied into
    several folders). Faces that don't form a large-enough cluster land in
    `unclustered/` instead of being silently dropped - nothing detected is
    ever dropped, only ungrouped. Pass 2 re-runs from scratch every
    invocation since it's fast relative to detection; there's no reason to
    checkpoint it separately.

Job control (--background / status / restart) reuses the exact same
runstate.py machinery as `find`, namespaced under its own "group" run
directory (see paths.runs_root) so the two commands' background runs never
collide or shadow each other.
"""
from __future__ import annotations

import argparse
import multiprocessing
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from textwrap import dedent

import numpy as np
from tqdm import tqdm

from facematch_core.cluster import (
    DEFAULT_MERGE_THRESHOLD,
    DEFAULT_MIN_CLUSTER_SIZE,
    cluster_embeddings,
    sort_clusters_by_size,
)
from facematch_core.events import ProgressTracker
from facematch_core.group_store import GroupStore
from facematch_core.sources import Candidate, enumerate_source
from facematch_core.worker import init_worker_group, process_candidate_group, safe_dest_name

from . import paths, runstate
from .config import get_default_sources


def candidate_generator(sources: list[str], scratch_root: str, tracker: ProgressTracker,
                         store: GroupStore, retry_errors: bool, log, cand_registry: dict):
    """The producer: enumerates all sources lazily. Anything already recorded
    in group_checkpoint.sqlite3 is tallied from its cached status and skipped
    without reaching a worker. Everything else is registered (so its source
    location is available once its result comes back, out of order, from the
    pool) and yielded on."""
    skipped = 0
    for source in sources:
        if not os.path.exists(source):
            log(f"[warn] source not found, skipping: {source}")
            continue
        tracker.set_current_source(f"[enumerating] {source}")
        log(f"=== Scanning source: {source} ===")
        for cand in enumerate_source(source, scratch_root):
            tracker.add_discovered()
            if store.is_done(cand.key, retry_errors=retry_errors):
                status = store.cached_status(cand.key)
                kind = "errored" if status == "error" else "rejected" if status == "no_face" else "matched"
                tracker.record_processed(kind)
                skipped += 1
                continue
            cand_registry[cand.key] = cand
            yield cand
    tracker.set_total_known()
    if skipped:
        log(f"[resume] skipped {skipped} already-processed items")


# ---------------------------------------------------------------------------
# argparse wiring: `facematch group [run flags]`, plus two nested actions,
# `facematch group status` and `facematch group restart`.
# ---------------------------------------------------------------------------

def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.formatter_class = argparse.RawDescriptionHelpFormatter
    parser.description = (
        "Cluster every face found across a source (folder or zip) into per-person "
        "folders, with no reference photos required."
    )
    parser.epilog = dedent(f"""\
        examples:
          facematch group                                          run in the foreground; shows a live progress bar
          facematch group --sources ~/Photos a.zip                  scan specific paths instead of sources.local.json
          facematch group --out ~/Photos-by-person                  choose where person_NNN/ folders are written
          facematch group --threshold 0.52 --min-cluster-size 3     stricter merging, fewer/larger person groups
          facematch group --limit 20                                stop detection after 20 newly-processed files
          facematch group --background                              start the same scan detached; prints a run id
          facematch group status                                    check on the most recent run (background or not)
          facematch group status --watch                            keep watching a background run until it finishes
          facematch group restart                                   wipe the face-detection checkpoint, then run again fresh

        by default, a run RESUMES: any file already recorded in
        group_checkpoint.sqlite3 is skipped instantly during detection (its
        already-detected faces are still included in clustering). use
        `facematch group restart` to re-detect everything from zero instead.

        every detected face ends up somewhere under --out: in a person_NNN/
        folder if it's part of a large-enough cluster, or in unclustered/ if
        not (a stranger in the background, a bad detection, or just not
        enough photos of that person yet to form a confident group) -
        nothing is ever dropped silently. a file with several people in it
        is copied into every relevant person's folder.
        """)
    parser.add_argument(
        "--sources", nargs="+", default=None,
        help="Paths/zips to scan. Defaults to the 'sources' list in sources.local.json "
             "(see sources.example.json) if omitted.",
    )
    parser.add_argument(
        "--out", default=None,
        help=f"Where to write person_NNN/ and unclustered/ folders (default: {paths.default_grouped_dir()}).",
    )
    parser.add_argument(
        "--threshold", type=float, default=DEFAULT_MERGE_THRESHOLD,
        help=f"Cosine similarity cutoff to merge two faces into the same person, 0-1 "
             f"(default: {DEFAULT_MERGE_THRESHOLD} - stricter than find's, since merging two "
             "different people is a worse mistake here than under-merging one person into two groups).",
    )
    parser.add_argument(
        "--min-cluster-size", type=int, default=DEFAULT_MIN_CLUSTER_SIZE,
        help=f"Smallest cluster that counts as a real person (default: {DEFAULT_MIN_CLUSTER_SIZE}). "
             "Smaller clusters land in unclustered/ instead of getting their own folder.",
    )
    parser.add_argument(
        "--limit", type=int, default=None,
        help="Stop detection after N newly-processed candidates. Handy for a quick test before a full scan.",
    )
    parser.add_argument(
        "--workers", type=int, default=max(1, (os.cpu_count() or 2) - 1),
        help="Worker process count for the detection pass (default: cpu_count - 1).",
    )
    parser.add_argument(
        "--retry-errors", action="store_true",
        help="Re-attempt files previously checkpointed as 'error' instead of skipping them.",
    )
    parser.add_argument(
        "--background", action="store_true",
        help="Start this same scan as a detached background process and return immediately. "
             "Check on it with `facematch group status`.",
    )
    # Internal: set automatically on the detached child process spawned by
    # --background, so it knows to write status.json instead of drawing a
    # tqdm bar. Not meant to be passed by hand.
    parser.add_argument("--_run-id", dest="_run_id", default=None, help=argparse.SUPPRESS)

    nested = parser.add_subparsers(dest="group_action")

    status_p = nested.add_parser(
        "status",
        help="Show the progress of a background (or the most recent) group run",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=dedent("""\
            examples:
              facematch group status                  show the most recent run's progress
              facematch group status --run-id 20260926T101500-a1b2c3
              facematch group status --watch          keep refreshing until the run finishes
            """),
    )
    status_p.add_argument("--run-id", default=None, help="Which run to inspect (default: the most recent one).")
    status_p.add_argument("--watch", action="store_true", help="Poll and re-print the status until the run ends.")

    restart_p = nested.add_parser(
        "restart",
        help="Delete the face-detection checkpoint so the next group re-scans everything from scratch",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=dedent("""\
            examples:
              facematch group restart          asks for confirmation, then resets
              facematch group restart --yes    resets without asking

            this removes group_checkpoint.sqlite3 (so every file looks
            unprocessed again on the next `facematch group`). folders already
            written under --out are left in place - re-running will just
            re-detect and re-cluster, adding/overwriting files there as
            needed, never deleting anything already found.
            """),
    )
    restart_p.add_argument("--yes", action="store_true", help="Skip the confirmation prompt.")


def run(args: argparse.Namespace) -> None:
    if args.out is None:
        args.out = str(paths.default_grouped_dir())
    action = getattr(args, "group_action", None)
    if action == "status":
        return run_status(args)
    if action == "restart":
        return run_restart(args)
    return run_scan(args)


# ---------------------------------------------------------------------------
# `facematch group` (default action): detect, cluster, materialize -
# foreground or background.
# ---------------------------------------------------------------------------

def run_scan(args: argparse.Namespace) -> None:
    sources = args.sources or get_default_sources()
    if not sources:
        print("ERROR: no sources given. Pass --sources, or create sources.local.json (see sources.example.json).")
        sys.exit(1)

    if args.background and not args._run_id:
        _start_background(args)
        return

    is_background_child = bool(args._run_id)
    state = runstate.RunState("group", args._run_id) if is_background_child else None

    if state is not None:
        log = print  # stdout is already redirected to the run's log.txt by the parent
        on_update = lambda snap: state.write_status(snap)  # noqa: E731
        pbar = None
    else:
        pbar = tqdm(unit="file", dynamic_ncols=True, desc="group")
        log = tqdm.write

        def on_update(snap):
            if snap.total_known:
                pbar.total = snap.total_discovered
            pbar.n = snap.processed
            # ProgressTracker's fields are named for find's vocabulary
            # (matched/rejected/errored); relabel them here for what they
            # actually mean during group's detection pass.
            pbar.set_postfix(with_faces=snap.matched, no_face=snap.rejected, errored=snap.errored, refresh=False)
            pbar.refresh()

    out_dir = Path(args.out)
    scratch_root = paths.scratch_root("group")
    store_path = paths.group_checkpoint_path()
    scratch_root.mkdir(parents=True, exist_ok=True)

    store = GroupStore(store_path)
    log(f"Threshold={args.threshold}  min-cluster-size={args.min_cluster_size}  Workers={args.workers}")
    log(f"Checkpoint: {len(store)} file(s) already recorded in {store_path}")

    tracker = ProgressTracker(on_update=on_update)
    tracker.set_phase("processing")

    # One intra-op thread per worker process - see facematch_core.model's
    # get_face_app docstring for why (avoids N-fold oversubscription across
    # N worker processes, exactly the same reasoning as find.py).
    intra_op_threads = 1

    cand_registry: dict[str, Candidate] = {}
    result_summary = None
    exit_status = "finished"
    try:
        with multiprocessing.Pool(
            processes=args.workers,
            initializer=init_worker_group,
            initargs=(str(scratch_root), intra_op_threads),
        ) as pool:
            gen = candidate_generator(sources, str(scratch_root), tracker, store, args.retry_errors, log, cand_registry)
            count = 0
            for result in pool.imap_unordered(process_candidate_group, gen, chunksize=1):
                status = result["status"]
                key = result["key"]
                kind = result["kind"]
                tracker.set_current_source(result["display_name"])
                cand = cand_registry.pop(key, None)

                if status == "done":
                    tracker.record_processed("matched")
                elif status == "no_face":
                    tracker.record_processed("rejected")
                else:
                    tracker.record_processed("errored")

                store.record_file(
                    key, result["display_name"], kind, status,
                    error=result.get("error"),
                    loose_path=cand.loose_path if cand else None,
                    zip_path=cand.zip_path if cand else None,
                    zip_entry=cand.zip_entry if cand else None,
                    faces=result.get("faces"),
                )

                count += 1
                if args.limit and count >= args.limit:
                    log(f"[limit reached] stopping after {count} newly-processed candidates")
                    break

        stats = store.stats()
        log(f"Detection complete: {stats['files']} file(s), {stats['faces']} face(s) recorded.")
        tracker.set_phase("clustering")
        result_summary = _cluster_and_materialize(args, store, out_dir, log)
        tracker.set_phase("done")
        log(
            f"Grouped into {result_summary['clusters']} person folder(s) under {out_dir} "
            f"({result_summary['files_placed']} file placement(s), "
            f"{result_summary['unclustered_files']} file(s) in unclustered/)."
        )
    except BaseException as e:
        exit_status = "crashed"
        if state is not None:
            state.write_meta(exit_status="crashed", error=str(e), ended_at=time.time())
        raise
    finally:
        tracker.finish()
        store.close()
        if pbar is not None:
            pbar.close()
        if state is not None and exit_status == "finished":
            state.write_meta(exit_status="finished", ended_at=time.time(), result=result_summary)

    log("Group complete.")


def _cluster_and_materialize(args: argparse.Namespace, store: GroupStore, out_dir: Path, log) -> dict:
    file_keys: list[str] = []
    embeddings: list[np.ndarray] = []
    for file_key, emb in store.iter_faces():
        file_keys.append(file_key)
        embeddings.append(emb)

    if not embeddings:
        log("No faces detected across the scanned sources - nothing to group.")
        return {"clusters": 0, "files_placed": 0, "unclustered_files": 0}

    emb_matrix = np.stack(embeddings)
    labels = cluster_embeddings(emb_matrix, threshold=args.threshold)
    clusters = sort_clusters_by_size(labels)

    valid_clusters = [(label, idxs) for label, idxs in clusters if len(idxs) >= args.min_cluster_size]
    small_clusters = [(label, idxs) for label, idxs in clusters if len(idxs) < args.min_cluster_size]

    log(
        f"{len(clusters)} raw face cluster(s) -> {len(valid_clusters)} person group(s) "
        f"(>= {args.min_cluster_size} faces), {len(small_clusters)} too small to count as a person on their own."
    )

    out_dir.mkdir(parents=True, exist_ok=True)

    # file_key -> set of person folder names it belongs in (a file with
    # several people in it belongs in several folders at once).
    placements: dict[str, set[str]] = {}
    for rank, (_label, idxs) in enumerate(valid_clusters, start=1):
        person_dir_name = f"person_{rank:03d}"
        for i in idxs:
            placements.setdefault(file_keys[i], set()).add(person_dir_name)

    # A file only counts as genuinely unclustered if NONE of its faces made
    # it into a valid-size cluster - a file with one clustered face and one
    # singleton stranger face already shows up in that person's folder,
    # which is enough for the "find every face somewhere" guarantee.
    unclustered_file_keys = {
        file_keys[i] for _label, idxs in small_clusters for i in idxs if file_keys[i] not in placements
    }

    scratch_root = paths.scratch_root("group_materialize")
    files_placed = 0
    all_file_keys = set(placements) | unclustered_file_keys
    for file_key in tqdm(sorted(all_file_keys), desc="group (copying)", unit="file", leave=False):
        info = store.file_info(file_key)
        if info is None or info["status"] != "done":
            continue
        dest_names = placements.get(file_key) or {"unclustered"}
        for dest_name in dest_names:
            dest_dir = out_dir / dest_name
            dest_dir.mkdir(parents=True, exist_ok=True)
            try:
                if _materialize_file(info, dest_dir, scratch_root):
                    files_placed += 1
            except Exception as e:
                log(f"[error] could not copy {info['display_name']} into {dest_dir}: {e}")

    return {
        "clusters": len(valid_clusters),
        "files_placed": files_placed,
        "unclustered_files": len(unclustered_file_keys),
    }


def _materialize_file(info: dict, dest_dir: Path, scratch_root: Path) -> bool:
    """Copy one recorded file into dest_dir. Reuses Candidate.extract_to so
    zip-streaming (incl. the cached zip-handle path) works identically to
    the detection pass - no separate zip-reading code path to keep in sync."""
    dest_name = safe_dest_name(info["display_name"])
    dest_path = dest_dir / dest_name
    if dest_path.exists():
        return False  # already placed here on a prior invocation
    cand = Candidate(
        display_name=info["display_name"], ext="", kind=info["kind"], key="",
        loose_path=info["loose_path"], zip_path=info["zip_path"], zip_entry=info["zip_entry"],
    )
    local_path = cand.extract_to(str(scratch_root))
    try:
        shutil.copy2(local_path, dest_path)
    finally:
        if cand.loose_path is None and os.path.exists(local_path):
            os.remove(local_path)
    return True


def _child_argv(args: argparse.Namespace, run_id: str) -> list[str]:
    argv = ["group"]
    if args.sources:
        argv += ["--sources", *args.sources]
    argv += ["--out", str(args.out)]
    argv += ["--threshold", str(args.threshold)]
    argv += ["--min-cluster-size", str(args.min_cluster_size)]
    if args.limit is not None:
        argv += ["--limit", str(args.limit)]
    argv += ["--workers", str(args.workers)]
    if args.retry_errors:
        argv.append("--retry-errors")
    argv += ["--_run-id", run_id]
    return argv


def _start_background(args: argparse.Namespace) -> None:
    run_id = runstate.new_run_id()
    state = runstate.RunState("group", run_id)
    state.dir.mkdir(parents=True, exist_ok=True)
    state.write_meta(
        run_id=run_id,
        command="group",
        args={
            "sources": args.sources,
            "out": args.out,
            "threshold": args.threshold,
            "min_cluster_size": args.min_cluster_size,
            "limit": args.limit,
            "workers": args.workers,
            "retry_errors": args.retry_errors,
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

    print(f"Started group in the background (run id: {run_id}, pid {proc.pid}).")
    print(f"  facematch group status                check its progress")
    print(f"  facematch group status --watch         follow it live")
    print(f"  log: {state.log_path}")


# ---------------------------------------------------------------------------
# `facematch group status`
# ---------------------------------------------------------------------------

def _format_status_line(run_id: str, meta: dict, status: dict, state_label: str) -> str:
    processed = status.get("processed", 0)
    total = status.get("total_discovered", 0)
    total_known = status.get("total_known", False)
    with_faces = status.get("matched", 0)
    no_face = status.get("rejected", 0)
    errored = status.get("errored", 0)
    rate = status.get("rate_per_min", 0.0)
    elapsed = status.get("elapsed_seconds", 0.0)
    phase = status.get("phase", "starting")

    progress = f"{processed}/{total}" if total_known else f"{processed} (still enumerating)"
    eta = ""
    if total_known and rate > 0 and total > processed and phase == "processing":
        remaining_min = (total - processed) / rate
        eta = f", ETA ~{remaining_min:.1f} min"

    lines = [
        f"run {run_id}  [{state_label}]",
        f"  phase: {phase}",
        f"  detection: {progress}{eta}",
        f"  with faces: {with_faces}   no face: {no_face}   errored: {errored}",
        f"  rate: {rate:.1f}/min   elapsed: {elapsed:.0f}s",
    ]
    result = meta.get("result")
    if result:
        lines.append(
            f"  result: {result['clusters']} person folder(s), {result['files_placed']} file placement(s), "
            f"{result['unclustered_files']} file(s) unclustered"
        )
    if meta.get("error"):
        lines.append(f"  error: {meta['error']}")
    return "\n".join(lines)


def run_status(args: argparse.Namespace) -> None:
    run_id = args.run_id or paths.latest_run_id("group")
    if run_id is None:
        print("No group runs recorded yet. Start one with `facematch group --background`.")
        sys.exit(1)

    state = runstate.RunState("group", run_id)
    if not state.dir.exists():
        print(f"ERROR: no run '{run_id}' found under {paths.runs_root('group')}")
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
# `facematch group restart`
# ---------------------------------------------------------------------------

def run_restart(args: argparse.Namespace) -> None:
    checkpoint_path = paths.group_checkpoint_path()
    to_remove = [
        checkpoint_path,
        checkpoint_path.with_name(checkpoint_path.name + "-wal"),
        checkpoint_path.with_name(checkpoint_path.name + "-shm"),
    ]
    existing = [p for p in to_remove if p.exists()]

    if not existing:
        print("Nothing to reset - no previous group run found here.")
        return

    if not args.yes:
        print("This will delete:")
        for p in existing:
            print(f"  - {p}")
        print("Folders already written under --out are NOT deleted - only the checkpoint "
              "that tracks which files have already had their faces detected.")
        reply = input("Continue? [y/N] ").strip().lower()
        if reply not in ("y", "yes"):
            print("Aborted.")
            return

    for p in existing:
        p.unlink()
    print(f"Removed {len(existing)} file(s). Ready for a fresh `facematch group`.")
