# PyInstaller spec for "ccsync-companion".
#
# Produces a single-file executable per OS. Build separately on each target
# OS (PyInstaller does not cross-compile) — see README.md's "Build" section
# for the commands.
#
# Usage:
#   pyinstaller build.spec
#
# NOTE: per task instructions, this has NOT been run in this environment.
# Verify it end-to-end on a real Windows/macOS box before shipping.

# -*- mode: python ; coding: utf-8 -*-

import os
import sys
from pathlib import Path

block_cipher = None

# Pillow is optional at runtime (see src/ccsync_companion/tray.py); only
# bundle it if it's actually installed in the build environment, so a headless
# build doesn't fail trying to collect a missing package.
#
# pystray USED to be collected here too and deliberately is not any more
# (2026-08-17, docs/COMMERCIAL_READINESS.md item 3): it is LGPLv3, and a
# single-file PyInstaller freeze conveys it with no way for the recipient to
# relink against a modified copy, which is precisely what LGPL §4 requires.
# The tray is ccsync_companion/tray_native.py now -- ours, ctypes/PyObjC,
# written from the OS APIs. Do NOT re-add pystray here: the CCSYNC_TRAY_BACKEND
# escape hatch in tray.py is a dev-machine affordance and refuses to load in a
# frozen build for exactly this reason.
hidden_imports = ["watchdog", "watchdog.observers", "watchdog.events",
                  # the Timeline Cards role imports the MulticamPipeline
                  # engine over a runtime sys.path, so static analysis never
                  # sees the engine's own imports -- the project-library pair
                  # must be named or the frozen role pushes "No module named
                  # 'psycopg2'" onto every /cards state (2026-08-31).
                  # psycopg2 is NOT named here any more (GL-32, CR-375,
                  # 2026-10-07): see the lgpl_datas block below.
                  "zstandard"]
if sys.platform == "darwin":
    # watchdog picks its backend at import time inside a try/except chain
    # (fsevents on darwin, ReadDirectoryChangesW on win32, inotify on linux),
    # which PyInstaller's static analysis cannot follow -- so the macOS build
    # collects only the generic observers package and falls back to the
    # polling observer at runtime, or fails outright. The Windows backend is
    # a stdlib-ctypes affair and needs no help; this one is a C extension.
    hidden_imports.append("watchdog.observers.fsevents")
try:
    import PIL  # noqa: F401

    hidden_imports.append("PIL")
except ImportError:
    pass
if sys.platform == "darwin":
    # tray_native's macOS backend imports AppKit/Foundation/objc lazily inside
    # methods, which PyInstaller's static analysis does not follow. pyobjc came
    # in through pystray before; now it is ours to name.
    hidden_imports += ["AppKit", "Foundation", "objc"]

# numpy and onnxruntime: the CLAP audio tower runs in this binary now
# (docs/MUSIC_INGEST_PLAN.md step 3). Neither is optional at runtime -- both
# are hard dependencies in pyproject.toml -- but both need naming here anyway:
#
#   * `music_clap_sidecar` imports them INSIDE its functions (so a tray that
#     never ingests music never pays for the import), and PyInstaller's static
#     analysis does not follow a deferred import into a module-level graph;
#   * onnxruntime is a C extension whose Python half loads its own
#     `onnxruntime_pybind11_state` and ships a capi/ directory of shared
#     libraries and version metadata that no import statement mentions.
#     collect_all is the only thing that brings those along, and without them
#     the frozen build imports and then raises on the first InferenceSession
#     -- the same shape of failure the vendored prompt's `datas` line exists
#     to prevent.
#
# Guarded like the Pillow block above so a build environment that is missing
# one of them fails at pip time (where the message is about a dependency)
# rather than inside PyInstaller's analysis.
onnx_datas = []
onnx_binaries = []
try:
    from PyInstaller.utils.hooks import collect_all

    hidden_imports.append("numpy")
    _ort_datas, _ort_binaries, _ort_hidden = collect_all("onnxruntime")
    onnx_datas += _ort_datas
    onnx_binaries += _ort_binaries
    hidden_imports += _ort_hidden
    hidden_imports.append("onnxruntime.capi.onnxruntime_pybind11_state")
except Exception:  # noqa: BLE001 - a build without it fails louder at import
    hidden_imports.append("onnxruntime")

# The library walk (docs/LIBRARY_WALK_PLAN.md): `library.py` reads a
# timeline's items straight out of Resolve's project library rather than
# walking them through the scripting API. Both of its dependencies need naming
# here, for the same reason numpy/onnxruntime do above -- `library.py` imports
# them INSIDE its functions so a companion that never reaches a library never
# pays for the import, and PyInstaller does not follow a deferred import.
#
#   * pg8000 (PostgreSQL, for a network library). `pg8000/__init__.py` is a
#     thin re-export, but the code paths that matter live in submodules and
#     `pg8000.native` in particular is imported by name at call time. scramp
#     (and its asn1crypto) is pulled in by pg8000.core's `from scramp import
#     ScramClient` for SCRAM-SHA-256 auth: the fleet's postgres:13 currently
#     negotiates plain md5 (AuthenticationMD5Password, code 5 -- measured
#     2026-08-26, `password_encryption = md5`), so a frozen build that dropped
#     scramp would work HERE and fail the day a library server is re-hashed to
#     scram-sha-256. Name it.
#
#   * zstandard, for the `Clip` blob that carries a pool clip's live media
#     path. Its `__init__` picks a backend under `if platform
#     .python_implementation() ...` at import time; `backend_c` is the C
#     extension we actually want and the one whose cp312 wheel we lock for
#     win_amd64 / macosx_x86_64 / macosx_arm64. `backend_cffi` is deliberately
#     NOT listed: it needs cffi, which is not in requirements.lock (it is an
#     optional extra of zstandard), and naming a module that is not installed
#     is a hard Analysis error rather than the graceful fallback it looks like.
hidden_imports += [
    "pg8000",
    "pg8000.native",
    "pg8000.dbapi",
    "pg8000.core",
    "pg8000.converters",
    "pg8000.exceptions",
    "pg8000.types",
    "scramp",
    "asn1crypto.x509",  # scramp.core: `from asn1crypto.x509 import Certificate`
    "dateutil.parser",  # pg8000.converters: `from dateutil.parser import parse`
    "zstandard",
    "zstandard.backend_c",
]

# GL-32 (CR-375, 2026-10-07, COM-H3): psycopg2 is LGPL-3.0-or-later. Frozen
# into the one-file exe it was unpacked to a fresh temp directory on every
# launch and nobody could replace it without rebuilding our exe, which LGPL
# section 4 requires them to be able to do (the reason pystray left, above).
# So it is kept OUT of the analysed archive (`excludes` below) and shipped as
# plain files under ccsync_lib/ in the bundle, byte-identical to the wheel's
# (on macOS this also stops PyInstaller rewriting and re-signing its
# dylibs). ccsync_companion/lgpl_libs.py puts ~/.ccsync/lib (the user's own
# build, wins) and <_MEIPASS>/ccsync_lib on sys.path before the Cards engine
# imports it. A HARD failure when psycopg2 is not installed: a build that
# silently dropped it would fail on every /cards state, as 2026-08-31 did.
def _collect_lgpl_tree():
    import importlib.util

    _spec = importlib.util.find_spec("psycopg2")
    if _spec is None or not _spec.submodule_search_locations:
        raise SystemExit(
            "psycopg2 is not installed in the build venv -- install "
            "companion/requirements.lock before building (GL-32)")
    _pkg = Path(list(_spec.submodule_search_locations)[0])
    _roots = [_pkg]
    # Linux wheels keep libpq/OpenSSL in a sibling psycopg2_binary.libs
    # directory; Windows and macOS keep them inside the package.
    _libs = _pkg.parent / "psycopg2_binary.libs"
    if _libs.is_dir():
        _roots.append(_libs)
    _out = []
    for _root in _roots:
        for _f in sorted(_root.rglob("*")):
            if _f.is_dir() or "__pycache__" in _f.parts or _f.suffix == ".pyc":
                continue
            _dest = Path("ccsync_lib") / _root.name / _f.parent.relative_to(_root)
            _out.append((str(_f), str(_dest).replace("\\", "/")))
    return _out


lgpl_datas = _collect_lgpl_tree()

entry_point = "launcher.py"  # absolute-import shim; running the package __main__.py directly breaks relative imports

# Windows wants a .ico and we ship one. macOS wants an .icns, which this repo
# does not have, and handing PyInstaller the .ico there is not "no icon" -- it
# tries to convert it (needing Pillow's icns support) and fails the build. The
# macOS artifact is a BARE executable, not a .app bundle (no BUNDLE step
# below): it is launched by a LaunchAgent and lives in the menu bar as an
# NSStatusItem, so it has no Dock presence to put an icon on anyway. The window
# icon (assets/icon.png, collected in datas) is unaffected on every platform.
exe_icon = None
exe_version = None
if sys.platform == "win32":
    exe_icon = "src/ccsync_companion/assets/icon.ico"
    # CR-373 / GL-30 (2026-10-07): a VERSIONINFO resource, so an unsigned beta
    # exe names itself in Explorer and SmartScreen's More info instead of
    # showing a blank description. tools/winversion.py is stdlib-only.
    sys.path.insert(0, str(Path(SPECPATH).resolve().parent / "tools"))
    import winversion
    exe_version = winversion.write(
        Path(SPECPATH).resolve() / "build" / "version_info.txt",
        version=winversion.read_assigned_version(
            Path(SPECPATH).resolve() / "src" / "ccsync_companion" / "config.py",
            "VERSION"),
        file_description="CC Sync companion",
        internal_name="ccsync-companion",
        original_filename="ccsync-companion.exe")

# fusionscript.dll (Resolve's scripting library, loaded into this process at
# runtime by resolve_bridge) links against the stable-ABI forwarder
# python3.dll, which PyInstaller can't discover statically. If it isn't in
# the bundle, Windows resolves it from whatever Python is installed on the
# editor's machine: a same-version install works by luck, a mismatched one
# (e.g. 3.13 vs our bundled 3.12) pulls a second uninitialized Python
# runtime into the process and segfaults on the watcher's first Resolve
# poll, and no install at all silently disables the Resolve bridge. Bundle
# the build interpreter's own forwarder so the lookup never leaves the exe.
#
# macOS: the same class of problem exists in theory -- fusionscript.so is
# loaded into this process by resolve_bridge and locates its own Python --
# but the mechanism differs (dyld + PYTHONHOME rather than the PEP 514
# registry + python3.dll), and resolve_bridge._pin_frozen_python3_home()
# already points PYTHONHOME/PYTHON3HOME at sys._MEIPASS on every platform.
# Nothing is added here for darwin on purpose: bundling a libpython that
# Resolve does not actually ask for is a good way to load a SECOND runtime
# into the process. Revisit only if the first real-Mac Resolve bridge test
# shows fusionscript failing to find a Python (see docs/GOTCHAS.md).
extra_binaries = []
if sys.platform == "win32":
    _python3_dll = Path(sys.base_prefix) / "python3.dll"
    if _python3_dll.exists():
        extra_binaries.append((str(_python3_dll), "."))

# LG-12 (docs/LEGAL_GAP_FEATURES_PLAN.md, 2026-09-25): the licence texts
# travel with the binary. THIRD_PARTY_LICENSES.txt is generated by
# `python tools/gen_notices.py --write-texts` (every runtime distribution in
# requirements.lock, plus tools/notices_extra/ for CPython, Tcl/Tk, OpenSSL
# and libpq) and committed; the notices document rides beside it. Both land
# in ccsync_companion/assets, where theme.asset_path() already looks, so the
# settings window's About -> "Open-source licences" (G1a) opens
# <_MEIPASS>/ccsync_companion/assets/THIRD_PARTY_LICENSES.txt.
#
# A HARD failure when absent, unlike the Pillow probe above: a binary that
# conveys LGPL and MIT code without their texts is the thing LG-12 exists to
# stop, and it must not be possible to build one by forgetting a command.
_repo_root = Path(SPECPATH).resolve().parent
_licence_texts = _repo_root / "docs" / "legal" / "licenses" / "companion" / "THIRD_PARTY_LICENSES.txt"
_notices = _repo_root / "docs" / "legal" / "THIRD_PARTY_NOTICES.md"
for _required in (_licence_texts, _notices):
    if not _required.exists():
        raise SystemExit(
            f"{_required} is missing -- generate it before building:\n"
            f"  python tools/gen_notices.py --write-texts")
licence_datas = [
    (str(_licence_texts), "ccsync_companion/assets"),
    (str(_notices), "ccsync_companion/assets"),
]

a = Analysis(
    [entry_point],
    pathex=["src"],
    binaries=extra_binaries + onnx_binaries,
    # The marks: theme.asset_path() reads these back out of sys._MEIPASS at
    # this exact relative path -- icon.png for every popup window, and the
    # white-on-transparent mark for the tray icon's tinted/pulsing one
    # (2026-08-10). Listed file by file rather than collecting the directory:
    # icon.ico is already handed to EXE(icon=...) and has no business in the
    # bundle twice, and a glob would ship whatever anyone drops in assets/.
    #
    # BOTH marks ship (2026-08-17, docs/COMMERCIAL_READINESS.md item 10):
    # cc_mark_white.png is the Creators Club mark and what every build wears
    # by default (owner's decision 2026-08-18 -- this is CC-branded software,
    # not white-label; item 10's neutral default was reversed); ccsync_mark.png
    # is the neutral alternative a white-label fleet can select with
    # brand_logo / CCSYNC_BRAND_LOGO=ccsync_mark.png.
    datas=[
        ("src/ccsync_companion/assets/icon.png", "ccsync_companion/assets"),
        ("src/ccsync_companion/assets/ccsync_mark.png", "ccsync_companion/assets"),
        ("src/ccsync_companion/assets/cc_mark_white.png", "ccsync_companion/assets"),
        # The field backup page (field_server.py), served from disk so it works with no network.
        ("src/ccsync_companion/assets/field/index.html", "ccsync_companion/assets/field"),
        ("src/ccsync_companion/assets/field/field.css", "ccsync_companion/assets/field"),
        ("src/ccsync_companion/assets/field/field.js", "ccsync_companion/assets/field"),
        # The licence the editor accepted in the wizard (2026-08-17,
        # docs/COMMERCIAL_READINESS.md item 3). eula.py reads its version out
        # of this file to decide whether ~/.ccsync/eula_accepted.json is still
        # current. WITHOUT this line a frozen build has no document,
        # EULA_VERSION reads "" and acceptance_ok() fails OPEN -- deliberately
        # (a packaging fault must never stop a fleet syncing), which means the
        # gate would silently do nothing in every shipped build.
        ("src/ccsync_companion/assets/EULA.md", "ccsync_companion/assets"),
        # The local-VLM prompt (2026-08-18, docs/BROLL_INGEST_PLAN.md §3.3).
        # broll_vlm/compact_format.py is a VERBATIM copy of the indexer's and
        # reads this file off disk beside itself (PROMPT_PATH); PyInstaller
        # collects .py files into the archive but never a .md, so without this
        # line a frozen build imports fine and then dies with FileNotFoundError
        # on the first clip an editor tries to index -- the same failure the
        # EULA.md line above exists to prevent, one feature later.
        ("src/ccsync_companion/broll_vlm/prompts/index_clip_v7_compact.md",
         "ccsync_companion/broll_vlm/prompts"),
    ] + [
        # The "originals on request" Resolve menu (2026-10-31,
        # docs/SELECTIVE_ORIGINALS.md 12.1). resolve_menu_install.py reads
        # these out of sys._MEIPASS and writes them into Resolve's Scripts
        # folder at startup; a .lua is never collected on its own, so a build
        # without these lines installs no menu and logs why.
        # test_resolve_menu_install pins this list to the folder's contents.
        (f"src/ccsync_companion/resolve_menu/{_name}", "ccsync_companion/resolve_menu")
        for _name in (
            "_originals_common.lua",
            "Bring originals - selected media pool clips.lua",
            "Bring originals - timeline clips between In and Out.lua",
            "Bring originals - whole timeline.lua",
            "Stop originals - selected media pool clips.lua",
            "Stop originals - timeline clips between In and Out.lua",
        )
    ] + licence_datas + onnx_datas + lgpl_datas,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # LG-11 (docs/LEGAL_GAP_FEATURES_PLAN.md 4.5, 2026-09-25): measured on a
    # build from a venv made from requirements.lock + pyinstaller==6.21.0,
    # config.py's `except ImportError: import tomli` fallback (dead code on
    # the >=3.12 this package requires) resolved to setuptools' VENDORED
    # tomli, PyInstaller's setuptools hook then collected all of setuptools
    # (plus pyi_rth_setuptools and _distutils_hack), and tools/scan_frozen.py
    # failed the build: setuptools is not in the lock, it only arrives as
    # PyInstaller's own dependency. Nothing in the companion imports any of
    # these at run time. `tomli` itself cannot be listed: PyInstaller's
    # setuptools pre-import hook aliases it and raises on an excluded name.
    excludes=["setuptools", "pkg_resources", "_distutils_hack",
              # GL-32: shipped as files under ccsync_lib/, see lgpl_datas
              "psycopg2"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="ccsync-companion",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    # UPX packing on a SELF-UPDATING, UNSIGNED exe maximises AV heuristic
    # hits, and an AV quarantine of the freshly-renamed exe is the one
    # failure mode the rollback path has no recovery from: the running
    # image has already been renamed to .old and the new one is gone
    # (AUDIT_2 §2-low, alongside CORE-H6). ~8 MB of download is a cheap
    # trade for not bricking an editor's install.
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    # Windowed, NOT console: the tray icon + ~/.ccsync/companion.log are the
    # real interfaces. console=True (the original choice) meant every direct
    # launch -- the installer's, the self-upgrade respawn, the Run-key
    # autostart -- popped an EMPTY console window (output is redirected to
    # null), and closing that mystery window KILLS the companion. Seen live
    # 2026-07-25: the base-rig install "failed" because the user closed it.
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    # None = PyInstaller AD-HOC signs the macOS binary itself (`codesign -s -`),
    # which is not optional on Apple silicon: an unsigned arm64 binary is killed
    # by the kernel on launch.
    #
    # CCSYNC_APPLE_DEV_ID (COMMERCIAL_READINESS.md item 4, 2026-08-17) makes
    # PyInstaller sign with a real Developer ID instead. The old rule here --
    # "do NOT set a Developer ID without sorting out notarisation" -- still
    # holds and is now satisfied: tools/release_macos.sh re-signs with
    # --options runtime --timestamp and runs notarytool + stapler when
    # CCSYNC_NOTARY_PROFILE is set, and warns loudly when it is not. Reading
    # the same env var here means a build driven by `pyinstaller build.spec`
    # directly (no release script) does not silently produce an ad-hoc binary
    # that the release script then has to fix.
    codesign_identity=(os.environ.get("CCSYNC_APPLE_DEV_ID") or None),
    entitlements_file=None,
    icon=exe_icon,
    version=exe_version,
)
