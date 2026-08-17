#!/usr/bin/env bash
#
# CC Sync -- macOS uninstall.
#
# Removes the CCSync software this Mac runs. IT NEVER TOUCHES YOUR SYNCED
# MEDIA: the project tree on your SSD is left exactly as it is, in both
# modes. The macOS counterpart of installer/windows_uninstall.ps1.
#
#   (default) -- stop and remove the companion + Syncthing this installer
#     put in ~/.local/ccsync, remove both LaunchAgents, and drop this
#     install's own rclone stanza (the one config.toml's `remote` names) from
#     ~/.config/rclone/rclone.conf -- and only that one. Your
#     sign-in and settings in ~/.ccsync are kept.
#
#   --full -- also remove your sign-in and settings (~/.ccsync), except
#     ~/.ccsync/state (see below).
#
# Never uninstalls a Tailscale / rclone / Syncthing that came from Homebrew:
# those may be shared with other tools -- `brew uninstall` them yourself if
# you want them gone. The rclone SSH key in ~/.ssh is never deleted either
# (shared location); --full just says where it is.
#
# Resolve's Mapped Mount preference is LEFT IN PLACE on purpose: it is
# Resolve's own configuration, it is harmless without CCSync, and removing
# it means editing Resolve's preference files -- which this script will not
# do behind your back. One line at the end says how to remove it by hand.
#
# Every step is guarded and idempotent -- safe to re-run. --dry-run prints
# what it would do and touches nothing.
#
# NOT YET RUN ON A REAL MAC (pending first real-Mac validation, 2026-08-03).
#
# Usage:
#   ./macos_uninstall.sh [--full] [--dry-run]
#
set -u

DRY_RUN=0
FULL=0

usage() {
    echo "Usage: $0 [--full] [--dry-run]"
    echo ""
    echo "  --full     also remove your sign-in and settings (~/.ccsync)"
    echo "  --dry-run  report what would happen and change nothing"
    exit 1
}

while [ $# -gt 0 ]; do
    case "$1" in
        --full)    FULL=1; shift ;;
        --dry-run) DRY_RUN=1; shift ;;
        -h|--help) usage ;;
        *) echo "Unknown argument: $1"; usage ;;
    esac
done

step() { echo "[uninstall] $1"; }
skip() { echo "[uninstall] SKIP: $1"; }
warn() { echo "[uninstall] WARNING: $1" >&2; }
dry()  { echo "[uninstall] [dry-run] $1"; }

CCSYNC_LOCAL="$HOME/.local/ccsync"
BIN_DIR="$CCSYNC_LOCAL/bin"
SYNCTHING_HOME="$CCSYNC_LOCAL/syncthing-config"
CCSYNC_PROFILE="$HOME/.ccsync"
LAUNCH_AGENTS_DIR="$HOME/Library/LaunchAgents"
# BOTH label generations. The agents were renamed com.creatorsclub.* ->
# com.ccsync.* on 2026-08-17 (docs/COMMERCIAL_READINESS.md item 10 -- a
# launchd label is a durable, user-visible identifier and must not carry
# another company's reverse-DNS name), so an uninstaller that knows only the
# new names leaves every Mac provisioned before that with two live agents and
# no way to stop them from the wizard.
COMPANION_PLIST="$LAUNCH_AGENTS_DIR/com.ccsync.companion.plist"
SYNCTHING_PLIST="$LAUNCH_AGENTS_DIR/com.ccsync.syncthing.plist"
COMPANION_PLIST_LEGACY="$LAUNCH_AGENTS_DIR/com.creatorsclub.ccsync.companion.plist"
SYNCTHING_PLIST_LEGACY="$LAUNCH_AGENTS_DIR/com.creatorsclub.ccsync.syncthing.plist"
RCLONE_CONF_PATH="$HOME/.config/rclone/rclone.conf"
# Resolved from THIS machine's config.toml below (see LOCAL_ROOT). The name
# stopped being a constant on 2026-08-17 (WP0): the bootstrap takes it from
# the dashboard's site manifest and falls back to "ccsync_sftp", so an
# uninstaller with a hardcoded name would silently leave the stanza behind on
# any site that names its remote something else -- and on every install made
# before that, whose config.toml still names the old one.
REMOTE_NAME="ccsync_sftp"
# Same story as REMOTE_NAME: the prefix is site data since 2026-08-17
# (docs/COMMERCIAL_READINESS.md item 11), read from this machine's own
# config.toml below. P:\ only as the last-resort default, which is what every
# install made before the change has.
CANONICAL_PREFIX='P:\'

LOCAL_ROOT=""
if [ -f "$CCSYNC_PROFILE/config.toml" ]; then
    # ...and un-escape TOML's doubled backslashes, so a Windows-style value
    # is reported the way the editor typed it rather than as P:\\.
    LOCAL_ROOT="$(sed -n 's/^[[:space:]]*local_root[[:space:]]*=[[:space:]]*"\(.*\)".*/\1/p' \
        "$CCSYNC_PROFILE/config.toml" | head -n 1 | sed 's/\\\\/\\/g')"
    CONFIGURED_REMOTE="$(sed -n 's/^[[:space:]]*remote[[:space:]]*=[[:space:]]*"\([^"]*\)".*/\1/p' \
        "$CCSYNC_PROFILE/config.toml" | head -n 1)"
    [ -n "$CONFIGURED_REMOTE" ] && REMOTE_NAME="$CONFIGURED_REMOTE"
    CONFIGURED_PREFIX="$(sed -n 's/^[[:space:]]*canonical_prefix[[:space:]]*=[[:space:]]*"\(.*\)".*/\1/p' \
        "$CCSYNC_PROFILE/config.toml" | head -n 1 | sed 's/\\\\/\\/g')"
    [ -n "$CONFIGURED_PREFIX" ] && CANONICAL_PREFIX="$CONFIGURED_PREFIX"
fi

if [ "$FULL" = 1 ]; then
    step "mode: FULL (also removes your sign-in and settings in $CCSYNC_PROFILE)"
else
    step "mode: keep your sign-in and settings in $CCSYNC_PROFILE"
fi
step "your synced media is never touched by this script -- only the CCSync software itself."
if [ "$DRY_RUN" = 1 ]; then
    step "DRY RUN -- nothing will be changed"
fi

# ----------------------------------------------------------------------
# 1. LaunchAgents
# ----------------------------------------------------------------------
# bootout BEFORE deleting the plist: launchd keeps running the job it has
# already loaded, and a deleted plist just means it cannot be booted out by
# path any more (it comes back at the next logon only if the file is there,
# but the CURRENT session keeps the running job either way).
for plist in "$COMPANION_PLIST" "$SYNCTHING_PLIST" \
             "$COMPANION_PLIST_LEGACY" "$SYNCTHING_PLIST_LEGACY"; do
    if [ ! -f "$plist" ]; then
        skip "no LaunchAgent: $plist"
        continue
    fi
    if [ "$DRY_RUN" = 1 ]; then
        dry "would unload and delete LaunchAgent: $plist"
        continue
    fi
    launchctl bootout "gui/$(id -u)" "$plist" >/dev/null 2>&1 || true
    launchctl unload "$plist" >/dev/null 2>&1 || true
    rm -f "$plist"
    step "unloaded and removed LaunchAgent: $plist"
done

# ----------------------------------------------------------------------
# 2. running processes -- ONLY the ones we installed
# ----------------------------------------------------------------------
# A Mac may well run its own Homebrew Syncthing for the editor's personal
# files, and killing that would be this script destroying data it never
# installed. So: match by pattern like the bootstrap does (:446), then keep
# only the PIDs whose executable actually lives under ~/.local/ccsync.
# `ps -o comm=` prints the full executable path on macOS.
stop_ours() {
    local pattern="$1" label="$2" pid exe found=0
    for pid in $(pgrep -f "$pattern" 2>/dev/null); do
        [ "$pid" = "$$" ] && continue
        exe="$(ps -p "$pid" -o comm= 2>/dev/null)"
        case "$exe" in
            "$CCSYNC_LOCAL"/*)
                found=1
                if [ "$DRY_RUN" = 1 ]; then
                    dry "would stop $label: PID $pid ($exe)"
                else
                    kill "$pid" 2>/dev/null || true
                    step "stopped $label: PID $pid ($exe)"
                fi
                ;;
            *)
                skip "leaving PID $pid alone -- '$exe' is not under $CCSYNC_LOCAL (not ours)"
                ;;
        esac
    done
    if [ "$found" = 0 ]; then
        skip "no running $label from $CCSYNC_LOCAL"
    fi
}

stop_ours "ccsync-companion" "companion"
stop_ours "syncthing" "Syncthing"

# ----------------------------------------------------------------------
# 3. program files
# ----------------------------------------------------------------------
# Directory-level removal on purpose. The self-upgrade machinery stages and
# retires binaries next to the live one -- ccsync-companion.new and
# ccsync-companion.old (extensionless on macOS; only Windows has the .exe
# forms) -- and a per-file whitelist would leave those behind. If this is
# ever refactored into a selective delete, those two names have to be in it.
if [ -d "$CCSYNC_LOCAL" ]; then
    if [ "$DRY_RUN" = 1 ]; then
        dry "would delete $CCSYNC_LOCAL (rclone/syncthing/companion binaries in bin/, plus the Syncthing identity in syncthing-config/)"
    else
        rm -rf "$CCSYNC_LOCAL"
        step "removed $CCSYNC_LOCAL (binaries and the Syncthing identity)"
    fi
    warn "that included the Syncthing identity in $SYNCTHING_HOME. A reinstall generates a NEW device ID, so the admin has to approve this Mac again on the dashboard before lane C syncs. Your media was not touched."
else
    skip "already absent: $CCSYNC_LOCAL"
fi

if [ -d "$BIN_DIR" ]; then
    warn "$BIN_DIR still exists -- remove it by hand: rm -rf \"$CCSYNC_LOCAL\""
fi

# ----------------------------------------------------------------------
# 4. rclone remote stanza
# ----------------------------------------------------------------------
# Only OUR stanza: rclone.conf routinely holds the editor's own remotes, and
# some of them carry credentials. Same awk stanza walk the bootstrap uses to
# rewrite it, minus the reprint.
if [ ! -f "$RCLONE_CONF_PATH" ]; then
    skip "no rclone config: $RCLONE_CONF_PATH"
elif ! grep -qF "[$REMOTE_NAME]" "$RCLONE_CONF_PATH"; then
    skip "no [$REMOTE_NAME] stanza in $RCLONE_CONF_PATH"
elif [ "$DRY_RUN" = 1 ]; then
    dry "would remove the [$REMOTE_NAME] stanza from $RCLONE_CONF_PATH (every other remote preserved)"
else
    RCLONE_TMP="$(mktemp "${RCLONE_CONF_PATH}.ccsync.XXXXXX")"
    awk -v sect="[$REMOTE_NAME]" '
        $0 == sect { inside=1; next }
        inside && /^\[/ { inside=0 }
        !inside { print }
    ' "$RCLONE_CONF_PATH" > "$RCLONE_TMP"
    # Same permissions as the file being replaced -- it can hold credentials
    # for the remotes we are keeping.
    chmod 600 "$RCLONE_TMP"
    mv "$RCLONE_TMP" "$RCLONE_CONF_PATH"
    step "removed the [$REMOTE_NAME] stanza from $RCLONE_CONF_PATH (other remotes untouched)"
fi

# ----------------------------------------------------------------------
# 5. sign-in and settings (kept unless --full)
# ----------------------------------------------------------------------
if [ "$FULL" = 1 ]; then
    if [ -d "$CCSYNC_PROFILE" ]; then
        # Everything except state/. That directory holds the questions this
        # machine has already answered once and for all --
        # state/project_prompts.json is the "Project '<X>' isn't set up on
        # the server -- set it up now?" memory. Deleting it makes every
        # prompt the editor already dismissed come back on the next install,
        # which reads as "the fix didn't work" (exactly how the Blackmagic
        # Proxy Generator "New Doc" prompt kept coming back; seen live
        # 2026-07-25). It holds no identity, no credentials and no media.
        removed=0
        for item in "$CCSYNC_PROFILE"/* "$CCSYNC_PROFILE"/.[!.]*; do
            [ -e "$item" ] || continue
            case "$(basename "$item")" in
                state) continue ;;
            esac
            if [ "$DRY_RUN" = 1 ]; then
                dry "would delete $item"
            else
                rm -rf "$item"
            fi
            removed=$((removed + 1))
        done
        if [ "$DRY_RUN" != 1 ]; then
            step "removed your sign-in and settings from $CCSYNC_PROFILE ($removed item(s), including config.toml, identity.json and volume.json)"
        fi
        if [ -d "$CCSYNC_PROFILE/state" ]; then
            step "KEPT $CCSYNC_PROFILE/state -- the prompts you have already answered stay answered after a reinstall (no identity or credentials live there)."
        fi
    else
        skip "already absent: $CCSYNC_PROFILE"
    fi
    warn "FULL uninstall: your saved sign-in is gone. A reinstall needs the admin to approve this Mac again before anything syncs. Your media was not touched."
    if [ -f "$HOME/.ssh/ccsync_ed25519" ]; then
        step "NOTE: the rclone SSH key remains at $HOME/.ssh/ccsync_ed25519 (left in place -- delete it by hand if you want it gone; the admin would then re-run setup_editor_account.py)."
    fi
else
    if [ -d "$CCSYNC_PROFILE" ]; then
        step "KEPT your sign-in and settings: $CCSYNC_PROFILE (config.toml, identity.json, state)"
    fi
    step "run with --full to also remove your sign-in and settings."
fi

# ----------------------------------------------------------------------
# 6. what is deliberately left behind
# ----------------------------------------------------------------------
echo ""
echo "=================================================================="
step "CCSync uninstall complete$([ "$DRY_RUN" = 1 ] && echo ' (dry run -- nothing changed)')."
step "Resolve still maps $CANONICAL_PREFIX -> ${LOCAL_ROOT:-your local root}; remove it in DaVinci Resolve > Preferences > Media Storage if desired."
step "Tailscale / rclone / Syncthing installed with Homebrew were left alone; 'brew uninstall' them yourself if you want them gone."
step "YOUR SYNCED MEDIA ON THE SSD WAS NOT TOUCHED -- not one file in ${LOCAL_ROOT:-your project tree} was read, moved or deleted by this script."
echo "=================================================================="
