#!/usr/bin/env bash
#
# Creators Club Sync -- macOS editor bootstrap.
#
# Idempotent setup for a remote Resolve editor's Mac:
#   - Tailscale   (brew cask, else prints download URL)
#   - rclone      (brew, else direct tarball to ~/.local/ccsync/bin)
#   - Syncthing   (brew, else direct tarball to the same bin dir) + a
#                 LaunchAgent to autostart it
#   - ~/Creators_Club (the local sync root -- Resolve's Mapped Mount
#     preference points here; see docs/EDITOR_SETUP.md, that part is manual)
#   - rclone remote config stanza template in ~/.config/rclone/rclone.conf
#   - a LaunchAgent autostart entry for the companion app, if it exists yet
#   - prints this machine's Syncthing device ID at the end
#
# Every step checks current state before acting and prints a line saying
# what it did or what it skipped, so this script is safe to re-run.
#
# This script does NOT run `tailscale up` (joining the tailnet) or generate
# SSH keys -- those are one-time interactive/manual steps, see
# docs/EDITOR_SETUP.md. It also does NOT set Resolve's Mapped Mount
# preference -- that can't be scripted (Resolve scripting API doesn't
# expose it), see docs/EDITOR_SETUP.md for the manual walkthrough.
#
# Usage:
#   ./macos_bootstrap.sh --tailnet-host truenas.tailnet.ts.net --editor-name jsmith [--dry-run]
#
set -u

DRY_RUN=0
TAILNET_HOST=""
EDITOR_NAME=""
COMPANION_APP_PATH="$HOME/Applications/CCSyncCompanion.app"

usage() {
    echo "Usage: $0 --tailnet-host <host> --editor-name <name> [--companion-app-path <path>] [--dry-run]"
    exit 1
}

while [ $# -gt 0 ]; do
    case "$1" in
        --tailnet-host)
            TAILNET_HOST="$2"; shift 2 ;;
        --editor-name)
            EDITOR_NAME="$2"; shift 2 ;;
        --companion-app-path)
            COMPANION_APP_PATH="$2"; shift 2 ;;
        --dry-run)
            DRY_RUN=1; shift ;;
        -h|--help)
            usage ;;
        *)
            echo "Unknown argument: $1"; usage ;;
    esac
done

if [ -z "$TAILNET_HOST" ] || [ -z "$EDITOR_NAME" ]; then
    usage
fi

step() { echo "[ccsync] $1"; }
skip() { echo "[ccsync] SKIP: $1"; }
warn() { echo "[ccsync] WARNING: $1" >&2; }
dry()  { echo "[ccsync] [dry-run] $1"; }

BIN_DIR="$HOME/.local/ccsync/bin"
CC_ROOT="$HOME/Creators_Club"
LAUNCH_AGENTS_DIR="$HOME/Library/LaunchAgents"
RCLONE_CONF_DIR="$HOME/.config/rclone"
RCLONE_CONF_PATH="$RCLONE_CONF_DIR/rclone.conf"
SYNCTHING_HOME="$HOME/.local/ccsync/syncthing-config"
KEY_FILE_PATH="$HOME/.ssh/ccsync_ed25519"
REMOTE_NAME="creators_club_sftp"

ensure_dir() {
    local path="$1"
    if [ -d "$path" ]; then
        skip "directory already exists: $path"
    else
        if [ "$DRY_RUN" = 1 ]; then
            dry "would create directory: $path"
        else
            mkdir -p "$path"
            step "created directory: $path"
        fi
    fi
}

have_cmd() { command -v "$1" >/dev/null 2>&1; }

ensure_dir "$BIN_DIR"

# ----------------------------------------------------------------------
# 1. Tailscale
# ----------------------------------------------------------------------
step "checking Tailscale..."
if have_cmd tailscale || [ -d "/Applications/Tailscale.app" ]; then
    skip "Tailscale already installed"
else
    if have_cmd brew; then
        if [ "$DRY_RUN" = 1 ]; then
            dry "would run: brew install --cask tailscale"
        else
            step "installing Tailscale via brew..."
            if brew install --cask tailscale; then
                step "Tailscale installed"
            else
                warn "brew install of tailscale failed"
            fi
        fi
    else
        warn "Homebrew not found. Download and install Tailscale manually from https://tailscale.com/download/mac then re-run this script."
        exit 1
    fi
fi

# ----------------------------------------------------------------------
# 2. rclone
# ----------------------------------------------------------------------
step "checking rclone..."
RCLONE_BIN=""
if have_cmd rclone; then
    RCLONE_BIN="$(command -v rclone)"
elif [ -x "$BIN_DIR/rclone" ]; then
    RCLONE_BIN="$BIN_DIR/rclone"
fi

if [ -n "$RCLONE_BIN" ]; then
    skip "rclone already installed: $RCLONE_BIN"
else
    installed=0
    if have_cmd brew; then
        if [ "$DRY_RUN" = 1 ]; then
            dry "would run: brew install rclone"
            installed=1
        else
            step "installing rclone via brew..."
            if brew install rclone; then
                installed=1
            else
                warn "brew install of rclone failed, falling back to direct download"
            fi
        fi
    fi
    if [ "$installed" = 0 ]; then
        ARCH="$(uname -m)"
        if [ "$ARCH" = "arm64" ]; then
            ZIP_URL="https://downloads.rclone.org/rclone-current-osx-arm64.zip"
        else
            ZIP_URL="https://downloads.rclone.org/rclone-current-osx-amd64.zip"
        fi
        ZIP_PATH="/tmp/ccsync-rclone.zip"
        EXTRACT_DIR="/tmp/ccsync-rclone-extract"
        if [ "$DRY_RUN" = 1 ]; then
            dry "would download $ZIP_URL, extract, and copy rclone to $BIN_DIR"
        else
            step "downloading rclone from $ZIP_URL ..."
            curl -fsSL "$ZIP_URL" -o "$ZIP_PATH"
            rm -rf "$EXTRACT_DIR"
            mkdir -p "$EXTRACT_DIR"
            unzip -q -o "$ZIP_PATH" -d "$EXTRACT_DIR"
            FOUND="$(find "$EXTRACT_DIR" -name rclone -type f | head -n 1)"
            if [ -z "$FOUND" ]; then
                warn "could not find rclone binary inside the downloaded zip -- install rclone manually"
            else
                cp "$FOUND" "$BIN_DIR/rclone"
                chmod +x "$BIN_DIR/rclone"
                step "installed rclone to $BIN_DIR/rclone"
            fi
        fi
    fi
fi

# ----------------------------------------------------------------------
# 3. Syncthing (+ LaunchAgent autostart)
# ----------------------------------------------------------------------
step "checking Syncthing..."
SYNCTHING_BIN=""
if have_cmd syncthing; then
    SYNCTHING_BIN="$(command -v syncthing)"
elif [ -x "$BIN_DIR/syncthing" ]; then
    SYNCTHING_BIN="$BIN_DIR/syncthing"
fi

if [ -n "$SYNCTHING_BIN" ]; then
    skip "Syncthing already installed: $SYNCTHING_BIN"
else
    installed=0
    if have_cmd brew; then
        if [ "$DRY_RUN" = 1 ]; then
            dry "would run: brew install syncthing"
            installed=1
        else
            step "installing Syncthing via brew..."
            if brew install syncthing; then
                installed=1
                SYNCTHING_BIN="$(command -v syncthing)"
            else
                warn "brew install of syncthing failed, falling back to direct download"
            fi
        fi
    fi
    if [ "$installed" = 0 ]; then
        ARCH="$(uname -m)"
        if [ "$ARCH" = "arm64" ]; then
            TAR_URL="https://github.com/syncthing/syncthing/releases/latest/download/syncthing-macos-arm64.tar.gz"
        else
            TAR_URL="https://github.com/syncthing/syncthing/releases/latest/download/syncthing-macos-amd64.tar.gz"
        fi
        TAR_PATH="/tmp/ccsync-syncthing.tar.gz"
        EXTRACT_DIR="/tmp/ccsync-syncthing-extract"
        if [ "$DRY_RUN" = 1 ]; then
            dry "would download $TAR_URL, extract, and copy syncthing to $BIN_DIR"
        else
            step "downloading Syncthing from $TAR_URL ..."
            curl -fsSL "$TAR_URL" -o "$TAR_PATH"
            rm -rf "$EXTRACT_DIR"
            mkdir -p "$EXTRACT_DIR"
            tar -xzf "$TAR_PATH" -C "$EXTRACT_DIR"
            FOUND="$(find "$EXTRACT_DIR" -name syncthing -type f | head -n 1)"
            if [ -z "$FOUND" ]; then
                warn "could not find syncthing binary inside the downloaded tarball -- install Syncthing manually"
            else
                cp "$FOUND" "$BIN_DIR/syncthing"
                chmod +x "$BIN_DIR/syncthing"
                SYNCTHING_BIN="$BIN_DIR/syncthing"
                step "installed Syncthing to $BIN_DIR/syncthing"
            fi
        fi
    fi
fi
if [ "$DRY_RUN" = 1 ] && [ -z "$SYNCTHING_BIN" ]; then
    SYNCTHING_BIN="$BIN_DIR/syncthing"
fi

SYNCTHING_PLIST="$LAUNCH_AGENTS_DIR/com.creatorsclub.ccsync.syncthing.plist"
ensure_dir "$LAUNCH_AGENTS_DIR"
if [ -f "$SYNCTHING_PLIST" ]; then
    skip "Syncthing LaunchAgent already present: $SYNCTHING_PLIST"
else
    if [ "$DRY_RUN" = 1 ]; then
        dry "would write LaunchAgent plist: $SYNCTHING_PLIST (runs $SYNCTHING_BIN serve --home=$SYNCTHING_HOME)"
    else
        cat > "$SYNCTHING_PLIST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.creatorsclub.ccsync.syncthing</string>
    <key>ProgramArguments</key>
    <array>
        <string>$SYNCTHING_BIN</string>
        <string>serve</string>
        <string>--home=$SYNCTHING_HOME</string>
        <string>--no-browser</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
</dict>
</plist>
PLIST
        step "wrote Syncthing LaunchAgent: $SYNCTHING_PLIST (load it with: launchctl load $SYNCTHING_PLIST)"
    fi
fi

# ----------------------------------------------------------------------
# 4. ~/Creators_Club local sync root
# ----------------------------------------------------------------------
ensure_dir "$CC_ROOT"

# ----------------------------------------------------------------------
# 5. rclone remote config stanza
# ----------------------------------------------------------------------
ensure_dir "$RCLONE_CONF_DIR"

STANZA="[$REMOTE_NAME]
type = sftp
host = $TAILNET_HOST
user = $EDITOR_NAME
port = 22
key_file = $KEY_FILE_PATH
shell_type = unix
"

has_section=0
if [ -f "$RCLONE_CONF_PATH" ] && grep -qF "[$REMOTE_NAME]" "$RCLONE_CONF_PATH"; then
    has_section=1
fi

if [ "$has_section" = 1 ]; then
    skip "rclone.conf already has a [$REMOTE_NAME] section: $RCLONE_CONF_PATH"
else
    if [ "$DRY_RUN" = 1 ]; then
        dry "would append this stanza to $RCLONE_CONF_PATH :"
        echo "$STANZA"
    else
        printf '\n%s\n' "$STANZA" >> "$RCLONE_CONF_PATH"
        step "appended [$REMOTE_NAME] stanza to $RCLONE_CONF_PATH"
    fi
fi

if [ ! -f "$KEY_FILE_PATH" ]; then
    warn "SSH private key not found at $KEY_FILE_PATH -- generate a keypair (ssh-keygen -t ed25519 -f \"$KEY_FILE_PATH\"), send the .pub file to the admin for server/setup_editor_account.py, and this rclone remote will start working."
fi

# ----------------------------------------------------------------------
# 6. Companion autostart (guarded -- app may not exist yet)
# ----------------------------------------------------------------------
step "checking companion app at $COMPANION_APP_PATH..."
COMPANION_PLIST="$LAUNCH_AGENTS_DIR/com.creatorsclub.ccsync.companion.plist"
if [ ! -e "$COMPANION_APP_PATH" ]; then
    warn "companion app not found at $COMPANION_APP_PATH -- skipping autostart registration. Install the companion app later and re-run this script to register autostart."
else
    if [ -f "$COMPANION_PLIST" ]; then
        skip "companion LaunchAgent already present: $COMPANION_PLIST"
    else
        if [ "$DRY_RUN" = 1 ]; then
            dry "would write LaunchAgent plist: $COMPANION_PLIST (runs $COMPANION_APP_PATH/Contents/MacOS/ccsync-companion)"
        else
            cat > "$COMPANION_PLIST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.creatorsclub.ccsync.companion</string>
    <key>ProgramArguments</key>
    <array>
        <string>open</string>
        <string>-a</string>
        <string>$COMPANION_APP_PATH</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
</dict>
</plist>
PLIST
            step "wrote companion LaunchAgent: $COMPANION_PLIST (load it with: launchctl load $COMPANION_PLIST)"
        fi
    fi
fi

# ----------------------------------------------------------------------
# 7. Print Syncthing device ID
# ----------------------------------------------------------------------
step "determining this machine's Syncthing device ID..."
if [ "$DRY_RUN" = 1 ]; then
    dry "would run: $SYNCTHING_BIN generate --home=$SYNCTHING_HOME (if not already generated)"
    dry "would run: $SYNCTHING_BIN --device-id --home=$SYNCTHING_HOME"
    echo ""
    echo "=================================================================="
    echo " Bootstrap complete (dry run). No changes were made."
    echo "=================================================================="
else
    if [ ! -d "$SYNCTHING_HOME" ]; then
        step "generating Syncthing config at $SYNCTHING_HOME ..."
        "$SYNCTHING_BIN" generate --home="$SYNCTHING_HOME" >/dev/null 2>&1
    else
        skip "Syncthing config already generated at $SYNCTHING_HOME"
    fi

    DEVICE_ID="$("$SYNCTHING_BIN" --device-id --home="$SYNCTHING_HOME" 2>/dev/null)"
    echo ""
    echo "=================================================================="
    echo " Bootstrap complete."
    echo ""
    echo " Your Syncthing device ID is:"
    echo ""
    echo "     $DEVICE_ID"
    echo ""
    echo " Send this device ID to the admin so they can approve it with"
    echo " server/accept_device.py for each project you're working on."
    echo ""
    echo " Remaining manual steps (see docs/EDITOR_SETUP.md):"
    echo "   1. tailscale up   (join the tailnet, one-time interactive login)"
    echo "   2. generate an SSH keypair for rclone if you haven't already:"
    echo "        ssh-keygen -t ed25519 -f \"$KEY_FILE_PATH\""
    echo "      and send the .pub file to the admin"
    echo "   3. connect DaVinci Resolve to the Project Server"
    echo "   4. Playback > Proxy Handling > Prefer Proxies"
    echo "   5. Preferences > Media Storage > add ~/Creators_Club as a Mapped"
    echo "      Mount for P:\\  (manual, one-time -- see docs/EDITOR_SETUP.md)"
    echo "=================================================================="
fi
