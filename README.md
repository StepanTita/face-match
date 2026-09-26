# face-match

A personal tool for finding photos and videos of a specific person across a
large, messy photo/video archive (phone backups, cloud exports, old drives),
using face-embedding similarity instead of manual browsing.

It builds a small set of reference face embeddings from photos/videos you
provide, then streams through your archive (folders and/or zip files,
including nested zips) comparing every detected face against those
references and copying anything that matches above a threshold into a
`matched/` folder.

## How it works

- **Embeddings**: [InsightFace](https://github.com/deepinsight/insightface)
  (`buffalo_l` / ArcFace) via ONNX Runtime, run on CPU.
- **Streaming scan**: zip archives are read entry-by-entry rather than fully
  extracted, so scanning works even against very large exports (e.g. a full
  cloud photo takeout) without needing that much free disk space.
- **High recall by default**: the match threshold is tuned low relative to
  typical face-verification defaults, on the assumption that missing a real
  match is worse than having to manually reject some false positives.
- **Parallel**: a pool of worker processes (default: CPU count - 1) does the
  actual decoding/detection/embedding, so scanning scales with cores.
- **Checkpointed/resumable**: every processed file is recorded in a local
  SQLite checkpoint as it's completed, so an interrupted or killed scan can
  be resumed from where it left off, without redoing work or duplicating
  matches.
- **Live progress**: the scan writes `progress.json` continuously; open
  `progress.html` in a browser (served locally) to watch progress and recent
  matches update in real time.
- **Dedupe pass**: the same real-world photo often exists multiple times
  across overlapping backup sources. A separate dedupe script groups
  matched files by exact hash and perceptual hash, moving duplicates aside
  while leaving one canonical copy in place.

## Setup

```bash
uv sync
```

### Reference photos

Create a `references/` folder in the project root (this is gitignored - it
will contain real photos of the person you're matching against, so it should
never be committed) and put a handful of clear photos (and optionally a
short video) of that person in it. More references, across different
ages/angles/lighting, improve accuracy.

Then build the embeddings:

```bash
uv run build_references.py
```

This produces `reference_embeddings.npz`.

### Configuring your sources

Copy the example config and edit it with your own paths:

```bash
cp sources.example.json sources.local.json
```

```json
{
  "drive_root": "/path/to/your/archive",
  "sources": [
    "/path/to/your/photos.zip",
    "/path/to/your/photos_folder"
  ]
}
```

`sources.local.json` is gitignored. Each entry in `sources` can be a
directory or a `.zip` file.

## Running a scan

```bash
uv run scan.py
```

or, to override the configured sources for a one-off run:

```bash
uv run scan.py --sources "/path/a" "/path/b/archive.zip" --threshold 0.38 --workers 8
```

Useful flags:

- `--threshold` - cosine similarity cutoff for a match (default tuned for recall).
- `--workers` - number of worker processes.
- `--limit N` - stop after N newly-processed candidates (useful for testing).
- `--retry-errors` - re-attempt items previously checkpointed as errors.

While it's running, open `progress.html` (e.g. via `python -m http.server`
in the project directory) to watch live progress.

Matches are copied into `matched/`, logged in `matched/matches.csv`, and
tracked in `checkpoint.sqlite3` so the scan can be safely stopped and
resumed at any time.

### Backfilling full videos

Earlier versions of the scan only saved a thumbnail for matched videos.
`backfill_videos.py` copies the full video file for any already-matched
video row that's missing one, without re-running detection:

```bash
uv run backfill_videos.py
```

## Deduplicating results

```bash
uv run dedupe.py
```

This groups matched files that are byte-identical or perceptually
near-identical (e.g. the same photo re-exported at different quality by
different backup pipelines), keeping the highest-confidence copy in place
and moving the rest into `matched/duplicates/<group>/`. It's safe to run
incrementally / repeatedly - already-classified files are never reshuffled.
