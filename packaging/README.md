# Packaging

Building `facematch` into a single native binary with [PyInstaller](https://pyinstaller.org),
so it can be run without a Python toolchain.

## Status

- **macOS (arm64): verified.** Built and tested for real on this machine —
  `build-references`, `find`, and `group` all run real face detection,
  embedding, matching, and clustering inside the frozen binary, including
  the multiprocessing worker pool `find`/`group` use for parallelism.
  Model weights download correctly on first run from a clean cache.
- **Linux: configured, not yet verified.** The spec file and dependency
  handling below should apply equally to Linux (same PyInstaller, same
  Python packages), but this repo has only been built and tested on macOS
  so far — nobody has actually run a Linux build of it yet. Treat the Linux
  steps below as a starting point, not a guarantee.
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

## Building for Linux (unverified)

Should be, in principle:

```bash
uv sync
uv run pyinstaller packaging/pyinstaller/facematch.spec \
    --distpath packaging/pyinstaller/dist \
    --workpath packaging/pyinstaller/build
```
run on an actual Linux machine (PyInstaller does not cross-compile — a
Linux binary has to be built on Linux, same as the macOS one had to be
built on macOS). The three fixes above are all Python-level, not
macOS-specific, so they should carry over unchanged. What's genuinely
unverified: whether `collect_all()` pulls in the right `.so` files for
Linux's OpenCV/ONNX Runtime wheels, and whether any Linux-only native
dependency (e.g. a system OpenCV shared library some `opencv-python-headless`
builds still expect) is missing until someone actually tries this on a
real Linux box and reports back. This section will be updated once that
happens.

## Not part of this pass

- Code signing / notarization (macOS) - needed before distributing the
  binary to anyone besides the person who built it.
- Bundling `buffalo_l` model weights into the binary (fully offline from
  first launch) instead of downloading them on first run.
- Bundling static `ffmpeg`/`ffprobe` binaries instead of requiring them on
  PATH.
- Any installer/distribution mechanism (Homebrew tap, `.deb`, AppImage,
  etc.) - this pass only proves the binary itself can be built and works.
