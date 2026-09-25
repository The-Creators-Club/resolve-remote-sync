#!/usr/bin/env bash
#
# Table test for macos_bootstrap.sh's print_first_setup_steps
# (ui-onboarding-11, bug hunt 2026-09-24 wave 2).
#
# The end banner listed "1. tailscale up  2. ssh-keygen ... send the .pub
# file  3. SIGN IN" as remaining manual steps on every run, and the wizard
# streams that banner into the install log an editor sends their admin. The
# wizard has done all three before it runs the script, so a reader of the log
# made and sent a second key. The wizard now sets CCSYNC_FROM_WIZARD=1 and the
# banner's first three steps come from this function. A missing companion is
# still step 3 either way.
#
# The function is SLICED OUT of the script rather than sourced -- sourcing it
# would run the whole installer.
#
# Run (Git Bash, macOS or Linux):
#   bash installer/tests/test_macos_first_steps.sh
# Exits 1 on any failure.
set -u

HERE="$(cd "$(dirname "$0")" && pwd)"
SCRIPT="$HERE/../macos_bootstrap.sh"
[ -f "$SCRIPT" ] || { echo "FAIL: no $SCRIPT"; exit 1; }

fail=0
ok()   { echo "  PASS  $1"; }
bad()  { echo "  FAIL  $1"; fail=$((fail + 1)); }

SRC="$(awk '
    index($0, "print_first_setup_steps() {") { on = 1 }
    on { print }
    on && /^}/ { exit }
' "$SCRIPT")"
case "$SRC" in
    *'}'*) ;;
    *) echo "FAIL: could not slice print_first_setup_steps out of $SCRIPT"; exit 1 ;;
esac
eval "$SRC"

KEY_FILE_PATH="/Users/ana/.ssh/ccsync_ed25519"

# --- a wizard run -------------------------------------------------------------
out="$(CCSYNC_FROM_WIZARD=1 COMPANION_MISSING=0 print_first_setup_steps)"
case "$out" in *ssh-keygen*) bad "a wizard run still asks for ssh-keygen" ;; *) ok "a wizard run does not ask for a second key" ;; esac
case "$out" in *"tailscale up"*) bad "a wizard run still says tailscale up" ;; *) ok "a wizard run does not ask to join Tailscale again" ;; esac
case "$out" in *EDITOR_SETUP*) bad "a wizard run names a docs folder" ;; *) ok "a wizard run names no docs folder" ;; esac
case "$out" in *"DONE BY THE SETUP WIZARD: the companion is signed in"*) ok "a wizard run says the sign-in is done" ;; *) bad "a wizard run does not say step 3 is done: $out" ;; esac

# --- a wizard run whose companion did not install: step 3 is still the problem
out="$(CCSYNC_FROM_WIZARD=1 COMPANION_MISSING=1 print_first_setup_steps)"
case "$out" in *"INSTALL THE SYNC APP"*) ok "a missing companion is still step 3 on a wizard run" ;; *) bad "a wizard run hid a missing companion: $out" ;; esac

# --- a hand run: unchanged ----------------------------------------------------
out="$(CCSYNC_FROM_WIZARD= COMPANION_MISSING=0 print_first_setup_steps)"
case "$out" in *"ssh-keygen -t ed25519 -f \"$KEY_FILE_PATH\""*) ok "a hand run keeps the ssh-keygen line" ;; *) bad "a hand run lost its ssh-keygen line: $out" ;; esac
case "$out" in *"tailscale up"*"SIGN IN"*) ok "a hand run keeps tailscale up and SIGN IN" ;; *) bad "a hand run lost a step: $out" ;; esac
case "$out" in *TrueNAS*) bad "a hand run names a storage vendor" ;; *) ok "a hand run names no storage vendor" ;; esac

# --- unset variables are safe (the script runs under set -u) ------------------
out="$(unset CCSYNC_FROM_WIZARD COMPANION_MISSING; print_first_setup_steps 2>&1)"
case "$out" in *"unbound variable"*) bad "unset variables break the banner under set -u" ;; *) ok "unset variables are safe" ;; esac

# --- the banner calls it ------------------------------------------------------
if grep -q '^    print_first_setup_steps$' "$SCRIPT"; then
    ok "the end banner goes through print_first_setup_steps"
else
    bad "nothing in macos_bootstrap.sh calls print_first_setup_steps"
fi

echo ""
if [ "$fail" -gt 0 ]; then
    echo "$fail FAILED"
    exit 1
fi
echo "all first-setup-steps cases pass"
