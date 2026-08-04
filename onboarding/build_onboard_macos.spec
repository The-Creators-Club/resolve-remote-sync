# PyInstaller spec for the macOS onboarding wizard -- "CCSync Onboarding.app".
#
# The darwin twin of build_onboard.spec. Build ON A MAC (PyInstaller does not
# cross-compile), from onboarding/, with a python that has pyinstaller and
# can import the companion package (companion/.venv after
# tools/release_macos.sh has run is exactly that):
#
#     ../companion/.venv/bin/python -m PyInstaller build_onboard_macos.spec --noconfirm
#
# or via tools/build_onboard_macos.sh, which also verifies the signature and
# zips the .app. Output:
#
#     dist/ccsync-onboard            -- the bare windowed onefile binary
#     dist/CCSync Onboarding.app     -- the double-clickable bundle around it
#
# macos_bootstrap.sh and the macOS companion binary are packed inside and
# extracted to sys._MEIPASS at launch, which steps.find_bootstrap_script() /
# find_companion_exe() already look in. The companion binary loses its
# executable bit inside `datas` -- deliberate non-issue: macos_bootstrap.sh
# chmod +x's its staged copy before moving it into place.
#
# Gatekeeper: PyInstaller ad-hoc signs the binary AND the .app
# (codesign_identity=None below means `codesign -s -`, not "unsigned" --
# mandatory on Apple silicon, same as companion/build.spec). An ad-hoc
# signed app that arrives with the com.apple.quarantine xattr (browser
# download, AirDrop) is still blocked by Gatekeeper on first open; macOS 15
# requires System Settings > Privacy & Security > "Open Anyway" once. A
# curl download or a USB copy carries no quarantine and opens directly.
# NOT YET RUN ON A REAL MAC -- validate before handing to an editor.

import sys
from pathlib import Path

block_cipher = None

SPEC_DIR = Path(SPECPATH)
REPO_ROOT = SPEC_DIR.parent
COMPANION_SRC = REPO_ROOT / "companion" / "src"
BOOTSTRAP_SH = REPO_ROOT / "installer" / "macos_bootstrap.sh"
COMPANION_BIN = REPO_ROOT / "companion" / "dist" / "ccsync-companion"

sys.path.insert(0, str(COMPANION_SRC))
sys.path.insert(0, str(SPEC_DIR))

if sys.platform != "darwin":
    raise SystemExit(
        "build_onboard_macos.spec builds the macOS wizard and only runs on a "
        "Mac (PyInstaller does not cross-compile). onboard.exe comes from "
        "build_onboard.spec on Windows."
    )

if not COMPANION_BIN.exists():
    raise SystemExit(
        f"macOS companion binary not found at {COMPANION_BIN} -- build it first:\n"
        f"  ./tools/release_macos.sh"
    )

a = Analysis(
    ["onboard.py"],
    pathex=[str(SPEC_DIR), str(COMPANION_SRC)],
    binaries=[],
    datas=[
        (str(BOOTSTRAP_SH), "."),
        (str(COMPANION_BIN), "."),   # bundled so the wizard installs everything
        # Logo for the wizard window icon -- theme.apply_window_icon() reads
        # it from sys._MEIPASS/ccsync_companion/assets/icon.png.
        (str(COMPANION_SRC / "ccsync_companion" / "assets" / "icon.png"),
         "ccsync_companion/assets"),
    ],
    hiddenimports=[
        # Same set as build_onboard.spec, same reasoning.
        "ccsync_companion",
        "ccsync_companion.identity",
        "ccsync_companion.config",
        "ccsync_companion.theme",
        "ccsync_companion.reporter",
        "ccsync_companion.sync",
        "ccsync_companion.sync.base",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Same exclusions as build_onboard.spec: the wizard needs none of the
        # tray/sync machinery or its heavy deps.
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
    name="ccsync-onboard",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    # upx=False for the same reason as every other spec in this repo: a
    # packed, unsigned onefile binary is the classic AV/Gatekeeper
    # false-positive shape, and this is an editor's FIRST contact.
    upx=False,
    runtime_tmpdir=None,
    console=False,  # GUI app -- no Terminal window
    # Ad-hoc signature (see the header comment); an unsigned arm64 binary is
    # killed by the kernel on launch.
    codesign_identity=None,
    entitlements_file=None,
    # No .icns in this repo (same note as companion/build.spec); the window
    # icon comes from assets/icon.png via theme.apply_window_icon().
    icon=None,
)

app = BUNDLE(
    exe,
    name="CCSync Onboarding.app",
    icon=None,
    bundle_identifier="com.creatorsclub.ccsync.onboard",
    info_plist={
        "CFBundleShortVersionString": "1.0.19",  # INSTALLER_VERSION -- bump together
        "NSHighResolutionCapable": True,
        # The wizard is a foreground app with a real window; no LSUIElement.
    },
)
