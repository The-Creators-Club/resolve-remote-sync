#!/usr/bin/env bash
#
# Creators Club Sync -- macOS onboarding wizard build.
#
# Builds "CCSync Onboarding.app" (onboarding/build_onboard_macos.spec) and
# zips it for handoff. The Mac-side sibling of the -RebuildOnboard half of
# installer/build_editor_package.ps1: version parity, staleness guard on the
# bundled companion, PyInstaller, signature check, zip.
#
# Like tools/release_macos.sh it is written on Windows and RUNS ONLY ON
# macOS (--dry-run inspects anywhere). With --publish it uploads the zip as
# the macos kind=onboard package -- which is what a Mac's [ INSTALLER ]
# click downloads by default (dashboard 0.3.7 names macos onboard uploads by
# content: zip magic -> .zip, else .sh). This SUPERSEDES the pre-1.0.17
# behavior where every Windows ship pushed macos_bootstrap.sh into that
# slot; build_editor_package.ps1 now only warns when this channel is stale.
#
# Usage:
#   ./tools/build_onboard_macos.sh [--dry-run] [--publish [--make-current]]
#                                  [--dashboard-url URL] [--admin-user NAME]
#
set -u

DRY_RUN=0
PUBLISH=0
MAKE_CURRENT=0
DASHBOARD_URL="http://100.71.216.3:8480"
ADMIN_USER="alex"

usage() {
    echo "Usage: $0 [--dry-run] [--publish [--make-current]]"
    echo "          [--dashboard-url <url>] [--admin-user <name>]"
    echo ""
    echo "  --publish         upload the zipped .app as the macos kind=onboard"
    echo "                    package (prompts for your dashboard password)"
    echo "  --make-current    with --publish: [ INSTALLER ] serves it to Macs"
    echo "                    immediately"
    echo "  --dashboard-url   default: $DASHBOARD_URL"
    echo "  --admin-user      dashboard admin for --publish (default: $ADMIN_USER)"
    exit 1
}

while [ $# -gt 0 ]; do
    case "$1" in
        --dry-run)        DRY_RUN=1; shift ;;
        --publish)        PUBLISH=1; shift ;;
        --make-current)   MAKE_CURRENT=1; shift ;;
        --dashboard-url)  DASHBOARD_URL="$2"; shift 2 ;;
        --admin-user)     ADMIN_USER="$2"; shift 2 ;;
        -h|--help) usage ;;
        *) echo "Unknown argument: $1"; usage ;;
    esac
done

step() { echo "[onboard-build] $1"; }
warn() { echo "[onboard-build] WARNING: $1" >&2; }
dry()  { echo "[onboard-build] [dry-run] $1"; }
rule() { echo "=================================================================="; }
fail() {
    echo "[onboard-build] FAILED: $1" >&2
    exit 1
}

have_cmd() { command -v "$1" >/dev/null 2>&1; }

capture() {
    local path="$1" expr="$2"
    [ -f "$path" ] || return 0
    sed -n "$expr" "$path" 2>/dev/null | head -n 1
}

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
ONBOARDING_DIR="$REPO_ROOT/onboarding"
COMPANION_DIR="$REPO_ROOT/companion"
COMPANION_BIN="$COMPANION_DIR/dist/ccsync-companion"
COMPANION_MANIFEST="$COMPANION_DIR/dist/ccsync-release.json"
VENV_PY="$COMPANION_DIR/.venv/bin/python"
APP_NAME="CCSync Onboarding.app"
APP_PATH="$ONBOARDING_DIR/dist/$APP_NAME"

rule
step "repo root: $REPO_ROOT"

# ----------------------------------------------------------------------
# 1/5 platform guard
# ----------------------------------------------------------------------
UNAME_S="$(uname -s 2>/dev/null || echo unknown)"
if [ "$UNAME_S" != "Darwin" ]; then
    if [ "$DRY_RUN" = 1 ]; then
        warn "this is $UNAME_S, not macOS -- --dry-run continues in INSPECTION MODE"
    else
        fail "this script builds the macOS wizard and only runs on a Mac (uname says '$UNAME_S').
         onboard.exe comes from installer/build_editor_package.ps1 on the base rig."
    fi
fi

# ----------------------------------------------------------------------
# 2/5 version parity (same trio tools/release_macos.sh reports on)
# ----------------------------------------------------------------------
ONBOARD_VERSION="$(capture "$ONBOARDING_DIR/steps.py" 's/^INSTALLER_VERSION[[:space:]]*=[[:space:]]*"\([^"]*\)".*/\1/p')"
BOOTSTRAP_PS1_VERSION="$(capture "$REPO_ROOT/installer/windows_bootstrap.ps1" 's/^\$InstallerVersion[[:space:]]*=[[:space:]]*"\([^"]*\)".*/\1/p')"
MAC_BOOTSTRAP_VERSION="$(capture "$REPO_ROOT/installer/macos_bootstrap.sh" 's/^INSTALLER_VERSION="\([^"]*\)".*/\1/p')"
SPEC_VERSION="$(capture "$ONBOARDING_DIR/build_onboard_macos.spec" 's/.*CFBundleShortVersionString": "\([^"]*\)".*/\1/p')"

[ -n "$ONBOARD_VERSION" ] || fail "could not parse INSTALLER_VERSION from onboarding/steps.py"
step "installer version (steps.py):              $ONBOARD_VERSION"
step "installer version (windows_bootstrap.ps1): $BOOTSTRAP_PS1_VERSION"
step "installer version (macos_bootstrap.sh):    $MAC_BOOTSTRAP_VERSION"
step "bundle version (build_onboard_macos.spec): $SPEC_VERSION"

if [ "$ONBOARD_VERSION" != "$BOOTSTRAP_PS1_VERSION" ] || [ "$ONBOARD_VERSION" != "$MAC_BOOTSTRAP_VERSION" ]; then
    fail "installer version drift -- steps.py, windows_bootstrap.ps1 and macos_bootstrap.sh
         must carry the SAME number (they ship as a set). Fix and re-run."
fi
if [ -n "$SPEC_VERSION" ] && [ "$SPEC_VERSION" != "$ONBOARD_VERSION" ]; then
    fail "build_onboard_macos.spec's CFBundleShortVersionString ('$SPEC_VERSION') does not match
         INSTALLER_VERSION ('$ONBOARD_VERSION') -- bump them together."
fi
step "version parity OK"

# ----------------------------------------------------------------------
# 3/5 the bundled companion
# ----------------------------------------------------------------------
if [ ! -f "$COMPANION_BIN" ]; then
    if [ "$DRY_RUN" = 1 ]; then
        dry "companion binary missing at $COMPANION_BIN -- a real run would fail here"
    else
        fail "no macOS companion binary at $COMPANION_BIN -- build it first: ./tools/release_macos.sh
         (the wizard bundles that binary; there is nothing to bundle yet)"
    fi
else
    step "bundling companion: $COMPANION_BIN"
    # The manifest is the honesty record: refuse to quietly bundle a binary
    # that release_macos.sh would not vouch for.
    if [ -f "$COMPANION_MANIFEST" ]; then
        MANIFEST_SHA="$(capture "$COMPANION_MANIFEST" 's/.*"sha256":[[:space:]]*"\([^"]*\)".*/\1/p')"
        MANIFEST_STAMP="$(capture "$COMPANION_MANIFEST" 's/.*"version_stamp":[[:space:]]*"\([^"]*\)".*/\1/p')"
        ACTUAL_SHA="$(shasum -a 256 "$COMPANION_BIN" 2>/dev/null | awk '{print $1}' | tr 'A-Z' 'a-z')"
        if [ -n "$MANIFEST_SHA" ] && [ -n "$ACTUAL_SHA" ] && [ "$MANIFEST_SHA" != "$ACTUAL_SHA" ]; then
            fail "dist/ccsync-companion does not match dist/ccsync-release.json (sha256 drift) --
         the binary is not the one the manifest describes. Re-run ./tools/release_macos.sh."
        fi
        case "$MANIFEST_STAMP" in
            *+dirty*) warn "the bundled companion is a +dirty build ($MANIFEST_STAMP) -- fine for testing, do not hand this wizard to an editor" ;;
            *) step "companion manifest: $MANIFEST_STAMP" ;;
        esac
    else
        warn "no ccsync-release.json next to the companion binary -- cannot vouch for what is being bundled (build it with ./tools/release_macos.sh)"
    fi
fi

# ----------------------------------------------------------------------
# 4/5 PyInstaller
# ----------------------------------------------------------------------
if [ "$DRY_RUN" = 1 ]; then
    dry "would run: \"$VENV_PY\" -m PyInstaller build_onboard_macos.spec --noconfirm   (in $ONBOARDING_DIR)"
    dry "would verify the ad-hoc signature: codesign -dv \"$APP_PATH\""
    dry "would zip: ditto -c -k --keepParent \"$APP_PATH\" dist/ccsync-onboard-macos-$ONBOARD_VERSION.zip"
    if [ "$PUBLISH" = 1 ]; then
        MC=0
        [ "$MAKE_CURRENT" = 1 ] && MC=1
        dry "would log in to $DASHBOARD_URL as '$ADMIN_USER' (password read from the terminal, never argv)"
        dry "would PUT $DASHBOARD_URL/api/v1/admin/packages/macos/$ONBOARD_VERSION?kind=onboard&sha256=<sha256>&make_current=$MC"
    fi
    step "dry run complete -- nothing was built or published"
    exit 0
fi

[ -x "$VENV_PY" ] || fail "no python at $VENV_PY -- run ./tools/release_macos.sh first (it creates the venv this build reuses)"
if ! "$VENV_PY" -c "import PyInstaller" >/dev/null 2>&1; then
    fail "PyInstaller is not importable from $VENV_PY -- run ./tools/release_macos.sh first (it pip-installs it)"
fi

step "building (this takes a minute)..."
( cd "$ONBOARDING_DIR" && "$VENV_PY" -m PyInstaller build_onboard_macos.spec --noconfirm ) \
    || fail "PyInstaller failed -- whatever is in onboarding/dist is stale; nothing was zipped"
[ -d "$APP_PATH" ] || fail "PyInstaller reported success but there is no bundle at $APP_PATH"
step "built $APP_PATH"

if have_cmd codesign; then
    CODESIGN_OUT="$(codesign -dv "$APP_PATH" 2>&1)"
    CODESIGN_RC=$?
    echo "$CODESIGN_OUT" | sed 's/^/    /'
    if [ "$CODESIGN_RC" != 0 ]; then
        fail "codesign -dv says this bundle is NOT signed (exit $CODESIGN_RC).
         Re-sign by hand before handing it out:  codesign --force --deep --sign - \"$APP_PATH\"
         An unsigned arm64 binary is killed on launch."
    fi
else
    warn "no codesign on PATH -- could NOT confirm the bundle is signed"
fi

# ----------------------------------------------------------------------
# 5/5 zip + what next
# ----------------------------------------------------------------------
ZIP_PATH="$ONBOARDING_DIR/dist/ccsync-onboard-macos-$ONBOARD_VERSION.zip"
# ditto, not zip: it preserves the resource forks/xattrs Finder expects, and
# it is what everyone uses to ship .app bundles.
ditto -c -k --keepParent "$APP_PATH" "$ZIP_PATH" || fail "ditto failed -- no zip was produced"
ZIP_SHA="$(shasum -a 256 "$ZIP_PATH" | awk '{print $1}' | tr 'A-Z' 'a-z')"
step "zipped: $ZIP_PATH"
step "  sha256: $ZIP_SHA"

# ----------------------------------------------------------------------
# 6/6 publish (macos, kind=onboard -- what a Mac's [ INSTALLER ] serves)
# ----------------------------------------------------------------------
DASHBOARD_URL="${DASHBOARD_URL%/}"

if [ "$PUBLISH" != 1 ]; then
    echo ""
    rule
    step "BUILT, NOT PUBLISHED. Mac editors keep downloading whatever the"
    step "macos installer channel currently holds."
    rule
    echo ""
    echo "  Publish it so [ INSTALLER ] serves this wizard to every Mac:"
    echo ""
    echo "      $0 --publish --make-current"
    echo ""
    echo "  Or hand the zip over directly (USB/AirDrop/scp): unzip + open."
    echo "  If it arrives with the quarantine xattr (browser/AirDrop), first"
    echo "  open needs System Settings > Privacy & Security > 'Open Anyway'"
    echo "  (ad-hoc signature); a curl/scp copy opens directly."
    echo ""
    rule
    exit 0
fi

have_cmd curl || fail "no curl on PATH -- cannot publish"

# --- log in (same shape as release_macos.sh: password via stdin, cookie
# jar in a private temp dir) -------------------------------------------
PUB_STAGE="$(mktemp -d "${TMPDIR:-/tmp}/ccsync-onboard-pub.XXXXXXXX")" || fail "could not create a temp dir"
chmod 700 "$PUB_STAGE"
# shellcheck disable=SC2064  # expand PUB_STAGE now, on purpose
trap "rm -rf '$PUB_STAGE'" EXIT INT TERM
COOKIE_JAR="$PUB_STAGE/cookies.txt"
BODY_FILE="$PUB_STAGE/response.json"

json_escape() { printf '%s' "$1" | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g'; }

printf 'dashboard password for %s@%s: ' "$ADMIN_USER" "$DASHBOARD_URL" >&2
read -r -s DASH_PASSWORD
echo "" >&2

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

MC=0
[ "$MAKE_CURRENT" = 1 ] && MC=1
PUT_URL="$DASHBOARD_URL/api/v1/admin/packages/macos/$ONBOARD_VERSION?kind=onboard&sha256=$ZIP_SHA&make_current=$MC"
step "uploading $(du -k "$ZIP_PATH" | awk '{print $1}') KB to $PUT_URL"
PUT_CODE="$(curl -s -o "$BODY_FILE" -w '%{http_code}' --max-time 600 \
    -b "$COOKIE_JAR" -H "Content-Type: application/octet-stream" \
    -T "$ZIP_PATH" "$PUT_URL" || true)"

echo ""
cat "$BODY_FILE" 2>/dev/null | head -c 2000
echo ""
echo ""

if [ "$PUT_CODE" = "409" ]; then
    fail "HTTP 409: a macos onboard package v$ONBOARD_VERSION is already published
         (different bytes, or a pre-1.0.17 Windows ship uploaded the .sh at this
         number). The server keeps what it has. Bump the shared installer
         version (steps.py + windows_bootstrap.ps1 + macos_bootstrap.sh + the
         spec's CFBundleShortVersionString), rebuild, and re-run."
elif [ "$PUT_CODE" != "200" ]; then
    fail "publish failed with HTTP $PUT_CODE -- see the response above. Nothing is current that was not current before."
fi

if [ "$MAKE_CURRENT" = 1 ]; then
    step "published macos installer v$ONBOARD_VERSION and made it CURRENT --"
    step "a Mac's [ INSTALLER ] click now downloads ccsync-onboard-$ONBOARD_VERSION.zip"
else
    step "published macos installer v$ONBOARD_VERSION -- STAGED, not current"
    step "flip [ MAKE CURRENT ] on the dashboard admin page (or re-run with --make-current)"
fi
step "the Terminal route (macos_bootstrap.sh) remains available inside the"
step "editor package on P:\\ and in this repo -- it is no longer what /download serves."
exit 0
