# Packaging

Building `facematch` into a single native binary with [PyInstaller](https://pyinstaller.org),
so it can be run without a Python toolchain.

## Status

- **macOS (arm64): verified.** Built and tested for real on this machine —
  `build-references`, `find`, and `group` all run real face detection,
  embedding, matching, and clustering inside the frozen binary, including
  the multiprocessing worker pool `find`/`group` use for parallelism.
  Model weights download correctly on first run from a clean cache.
- **Linux (arm64, via Docker): verified.** Built and tested for real inside
  a `python:3.11` Docker container (`docker run --platform linux/arm64
  python:3.11 ...`) — the same real end-to-end test as macOS (build
  references, run `find` against `examples/`, confirm a genuine match with
  auto-dedupe running afterward) passed. This proves the PyInstaller
  approach itself works on Linux, not just macOS.
- **Linux (x86_64): configured, verified by CI.** `.github/workflows/
  release.yml` builds and smoke-tests an `ubuntu-latest` (x86_64) binary on
  every tagged release — this is the actual target architecture for most
  Linux users and hasn't been tested outside CI, since this development
  machine is Apple Silicon and can only run Linux containers natively at
  arm64 (x86_64 emulation via QEMU was available but not needed once the
  native arm64 test already answered the real question: does this
  dependency stack work under PyInstaller on Linux at all).
- **Unsigned.** This produces a plain, unsigned binary. macOS Gatekeeper
  will block it for anyone except the person who built it until it's
  code-signed and notarized (requires an Apple Developer account) — that's
  a deliberate later step, not part of this pass.
- **ffmpeg required separately.** Video support needs `ffmpeg`/`ffprobe` on
  the user's PATH; they are not bundled into the binary. `find`/`group`/
  `build-references` print a clear warning at startup if they're missing,
  rather than failing video files with a cryptic subprocess error.
- **Model weights downloaded on first run**, not bundled — the binary calls
  out to InsightFace's normal `buffalo_l` download the first time it's used,
  same as running from source. This keeps the binary smaller at the cost of
  needing network once before the first real scan.

## Building

```bash
uv sync   # pulls in pyinstaller + pyinstaller-hooks-contrib as a dev dependency
uv run pyinstaller packaging/pyinstaller/facematch.spec \
    --distpath packaging/pyinstaller/dist \
    --workpath packaging/pyinstaller/build
```

The binary lands at `packaging/pyinstaller/dist/facematch`. Try it:

```bash
./packaging/pyinstaller/dist/facematch --help
```

`packaging/pyinstaller/dist/` and `build/` are gitignored (large, platform-
specific build output) — only `facematch.spec` and `entry.py` are committed.

## What actually made this work

This dependency stack (InsightFace + ONNX Runtime + OpenCV + pillow-heif) is
unusually heavy for PyInstaller — a plain `pyinstaller entry.py` does not
work out of the box. Three real problems had to be solved, in the order
they were found:

1. **Relative imports break when PyInstaller runs a file as a top-level
   script.** `facematch_cli/__main__.py` does `from . import find, group,
   ...`, which needs `facematch_cli` to be a real package at import time.
   Pointing PyInstaller directly at `__main__.py` runs it with no package
   context and fails with "attempted relative import with no known parent
   package". `packaging/pyinstaller/entry.py` works around this by
   importing `facematch_cli.__main__` properly instead of being that file.

2. **InsightFace's own frozen-app data lookup expects a bundle-root
   `objects/` directory**, not the package-relative `insightface/data/
   objects/` path `PyInstaller`'s `collect_all()` preserves by default.
   `insightface/data/pickle_object.py` has explicit `if getattr(sys,
   'frozen', False): base_dir = sys._MEIPASS` handling that looks for
   `<bundle_root>/objects/meanshape_68.pkl` directly — InsightFace already
   expects to be frozen this way, it just needs the file placed where it's
   looking. Without this, model loading crashes with
   `AttributeError: 'NoneType' object has no attribute 'shape'` (a missing
   landmark file quietly returns `None` a few frames before the real crash).
   `facematch.spec` adds this file at the bundle root explicitly, alongside
   the normal `collect_all("insightface")` data.

3. **`multiprocessing.resource_tracker` always re-execs `sys.executable -c
   "<code>"`** to launch its cleanup helper process, regardless of the
   Pool's start method. In a frozen app `sys.executable` is this binary,
   which has no `-c` flag — without handling this, the resource tracker's
   relaunch either crashes outright or (worse) gets misinterpreted as a
   bogus `facematch` subcommand invocation. `multiprocessing.freeze_support()`
   does NOT cover this specific case (it only handles the Pool worker
   `--multiprocessing-fork` bootstrap). `entry.py` detects the `-c`
   convention itself, before importing anything else, and just `exec()`s
   the code — the same thing a real `python -c` would do.

`collect_all()` on `onnxruntime`, `insightface`, `cv2`, and `pillow_heif`
handles the rest (their compiled extensions and remaining package data).

## Building for Linux

PyInstaller does not cross-compile — a Linux binary has to be built on
Linux, same as the macOS one had to be built on macOS. On an actual Linux
machine (or in a Linux container):

```bash
sudo apt install libgl1 libglib2.0-0 libsm6 libxext6 libxrender1  # or your distro's equivalent
uv sync
uv run pyinstaller packaging/pyinstaller/facematch.spec \
    --distpath packaging/pyinstaller/dist \
    --workpath packaging/pyinstaller/build
```

The three fixes above are all Python-level, not macOS-specific, and carry
over unchanged — this has now actually been verified for real (see
Status above), both locally on arm64 via Docker and in CI on x86_64.

## Automated releases

`.github/workflows/release.yml` builds macOS and Linux binaries and attaches
them to a GitHub Release — this is what [`install.sh`](../install.sh)
downloads from. See that workflow file for the exact build/test steps it
runs (the same smoke test and real end-to-end scan described above, run in
CI for both platforms on every release).

It runs two ways:

- **Automatically**, whenever a `v*` tag is pushed:
  ```bash
  git tag -a v0.1.1 -m "v0.1.1: ..."
  git push origin v0.1.1
  ```
- **Manually**, without pushing a tag first — useful for re-cutting a release
  after fixing a failed build, or releasing from a branch:
  - **GitHub UI**: Actions tab → "Release" workflow → "Run workflow" →
    enter the version tag (e.g. `v0.1.1`) → Run workflow.
  - **`gh` CLI**:
    ```bash
    gh workflow run release.yml -f tag=v0.1.1
    ```
  A manual run creates the `v0.1.1` tag automatically if it doesn't already
  exist yet, pointing at whichever branch/commit the workflow ran against.

## Not part of this pass

- Code signing / notarization (macOS) - needed before distributing the
  binary to anyone besides the person who built it.
- Bundling `buffalo_l` model weights into the binary (fully offline from
  first launch) instead of downloading them on first run.
- Bundling static `ffmpeg`/`ffprobe` binaries instead of requiring them on
  PATH.
- Any installer/distribution mechanism (Homebrew tap, `.deb`, AppImage,
  etc.) - this pass only proves the binary itself can be built and works.
