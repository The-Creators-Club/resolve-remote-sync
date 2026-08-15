#!/usr/bin/env bash
#
# Creators Club Sync -- macOS onboarding wizard build.
#
# Builds "CCSync Onboarding.app" (onboarding/build_onboard_macos.spec) and
# zips it for handoff. The Mac-side sibling of the -RebuildOnboard half of
# installer/build_editor_package.ps1: version parity, staleness guard on the
# bundled companion, an already-published pre-flight when --publish is asked
# for (before the build, not after it), PyInstaller, signature check, zip.
#
# WATCH THE FIRST RUN AFTER 2026-08-05: the spec moved from onefile to ONEDIR
# (KNOWN_BUGS item 9 -- onefile .app bundles become a hard error in
# PyInstaller 7), a change made on Windows that has never been built. Nothing
# here needed a path change (dist/CCSync Onboarding.app is a directory in both
# modes, and it is the only thing this script touches), but the bundle now
# contains real nested code, so the signature checks below verify --deep
# --strict, on the bundle and on the unzipped copy.
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

# Normalised HERE and not in the publish section any more: the already-published
# pre-flight added by SHIP-12 runs BEFORE the build, and it builds URLs too.
DASHBOARD_URL="${DASHBOARD_URL%/}"

step() { echo "[onboard-build] $1"; }
warn() { echo "[onboard-build] WARNING: $1" >&2; }
dry()  { echo "[onboard-build] [dry-run] $1"; }
rule() { echo "=================================================================="; }
fail() {
    echo "[onboard-build] FAILED: $1" >&2
    exit 1
}

have_cmd() { command -v "$1" >/dev/null 2>&1; }

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
# 3b/5 pre-flight: is this installer version already published? (--publish)
# ----------------------------------------------------------------------
# BEFORE the build, not after it (SHIP-12, 2026-08-14). The server was first
# consulted at the PUT, which is behind PyInstaller, two codesign passes, a
# ditto zip, a zip round-trip verification AND a password prompt -- so an
# admin re-running this after a half-failed ship spent all of that to be told
# to bump a version number and start over. tools/release_macos.sh learned this
# in its own words ("discovering that after a password prompt wastes the run --
# tools/ship.ps1 learned the same lesson on 2026-07-26"); this is that
# pre-flight, keyed on the macos onboard slot.
if [ "$PUBLISH" = 1 ] && [ "$DRY_RUN" != 1 ]; then
    have_cmd curl || fail "no curl on PATH -- cannot publish"
    REPORT_TOKEN="$(capture "$HOME/.ccsync/config.toml" 's/^[[:space:]]*dashboard_token[[:space:]]*=[[:space:]]*"\([^"]*\)".*/\1/p')"
    if [ -z "$REPORT_TOKEN" ]; then
        step "NOTE: no dashboard_token in ~/.ccsync/config.toml -- skipping the already-published pre-flight (a 409 after the build means exactly that)"
    else
        # -K - : the token rides in curl's config on stdin, never on its command
        # line, where any local process could read it out of the process list.
        # -r 0-0 : ask for the first byte only. The route is GET-only (HEAD is a
        # 405, measured 2026-08-03) and FileResponse honours Range with a 206.
        PRE_CODE="$(printf 'header = "X-CCSync-Token: %s"\n' "$REPORT_TOKEN" \
            | curl -s -K - -o /dev/null -r 0-0 -w '%{http_code}' --max-time 20 \
              "$DASHBOARD_URL/api/v1/companion/package/macos/$ONBOARD_VERSION?kind=onboard" || true)"
        if [ "$PRE_CODE" = "200" ] || [ "$PRE_CODE" = "206" ]; then
            fail "a macos installer (kind=onboard) v$ONBOARD_VERSION is ALREADY published -- nothing has been built.
         Bump the shared installer version in ALL FOUR places and re-run:
             onboarding/steps.py                    INSTALLER_VERSION
             installer/windows_bootstrap.ps1        \$InstallerVersion
             installer/macos_bootstrap.sh           INSTALLER_VERSION
             onboarding/build_onboard_macos.spec    CFBundleShortVersionString
         (If you meant to republish the SAME wizard: ditto stamps the zip, so a
         rebuild is never byte-identical and the server would keep what it has.)"
        elif [ "$PRE_CODE" = "404" ]; then
            step "pre-flight: installer v$ONBOARD_VERSION is not on the macos channel yet"
        else
            warn "pre-flight check returned HTTP $PRE_CODE (not 200/206/404) -- continuing anyway"
        fi
    fi
fi

# ----------------------------------------------------------------------
# 4/5 PyInstaller
# ----------------------------------------------------------------------
if [ "$DRY_RUN" = 1 ]; then
    dry "would run: \"$VENV_PY\" -m PyInstaller build_onboard_macos.spec --noconfirm   (in $ONBOARDING_DIR)"
    dry "would verify the ad-hoc signature: codesign -dv \"$APP_PATH\""
    dry "would verify the nested code too (onedir): codesign --verify --all-architectures --deep --strict \"$APP_PATH\""
    dry "would zip: ditto -c -k --keepParent \"$APP_PATH\" dist/ccsync-onboard-macos-$ONBOARD_VERSION.zip"
    dry "would unzip that into a temp dir and re-verify it -- the zip is what an editor receives"
    if [ "$PUBLISH" = 1 ]; then
        MC=0
        [ "$MAKE_CURRENT" = 1 ] && MC=1
        dry "would first ask (with the report token from ~/.ccsync/config.toml, BEFORE building) whether macos installer v$ONBOARD_VERSION is already published"
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
    # -dv only reports the OUTER signature. Since the onedir migration
    # (2026-08-05) the bundle contains real nested code -- every collected
    # dylib plus the whole ccsync-companion binary, in Contents/Frameworks --
    # and a broken nested signature is invisible to -dv while Gatekeeper
    # refuses the app on the editor's machine. PyInstaller signs the bundle
    # with --deep; verify with the same depth it claims (this is also exactly
    # what PyInstaller's own bundle self-check runs).
    VERIFY_OUT="$(codesign --verify --all-architectures --deep --strict "$APP_PATH" 2>&1)"
    VERIFY_RC=$?
    [ -n "$VERIFY_OUT" ] && echo "$VERIFY_OUT" | sed 's/^/    /'
    if [ "$VERIFY_RC" != 0 ]; then
        fail "codesign --verify --deep --strict rejected the bundle (exit $VERIFY_RC, output above).
         A nested binary inside Contents/Frameworks is unsigned or modified; an editor's
         Gatekeeper will refuse this app. Do NOT publish it. Re-sign the whole bundle
         (codesign --force --deep --sign - \"$APP_PATH\") and verify again, or rebuild."
    fi
    step "signature verified (--deep --strict)"
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

# The zip is what an editor actually receives, so verify the SHIPPED bytes and
# not only the bundle sitting in dist/. This matters since the onedir
# migration (2026-08-05): a onedir .app is full of the symlinks BUNDLE creates
# between Contents/Frameworks and Contents/Resources, and an archiver that
# resolves them into copies (or drops xattrs) produces a zip that unpacks into
# a bundle Gatekeeper rejects -- with the dist/ copy still verifying perfectly.
# ditto is used for exactly this reason; this step proves it, once, per build.
if have_cmd codesign; then
    ZIPCHECK_DIR="$(mktemp -d "${TMPDIR:-/tmp}/ccsync-onboard-zipcheck.XXXXXXXX")" \
        || fail "could not create a temp dir to unzip the wizard into"
    ROUNDTRIP_ERR=""
    if ditto -x -k "$ZIP_PATH" "$ZIPCHECK_DIR"; then
        ROUNDTRIP_OUT="$(codesign --verify --all-architectures --deep --strict "$ZIPCHECK_DIR/$APP_NAME" 2>&1)"
        ROUNDTRIP_RC=$?
        if [ "$ROUNDTRIP_RC" != 0 ]; then
            ROUNDTRIP_ERR="the unzipped copy fails codesign --verify --deep --strict:
         ${ROUNDTRIP_OUT}
         The bundle in dist/ verified, so the ZIP is what broke it (lost symlinks or
         extended attributes). Do NOT publish this zip."
        fi
    else
        ROUNDTRIP_ERR="the zip that was just written cannot be unpacked by ditto -x -k."
    fi
    rm -rf "$ZIPCHECK_DIR"
    [ -z "$ROUNDTRIP_ERR" ] || fail "$ROUNDTRIP_ERR"
    step "  zip round-trip verified (unzipped copy still passes --deep --strict)"
fi

# ----------------------------------------------------------------------
# 6/6 publish (macos, kind=onboard -- what a Mac's [ INSTALLER ] serves)
# ----------------------------------------------------------------------
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
    # 409 has two very different meanings and only one of them is a failure --
    # the distinction build_editor_package.ps1 makes on the Windows side and
    # this script did not (SHIP-12). Ask what the server actually holds: the
    # download route reports the stored sha in a header and accepts this admin
    # session, so no JSON parsing and no second credential is needed.
    SERVER_SHA="$(curl -s -D - -o /dev/null -r 0-0 --max-time 20 -b "$COOKIE_JAR" \
        "$DASHBOARD_URL/api/v1/companion/package/macos/$ONBOARD_VERSION?kind=onboard" 2>/dev/null \
        | LC_ALL=C awk 'tolower($1) == "x-ccsync-sha256:" { gsub(/[[:space:]]/, "", $2); print tolower($2); exit }' || true)"
    if [ -n "$SERVER_SHA" ] && [ "$SERVER_SHA" = "$ZIP_SHA" ]; then
        step "macos installer v$ONBOARD_VERSION is already published and is BYTE-IDENTICAL to the zip just built -- nothing to upload"
        if [ "$MAKE_CURRENT" = 1 ]; then
            step "NOTE: --make-current could not be applied by a skipped upload -- confirm v$ONBOARD_VERSION is CURRENT on the dashboard admin page"
        fi
        exit 0
    fi
    fail "HTTP 409: a macos onboard package v$ONBOARD_VERSION is already published with
         DIFFERENT bytes (server holds sha ${SERVER_SHA:-unknown}, this zip is $ZIP_SHA) --
         or a pre-1.0.17 Windows ship uploaded the .sh at this number. The server keeps
         what it has. Bump the shared installer version (steps.py +
         windows_bootstrap.ps1 + macos_bootstrap.sh + the spec's
         CFBundleShortVersionString), rebuild, and re-run."
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
