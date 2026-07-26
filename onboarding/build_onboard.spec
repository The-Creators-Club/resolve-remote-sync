# PyInstaller spec for onboard.exe -- the guided Windows onboarding wizard.
#
# Build (from onboarding/, in a venv that has pyinstaller + the companion
# package importable -- see README.md):
#
#     pyinstaller build_onboard.spec
#
# Output: dist/onboard.exe -- a ONE-FILE build (there is no COLLECT step
# below). windows_bootstrap.ps1, ccsync-companion.exe and the
# ccsync_companion package are packed into that exe and extracted to
# sys._MEIPASS at launch, which steps.find_bootstrap_script() /
# find_companion_exe() already look in -- see steps.py's
# find_bootstrap_script docstring for the exact lookup order.

import sys
from pathlib import Path

block_cipher = None

SPEC_DIR = Path(SPECPATH)
REPO_ROOT = SPEC_DIR.parent
COMPANION_SRC = REPO_ROOT / "companion" / "src"
BOOTSTRAP_PS1 = REPO_ROOT / "installer" / "windows_bootstrap.ps1"
COMPANION_EXE = REPO_ROOT / "companion" / "dist" / "ccsync-companion.exe"

sys.path.insert(0, str(COMPANION_SRC))
sys.path.insert(0, str(SPEC_DIR))

if not COMPANION_EXE.exists():
    raise SystemExit(
        f"companion exe not found at {COMPANION_EXE} -- build it first:\n"
        f"  cd companion && .venv\\Scripts\\python -m PyInstaller build.spec --noconfirm"
    )

a = Analysis(
    ["onboard.py"],
    pathex=[str(SPEC_DIR), str(COMPANION_SRC)],
    binaries=[],
    datas=[
        (str(BOOTSTRAP_PS1), "."),
        (str(COMPANION_EXE), "."),   # bundled so onboard.exe installs everything
        # Logo for the wizard window icon -- theme.apply_window_icon() reads
        # it from sys._MEIPASS/ccsync_companion/assets/icon.png.
        (str(COMPANION_SRC / "ccsync_companion" / "assets" / "icon.png"),
         "ccsync_companion/assets"),
    ],
    hiddenimports=[
        "ccsync_companion",
        "ccsync_companion.identity",
        "ccsync_companion.config",
        "ccsync_companion.theme",
        # identity.py pulls these in for HttpPostFn/default_http_post; both
        # are lightweight (json/urllib/dataclasses only, no watchdog/pystray)
        # -- see reporter.py's and sync/base.py's own docstrings.
        "ccsync_companion.reporter",
        "ccsync_companion.sync",
        "ccsync_companion.sync.base",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Not needed by the onboarding wizard -- keeps the build small and
        # avoids pulling in the tray/sync engines' own heavier dependencies
        # (watchdog, pystray, Pillow) that identity.py/config.py don't need.
        "ccsync_companion.app",
        "ccsync_companion.tray",
        "ccsync_companion.watcher",
        "ccsync_companion.popup",
        "ccsync_companion.fixer",
        "ccsync_companion.resolve_bridge",
        "ccsync_companion.selection",
        "ccsync_companion.consolidate",
        "ccsync_companion.manifest",
        "ccsync_companion.sync.rclone_lane",
        "ccsync_companion.sync.syncthing_lane",
        "watchdog",
        "pystray",
        "PIL",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

# One-FILE build: a single distributable onboard.exe. Everything (the
# bundled windows_bootstrap.ps1 and the ccsync_companion modules) is packed
# into the exe and extracted to sys._MEIPASS at launch, which
# steps.find_bootstrap_script() already looks in.
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="onboard",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    # upx=False deliberately. A UPX-packed, unsigned, onefile exe is the
    # classic SmartScreen / AV false-positive shape -- and this is a binary a
    # remote editor has to download and run as their FIRST contact with the
    # system. A few MB of size is worth not having the installer quarantined.
    upx=False,
    runtime_tmpdir=None,
    console=False,  # GUI app -- no console window
    icon=str(COMPANION_SRC / "ccsync_companion" / "assets" / "icon.ico"),
)
