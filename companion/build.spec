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
hidden_imports = ["watchdog", "watchdog.observers", "watchdog.events"]
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

entry_point = "launcher.py"  # absolute-import shim; running the package __main__.py directly breaks relative imports

# Windows wants a .ico and we ship one. macOS wants an .icns, which this repo
# does not have, and handing PyInstaller the .ico there is not "no icon" -- it
# tries to convert it (needing Pillow's icns support) and fails the build. The
# macOS artifact is a BARE executable, not a .app bundle (no BUNDLE step
# below): it is launched by a LaunchAgent and lives in the menu bar as an
# NSStatusItem, so it has no Dock presence to put an icon on anyway. The window
# icon (assets/icon.png, collected in datas) is unaffected on every platform.
exe_icon = None
if sys.platform == "win32":
    exe_icon = "src/ccsync_companion/assets/icon.ico"

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

a = Analysis(
    [entry_point],
    pathex=["src"],
    binaries=extra_binaries,
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
    ],
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
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
)
