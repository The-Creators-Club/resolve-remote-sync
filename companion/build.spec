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

# fusionscript.dll (Resolve's scripting library, loaded into this process at
# runtime by resolve_bridge) links against the stable-ABI forwarder
# python3.dll, which PyInstaller can't discover statically. If it isn't in
# the bundle, Windows resolves it from whatever Python is installed on the
# editor's machine: a same-version install works by luck, a mismatched one
# (e.g. 3.13 vs our bundled 3.12) pulls a second uninitialized Python
# runtime into the process and segfaults on the watcher's first Resolve
# poll, and no install at all silently disables the Resolve bridge. Bundle
# the build interpreter's own forwarder so the lookup never leaves the exe.
extra_binaries = []
if sys.platform == "win32":
    _python3_dll = Path(sys.base_prefix) / "python3.dll"
    if _python3_dll.exists():
        extra_binaries.append((str(_python3_dll), "."))

a = Analysis(
    [entry_point],
    pathex=["src"],
    binaries=extra_binaries,
    # The Creators Club logo: theme.apply_window_icon() reads it back out of
    # sys._MEIPASS at this exact relative path for every popup window.
    datas=[("src/ccsync_companion/assets/icon.png", "ccsync_companion/assets")],
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
    codesign_identity=None,
    entitlements_file=None,
    icon="src/ccsync_companion/assets/icon.ico",
)
