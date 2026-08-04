#!/usr/bin/env bash
#
# Creators Club Sync -- macOS companion release.
#
# The Mac-side twin of tools/release.ps1: verify version parity, run the
# tests, run PyInstaller, confirm the ad-hoc signature, and stamp a manifest
# describing exactly what came out. Optionally publish it to the dashboard's
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
DASHBOARD_URL="http://100.71.216.3:8480"
ADMIN_USER="alex"

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
    echo "  --dashboard-url   default: $DASHBOARD_URL"
    echo "  --admin-user      dashboard admin for --publish (default: $ADMIN_USER)"
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

# Minimal JSON string escaping, same as macos_bootstrap.sh's: a password (or
# a git describe from a strangely named branch) must not be able to break out
# of the string it is written into.
json_escape() { printf '%s' "$1" | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g'; }

# First capture group of the first matching line, or "" when absent -- the
# bash twin of release.ps1's Get-Capture.
capture() {
    local path="$1" expr="$2"
    [ -f "$path" ] || return 0
    sed -n "$expr" "$path" 2>/dev/null | head -n 1
}

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
COMPANION_DIR="$REPO_ROOT/companion"
CONFIG_PY="$COMPANION_DIR/src/ccsync_companion/config.py"
PYPROJECT="$COMPANION_DIR/pyproject.toml"
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
printf 'dashboard password for %s@%s: ' "$ADMIN_USER" "$DASHBOARD_URL" >&2
# -s: never echoed. The password goes to curl on STDIN, never in argv and
# never in an environment variable.
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

# --- upload -----------------------------------------------------------
MC=0
[ "$MAKE_CURRENT" = 1 ] && MC=1
PUT_URL="$DASHBOARD_URL/api/v1/admin/packages/macos/$VERSION?kind=companion&sha256=$SHA&make_current=$MC"
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

if [ "$MAKE_CURRENT" = 1 ]; then
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
