#!/usr/bin/env bash
#
# bug-ops-4 (bug hunt 2026-09-24): macos_uninstall.sh --full reported "removed
# your sign-in and settings ... including config.toml, identity.json" without
# looking, so a root-owned config.toml (a sudo'd bootstrap run) survived with
# the machine's cce1. fleet credential in it while the editor was told it was
# gone. remove_profile_contents re-lists the directory and says what is left.
#
# The function is SLICED OUT of the script, the way test_macos_site_values.sh
# does it: sourcing the uninstaller would run it. `rm` is shadowed by a shell
# function so a file can refuse to go without needing root or a Mac.
#
# Run (Git Bash, macOS or Linux):
#   bash installer/tests/test_macos_uninstall_profile.sh
# Exits 1 on any failure.
set -u

HERE="$(cd "$(dirname "$0")" && pwd)"
SCRIPT="$HERE/../macos_uninstall.sh"
[ -f "$SCRIPT" ] || { echo "FAIL: no $SCRIPT"; exit 1; }

fail=0
ok()  { echo "  PASS  $1"; }
bad() { echo "  FAIL  $1"; fail=$((fail + 1)); }

SRC="$(awk '
    index($0, "remove_profile_contents() {") { on = 1 }
    on { print }
    on && /^}/ { exit }
' "$SCRIPT")"
case "$SRC" in
    *'return 1'*) ;;
    *) echo "FAIL: could not slice remove_profile_contents out of $SCRIPT -- did it get renamed?"; exit 1 ;;
esac
eval "$SRC"

STEP=""; WARN=""
step() { STEP="$1"; }
warn() { WARN="$1"; }

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

# 1. everything goes: success, and state/ is kept.
P="$TMP/one"; mkdir -p "$P/state"
echo x > "$P/config.toml"; echo x > "$P/identity.json"; echo x > "$P/.hidden"
echo keep > "$P/state/project_prompts.json"
STEP=""; WARN=""
if remove_profile_contents "$P"; then ok "clean removal returns 0"; else bad "clean removal returned non-zero"; fi
[ -z "$WARN" ] && ok "no warning on a clean removal" || bad "warned on a clean removal: $WARN"
case "$STEP" in *"removed your sign-in"*"3 item(s)"*) ok "says what it removed" ;; *) bad "step line was: $STEP" ;; esac
[ -f "$P/state/project_prompts.json" ] && ok "state/ kept" || bad "state/ was deleted"
[ ! -e "$P/config.toml" ] && [ ! -e "$P/.hidden" ] && ok "files gone" || bad "files survived a clean run"

# 2. config.toml refuses to go: the survivor is named and the run is NOT complete.
P="$TMP/two"; mkdir -p "$P/state"
echo x > "$P/config.toml"; echo x > "$P/identity.json"
rm() {
    local last
    for last in "$@"; do :; done
    case "$last" in *config.toml) return 1 ;; esac
    command rm "$@"
}
STEP=""; WARN=""
if remove_profile_contents "$P"; then bad "a survivor returned 0 (HEAD's behaviour: 'removed' regardless)"; else ok "a survivor returns 1"; fi
unset -f rm
case "$WARN" in *"could NOT remove 1"*"$P/config.toml"*) ok "the survivor is named" ;; *) bad "warning was: $WARN" ;; esac
case "$STEP" in *"removed your sign-in"*) bad "still claimed the sign-in was removed: $STEP" ;; *) ok "no 'removed your sign-in' claim" ;; esac

# 3. the caller wires the verdict: a survivor makes the closing line NOT complete.
grep -q 'remove_profile_contents "\$CCSYNC_PROFILE" || { REMOVAL_INCOMPLETE=1; PROFILE_SURVIVED=1; }' "$SCRIPT" \
    && ok "section 5 feeds REMOVAL_INCOMPLETE" || bad "section 5 no longer feeds the closing verdict"

if [ "$fail" -gt 0 ]; then
    echo "$fail failure(s)"
    exit 1
fi
echo "all passed"
exit 0
