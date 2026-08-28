#!/usr/bin/env bash
#
# Table tests for the pure string helpers in macos_bootstrap.sh that decide
# WHO THIS DEPLOYMENT IS: site_value (the flat-JSON manifest reader),
# canonical_prefix_letter (the Resolve Mapped Mount prefix) and verify_sha256
# (the pinned-download gate).
#
# WHY these three and not more (2026-08-17, docs/COMMERCIAL_READINESS.md items
# 11 and 13). macos_bootstrap.sh has never run on a real Mac, and almost every
# line of it needs one -- diskutil, launchctl, xattr, the Resolve preference
# write. These three do not: they are text in, text out, and they are exactly
# the three that decide where terabytes go and what binary gets installed.
# Their Windows counterparts are pinned by installer/tests/Test-DriveMapParser.ps1.
#
# The functions are SLICED OUT of the script rather than sourced -- sourcing it
# would run the whole installer. If a slice marker below stops matching, this
# test fails loudly instead of silently testing nothing.
#
# Run (Git Bash, macOS or Linux):
#   bash installer/tests/test_macos_site_values.sh
# Exits 1 on any failure.
set -u

HERE="$(cd "$(dirname "$0")" && pwd)"
SCRIPT="$HERE/../macos_bootstrap.sh"
[ -f "$SCRIPT" ] || { echo "FAIL: no $SCRIPT"; exit 1; }

fail=0
ok()   { echo "  PASS  $1"; }
bad()  { echo "  FAIL  $1"; fail=$((fail + 1)); }

# --- slice out the helpers -------------------------------------------------
slice() {  # slice <start-marker> <end-marker>
    awk -v s="$1" -v e="$2" '
        index($0, s) { on = 1 }
        on && index($0, e) && !index($0, s) { exit }
        on { print }
    ' "$SCRIPT"
}

LOW_SPACE_SRC="$(slice 'LOW_SPACE_WARN_KB=' 'free_kb_for_path() {')"
SITE_VALUE_SRC="$(slice 'site_value() {' 'site_number() {')"
PREFIX_SRC="$(slice 'canonical_prefix_letter() {' 'CANONICAL_PREFIX="$(site_value')"
VERIFY_SRC="$(slice 'verify_sha256() {' '# ------')"

for name in SITE_VALUE_SRC PREFIX_SRC VERIFY_SRC LOW_SPACE_SRC; do
    eval "body=\$$name"
    case "$body" in
        *'}'*) ;;
        *) echo "FAIL: could not slice $name out of $SCRIPT -- did a function get renamed?"; exit 1 ;;
    esac
done

# verify_sha256 uses step/warn; canonical_prefix_letter uses nothing.
step() { :; }
warn() { LAST_WARN="$1"; }
eval "$SITE_VALUE_SRC"
eval "$PREFIX_SRC"
eval "$VERIFY_SRC"
eval "$LOW_SPACE_SRC"

# --- site_value ------------------------------------------------------------
# One flat JSON object by contract (dashboard api.api_site). sed, not a JSON
# parser: macOS ships neither jq nor a guaranteed python3.
SITE_JSON='{"schema": 1, "org_name": "Acme Video", "tree_name": "AcmeVideo", "canonical_prefix": "W:\\", "remote_root": "/volume1/media/AcmeVideo", "rclone_remote": "acme_sftp", "sftp_port": 2222}'

check() {  # check <label> <expected> <actual>
    if [ "$2" = "$3" ]; then ok "$1"; else bad "$1: got '$3' want '$2'"; fi
}

check "site_value tree_name"       "AcmeVideo"                 "$(site_value tree_name)"
check "site_value rclone_remote"   "acme_sftp"                 "$(site_value rclone_remote)"
check "site_value remote_root"     "/volume1/media/AcmeVideo"  "$(site_value remote_root)"
check "site_value org_name with a space" "Acme Video"          "$(site_value org_name)"
check "site_value of an absent key" ""                         "$(site_value not_a_key)"

SAVED="$SITE_JSON"
SITE_JSON=""
check "site_value with no manifest at all" "" "$(site_value tree_name)"
SITE_JSON="$SAVED"

# --- canonical_prefix_letter ----------------------------------------------
check "the default prefix"             "P" "$(canonical_prefix_letter 'P:\')"
check "a site that is not on P:"       "W" "$(canonical_prefix_letter 'W:\')"
check "lowercase is normalised"        "Q" "$(canonical_prefix_letter 'q:\')"
check "no trailing separator"          "T" "$(canonical_prefix_letter 'T:')"
check "a deeper prefix still yields the letter" "S" "$(canonical_prefix_letter 'S:\Tree\')"
# The JSON escaping survives sed unaltered, so the raw manifest value has TWO
# backslashes. The letter must come out the same either way.
check "raw JSON-escaped prefix"        "W" "$(canonical_prefix_letter 'W:\\')"
check "a UNC prefix is refused"        ""  "$(canonical_prefix_letter '\\nas\Pool\Tree')"
check "a POSIX prefix is refused"      ""  "$(canonical_prefix_letter '/volume1/media/Tree')"
check "a bare letter is refused"       ""  "$(canonical_prefix_letter 'P')"
check "an empty manifest value"        ""  "$(canonical_prefix_letter '')"

# --- verify_sha256 ---------------------------------------------------------
TMP="$(mktemp -d 2>/dev/null || mktemp -d -t ccsync)"
trap 'rm -rf "$TMP"' EXIT
printf 'ccsync' > "$TMP/artifact.zip"
# sha256("ccsync"), computed with the same shasum the function uses.
GOOD="$(shasum -a 256 "$TMP/artifact.zip" | awk '{print $1}')"

if verify_sha256 "$TMP/artifact.zip" "$GOOD" "test artifact"; then
    ok "verify_sha256 accepts a matching digest"
else
    bad "verify_sha256 rejected a matching digest"
fi
if [ -f "$TMP/artifact.zip" ]; then
    ok "verify_sha256 leaves a good file in place"
else
    bad "verify_sha256 deleted a GOOD file"
fi

BAD="0000000000000000000000000000000000000000000000000000000000000000"
if verify_sha256 "$TMP/artifact.zip" "$BAD" "test artifact"; then
    bad "verify_sha256 ACCEPTED a mismatching digest"
else
    ok "verify_sha256 rejects a mismatching digest"
fi
# The deletion is the point: a bad archive must not survive to be unzipped by
# some later branch or a re-run that skips the download because the file is
# already there.
if [ -f "$TMP/artifact.zip" ]; then
    bad "verify_sha256 left a BAD file on disk"
else
    ok "verify_sha256 deletes a bad file"
fi
if verify_sha256 "$TMP/does-not-exist.zip" "$GOOD" "missing artifact"; then
    bad "verify_sha256 ACCEPTED a missing file"
else
    ok "verify_sha256 rejects a missing file"
fi

# --- the pins themselves are present and well-formed -----------------------
# Not a network call: just that nobody replaced a digest with a placeholder or
# left a version and its hash out of step (installer/README.md, "Bumping a
# pinned download").
for var in RCLONE_VERSION SYNCTHING_VERSION; do
    val="$(grep -E "^${var}=" "$SCRIPT" | head -n 1 | cut -d'"' -f2)"
    case "$val" in
        v[0-9]*) ok "$var is pinned ($val)" ;;
        *) bad "$var is not a pinned version: '$val'" ;;
    esac
done
for var in RCLONE_SHA256_ARM64 RCLONE_SHA256_AMD64 SYNCTHING_SHA256_ARM64 SYNCTHING_SHA256_AMD64; do
    val="$(grep -E "^${var}=" "$SCRIPT" | head -n 1 | cut -d'"' -f2)"
    if printf '%s' "$val" | grep -qE '^[0-9a-f]{64}$'; then
        ok "$var is a 64-hex sha256"
    else
        bad "$var is not a 64-hex sha256: '$val'"
    fi
done
# "latest"-style URLs are what the pin replaced; they must not come back.
# Comments are stripped first -- both strings survive in the prose that
# explains why they are gone, which is the point of that prose.
CODE_ONLY="$(grep -v '^[[:space:]]*#' "$SCRIPT")"
if printf '%s' "$CODE_ONLY" | grep -qE 'rclone-current-|releases/latest'; then
    printf '%s' "$CODE_ONLY" | grep -nE 'rclone-current-|releases/latest' | head -n 3
    bad "an unpinned 'latest' download URL is back in macos_bootstrap.sh"
else
    ok "no unpinned 'latest' download URL in macos_bootstrap.sh"
fi
# Same for the tenant literal item 10 removed: com.creatorsclub.* may appear
# ONLY as a *_LEGACY value being retired, never as a label being written.
BAD_LABEL="$(printf '%s' "$CODE_ONLY" | grep -F 'com.creatorsclub' | grep -v 'LEGACY' || true)"
if [ -n "$BAD_LABEL" ]; then
    printf '%s\n' "$BAD_LABEL" | head -n 3
    bad "a com.creatorsclub.* label is being WRITTEN again"
else
    ok "com.creatorsclub.* appears only as the retired legacy label"
fi

# --- low_space_message (UX-14, resilience sweep 2026-08-28) ----------------
# A warning, not a refusal, so the only things that can be wrong are the
# threshold, the arithmetic and the wording. "could not measure" (an empty or
# non-numeric argument, which is what free_kb_for_path prints when df fails)
# must print NOTHING rather than "0 GB free".
check "plenty of room says nothing"     "" "$(low_space_message 1073741824)"
check "exactly at the 200 GB floor"     "" "$(low_space_message 209715200)"
check "an unmeasurable volume says nothing" "" "$(low_space_message '')"
check "a non-numeric df result says nothing" "" "$(low_space_message 'Filesystem')"
check "41 GB free" \
    "This drive has 41 GB free. Synced proxies for one project are typically 50 to 300 GB." \
    "$(low_space_message 42991616)"
check "a nearly empty drive still names a figure" \
    "This drive has 1 GB free. Synced proxies for one project are typically 50 to 300 GB." \
    "$(low_space_message 1048576)"
case "$(low_space_message 42991616)" in
    *—*) bad "low_space_message contains an em dash" ;;
    *) ok "low_space_message has no em dash" ;;
esac

echo ""
if [ "$fail" -gt 0 ]; then
    echo "$fail FAILED"
    exit 1
fi
echo "all macos_bootstrap.sh site-value / pinned-download cases pass"
