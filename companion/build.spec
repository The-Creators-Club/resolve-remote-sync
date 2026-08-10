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

import sys
from pathlib import Path

block_cipher = None

# pystray/Pillow are optional at runtime (see src/ccsync_companion/tray.py);
# only bundle them if they're actually installed in the build environment,
# so a headless build doesn't fail trying to collect missing packages.
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
    import pystray  # noqa: F401
    import PIL  # noqa: F401

    hidden_imports += ["pystray", "PIL"]
    if sys.platform == "win32":
        hidden_imports.append("pystray._win32")
    elif sys.platform == "darwin":
        hidden_imports.append("pystray._darwin")
except ImportError:
    pass

entry_point = "launcher.py"  # absolute-import shim; running the package __main__.py directly breaks relative imports

# Windows wants a .ico and we ship one. macOS wants an .icns, which this repo
# does not have, and handing PyInstaller the .ico there is not "no icon" -- it
# tries to convert it (needing Pillow's icns support) and fails the build. The
# macOS artifact is a BARE executable, not a .app bundle (no BUNDLE step
# below): it is launched by a LaunchAgent and lives in the menu bar via
# pystray, so it has no Dock presence to put an icon on anyway. The window
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
    # The Creators Club logo: theme.asset_path() reads these back out of
    # sys._MEIPASS at this exact relative path -- icon.png for every popup
    # window, cc_mark_white.png for the tray icon's tinted/pulsing mark
    # (2026-08-10). Listed file by file rather than collecting the directory:
    # icon.ico is already handed to EXE(icon=...) and has no business in the
    # bundle twice, and a glob would ship whatever anyone drops in assets/.
    datas=[
        ("src/ccsync_companion/assets/icon.png", "ccsync_companion/assets"),
        ("src/ccsync_companion/assets/cc_mark_white.png", "ccsync_companion/assets"),
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
    # by the kernel on launch. Do NOT set a Developer ID here without also
    # sorting out notarisation -- a signed-but-unnotarised binary is worse off
    # with Gatekeeper than an ad-hoc one. tools/release_macos.sh verifies the
    # signature with `codesign -dv` after every build and refuses to publish
    # one that has none.
    codesign_identity=None,
    entitlements_file=None,
    icon=exe_icon,
)
