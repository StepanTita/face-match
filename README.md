# facematch

Find every photo and video of one person across a giant, messy archive —
phone backups, cloud takeouts, old external drives — without scrolling
through any of it by hand.

You give it a few reference photos of the person and a path. It streams
through everything under that path (folders, zip files, even zips nested
inside zips), runs face detection and embedding on every image and video it
finds, and copies out anything that matches. It runs entirely on your
machine: nothing is uploaded anywhere.

```bash
uv run facematch build-references
uv run facematch find --sources ~/Photos ~/old-icloud-export.zip
```

## Features

- **Streaming archive scan** — reads zip entries one at a time instead of
  extracting the whole archive first, so scanning a 200GB cloud export
  doesn't need 200GB of free disk space. Zips inside zips are handled the
  same way.
- **Resumable by default** — every processed file is checkpointed to a local
  SQLite database as it completes. Kill the scan, restart your machine,
  re-run the same command: it picks up exactly where it left off.
- **Parallel** — a pool of worker processes (CPU count − 1 by default) does
  the decoding, detection, and embedding, so it scales with cores.
- **Background jobs** — kick off a long scan, close the terminal, and check
  on it later:

  ```bash
  facematch find --background
  facematch find status --watch
  ```

- **Tuned for recall** — the match threshold defaults to the high-recall end
  of the typical range, on the assumption that missing a real match is worse
  than having to reject a few false positives by hand. Archive photos often
  span decades, with real changes in age and appearance and plenty of
  low-quality scans, so this matters more here than in a typical
  face-verification setup.
- **Dedupe pass** — the same photo often exists more than once across
  overlapping backups. `facematch dedupe` groups matches by exact and
  perceptual hash and files the duplicates aside, safe to re-run anytime.
- **Fully local** — no network calls, no accounts, no telemetry. See
  [Privacy](#privacy).

- **Group by person, no references needed** — `facematch group` detects
  every face across an archive and clusters them into `person_001/`,
  `person_002/`, ... folders using face-embedding similarity alone. Faces
  that don't form a confident group land in `unclustered/` instead of being
  dropped, and a file with several people in it is placed in every relevant
  person's folder.

Not built yet: packaged binaries so you don't need a Python toolchain to run
this — see [Roadmap](#roadmap).

## Install

Requires [`uv`](https://docs.astral.sh/uv/) and Python 3.11+.

```bash
git clone <this repo>
cd facematch
uv sync
```

`uv sync` builds the workspace's two packages — `facematch-core` (the
engine) and `facematch-cli` (the `facematch` command) — into a local
virtualenv. Run the tool with `uv run facematch ...` from whichever
directory holds your `references/`, `matched/`, and configuration: every
command resolves its inputs and outputs relative to the current working
directory, so a given directory is a self-contained "project" for one
person's search.

Packaged, double-clickable binaries for macOS and Linux (no `uv`/Python
setup required) are planned but not available yet.

## Quickstart

**1. Give it some reference photos.** Create a `references/` folder and drop
in a handful of clear photos (and optionally a short video) of the person
you're looking for — different ages, angles, and lighting all help.

```bash
mkdir references
cp ~/some-clear-photos-of-them/*.jpg references/
```

`references/` is gitignored: it holds real photos of a real person and
should never end up in version control.

**2. Build embeddings from them:**

```bash
uv run facematch build-references
```

This writes `reference_embeddings.npz`.

**3. Point it at an archive:**

```bash
uv run facematch find --sources ~/Photos ~/Downloads/icloud_export.zip
```

Matches land in `matched/`, get logged to `matched/matches.csv`, and are
tracked in `checkpoint.sqlite3` as the scan runs. Stop it anytime with
Ctrl-C — running the same command again resumes instead of starting over.

You can also point `find` at sources listed in a config file instead of
passing them as flags every time:

```bash
cp sources.example.json sources.local.json
# edit sources.local.json with your real paths — it's gitignored
uv run facematch find
```

**Don't know who's in the archive, or want everyone sorted, not just one
person?** Skip references entirely:

```bash
uv run facematch group --sources ~/Photos --out ~/Photos-by-person
```

This clusters every detected face by similarity and writes `person_001/`,
`person_002/`, ... folders under `--out`, plus an `unclustered/` folder for
faces that didn't form a confident group.

Every flag, default, and example invocation is documented in the CLI
itself — this README won't repeat it:

```bash
uv run facematch find --help
uv run facematch group --help
uv run facematch --help          # full list of commands
```

## How it works

1. **Reference embeddings.** Each reference photo/video goes through
   [InsightFace](https://github.com/deepinsight/insightface) (`buffalo_l` /
   ArcFace, via ONNX Runtime, CPU-only) to produce a 512-dimensional face
   embedding — a vector where visually similar faces land close together.
2. **Scan.** Every file under your source paths goes through the same
   detection + embedding step. Each detected face's embedding is compared
   against every reference embedding using cosine similarity.
3. **Threshold.** A face counts as a match if its best similarity score
   clears the configured threshold (`--threshold`, high-recall by default —
   see [Features](#features)).
4. **Checkpoint.** Whether a file matched, didn't match, or errored, the
   outcome is committed to `checkpoint.sqlite3` immediately, one file at a
   time — so a scan is safe to interrupt at any point and resume later
   without redoing work or double-copying matches.

## Commands

Each command is fully documented by its own `--help`, including realistic
example invocations — run `facematch <command> --help` for the complete
picture. This is just the map:

| Command | What it does |
|---|---|
| `facematch build-references` | Build `reference_embeddings.npz` from the photos/videos in `references/`. |
| `facematch find` | Scan your archive and copy out matches. Supports `--background`, `find status`, and `find restart` for job control. |
| `facematch group` | Cluster every face in your archive by person, no references needed. Supports the same `--background` / `status` / `restart` job control as `find`. |
| `facematch dedupe` | Collapse duplicate matches (exact + perceptual hash) into one canonical copy each. |
| `facematch backfill-videos` | Copy full video files for matches that only have a saved thumbnail, without re-running detection. |

## Privacy

This tool exists to run face recognition against your own private photo and
video archive, so it's worth being explicit: **everything happens on your
machine.** There are no network calls, no accounts, and no telemetry. Source
files are only ever read and copied, never modified or deleted. The engine
(`packages/core`) is a small, readable Python package if you want to verify
any of that yourself rather than take it on faith.

## Project layout

A `uv` workspace with two packages, split so a future GUI can reuse the same
engine without duplicating any matching logic:

- **`packages/core`** (`facematch-core`) — the engine: model loading,
  image/video decoding, embedding and matching, archive walking, and
  checkpointing. No CLI or UI code lives here.
- **`packages/cli`** (`facematch-cli`) — the `facematch` command, a thin
  front end over `facematch-core`.

## Roadmap

- Packaged, signed binaries for macOS and Linux, so running this doesn't
  require a Python toolchain.

## Contributing

Issues and pull requests are welcome. There's no formal contributing guide
yet — for anything beyond a small fix, open an issue first to talk through
the approach.

## License

[MIT](LICENSE)
