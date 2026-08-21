# PyInstaller spec for the macOS onboarding wizard -- "CCSync Onboarding.app".
#
# ######################################################################
# # ONEDIR SINCE 2026-08-05 -- THE FIRST MAC BUILD MUST BE WATCHED.    #
# ######################################################################
#
# This spec was ONEFILE through installer 1.0.19 (the only .app that has ever
# been built and handed out). It is now ONEDIR -- EXE(exclude_binaries=True)
# -> COLLECT -> BUNDLE -- because PyInstaller 6.21 already logs
#
#     "Onefile mode in combination with macOS .app bundles (windowed mode)
#      don't make sense ... Please migrate to onedir mode. This will become
#      an error in v7.0."
#
# and the only machine that can build this artifact is a Mac, so a v7 upgrade
# would surface as a broken release on the one path with no fallback
# (KNOWN_BUGS.md item 9). The migration was written ON WINDOWS and has NEVER
# BEEN BUILT: run tools/build_onboard_macos.sh on the Mac and walk the wizard
# step of installer/MACOS_FIRST_RUN.md (section C) -- build, `codesign --verify
# --deep --strict`, unzip, double-click -- BEFORE publishing it to editors.
#
# What onedir changes, and what it deliberately does not:
#
#   * The artifact is still dist/CCSync Onboarding.app, still zipped by
#     `ditto -c -k --keepParent`. That is Apple's own way to zip a bundle and
#     it preserves symlinks -- which matters now, because a onedir .app is
#     full of the cross-links BUNDLE creates between Contents/Frameworks and
#     Contents/Resources. The zip the dashboard serves keeps its shape, so
#     nothing downstream (publish, [ INSTALLER ], unzip, open) changes.
#
#   * dist/ccsync-onboard is no longer a bare distributable binary. In onedir
#     the EXE is built into build/ (WORKPATH) and COLLECT writes a plain
#     dist/ccsync-onboard/ DIRECTORY next to the .app. Nobody ships that
#     directory; tools/build_onboard_macos.sh only ever touches the .app.
#
#   * sys._MEIPASS still exists and still holds the bundled files, so
#     steps.find_bootstrap_script() / find_companion_exe() and
#     theme.apply_window_icon() resolve exactly as before -- but it now points
#     at <app>/Contents/Frameworks instead of an unpacked temp dir. BUNDLE
#     puts data files in Contents/Resources and cross-links them into
#     Contents/Frameworks (top-level entries are linked file by file), so
#     _MEIPASS/macos_bootstrap.sh and
#     _MEIPASS/ccsync_companion/assets/icon.png both resolve through symlinks.
#     The companion binary is Mach-O, so Analysis's binary-vs-data
#     reclassification moves it out of `datas` into `binaries` (that already
#     happens today, in onefile) and BUNDLE puts it straight into
#     Contents/Frameworks -- where, unlike a onefile extraction, it keeps its
#     0755 bit. steps.install_companion() chmods it anyway; the old "loses its
#     executable bit inside datas" caveat is simply no longer true.
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
#     build/build_onboard_macos/ccsync-onboard  -- the windowed bootloader exe
#     dist/ccsync-onboard/                      -- the onedir build (not shipped)
#     dist/CCSync Onboarding.app                -- the bundle that IS shipped
#
# Gatekeeper: PyInstaller ad-hoc signs every collected binary AND the .app
# itself, the latter with `codesign --deep` (codesign_identity=None below
# means `codesign -s -`, not "unsigned" -- mandatory on Apple silicon, same as
# companion/build.spec). In onedir this matters more than it did in onefile:
# the bundled companion binary is now a real nested Mach-O inside
# Contents/Frameworks rather than a byte range inside one exe, which is
# exactly the layout --deep expects (and the reason Apple wants onedir here).
# An ad-hoc signed app that arrives with the com.apple.quarantine xattr
# (browser download, AirDrop) is still blocked by Gatekeeper on first open;
# macOS 15 requires System Settings > Privacy & Security > "Open Anyway"
# once. A curl download or a USB copy carries no quarantine and opens
# directly.

import sys
from pathlib import Path

block_cipher = None

SPEC_DIR = Path(SPECPATH)
REPO_ROOT = SPEC_DIR.parent
COMPANION_SRC = REPO_ROOT / "companion" / "src"
BOOTSTRAP_SH = REPO_ROOT / "installer" / "macos_bootstrap.sh"
COMPANION_BIN = REPO_ROOT / "companion" / "dist" / "ccsync-companion"
EULA_MD = SPEC_DIR / "assets" / "EULA.md"

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
        # The white-on-transparent mark is what theme.apply_window_icon()
        # prefers now (tinted to the brand red at runtime); icon.png stays as
        # its fallback. Without the mark the wizard silently degrades to the
        # old April logo -- the first thing a new editor ever sees
        # (2026-08-11). BOTH marks ship: cc_mark_white.png is the Creators
        # Club mark and the default (2026-08-18); ccsync_mark.png is the
        # neutral one a white-label fleet selects with brand_logo /
        # CCSYNC_BRAND_LOGO (2026-08-17, COMMERCIAL_READINESS.md item 10).
        (str(COMPANION_SRC / "ccsync_companion" / "assets" / "ccsync_mark.png"),
         "ccsync_companion/assets"),
        (str(COMPANION_SRC / "ccsync_companion" / "assets" / "cc_mark_white.png"),
         "ccsync_companion/assets"),
        (str(COMPANION_SRC / "ccsync_companion" / "assets" / "icon.png"),
         "ccsync_companion/assets"),
        # The licence the wizard's first page shows and takes consent for
        # (2026-08-17, COMMERCIAL_READINESS.md item 3) --
        # steps.find_eula_asset() reads it from sys._MEIPASS/assets/EULA.md.
        # Same entry as build_onboard.spec; the two specs must ship the same
        # document or a Mac editor accepts something a Windows one did not.
        (str(EULA_MD), "assets"),
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

# ONEDIR (see the header): exclude_binaries=True means the EXE is just the
# bootloader + the PYZ, and a.binaries / a.datas are collected alongside it by
# COLLECT instead of being packed inside. Passing them here as well would
# quietly rebuild a onefile app -- PyInstaller ignores them for the archive
# and hands them to COLLECT via PKG.dependencies, but the intent would be
# wrong. runtime_tmpdir is gone with the same logic: it only ever meant
# anything for a onefile extraction, and there is no longer one.
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="ccsync-onboard",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    # upx=False for the same reason as every other spec in this repo: a
    # packed, unsigned binary is the classic AV/Gatekeeper false-positive
    # shape, and this is an editor's FIRST contact.
    upx=False,
    console=False,  # GUI app -- no Terminal window
    # Ad-hoc signature (see the header comment); an unsigned arm64 binary is
    # killed by the kernel on launch. COLLECT and BUNDLE inherit this (and
    # console/target_arch/entitlements) from the EXE, so it is set once.
    codesign_identity=None,
    entitlements_file=None,
    # No .icns in this repo (same note as companion/build.spec); the window
    # icon comes from assets/icon.png via theme.apply_window_icon().
    icon=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="ccsync-onboard",
)

app = BUNDLE(
    # BUNDLE takes the COLLECT, not the EXE: handing it a non-exclude_binaries
    # EXE is what triggers PyInstaller 6.21's onefile-.app deprecation warning
    # and becomes a hard error in v7.0.
    coll,
    name="CCSync Onboarding.app",
    icon=None,
    # com.creatorsclub.* until 2026-08-17 -- one tenant's name in the
    # reverse-DNS identity of a product sold to others
    # (docs/COMMERCIAL_READINESS.md item 10). The wizard is not a long-lived
    # job, so unlike the LaunchAgent labels this one needs no migration: a
    # renamed .app bundle id only re-prompts for the TCC permissions the
    # wizard asks for (Full Disk Access is NOT one of them).
    bundle_identifier="com.ccsync.onboard",
    info_plist={
        "CFBundleShortVersionString": "1.0.36",  # INSTALLER_VERSION -- bump together
        "NSHighResolutionCapable": True,
        # The wizard is a foreground app with a real window; no LSUIElement.
    },
)
