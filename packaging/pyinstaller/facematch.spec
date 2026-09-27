# PyInstaller spec for the `facematch` CLI.
#
# Build from the repo root:
#   uv run pyinstaller packaging/pyinstaller/facematch.spec
#
# See packaging/README.md for the full story on why each of these pieces is
# here - this dependency stack (InsightFace + ONNX Runtime + OpenCV) needed
# real trial and error, not just a default `pyinstaller entry.py`.
import os

from PyInstaller.utils.hooks import collect_all

block_cipher = None

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(SPEC), "..", ".."))

datas = []
binaries = []
hiddenimports = []

for pkg in ("onnxruntime", "insightface", "cv2", "pillow_heif"):
    pkg_datas, pkg_binaries, pkg_hiddenimports = collect_all(pkg)
    datas += pkg_datas
    binaries += pkg_binaries
    hiddenimports += pkg_hiddenimports

# insightface's own pickle_object.get_object() has explicit `sys.frozen`
# handling (see packaging/README.md) that looks for its data file at
# <bundle_root>/objects/<name>.pkl - NOT the package-relative
# insightface/data/objects/ path that `collect_all` above preserves. Both
# copies is harmless and keeps this working even if a future insightface
# release changes that convention back to a package-relative lookup.
import insightface  # noqa: E402

_insightface_objects_dir = os.path.join(os.path.dirname(insightface.__file__), "data", "objects")
if os.path.isdir(_insightface_objects_dir):
    datas.append((_insightface_objects_dir, "objects"))

a = Analysis(
    [os.path.join(os.path.dirname(SPEC), "entry.py")],
    pathex=[
        os.path.join(REPO_ROOT, "packages", "cli", "src"),
        os.path.join(REPO_ROOT, "packages", "core", "src"),
    ],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    cipher=block_cipher,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="facematch",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
