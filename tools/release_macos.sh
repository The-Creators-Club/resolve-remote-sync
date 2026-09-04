#!/usr/bin/env bash
#
# CC Sync -- macOS companion release.
#
# The Mac-side twin of tools/release.ps1: verify version + vendored-file
# parity, run the tests, run PyInstaller, confirm the ad-hoc signature, and
# stamp a manifest describing exactly what came out. Optionally publish it to the dashboard's
# upgrade channel, which is the ONLY place a macOS companion is ever served
# from (it never goes on the P:\ editor share -- that package carries the
# Windows exe and the two bootstrap scripts).
#
# WHY THIS FILE EXISTS AT ALL. PyInstaller does not cross-compile, so nothing
# on the Windows base rig can produce the Mac binary. Every Windows ship
# therefore succeeds while the macOS channel silently stays where it was:
# build_editor_package.ps1, tools/ship.ps1 and tools/check_deploy_drift.ps1
# all print an advisory when they notice, and this script is what you run in
# response. The 2026-07-25 "we verified it against a build nobody was
# running" incident (docs/RELEASE.md) is the same failure with one more
# machine in it.
#
# It is written on Windows and RUNS ONLY ON macOS -- it refuses to start
# anywhere else. Everything it does is read-only against the repo: it never
# runs a git write command, only rev-parse/describe/status for provenance.
# A dirty working tree does not block the build (that would make the common
# case impossible) but is called out loudly, and the manifest version is
# stamped "<version>+dirty" so an artifact built from uncommitted work can
# never be mistaken for a released one.
#
# Usage:
#   ./tools/release_macos.sh [--skip-tests] [--allow-dirty] [--dry-run]
#                            [--publish [--make-current]]
#                            [--dashboard-url URL] [--admin-user NAME]
#
set -u

INSPECT_ONLY=0
SKIP_TESTS=0
ALLOW_DIRTY=0
DRY_RUN=0
PUBLISH=0
MAKE_CURRENT=0
# No defaults since 2026-08-17 (WP0, docs/SYNOLOGY_PORT_PLAN.md): these used
# to name one deployment's dashboard and one person's account. --publish
# refuses without them; the environment is the setx-once equivalent here.
DASHBOARD_URL="${CCSYNC_DASHBOARD_URL:-}"
ADMIN_USER="${CCSYNC_ADMIN_USER:-}"

usage() {
    echo "Usage: $0 [--skip-tests] [--allow-dirty] [--dry-run]"
    echo "          [--publish [--make-current]] [--dashboard-url <url>]"
    echo "          [--admin-user <name>]"
    echo ""
    echo "  --skip-tests      do not run the companion suite (recorded in the"
    echo "                    manifest as tests_run=false)"
    echo "  --allow-dirty     acknowledge a dirty tree: shrink the banner to one"
    echo "                    line. The manifest is stamped +dirty either way."
    echo "  --dry-run         print every step, change nothing, build nothing"
    echo "  --publish         upload the built binary to the dashboard upgrade"
    echo "                    channel (prompts for your dashboard password)"
    echo "  --make-current    with --publish: offer it to the fleet immediately"
    echo "  --dashboard-url   REQUIRED with --publish (or CCSYNC_DASHBOARD_URL)"
    echo "  --admin-user      REQUIRED with --publish (or CCSYNC_ADMIN_USER)"
    exit 1
}

while [ $# -gt 0 ]; do
    case "$1" in
        --skip-tests)     SKIP_TESTS=1; shift ;;
        --allow-dirty)    ALLOW_DIRTY=1; shift ;;
        --dry-run)        DRY_RUN=1; shift ;;
        --publish)        PUBLISH=1; shift ;;
        --make-current)   MAKE_CURRENT=1; shift ;;
        --dashboard-url)  DASHBOARD_URL="$2"; shift 2 ;;
        --admin-user)     ADMIN_USER="$2"; shift 2 ;;
        -h|--help)        usage ;;
        *) echo "Unknown argument: $1"; usage ;;
    esac
done

step() { echo "[release] $1"; }
skip() { echo "[release] SKIP: $1"; }
warn() { echo "[release] WARNING: $1" >&2; }
dry()  { echo "[release] [dry-run] $1"; }
rule() { echo "=================================================================="; }
fail() {
    echo "[release] FAILED: $1" >&2
    exit 1
}

have_cmd() { command -v "$1" >/dev/null 2>&1; }

# WHERE this publishes to, and AS WHOM -- refused before the build, not after
# it (2026-08-17, WP0). Neither has a compiled-in default any more.
if [ "$PUBLISH" = 1 ]; then
    [ -n "$DASHBOARD_URL" ] || fail "--publish needs --dashboard-url (or CCSYNC_DASHBOARD_URL) -- there is no default dashboard compiled in"
    [ -n "$ADMIN_USER" ] || fail "--publish needs --admin-user (or CCSYNC_ADMIN_USER) -- there is no default admin account compiled in"
fi
DASHBOARD_URL="${DASHBOARD_URL%/}"

# ---CCSYNC-PASSWORD-HYGIENE-BEGIN---
# Everything between these two sentinels is COPY-SHARED, byte for byte, with
# the other macOS publish script (tools/release_macos.sh <-> tools/
# build_onboard_macos.sh). companion/tests/test_publish_password_hygiene.py
# greps the two copies against each other the way server/tests/
# test_cross_component.py does with the .stignore builders, so a change made
# to one copy fails the suite until it is made to both. (A third, simpler
# json_escape lives in installer/macos_bootstrap.sh for its own manifest; it
# is not part of this pair.)
#
# KNOWN_BUGS item 10, hit live 2026-08-04: json_escape() escaped backslash and
# double quote only, so a password carrying any byte < 0x20 produced INVALID
# JSON and the dashboard answered 422 json_invalid / "Invalid control
# character at 31" -- which reads as "wrong password" and is not. The usual
# source is a bracketed paste: zsh wraps pasted text in ESC[200~ ... ESC[201~
# and `read -r -s` captures the escapes along with the password.

# JSON string escaping, byte by byte: a password (or a git describe from a
# strangely named branch) must not be able to break out of the string it is
# written into, and no byte it contains may make the JSON invalid.
#
# od+awk rather than sed because a value may contain bytes that are not valid
# UTF-8, and BSD sed answers those with "RE error: illegal byte sequence"
# (macOS ships BSD sed and BWK awk -- MAC-9 is what assuming GNU tools costs
# here). LC_ALL=C keeps awk's %c a byte rather than a re-encoded character, so
# a UTF-8 password passes through as the bytes it arrived as. The escape
# characters themselves are built with sprintf("%c") so that no awk gets the
# chance to interpret a backslash in a printf format string.
json_escape() {
    printf '%s' "$1" | LC_ALL=C od -v -A n -t u1 | LC_ALL=C awk '
        BEGIN { bs = sprintf("%c", 92); dq = sprintf("%c", 34) }
        {
            for (i = 1; i <= NF; i++) {
                b = $i + 0
                if      (b == 92) printf "%s%s", bs, bs
                else if (b == 34) printf "%s%s", bs, dq
                else if (b == 10) printf "%sn", bs
                else if (b == 13) printf "%sr", bs
                else if (b ==  9) printf "%st", bs
                else if (b ==  8) printf "%sb", bs
                else if (b == 12) printf "%sf", bs
                else if (b < 32 || b == 127) printf "%su%04x", bs, b
                else printf "%c", b
            }
        }'
}

# Strip the wrappers a terminal puts around pasted text: bracketed paste is
# ESC[200~ before and ESC[201~ after. They are removed wherever they appear,
# not only at the ends, because pasting into a partly-typed line puts them in
# the middle.
strip_bracketed_paste() {
    local esc
    esc="$(printf '\033')"
    printf '%s' "$1" | LC_ALL=C sed -e "s/${esc}\[200~//g" -e "s/${esc}\[201~//g"
}

# Refuse a value that still carries a byte no keyboard produces. Stripping the
# paste wrappers is not enough on its own: a control byte that is NOT part of
# a wrapper would then travel as a valid JSON escape and come back 401
# "invalid credentials", which is a worse lie than the 422 it replaced. The
# position is 1-based and counted in bytes of the value itself.
reject_non_printable() {
    local label="$1" value="$2" found
    found="$(printf '%s' "$value" | LC_ALL=C od -v -A n -t u1 | LC_ALL=C awk '
        {
            for (i = 1; i <= NF; i++) {
                n++
                b = $i + 0
                if (b < 32 || b == 127) { printf "byte 0x%02x at position %d", b, n; exit }
            }
        }')"
    [ -z "$found" ] || fail "the $label contains a non-printable character ($found) -- retype it rather than pasting.
         A terminal wraps pasted text in invisible control bytes; the bracketed-paste
         pair (ESC[200~ ... ESC[201~) has already been stripped, so this byte is
         something else. Sent as-is it would build invalid JSON and the dashboard
         would answer 422 json_invalid, which reads as a wrong password and is not."
}

# Prompt for the dashboard password on stderr. -s: never echoed. The password
# goes to curl on STDIN, never in argv and never in an environment variable.
# The username rides in the same JSON object, so it is checked too. Sets
# DASH_PASSWORD.
read_dashboard_password() {
    reject_non_printable "username" "$ADMIN_USER"
    printf 'dashboard password for %s@%s: ' "$ADMIN_USER" "$DASHBOARD_URL" >&2
    read -r -s DASH_PASSWORD
    echo "" >&2
    DASH_PASSWORD="$(strip_bracketed_paste "$DASH_PASSWORD")"
    if [ -z "$DASH_PASSWORD" ]; then
        fail "no password was entered -- NOT publishing.
         (If you pasted one, the terminal may have delivered nothing but the
         paste wrapper, which is stripped: type it instead.)"
    fi
    reject_non_printable "password" "$DASH_PASSWORD"
}
# ---CCSYNC-PASSWORD-HYGIENE-END---

# First capture group of the first matching line, or "" when absent -- the
# bash twin of release.ps1's Get-Capture.
capture() {
    local path="$1" expr="$2"
    [ -f "$path" ] || return 0
    sed -n "$expr" "$path" 2>/dev/null | head -n 1
}

# Is the companion's vendored copy still byte-identical to its source? Prints
# "" when they agree, or a one-line description of the problem -- the bash twin
# of release.ps1's Get-VendorParityProblem (SHIP-3, 2026-08-14: this script
# calls itself "the Mac-side twin of tools/release.ps1" and had no such gate,
# and the suite that DOES pin this parity is server/tests, which this script
# does not run and a Mac cannot run through ship.cmd).
#
# FAIL SAFE, exactly like the Windows copy: a missing, unreadable or
# marker-less file is a problem, never a skip -- "I could not check" must not
# read as "fine".
#
# A fourth argument of "exact" compares the WHOLE file instead of the part
# below the marker -- for a vendored copy that cannot carry a header at all
# (the local-VLM prompt: its bytes are what the model is sent). Same rule as
# release.ps1's -Mode.
vendor_parity_problem() {
    local source_path="$1" vendored_path="$2" marker="$3" mode="${4:-marker}" count marker_line
    [ -f "$source_path" ] || { printf '%s' "cannot read $source_path (missing) -- refusing rather than skipping the check"; return 0; }
    [ -f "$vendored_path" ] || { printf '%s' "cannot read $vendored_path (missing) -- refusing rather than skipping the check"; return 0; }

    if [ "$mode" = "exact" ]; then
        if cmp -s "$vendored_path" "$source_path"; then
            printf '%s' ""
        else
            printf '%s' "the vendored copy has DRIFTED from its source (this pair carries no header -- the whole file must match)"
        fi
        return 0
    fi

    count="$(grep -c -x -F "$marker" "$vendored_path" 2>/dev/null || true)"
    [ -n "$count" ] || count=0
    if [ "$count" -eq 0 ]; then
        printf '%s' "the vendored copy has no '$marker' line -- that marker is what separates its header from the vendored bytes; restore it"
        return 0
    fi
    if [ "$count" -gt 1 ]; then
        printf '%s' "the vendored copy carries '$marker' more than once -- ambiguous header end; leave exactly one, as the last line of the header"
        return 0
    fi

    marker_line="$(grep -n -x -F "$marker" "$vendored_path" | head -n 1 | cut -d: -f1)"
    # Everything BELOW the marker line must be the source file, byte for byte.
    if tail -n "+$((marker_line + 1))" "$vendored_path" | cmp -s - "$source_path"; then
        printf '%s' ""
    else
        printf '%s' "the vendored copy has DRIFTED from its source below the marker (cmp says the bytes differ)"
    fi
}

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
COMPANION_DIR="$REPO_ROOT/companion"
CONFIG_PY="$COMPANION_DIR/src/ccsync_companion/config.py"
PYPROJECT="$COMPANION_DIR/pyproject.toml"
# The vendored-file parity pair (docs/YTDL_LOCAL_DOWNLOAD.md section 5).
# ytdl/web's copy is the SOURCE OF TRUTH; the companion carries a header and
# then the same bytes, because the frozen binary has no ytdlweb and the
# dashboard container has no ccsync_companion.
YTDL_COMMON_SRC="$REPO_ROOT/ytdl/web/ytdlweb/ytdl_common.py"
YTDL_COMMON_VENDORED="$COMPANION_DIR/src/ccsync_companion/ytdl_common.py"
# The identity verifier, whose copies cross TREES rather than reaching the
# companion: music/web's joined 2026-08-18 (docs/MUSIC_INGEST_PLAN.md step 2)
# because music ingest grew fleet routes with the same token-is-not-an-identity
# problem. Checked here as well as in release.ps1 for SHIP-3's reason -- a pair
# pinned in the Windows gate only lets a Mac build ship a drifted copy.
YTDL_COMMON_SRC_IDENTITY="$REPO_ROOT/ytdl/web/ytdlweb/identity.py"
VENDOR_MARKER="# --- vendored content below, byte-identical ---"
# Every pair, as "source|vendored|mode" -- the bash twin of release.ps1's
# $VendorPairs. The broll_vlm set joined 2026-08-18 (docs/BROLL_INGEST_PLAN.md
# section 3.3): the companion indexes b-roll with the INDEXER's local backend,
# so a drifted copy describes clips differently into the one search database.
VENDOR_PAIRS="
$YTDL_COMMON_SRC|$YTDL_COMMON_VENDORED|marker
$REPO_ROOT/broll/indexer/broll_index/local_models.py|$COMPANION_DIR/src/ccsync_companion/broll_vlm/local_models.py|marker
$REPO_ROOT/broll/indexer/broll_index/local_runtime.py|$COMPANION_DIR/src/ccsync_companion/broll_vlm/local_runtime.py|marker
$REPO_ROOT/broll/indexer/broll_index/local_vlm.py|$COMPANION_DIR/src/ccsync_companion/broll_vlm/local_vlm.py|marker
$REPO_ROOT/broll/indexer/broll_index/compact_format.py|$COMPANION_DIR/src/ccsync_companion/broll_vlm/compact_format.py|marker
$REPO_ROOT/broll/indexer/broll_index/contract.py|$COMPANION_DIR/src/ccsync_companion/broll_vlm/contract.py|marker
$REPO_ROOT/broll/indexer/broll_index/prompts/index_clip_v7_compact.md|$COMPANION_DIR/src/ccsync_companion/broll_vlm/prompts/index_clip_v7_compact.md|exact
$YTDL_COMMON_SRC_IDENTITY|$REPO_ROOT/music/web/musicweb/identity.py|marker
$REPO_ROOT/music/indexer/music_models.py|$COMPANION_DIR/src/ccsync_companion/music_clap/music_models.py|marker
$REPO_ROOT/music/indexer/mel_numpy.py|$COMPANION_DIR/src/ccsync_companion/music_clap/mel_numpy.py|marker
"
DIST_DIR="$COMPANION_DIR/dist"
ARTIFACT="$DIST_DIR/ccsync-companion"
MANIFEST="$DIST_DIR/ccsync-release.json"
VENV_DIR="$COMPANION_DIR/.venv"
VENV_PY="$VENV_DIR/bin/python"

rule
step "repo root: $REPO_ROOT"
if [ "$DRY_RUN" = 1 ]; then
    step "DRY RUN -- nothing will be built, written, or published"
fi

# ----------------------------------------------------------------------
# 1/6 platform guard
# ----------------------------------------------------------------------
echo ""
step "--- step 1/6: platform ---"

UNAME_S="$(uname -s 2>/dev/null || echo unknown)"
if [ "$UNAME_S" = "Darwin" ]; then
    step "macOS ($(uname -m), $(sw_vers -productVersion 2>/dev/null || echo 'version unknown'))"
elif [ "$DRY_RUN" = 1 ]; then
    # The one concession: --dry-run on the Windows dev box (Git Bash) so the
    # parity/provenance half can be exercised where this file is edited. It
    # cannot build, cannot sign, cannot publish -- every one of those steps is
    # already skipped by --dry-run.
    INSPECT_ONLY=1
    warn "this is $UNAME_S, not macOS -- --dry-run continues in INSPECTION MODE"
    warn "(version parity and git provenance only; no venv, no build, no publish)"
else
    echo ""
    fail "this script builds the macOS companion and only runs on a Mac (uname says '$UNAME_S').
         PyInstaller does not cross-compile: the Windows exe comes from
         tools\\release.ps1 on the base rig, and this binary comes from here.
         Copy the repo to the Mac (or pull it there) and run it again.
         --dry-run works anywhere if you only want to see the steps."
fi

# ----------------------------------------------------------------------
# 2/6 version parity + git provenance
# ----------------------------------------------------------------------
echo ""
step "--- step 2/6: version parity ---"

VERSION="$(capture "$CONFIG_PY" 's/^VERSION[[:space:]]*=[[:space:]]*"\([^"]*\)".*/\1/p')"
PYPROJECT_VERSION="$(capture "$PYPROJECT" 's/^version[[:space:]]*=[[:space:]]*"\([^"]*\)".*/\1/p')"
BOOTSTRAP_PS1_VERSION="$(capture "$REPO_ROOT/installer/windows_bootstrap.ps1" 's/^\$InstallerVersion[[:space:]]*=[[:space:]]*"\([^"]*\)".*/\1/p')"
ONBOARD_VERSION="$(capture "$REPO_ROOT/onboarding/steps.py" 's/^INSTALLER_VERSION[[:space:]]*=[[:space:]]*"\([^"]*\)".*/\1/p')"
MAC_BOOTSTRAP_VERSION="$(capture "$REPO_ROOT/installer/macos_bootstrap.sh" 's/^INSTALLER_VERSION="\([^"]*\)".*/\1/p')"

if [ -z "$VERSION" ]; then
    fail "could not parse VERSION from $CONFIG_PY -- that file is the single source of truth; nothing else can proceed"
fi

step "companion VERSION (config.py, authoritative): $VERSION"
step "companion version (pyproject.toml):           $PYPROJECT_VERSION"
step "installer version (windows_bootstrap.ps1):    $BOOTSTRAP_PS1_VERSION"
step "installer version (onboarding/steps.py):      $ONBOARD_VERSION"
step "installer version (macos_bootstrap.sh):       $MAC_BOOTSTRAP_VERSION"

if [ "$PYPROJECT_VERSION" != "$VERSION" ]; then
    echo ""
    fail "version parity check failed:
         companion/pyproject.toml says '$PYPROJECT_VERSION',
         companion/src/ccsync_companion/config.py says '$VERSION'.
         Set both to the SAME value and re-run."
fi

# The dashboard rejects anything else (_PACKAGE_VERSION_RE), so a 0.4.5-dev
# would build fine here and 422 at the publish -- after the whole build.
if ! printf '%s' "$VERSION" | grep -Eq '^[0-9]+\.[0-9]+\.[0-9]+$'; then
    fail "VERSION '$VERSION' does not look like 1.2.3 -- the dashboard refuses to publish anything else"
fi
step "version parity OK"

# --- vendored-file parity (docs/YTDL_LOCAL_DOWNLOAD.md section 5) -----
#
# Same class of failure as the installer version drift below, one layer down: a
# file duplicated across two trees that cannot import each other. The
# consequence is worse -- a companion whose ytdl_common has drifted from the
# NAS worker's downloads the same YouTube clip under a second filename into the
# one canonical tree, and nobody finds out until an editor sees the same video
# twice. The binary about to be built BAKES IN whatever is in companion/src, so
# this is the last moment the two copies can be compared, and the suite this
# script runs (companion/) does not compare them: the assertion lives in
# server/tests/test_cross_component.py, which only ship.cmd runs and which
# cannot run on a Mac. Hence a hard refusal here, exactly as tools/release.ps1
# does on Windows (SHIP-3, 2026-08-14).
VENDOR_PAIR_COUNT=0
# A here-string, NOT a pipeline: `... | while read` runs the loop in a subshell,
# where `fail`'s exit could not stop this script -- the gate would print and
# then build anyway. Reading with IFS='|' also survives a repo path with a
# space in it, which `for pair in $VENDOR_PAIRS` would not.
while IFS='|' read -r pair_src pair_vendored pair_mode; do
    [ -n "$pair_src" ] || continue
    VENDOR_PROBLEM="$(vendor_parity_problem "$pair_src" "$pair_vendored" "$VENDOR_MARKER" "$pair_mode")"
    if [ -n "$VENDOR_PROBLEM" ]; then
        echo ""
        fail "vendored-file parity check failed:
         $VENDOR_PROBLEM
         source   (edit THIS one): $pair_src
         vendored (do not edit)  : $pair_vendored
         Fix: make the change in the SOURCE file -- it is the source of truth -- then
         re-copy that whole file into the companion BELOW the marker line
         \"$VENDOR_MARKER\", leaving the companion header above it untouched
         (the local-VLM prompt has no header: copy it whole).
         (docs/YTDL_LOCAL_DOWNLOAD.md section 5 and docs/BROLL_INGEST_PLAN.md
         section 3.3: two trees that cannot import each other must not drift --
         one grows a second filename for the same YouTube clip, the other
         describes clips differently into the one search database.)"
    fi
    VENDOR_PAIR_COUNT=$((VENDOR_PAIR_COUNT + 1))
done <<< "$VENDOR_PAIRS"
step "vendored parity OK ($VENDOR_PAIR_COUNT pairs: ytdl_common.py + the broll_vlm set)"

# The installer number is a separate thing from the companion version and this
# script publishes none of the three files that carry it -- so drift here is
# reported, not fatal. It IS fatal in tools/release.ps1 and in
# build_editor_package.ps1 -Publish, which is where those files ship from.
if [ -n "$BOOTSTRAP_PS1_VERSION" ] && [ -n "$ONBOARD_VERSION" ] && [ -n "$MAC_BOOTSTRAP_VERSION" ]; then
    if [ "$BOOTSTRAP_PS1_VERSION" != "$ONBOARD_VERSION" ] || [ "$BOOTSTRAP_PS1_VERSION" != "$MAC_BOOTSTRAP_VERSION" ]; then
        warn "installer version drift (windows_bootstrap.ps1 '$BOOTSTRAP_PS1_VERSION', steps.py '$ONBOARD_VERSION', macos_bootstrap.sh '$MAC_BOOTSTRAP_VERSION') -- not this script's artifact, but fix it before the next Windows ship"
    fi
else
    warn "could not read all three installer version constants -- not this script's artifact, but check them"
fi

# --- git provenance (read-only) ---------------------------------------
GIT_COMMIT="$(git -C "$REPO_ROOT" rev-parse --short HEAD 2>/dev/null || true)"
GIT_DESCRIBE="$(git -C "$REPO_ROOT" describe --tags --always --dirty 2>/dev/null || true)"
GIT_STATUS="$(git -C "$REPO_ROOT" status --porcelain 2>/dev/null || true)"
GIT_DIRTY=false
VERSION_STAMP="$VERSION"
if [ -n "$GIT_STATUS" ]; then
    GIT_DIRTY=true
    VERSION_STAMP="$VERSION+dirty"
fi

echo ""
if [ "$GIT_DIRTY" = true ]; then
    DIRTY_COUNT="$(printf '%s\n' "$GIT_STATUS" | grep -c '[^[:space:]]' || true)"
    if [ "$ALLOW_DIRTY" = 1 ]; then
        warn "working tree is DIRTY ($DIRTY_COUNT path(s)) -- manifest will be stamped $VERSION_STAMP"
    else
        warn "############################################################"
        warn "# THE WORKING TREE IS DIRTY -- $DIRTY_COUNT uncommitted path(s)."
        warn "# The binary about to be built does NOT correspond to any commit."
        warn "# The manifest will be stamped '$VERSION_STAMP'. Do not publish"
        warn "# a +dirty build to the fleet unless you are deliberately"
        warn "# testing it on your own machine."
        warn "############################################################"
        COMPANION_CHANGES="$(printf '%s\n' "$GIT_STATUS" | grep 'companion/src' || true)"
        if [ -n "$COMPANION_CHANGES" ]; then
            warn "uncommitted companion/src changes -- these WILL be baked into the binary:"
            printf '%s\n' "$COMPANION_CHANGES" | head -n 12 | while IFS= read -r line; do
                echo "      $line" >&2
            done
        fi
    fi
else
    step "working tree clean at ${GIT_COMMIT:-unknown}"
fi

if [ "$INSPECT_ONLY" = 1 ]; then
    echo ""
    rule
    step "INSPECTION MODE: steps 3-6 (venv, tests, build, sign, manifest, publish)"
    step "are macOS-only. Run this on the Mac to do them."
    rule
    exit 0
fi

# ----------------------------------------------------------------------
# 3/6 venv + tests
# ----------------------------------------------------------------------
echo ""
step "--- step 3/6: venv + tests ---"

# ".[dev,tray]", not ".[dev]": dev is only pytest, and the tray extra is what
# carries pystray/Pillow (plus pyobjc on darwin). Without them build.spec's
# import probe quietly drops the tray from the bundle and the editor gets a
# companion with no menu-bar icon -- i.e. no visible interface at all.
PIP_EXTRAS='.[dev,tray]'

if [ "$DRY_RUN" = 1 ]; then
    if [ -x "$VENV_PY" ]; then
        dry "would reuse the venv at $VENV_DIR"
    else
        dry "would create a venv: python3 -m venv $VENV_DIR"
    fi
    dry "would run: \$VENV/bin/python -m pip install -e '$PIP_EXTRAS' pyinstaller   (in $COMPANION_DIR)"
else
    if [ -x "$VENV_PY" ]; then
        step "reusing the venv at $VENV_DIR"
    else
        have_cmd python3 || fail "no python3 on PATH -- install the Command Line Tools (xcode-select --install) or python.org 3.12"
        step "creating a venv at $VENV_DIR ..."
        python3 -m venv "$VENV_DIR" || fail "python3 -m venv failed"
    fi
    [ -x "$VENV_PY" ] || fail "no python at $VENV_PY after creating the venv"
    step "python: $("$VENV_PY" --version 2>&1)"
    step "installing the companion (editable) + pyinstaller ..."
    ( cd "$COMPANION_DIR" && "$VENV_PY" -m pip install --disable-pip-version-check -e "$PIP_EXTRAS" pyinstaller ) \
        || fail "pip install failed -- nothing was built"
fi

if [ "$SKIP_TESTS" = 1 ]; then
    warn "--skip-tests: the companion suite was skipped (recorded in the manifest as tests_run=false)"
elif [ "$DRY_RUN" = 1 ]; then
    dry "would run: CCSYNC_REQUIRE_RCLONE=1 \$VENV/bin/python -m pytest -q   (in $COMPANION_DIR)"
else
    step "running the companion tests..."
    # CCSYNC_REQUIRE_RCLONE=1: pytest exits 0 when tests SKIP, and on a Mac
    # the rclone fixture used to look for a hardcoded "rclone.exe" -- so the
    # 24 tests that invoke a REAL rclone to prove lane A is up-only and lane
    # B is down-only silently no-op'd and the suite still read green (MAC-4,
    # 2026-08-04). In a release that is a failure, not a skip.
    ( cd "$COMPANION_DIR" && CCSYNC_REQUIRE_RCLONE=1 "$VENV_PY" -m pytest -q ) \
        || fail "companion tests failed -- NOT building. Fix them, or re-run with --skip-tests if you know why. (A missing rclone now FAILS rather than skipping: install it, or put ~/.local/ccsync/bin on PATH.)"
    step "companion tests passed"
fi

# ----------------------------------------------------------------------
# 4/6 build + ad-hoc signature
# ----------------------------------------------------------------------
echo ""
step "--- step 4/6: PyInstaller build ---"

ARTIFACT_ARCH=""
# Developer ID / notarised, as opposed to the ad-hoc signature PyInstaller
# always applies. Signed into the release record (item 4, 2026-08-17).
SIGNED_BINARY=false
if [ "$DRY_RUN" = 1 ]; then
    dry "would run: \$VENV/bin/python -m PyInstaller build.spec --noconfirm   (in $COMPANION_DIR)"
    dry "would then confirm the ad-hoc signature: codesign -dv $ARTIFACT"
else
    step "building (this takes a minute)..."
    ( cd "$COMPANION_DIR" && "$VENV_PY" -m PyInstaller build.spec --noconfirm ) \
        || fail "PyInstaller failed -- the binary in dist/ is stale or missing; NOT writing a manifest"
    [ -f "$ARTIFACT" ] || fail "PyInstaller reported success but there is no binary at $ARTIFACT"
    chmod +x "$ARTIFACT" 2>/dev/null || true
    step "built $ARTIFACT"

    # --- Developer ID + notarisation (COMMERCIAL_READINESS.md item 4,
    # 2026-08-17). Set these on the release Mac:
    #   CCSYNC_APPLE_DEV_ID       "Developer ID Application: Name (TEAMID)"
    #   CCSYNC_NOTARY_PROFILE     a keychain profile made once with
    #                             `xcrun notarytool store-credentials`
    # With neither, the ad-hoc signature PyInstaller applies stays and the
    # build is stamped signed_binary=false. Ad-hoc is enough for the KERNEL
    # (an unsigned arm64 binary is killed on launch) but not for GATEKEEPER:
    # a downloaded ad-hoc binary is refused with "cannot be opened because the
    # developer cannot be verified", and the editor has to right-click-Open or
    # clear the quarantine bit by hand -- which is exactly the instruction a
    # customer must never be given.
    #
    # --options runtime (hardened runtime) and --timestamp are BOTH required
    # for notarisation; a signature without either is accepted by codesign and
    # rejected by notarytool minutes later, after the upload.
    SIGNED_BINARY=false
    if [ -n "${CCSYNC_APPLE_DEV_ID:-}" ]; then
        have_cmd codesign || fail "CCSYNC_APPLE_DEV_ID is set but there is no codesign on PATH"
        step "signing with Developer ID: $CCSYNC_APPLE_DEV_ID"
        codesign --force --sign "$CCSYNC_APPLE_DEV_ID" --options runtime --timestamp "$ARTIFACT" \
            || fail "codesign with '$CCSYNC_APPLE_DEV_ID' failed -- NOT publishing an unsigned build under a signed build's version number"
        if [ -n "${CCSYNC_NOTARY_PROFILE:-}" ]; then
            # notarytool takes an archive, never a bare Mach-O.
            NOTARY_ZIP="$DIST_DIR/ccsync-companion-notarize.zip"
            rm -f "$NOTARY_ZIP"
            ditto -c -k --keepParent "$ARTIFACT" "$NOTARY_ZIP" \
                || fail "could not zip the binary for notarisation"
            step "submitting to Apple for notarisation (this can take minutes)..."
            xcrun notarytool submit "$NOTARY_ZIP" --keychain-profile "$CCSYNC_NOTARY_PROFILE" --wait \
                || fail "notarisation failed -- run: xcrun notarytool log <submission-id> --keychain-profile $CCSYNC_NOTARY_PROFILE"
            rm -f "$NOTARY_ZIP"
            # A bare Mach-O cannot be stapled (there is nowhere to put the
            # ticket) -- Gatekeeper looks the ticket up online instead, which
            # is why this is a warning and not a failure. It is the reason a
            # .app bundle would be worth having one day.
            xcrun stapler staple "$ARTIFACT" 2>/dev/null \
                && step "notarisation ticket stapled" \
                || warn "could not staple the ticket to a bare Mach-O -- Gatekeeper will check Apple online instead (works, but needs a network on first launch)"
        else
            warn "CCSYNC_NOTARY_PROFILE is not set -- the binary is Developer ID SIGNED but NOT NOTARISED."
            warn "Gatekeeper still refuses a downloaded unnotarised binary. Create the profile once:"
            warn "  xcrun notarytool store-credentials <profile> --apple-id <id> --team-id <team> --password <app-specific-password>"
        fi
        SIGNED_BINARY=true
    else
        warn "**********************************************************************"
        warn "UNSIGNED BUILD (ad-hoc only). No CCSYNC_APPLE_DEV_ID in the environment."
        warn "Every Mac editor who DOWNLOADS this build meets Gatekeeper's"
        warn "'cannot be opened because the developer cannot be verified'."
        warn "Buy an Apple Developer Program membership (Developer ID Application"
        warn "certificate) and set CCSYNC_APPLE_DEV_ID + CCSYNC_NOTARY_PROFILE."
        warn "See docs/RELEASE.md 'Code signing'. The upgrade channel's own"
        warn "signature is separate and is still applied."
        warn "**********************************************************************"
    fi

    # PyInstaller ad-hoc signs macOS binaries automatically (codesign_identity
    # is None in build.spec, which means "-" / ad-hoc, not "unsigned"). An
    # UNSIGNED arm64 binary is killed on launch by the kernel -- Apple silicon
    # requires a valid signature even for a local build -- so the editor would
    # see "zsh: killed" or a silent no-op instead of a companion. Check it here
    # rather than on their machine.
    if have_cmd codesign; then
        CODESIGN_OUT="$(codesign -dv "$ARTIFACT" 2>&1)"
        CODESIGN_RC=$?
        if [ "$CODESIGN_RC" != 0 ]; then
            echo "$CODESIGN_OUT" | sed 's/^/    /'
            fail "codesign -dv says this binary is NOT signed (exit $CODESIGN_RC).
         PyInstaller normally ad-hoc signs it. Re-sign by hand before shipping:
             codesign --force --sign - '$ARTIFACT'
         An unsigned binary is killed on launch on Apple silicon."
        fi
        echo "$CODESIGN_OUT" | sed 's/^/    /'
        if printf '%s' "$CODESIGN_OUT" | grep -q 'Signature=adhoc'; then
            step "ad-hoc signature present"
            # Belt and braces on the flag the release record carries: if the
            # binary still reads ad-hoc, no Developer ID landed, whatever the
            # environment said (item 4, 2026-08-17).
            SIGNED_BINARY=false
        elif [ "$SIGNED_BINARY" = true ]; then
            step "Developer ID signature present"
        else
            warn "the signature is not ad-hoc -- read the codesign output above and make sure that is what you meant"
        fi
    else
        warn "no codesign on PATH -- could NOT confirm the binary is signed (install the Command Line Tools)"
    fi

    # Arch: the fleet's Macs are Apple silicon. A universal2/x86_64 build runs
    # under Rosetta at best and is a surprise nobody asked for.
    if have_cmd file; then
        FILE_OUT="$(file "$ARTIFACT" 2>/dev/null || true)"
        echo "    $FILE_OUT"
        case "$FILE_OUT" in
            *arm64*) ARTIFACT_ARCH="arm64" ;;
            *x86_64*) ARTIFACT_ARCH="x86_64" ;;
            *) ARTIFACT_ARCH="unknown" ;;
        esac
    else
        ARTIFACT_ARCH="$(uname -m)"
    fi
    if [ "$ARTIFACT_ARCH" != "arm64" ]; then
        warn "this binary is '$ARTIFACT_ARCH', not arm64 -- build it on an Apple silicon Mac (or expect Rosetta)"
    fi
fi

# ----------------------------------------------------------------------
# 5/6 manifest
# ----------------------------------------------------------------------
echo ""
step "--- step 5/6: release manifest ---"

SHA=""
SIZE_BYTES=0
ARTIFACT_MTIME=""
if [ -f "$ARTIFACT" ] && [ "$DRY_RUN" != 1 ]; then
    SHA="$(shasum -a 256 "$ARTIFACT" | awk '{print $1}' | tr 'A-Z' 'a-z')"
    SIZE_BYTES="$(stat -f%z "$ARTIFACT" 2>/dev/null || echo 0)"
    MTIME_EPOCH="$(stat -f%m "$ARTIFACT" 2>/dev/null || echo 0)"
    if [ "$MTIME_EPOCH" != 0 ]; then
        ARTIFACT_MTIME="$(date -u -r "$MTIME_EPOCH" +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || true)"
    fi
    # A build that "succeeded" against sources newer than the binary means the
    # binary on disk is not the one just described -- refuse to vouch for it.
    NEWER_SRC="$(find "$COMPANION_DIR/src" -name '*.py' -newer "$ARTIFACT" 2>/dev/null | head -n 1)"
    if [ -n "$NEWER_SRC" ]; then
        warn "companion source $NEWER_SRC is NEWER than the binary just built -- something changed mid-build; re-run"
    fi
elif [ "$DRY_RUN" != 1 ]; then
    fail "no binary at $ARTIFACT"
fi

[ -n "$ARTIFACT_ARCH" ] || ARTIFACT_ARCH="$(uname -m 2>/dev/null || echo unknown)"
# REL-4 / REL-7 (resilience sweep 2026-08-28). Two facts the publish needs and
# cannot measure for itself: the dashboard version this build requires (absent
# unless the companion declares one) and the release keys the binary trusts,
# which is what lets the NEXT release refuse a key the fleet would reject.
REQUIRES_DASHBOARD="$(capture "$CONFIG_PY" 's/^REQUIRES_DASHBOARD[[:space:]]*=[[:space:]]*"\([^"]*\)".*/\1/p')"
BAKED_PUBKEY_IDS="$(sed -n 's/^[[:space:]]*"\([A-Za-z0-9+/=]\{40,\}\)",[[:space:]]*$/\1/p' \
    "$REPO_ROOT/companion/src/ccsync_companion/release_pubkey.py" |
    while read -r k; do
        printf '%s' "$k" | base64 -d 2>/dev/null | shasum -a 256 | cut -c1-16
    done | paste -sd, - 2>/dev/null || true)"
TESTS_RUN=true
[ "$SKIP_TESTS" = 1 ] && TESTS_RUN=false
BUILT_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
BUILT_BY="$(id -un 2>/dev/null || echo unknown)@$(hostname -s 2>/dev/null || echo unknown)"

# Same field names as tools/release.ps1's manifest, in the same order, plus
# the macOS-specific ones -- tools/check_deploy_drift.ps1 and the installers
# read these keys by name.
write_manifest() {
    cat <<JSON
{
    "version":  "$(json_escape "$VERSION")",
    "version_stamp":  "$(json_escape "$VERSION_STAMP")",
    "platform":  "macos",
    "arch":  "$(json_escape "$ARTIFACT_ARCH")",
    "artifact":  "ccsync-companion",
    "sha256":  "$(json_escape "$SHA")",
    "size_bytes":  $SIZE_BYTES,
    "built_at":  "$BUILT_AT",
    "artifact_mtime":  "$(json_escape "$ARTIFACT_MTIME")",
    "git_commit":  "$(json_escape "$GIT_COMMIT")",
    "git_describe":  "$(json_escape "$GIT_DESCRIBE")",
    "git_dirty":  $GIT_DIRTY,
    "tests_run":  $TESTS_RUN,
    "requires_dashboard":  "$(json_escape "$REQUIRES_DASHBOARD")",
    "baked_pubkey_ids":  "$(json_escape "$BAKED_PUBKEY_IDS")",
    "signed_binary":  $SIGNED_BINARY,
    "built_by":  "$(json_escape "$BUILT_BY")",
    "built_with":  "tools/release_macos.sh"
}
JSON
}

if [ "$DRY_RUN" = 1 ]; then
    dry "would write $MANIFEST :"
    write_manifest | sed 's/^/    /'
else
    write_manifest > "$MANIFEST" || fail "could not write $MANIFEST"
    step "wrote $MANIFEST"
    step "  version : $VERSION_STAMP"
    step "  sha256  : $SHA"
    step "  size    : $((SIZE_BYTES / 1024)) KB"
    step "  arch    : $ARTIFACT_ARCH"
    step "  commit  : ${GIT_DESCRIBE:-unknown}"
fi

# ----------------------------------------------------------------------
# 6/6 publish
# ----------------------------------------------------------------------
echo ""
step "--- step 6/6: publish ---"

DASHBOARD_URL="${DASHBOARD_URL%/}"

if [ "$PUBLISH" != 1 ]; then
    rule
    step "NOTHING IS PUBLISHED YET. The Mac editors keep the build they have."
    rule
    echo ""
    echo "  Publish it to the dashboard upgrade channel:"
    echo ""
    echo "      $0 --publish --make-current"
    echo ""
    echo "    which is: POST $DASHBOARD_URL/api/v1/login            (session cookie)"
    echo "              PUT  $DASHBOARD_URL/api/v1/admin/packages/macos/$VERSION"
    echo "                   ?kind=companion&sha256=${SHA:-<sha256>}&make_current=1"
    echo "              body = the raw binary"
    echo ""
    echo "    Without --make-current the build is staged; flip [ MAKE CURRENT ]"
    echo "    on the dashboard admin page when you want the Mac editors to take it."
    echo "    A 409 means this version is already published -- bump VERSION."
    echo ""
    if [ "$DRY_RUN" = 1 ]; then step "dry run complete -- nothing was built, written, or published"; fi
    exit 0
fi

if [ "$DRY_RUN" = 1 ]; then
    MC=0
    [ "$MAKE_CURRENT" = 1 ] && MC=1
    dry "would log in to $DASHBOARD_URL as '$ADMIN_USER' (password read from the terminal, never argv)"
    dry "would PUT $DASHBOARD_URL/api/v1/admin/packages/macos/$VERSION?kind=companion&sha256=<sha256>&make_current=$MC"
    step "dry run complete -- nothing was built, written, or published"
    exit 0
fi

have_cmd curl || fail "no curl on PATH -- cannot publish"
[ -n "$SHA" ] || fail "no sha256 for $ARTIFACT -- nothing to publish"

# --- sign the release record (COMMERCIAL_READINESS.md item 4, 2026-08-17) ---
# The dashboard REFUSES an unsigned publish, so this runs before the password
# prompt: a missing release key should cost a message, not a login.
#
# THE RELEASE KEY LIVES ON THE RELEASE MACHINE, and the Mac is a second one.
# Copy it there ONCE, by hand, to ~/.ccsync-release/release.key (chmod 600) --
# or set CCSYNC_RELEASE_KEY to wherever you keep it. It is the same key the
# Windows ship signs with, because a companion trusts exactly the keys baked
# into it and Mac editors run the same baked list.
SIGN_PY="$VENV_PY"
[ -x "$SIGN_PY" ] || SIGN_PY="$(command -v python3 || true)"
[ -n "$SIGN_PY" ] || fail "no python to run tools/sign_release.py with"
MIN_VERSION="${CCSYNC_MIN_VERSION:-0.0.0}"
SIGN_ARGS="--signed-binary"
[ "$SIGNED_BINARY" = true ] || SIGN_ARGS=""
# shellcheck disable=SC2086  # SIGN_ARGS is a deliberate single optional flag
# --arch and --requires-dashboard are only PUBLISHED when the record covers
# them (sign_release drops the arch with a note, refuses a requires_dashboard
# it cannot sign). --git-* are unsigned provenance. REL-4/13/16, 2026-08-28.
[ -n "$REQUIRES_DASHBOARD" ] && SIGN_ARGS="$SIGN_ARGS --requires-dashboard $REQUIRES_DASHBOARD"
case "$ARTIFACT_ARCH" in
    x86_64|arm64|universal2) SIGN_ARGS="$SIGN_ARGS --arch $ARTIFACT_ARCH" ;;
esac
[ -n "$GIT_COMMIT" ] && SIGN_ARGS="$SIGN_ARGS --git-sha $GIT_COMMIT"
if [ "$GIT_DIRTY" = true ]; then
    SIGN_ARGS="$SIGN_ARGS --git-dirty 1"
else
    SIGN_ARGS="$SIGN_ARGS --git-dirty 0"
fi
SIGN_JSON="$("$SIGN_PY" "$REPO_ROOT/tools/sign_release.py" \
    --artifact "$ARTIFACT" --kind companion --platform macos \
    --version "$VERSION" --min-version "$MIN_VERSION" $SIGN_ARGS 2>/dev/null)" \
    || fail "could not sign the release record.
         The offline release key is missing on this Mac. Copy it from the
         release rig to ~/.ccsync-release/release.key (chmod 600), or set
         CCSYNC_RELEASE_KEY. Nothing was uploaded."
SIGN_QUERY="$(printf '%s' "$SIGN_JSON" | sed -n 's/.*"query": "\([^"]*\)".*/\1/p')"
[ -n "$SIGN_QUERY" ] || fail "tools/sign_release.py produced no query suffix -- NOT publishing"
SIGN_SHA="$(printf '%s' "$SIGN_JSON" | sed -n 's/.*"sha256": "\([^"]*\)".*/\1/p')"
[ "$SIGN_SHA" = "$SHA" ] || fail "the signed record describes $SIGN_SHA but the binary is $SHA -- NOT publishing"
step "signed release record (min_version $MIN_VERSION, signed_binary $SIGNED_BINARY)"

if [ "$GIT_DIRTY" = true ]; then
    warn "publishing $VERSION_STAMP -- built from an UNCOMMITTED tree (${GIT_DESCRIBE:-unknown});"
    warn "nobody will be able to reproduce what the Mac editors are running."
fi

# Private, per-run staging for the cookie jar. A session cookie in a
# predictable /tmp path is an admin session anyone on the machine can pick up.
PUB_STAGE="$(mktemp -d "${TMPDIR:-/tmp}/ccsync-release.XXXXXXXX")" || fail "could not create a temp dir"
chmod 700 "$PUB_STAGE"
# shellcheck disable=SC2064  # expand PUB_STAGE now, on purpose
trap "rm -rf '$PUB_STAGE'" EXIT INT TERM
COOKIE_JAR="$PUB_STAGE/cookies.txt"
BODY_FILE="$PUB_STAGE/response.json"

# --- pre-flight: is this version already published? -------------------
# The publish guard refuses to reuse a version number for different bytes --
# correctly -- but discovering that after a password prompt wastes the run
# (tools/ship.ps1 learned the same lesson on 2026-07-26). The download
# endpoint answers to the fleet report token, which this Mac may already have
# in ~/.ccsync/config.toml.
REPORT_TOKEN="$(capture "$HOME/.ccsync/config.toml" 's/^[[:space:]]*dashboard_token[[:space:]]*=[[:space:]]*"\([^"]*\)".*/\1/p')"
if [ -z "$REPORT_TOKEN" ]; then
    step "NOTE: no dashboard_token in ~/.ccsync/config.toml -- skipping the already-published pre-flight check (a 409 below means exactly that)"
else
    # -K - : the token rides in curl's config on stdin, never on its command
    # line, where any local process could read it out of the process list.
    # -r 0-0 : ask for the first byte only. The route is GET-only (HEAD is a
    # 405, measured 2026-08-03) and FileResponse honours Range with a 206, so
    # this is an existence check, not a 20 MB download.
    PRE_CODE="$(printf 'header = "X-CCSync-Token: %s"\n' "$REPORT_TOKEN" \
        | curl -s -K - -o /dev/null -r 0-0 -w '%{http_code}' --max-time 20 \
          "$DASHBOARD_URL/api/v1/companion/package/macos/$VERSION" || true)"
    if [ "$PRE_CODE" = "200" ] || [ "$PRE_CODE" = "206" ]; then
        fail "companion v$VERSION is ALREADY published for macos.
         Bump VERSION in companion/src/ccsync_companion/config.py AND
         companion/pyproject.toml, then re-run. Nothing was uploaded."
    elif [ "$PRE_CODE" = "404" ]; then
        step "pre-flight: v$VERSION is not on the server yet"
    else
        warn "pre-flight check returned HTTP $PRE_CODE (not 200/206/404) -- continuing anyway"
    fi
fi

# --- log in -----------------------------------------------------------
# Prompts, strips the terminal's bracketed-paste wrappers, and refuses a
# password still carrying a control byte (KNOWN_BUGS item 10). Sets
# DASH_PASSWORD.
read_dashboard_password

LOGIN_CODE="$(printf '{"username":"%s","password":"%s"}' \
        "$(json_escape "$ADMIN_USER")" "$(json_escape "$DASH_PASSWORD")" \
    | curl -s -o "$BODY_FILE" -w '%{http_code}' --max-time 30 \
      -c "$COOKIE_JAR" -H "Content-Type: application/json" \
      --data-binary @- "$DASHBOARD_URL/api/v1/login" || true)"
DASH_PASSWORD=""

if [ "$LOGIN_CODE" != "200" ]; then
    warn "$(cat "$BODY_FILE" 2>/dev/null || true)"
    fail "dashboard login failed (HTTP $LOGIN_CODE) -- NOT publishing"
fi
if ! grep -q '"is_admin"[[:space:]]*:[[:space:]]*true' "$BODY_FILE"; then
    fail "'$ADMIN_USER' is not a dashboard admin (DASH_ADMIN_USERS) -- NOT publishing"
fi
step "logged in as $ADMIN_USER"

# REL-1 (usability sweep 2026-09-04): the PUT answers `note` when it published
# the build but did NOT make it current -- the soak gate stands at the publish
# door now, and `--make-current` from a Mac was one of the two doors that used
# to walk past it. Read out of the body with sed rather than a JSON parser
# (this script has no python dependency by design); an absent field reads as
# empty, which is the "it did what you asked" case.
staged_note() {
    LC_ALL=C sed -n 's/.*"note"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' "$1" 2>/dev/null | head -n 1
}

# --- upload -----------------------------------------------------------
MC=0
[ "$MAKE_CURRENT" = 1 ] && MC=1
PUT_URL="$DASHBOARD_URL/api/v1/admin/packages/macos/$VERSION?kind=companion&sha256=$SHA&make_current=$MC$SIGN_QUERY"
step "uploading $((SIZE_BYTES / 1024)) KB to $PUT_URL"
PUT_CODE="$(curl -s -o "$BODY_FILE" -w '%{http_code}' --max-time 600 \
    -b "$COOKIE_JAR" -H "Content-Type: application/octet-stream" \
    -T "$ARTIFACT" "$PUT_URL" || true)"

echo ""
cat "$BODY_FILE" 2>/dev/null | head -c 2000
echo ""
echo ""

if [ "$PUT_CODE" = "409" ]; then
    fail "HTTP 409: macos companion v$VERSION is already published (with different bytes, or you re-ran).
         The server keeps what it has. Bump VERSION in config.py AND pyproject.toml,
         rebuild, and re-run."
elif [ "$PUT_CODE" != "200" ]; then
    fail "publish failed with HTTP $PUT_CODE -- see the response above. Nothing is current that was not current before."
fi

NOTE="$(staged_note "$BODY_FILE")"
if [ -n "$NOTE" ]; then
    step "macos companion v$VERSION: $NOTE"
    step "push it to one Mac from Settings > Packages, leave it running, then [ MAKE CURRENT ] there."
elif [ "$MAKE_CURRENT" = 1 ]; then
    step "published macos companion v$VERSION and made it CURRENT"
else
    step "published macos companion v$VERSION -- STAGED, not current"
    step "flip [ MAKE CURRENT ] on the dashboard admin page (or re-run with --make-current)"
fi

echo ""
rule
step "WHAT NEXT"
rule
echo ""
echo "  1. On the base rig, confirm the channel moved:"
echo ""
echo "       .\\tools\\check_deploy_drift.ps1 -AdminUser $ADMIN_USER"
echo ""
echo "     Its DASHBOARD section must show the current macos package as"
echo "     v$VERSION. If it still says something else, this upload is not"
echo "     the thing Mac editors will be offered."
echo ""
echo "  2. Mac editors are NOT pushed to. Each companion learns about"
echo "     v$VERSION on its next report to the dashboard and offers its editor"
echo "     the update in the menu bar; the editor has to click it. Watch who"
echo "     has not on the dashboard's fleet view."
echo ""
echo "  3. This Mac keeps running whatever is at"
echo "     ~/.local/ccsync/bin/ccsync-companion until it takes the same offer"
echo "     (or you copy the new binary there by hand and restart it)."
echo ""
rule
exit 0
