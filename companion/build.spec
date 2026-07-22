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

a = Analysis(
    [entry_point],
    pathex=["src"],
    binaries=[],
    datas=[],
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
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,  # keep a console window for status/log lines (see README)
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
