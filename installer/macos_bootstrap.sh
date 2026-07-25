#!/usr/bin/env bash
#
# Creators Club Sync -- macOS editor bootstrap.
#
# Idempotent setup for a remote Resolve editor's Mac:
#   - Tailscale   (brew cask, else prints download URL)
#   - rclone      (brew, else direct tarball to ~/.local/ccsync/bin)
#   - Syncthing   (brew, else direct zip to the same bin dir) + a
#                 LaunchAgent that is written AND loaded, so the daemon is
#                 actually running (lane C is dead without it)
#   - the local sync root (--local-root, default ~/Creators_Club -- Resolve's
#     Mapped Mount preference points here; see docs/EDITOR_SETUP.md, that
#     part is manual)
#   - rclone remote config stanza template in ~/.config/rclone/rclone.conf
#   - a seeded companion config at ~/.ccsync/config.toml
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
LOCAL_ROOT="$HOME/Creators_Club"
# Absolute on purpose: the SFTP session lands in the editor's home directory
# on the NAS, so a relative remote root resolves under ~/ and silently misses
# the real project tree.
REMOTE_ROOT="/mnt/tank/TheCreatorsPool/Creators_Club"
COMPANION_APP_PATH="$HOME/Applications/CCSyncCompanion.app"

usage() {
    echo "Usage: $0 --tailnet-host <host> --editor-name <name> [--local-root <path>]"
    echo "          [--remote-root <abs-path>] [--companion-app-path <path>] [--dry-run]"
    exit 1
}

while [ $# -gt 0 ]; do
    case "$1" in
        --tailnet-host)
            TAILNET_HOST="$2"; shift 2 ;;
        --editor-name)
            EDITOR_NAME="$2"; shift 2 ;;
        --local-root)
            LOCAL_ROOT="$2"; shift 2 ;;
        --remote-root)
            REMOTE_ROOT="$2"; shift 2 ;;
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

# Unix usernames are case-sensitive; a case mismatch produces a
# working-looking rclone.conf that fails later with a generic SSH auth error
# giving no hint that the username was the problem.
EDITOR_NAME_RAW="$EDITOR_NAME"
EDITOR_NAME="$(printf '%s' "$EDITOR_NAME" | tr '[:upper:]' '[:lower:]')"
if [ "$EDITOR_NAME" != "$EDITOR_NAME_RAW" ]; then
    warn "normalized --editor-name '$EDITOR_NAME_RAW' -> '$EDITOR_NAME'"
fi

case "$REMOTE_ROOT" in
    /*) ;;
    *) warn "--remote-root '$REMOTE_ROOT' is not absolute. The SFTP session starts in your home directory on the NAS, so a relative path resolves under ~/ and will not find the project tree. Prefix it with '/'." ;;
esac

step "configuring for editor '$EDITOR_NAME', local root '$LOCAL_ROOT', NAS '$TAILNET_HOST'"

BIN_DIR="$HOME/.local/ccsync/bin"
CC_ROOT="$LOCAL_ROOT"
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
            ASSET_ARCH="arm64"
        else
            ASSET_ARCH="amd64"
        fi

        # GitHub's /releases/latest/download/<name> alias only resolves when
        # that EXACT filename exists in the release. Syncthing's assets are
        # version-named, so the unversioned alias 404s. Note macOS assets are
        # .zip (the Linux/BSD ones are .tar.gz) -- unzip, don't tar.
        resolve_syncthing_url() {
            local url tag
            url="$(curl -fsSL -H 'User-Agent: ccsync-bootstrap' \
                    https://api.github.com/repos/syncthing/syncthing/releases/latest 2>/dev/null \
                  | grep -oE '"browser_download_url": *"[^"]+"' \
                  | sed -E 's/.*"browser_download_url": *"([^"]+)".*/\1/' \
                  | grep -E "syncthing-macos-${ASSET_ARCH}-v[^/]+\.zip$" \
                  | head -n 1)"
            if [ -n "$url" ]; then
                printf '%s' "$url"
                return 0
            fi
            # Backstop: the unauthenticated API is rate-limited to 60/hour per
            # IP, so sniff the version tag out of the release redirect instead.
            tag="$(curl -fsSL -o /dev/null -w '%{url_effective}' \
                    https://github.com/syncthing/syncthing/releases/latest 2>/dev/null \
                  | sed -nE 's#.*/tag/(v[0-9][^/]*)$#\1#p')"
            if [ -n "$tag" ]; then
                printf 'https://github.com/syncthing/syncthing/releases/download/%s/syncthing-macos-%s-%s.zip' \
                    "$tag" "$ASSET_ARCH" "$tag"
                return 0
            fi
            return 1
        }

        ZIP_PATH="/tmp/ccsync-syncthing.zip"
        EXTRACT_DIR="/tmp/ccsync-syncthing-extract"
        if [ "$DRY_RUN" = 1 ]; then
            dry "would resolve the latest syncthing-macos-${ASSET_ARCH}-<version>.zip via the GitHub API, download, unzip, and copy syncthing to $BIN_DIR"
        else
            ZIP_URL="$(resolve_syncthing_url || true)"
            if [ -z "$ZIP_URL" ]; then
                warn "could not determine a Syncthing download URL -- install Syncthing manually from https://syncthing.net/downloads/ and re-run this script"
            else
                step "downloading Syncthing from $ZIP_URL ..."
                curl -fsSL "$ZIP_URL" -o "$ZIP_PATH"
                rm -rf "$EXTRACT_DIR"
                mkdir -p "$EXTRACT_DIR"
                unzip -q -o "$ZIP_PATH" -d "$EXTRACT_DIR"
                FOUND="$(find "$EXTRACT_DIR" -name syncthing -type f | head -n 1)"
                if [ -z "$FOUND" ]; then
                    warn "could not find syncthing binary inside the downloaded zip -- install Syncthing manually"
                else
                    cp "$FOUND" "$BIN_DIR/syncthing"
                    chmod +x "$BIN_DIR/syncthing"
                    SYNCTHING_BIN="$BIN_DIR/syncthing"
                    step "installed Syncthing to $BIN_DIR/syncthing"
                fi
            fi
        fi
    fi
fi
if [ "$DRY_RUN" = 1 ] && [ -z "$SYNCTHING_BIN" ]; then
    SYNCTHING_BIN="$BIN_DIR/syncthing"
fi

# Generate the config/keys before the daemon is launched, so the device ID
# is stable and the LaunchAgent doesn't race a first-run key generation.
if [ "$DRY_RUN" = 1 ]; then
    dry "would run: $SYNCTHING_BIN generate --home=$SYNCTHING_HOME (if not already generated)"
else
    if [ ! -d "$SYNCTHING_HOME" ]; then
        step "generating Syncthing config at $SYNCTHING_HOME ..."
        "$SYNCTHING_BIN" generate --home="$SYNCTHING_HOME" >/dev/null 2>&1
    else
        skip "Syncthing config already generated at $SYNCTHING_HOME"
    fi
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
        step "wrote Syncthing LaunchAgent: $SYNCTHING_PLIST"
    fi
fi

# Writing the plist is not enough -- until it is loaded there is no running
# daemon, no REST API on 127.0.0.1:8384, and lane C never syncs at all.
if [ "$DRY_RUN" = 1 ]; then
    dry "would load the Syncthing LaunchAgent and confirm the daemon is running"
else
    if pgrep -qx syncthing 2>/dev/null || pgrep -f "syncthing.*serve" >/dev/null 2>&1; then
        skip "Syncthing daemon already running"
    else
        # bootstrap/gui is the modern form; fall back to `load` on older macOS.
        if launchctl bootstrap "gui/$(id -u)" "$SYNCTHING_PLIST" 2>/dev/null; then
            step "loaded Syncthing LaunchAgent (launchctl bootstrap)"
        elif launchctl load "$SYNCTHING_PLIST" 2>/dev/null; then
            step "loaded Syncthing LaunchAgent (launchctl load)"
        else
            warn "could not load $SYNCTHING_PLIST automatically -- start the daemon by hand with:"
            warn "    launchctl bootstrap gui/\$(id -u) \"$SYNCTHING_PLIST\""
        fi

        # Give it a moment, then confirm rather than assume.
        sleep 2
        if pgrep -qx syncthing 2>/dev/null || pgrep -f "syncthing.*serve" >/dev/null 2>&1; then
            step "Syncthing daemon is running"
        else
            warn "Syncthing daemon does not appear to be running yet -- check 'launchctl list | grep ccsync' and $SYNCTHING_HOME"
        fi
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
            step "wrote companion LaunchAgent: $COMPANION_PLIST"
            # Same trap as the Syncthing agent: a written-but-unloaded plist
            # does nothing until the next logon.
            if launchctl bootstrap "gui/$(id -u)" "$COMPANION_PLIST" 2>/dev/null; then
                step "loaded companion LaunchAgent (launchctl bootstrap)"
            elif launchctl load "$COMPANION_PLIST" 2>/dev/null; then
                step "loaded companion LaunchAgent (launchctl load)"
            else
                warn "could not load $COMPANION_PLIST automatically -- it will start at your next logon, or load it now with:"
                warn "    launchctl bootstrap gui/\$(id -u) \"$COMPANION_PLIST\""
            fi
        fi
    fi
fi

# ----------------------------------------------------------------------
# 6b. Companion config, seeded with what this script already knows
# ----------------------------------------------------------------------
# The companion's own first-run template leaves these blank, which silently
# yields a non-functional install -- notably `remote`, which must match the
# rclone remote name created above.
CCSYNC_CONFIG_DIR="$HOME/.ccsync"
CCSYNC_CONFIG_PATH="$CCSYNC_CONFIG_DIR/config.toml"

if [ -f "$CCSYNC_CONFIG_PATH" ]; then
    skip "companion config already exists: $CCSYNC_CONFIG_PATH"
    step "  confirm these values match, the companion will not fix them for you:"
    echo "      editor_name = \"$EDITOR_NAME\""
    echo "      local_root  = \"$CC_ROOT\""
    echo "      remote      = \"$REMOTE_NAME\""
    echo "      remote_root = \"$REMOTE_ROOT\""
elif [ "$DRY_RUN" = 1 ]; then
    dry "would write seeded companion config to $CCSYNC_CONFIG_PATH"
else
    ensure_dir "$CCSYNC_CONFIG_DIR"
    cat > "$CCSYNC_CONFIG_PATH" <<TOML
# ccsync-companion config -- seeded by macos_bootstrap.sh.
# See companion/README.md for the full reference. Restart the companion
# after editing this file.

editor_name = "$EDITOR_NAME"

# This machine's local copy of the project tree. Resolve's Mapped Mount
# preference must point P:\ here -- see docs/EDITOR_SETUP.md.
local_root = "$CC_ROOT"

# The shared-drive prefix used in Resolve's stored clip paths.
canonical_prefix = "P:\\\\"

# Must match the rclone remote name in ~/.config/rclone/rclone.conf.
remote = "$REMOTE_NAME"

# ABSOLUTE path on the NAS. The SFTP session starts in your home directory,
# so a relative value here would resolve under ~/ and miss the real tree.
remote_root = "$REMOTE_ROOT"

# OPTIONAL. Lanes A and B replicate the whole local_root <-> remote_root
# tree, so every Projects/<year>/<series>/<project> folder syncs whatever
# these say. They only affect two things: active_project is the destination
# the popup fixer suggests for media you add from outside the tree, and
# projects pairs positionally with syncthing_folder_ids for lane C's
# folder-ID check. Example:
#   projects = ["Projects/2026/Creator Profiles/Season 1"]
#   active_project = "Projects/2026/Creator Profiles/Season 1"
projects = []
active_project = ""

poll_interval = 3
scan_interval_up = 300
scan_interval_down = 120
watch_debounce_seconds = 10
transfers = 4

syncthing_url = "http://127.0.0.1:8384"
syncthing_api_key = ""
syncthing_folder_ids = []

rclone_path = "rclone"

log_path = "~/.ccsync/companion.log"
log_level = "INFO"

# Sync dashboard: reporting, managed one-at-a-time sync, and the tray's
# "Open dashboard" link. Tailnet address; token from the admin. Override
# at bootstrap time via DASHBOARD_URL / DASHBOARD_TOKEN env vars.
dashboard_url = "${DASHBOARD_URL:-http://100.71.216.3:8480}"
dashboard_token = "${DASHBOARD_TOKEN:-}"
TOML
    step "wrote seeded companion config: $CCSYNC_CONFIG_PATH"
    step "  the whole project tree syncs as-is; set active_project in that file only if you want popup-fixed media filed into a specific project."
fi

# ----------------------------------------------------------------------
# 7. Print Syncthing device ID
# ----------------------------------------------------------------------
# `syncthing --device-id` was removed in Syncthing v2 (exits 80, "unknown
# flag"). `generate` prints the ID on every run and is safe to re-run against
# an existing home ("Key exists; will not overwrite"), so parse it from
# there, keeping the old flag as a fallback for v1 installs.
device_id_from_generate() {
    "$SYNCTHING_BIN" generate --home="$SYNCTHING_HOME" 2>&1 \
      | grep -oE '[A-Z0-9]{7}(-[A-Z0-9]{7}){7}' \
      | head -n 1
}

device_id_legacy() {
    "$SYNCTHING_BIN" --device-id --home="$SYNCTHING_HOME" 2>/dev/null \
      | grep -oE '[A-Z0-9]{7}(-[A-Z0-9]{7}){7}' \
      | head -n 1
}

step "determining this machine's Syncthing device ID..."
if [ "$DRY_RUN" = 1 ]; then
    dry "would parse the device ID from: $SYNCTHING_BIN generate --home=$SYNCTHING_HOME"
    echo ""
    echo "=================================================================="
    echo " Bootstrap complete (dry run). No changes were made."
    echo "=================================================================="
else
    DEVICE_ID="$(device_id_from_generate)"
    if [ -z "$DEVICE_ID" ]; then
        DEVICE_ID="$(device_id_legacy)"
    fi

    echo ""
    echo "=================================================================="
    echo " Bootstrap complete."
    echo ""
    if [ -z "$DEVICE_ID" ]; then
        warn "could not determine the Syncthing device ID automatically."
        echo " Get it from the Syncthing web UI (http://127.0.0.1:8384)"
        echo " under Actions > Show ID, and send that to the admin."
    else
        echo " Your Syncthing device ID is:"
        echo ""
        echo "     $DEVICE_ID"
        echo ""
        echo " Send this device ID to the admin so they can approve it with"
        echo " server/accept_device.py for each project you're working on."
    fi
    echo ""
    echo " Remaining manual steps (see docs/EDITOR_SETUP.md):"
    echo "   1. tailscale up   (join the tailnet, one-time interactive login)"
    echo "   2. generate an SSH keypair for rclone if you haven't already:"
    echo "        ssh-keygen -t ed25519 -f \"$KEY_FILE_PATH\""
    echo "      and send the .pub file to the admin"
    echo "   3. connect DaVinci Resolve to the Project Server"
    echo "   4. Playback > Proxy Handling > Prefer Proxies"
    echo "   5. Preferences > Media Storage > add $CC_ROOT as a Mapped"
    echo "      Mount for P:\\  (manual, one-time -- see docs/EDITOR_SETUP.md)"
    echo "   6. do NOT mount any NAS share over SMB alongside this -- see the"
    echo "      drive-letter/mount warning in docs/EDITOR_SETUP.md"
    echo "=================================================================="
fi
