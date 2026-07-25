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

# Authoritative re-probe after every install route. Neither the brew branch
# nor the direct-download branch above set RCLONE_BIN, so without this it
# stays empty on a FRESH install and config.toml gets the unresolvable
# rclone_path = "rclone" that INST-7 is about.
if [ -z "$RCLONE_BIN" ]; then
    if have_cmd rclone; then
        RCLONE_BIN="$(command -v rclone)"
    elif [ -x "$BIN_DIR/rclone" ]; then
        RCLONE_BIN="$BIN_DIR/rclone"
    fi
    if [ -n "$RCLONE_BIN" ]; then
        step "rclone resolved to: $RCLONE_BIN"
    elif [ "$DRY_RUN" != 1 ]; then
        warn "rclone is NOT installed. Lanes A and B -- every video upload and every proxy download -- cannot run on this Mac. Install rclone (brew install rclone, or https://rclone.org/downloads/) and re-run this script."
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
elif [ -z "$SYNCTHING_BIN" ]; then
    # With set -u but no set -e, `"" generate ...` is a silently-ignored
    # "command not found" -- and everything downstream then assumed a config
    # existed. Say so instead.
    warn "Syncthing is not installed, so no Syncthing config was generated."
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

# Returns the first <string> inside a plist's ProgramArguments array, i.e.
# the program the agent actually runs. Empty when it can't be determined.
plist_program() {
    [ -f "$1" ] || return 0
    sed -n '/<key>ProgramArguments<\/key>/,/<\/array>/p' "$1" \
      | grep -o '<string>[^<]*</string>' \
      | head -n 1 \
      | sed -E 's#</?string>##g'
}

# Reload a LaunchAgent we just rewrote. bootout+bootstrap is the modern form;
# unload+load is the fallback on older macOS.
reload_agent() {
    local plist="$1"
    launchctl bootout "gui/$(id -u)" "$plist" >/dev/null 2>&1 || true
    launchctl unload "$plist" >/dev/null 2>&1 || true
    if launchctl bootstrap "gui/$(id -u)" "$plist" 2>/dev/null; then
        return 0
    fi
    launchctl load "$plist" 2>/dev/null
}

# INST-8: a failed brew/curl leaves SYNCTHING_BIN empty (set -u, no set -e),
# and the old code happily wrote a plist whose ProgramArguments[0] was
# <string></string>. Because the guard was "does the file exist", EVERY later
# run -- including one after the editor installed Syncthing by hand -- printed
# "already present" and never repaired it. So: never write a plist with an
# empty program, and make the guard compare the embedded path against the
# binary we found, rewriting and reloading on a mismatch.
SYNCTHING_PLIST_PROGRAM="$(plist_program "$SYNCTHING_PLIST")"
if [ -z "$SYNCTHING_BIN" ]; then
    warn "Syncthing was not installed, so no LaunchAgent was written (an agent with no program to run can never be repaired by a later run of this script)."
    warn "Install Syncthing (brew install syncthing, or https://syncthing.net/downloads/) and re-run this script."
    if [ -f "$SYNCTHING_PLIST" ] && [ -z "$SYNCTHING_PLIST_PROGRAM" ]; then
        warn "Removing the broken agent left by an earlier run: $SYNCTHING_PLIST"
        if [ "$DRY_RUN" != 1 ]; then
            launchctl bootout "gui/$(id -u)" "$SYNCTHING_PLIST" >/dev/null 2>&1 || true
            rm -f "$SYNCTHING_PLIST"
        fi
    fi
elif [ -f "$SYNCTHING_PLIST" ] && [ "$SYNCTHING_PLIST_PROGRAM" = "$SYNCTHING_BIN" ]; then
    skip "Syncthing LaunchAgent already present and correct: $SYNCTHING_PLIST"
else
    if [ -f "$SYNCTHING_PLIST" ]; then
        step "Syncthing LaunchAgent points at '$SYNCTHING_PLIST_PROGRAM' but Syncthing is at '$SYNCTHING_BIN' -- rewriting it"
    fi
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
        # A rewritten plist means launchd is still running the OLD program
        # until the agent is reloaded -- which is the whole point of repairing
        # it (INST-8).
        if reload_agent "$SYNCTHING_PLIST"; then
            step "reloaded the Syncthing LaunchAgent"
        else
            warn "could not reload $SYNCTHING_PLIST -- it will take effect at your next logon, or reload it now with:"
            warn "    launchctl bootout gui/\$(id -u) \"$SYNCTHING_PLIST\"; launchctl bootstrap gui/\$(id -u) \"$SYNCTHING_PLIST\""
        fi
    fi
fi

# Writing the plist is not enough -- until it is loaded there is no running
# daemon, no REST API on 127.0.0.1:8384, and lane C never syncs at all.
if [ "$DRY_RUN" = 1 ]; then
    dry "would load the Syncthing LaunchAgent and confirm the daemon is running"
elif [ -z "$SYNCTHING_BIN" ]; then
    warn "no Syncthing binary -- skipping the daemon start. Lane C (audio, After Effects projects, graphics, subtitles, .drp project files, docs) will not sync on this Mac until Syncthing is installed and this script re-run."
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
existing_host=""
existing_user=""
if [ -f "$RCLONE_CONF_PATH" ] && grep -qF "[$REMOTE_NAME]" "$RCLONE_CONF_PATH"; then
    has_section=1
    # Read host/user from THIS stanza only: awk from its header to the next
    # bracketed header (or EOF).
    existing_host="$(awk -v sect="[$REMOTE_NAME]" '
        $0 == sect { inside=1; next }
        /^\[/      { inside=0 }
        inside && /^[[:space:]]*host[[:space:]]*=/ {
            sub(/^[[:space:]]*host[[:space:]]*=[[:space:]]*/, ""); print; exit
        }' "$RCLONE_CONF_PATH")"
    existing_user="$(awk -v sect="[$REMOTE_NAME]" '
        $0 == sect { inside=1; next }
        /^\[/      { inside=0 }
        inside && /^[[:space:]]*user[[:space:]]*=/ {
            sub(/^[[:space:]]*user[[:space:]]*=[[:space:]]*/, ""); print; exit
        }' "$RCLONE_CONF_PATH")"
fi

if [ "$has_section" = 1 ] && [ "$existing_host" = "$TAILNET_HOST" ] && [ "$existing_user" = "$EDITOR_NAME" ]; then
    skip "rclone.conf already has a correct [$REMOTE_NAME] section: $RCLONE_CONF_PATH"
elif [ "$has_section" = 1 ]; then
    # INST-17: the single most likely reason to re-run this script is a
    # typo'd --editor-name, and skipping the whole stanza whenever the
    # section exists made that re-run a silent no-op for the one file that
    # carries the username. Rewrite this stanza in place; every other remote
    # in the file is preserved.
    warn "rclone.conf's [$REMOTE_NAME] disagrees with the values you passed:"
    warn "  host: '$existing_host' -> '$TAILNET_HOST'"
    warn "  user: '$existing_user' -> '$EDITOR_NAME'"
    if [ "$DRY_RUN" = 1 ]; then
        dry "would rewrite the [$REMOTE_NAME] stanza in $RCLONE_CONF_PATH (other remotes untouched):"
        echo "$STANZA"
    else
        RCLONE_TMP="$(mktemp "${RCLONE_CONF_PATH}.ccsync.XXXXXX")"
        awk -v sect="[$REMOTE_NAME]" -v stanza="$STANZA" '
            $0 == sect { inside=1; printf "%s\n", stanza; next }
            inside && /^\[/ { inside=0 }
            !inside { print }
        ' "$RCLONE_CONF_PATH" > "$RCLONE_TMP"
        # Same permissions as the file we are replacing; rclone.conf can hold
        # credentials for other remotes.
        chmod 600 "$RCLONE_TMP"
        mv "$RCLONE_TMP" "$RCLONE_CONF_PATH"
        step "rewrote the [$REMOTE_NAME] stanza in $RCLONE_CONF_PATH (host=$TAILNET_HOST, user=$EDITOR_NAME)"
    fi
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
COMPANION_MISSING=0
if [ ! -e "$COMPANION_APP_PATH" ]; then
    # INST-6: this used to be one skippable WARNING line in the middle of an
    # otherwise successful-looking run that ended with "Bootstrap complete"
    # and a device ID -- so a Mac editor reasonably concluded they were set
    # up. They are not: without the companion there are NO sync lanes, no
    # popup fixer, no dashboard reporting and no project selection on this
    # machine. Say that unmissably.
    COMPANION_MISSING=1
    echo ""
    warn "**********************************************************************"
    warn "THE SYNC APP IS NOT INSTALLED ON THIS MAC."
    warn ""
    warn "No companion app was found at:"
    warn "    $COMPANION_APP_PATH"
    warn ""
    warn "That app is what actually syncs. Without it, NOTHING on this Mac will:"
    warn "  - upload your camera originals to the NAS      (lane A)"
    warn "  - download proxies from the NAS                (lane B)"
    warn "  - sync audio / AE / graphics / subtitles / .drp (lane C)"
    warn "  - report status to the dashboard, or let you pick projects"
    warn ""
    warn "A macOS build of the companion is NOT SHIPPED YET. Everything this"
    warn "script configured (Tailscale, rclone, Syncthing, the rclone remote)"
    warn "is real and correct, but this Mac cannot sync on its own until the"
    warn "app exists. Tell Alex you ran this on a Mac before you rely on it."
    warn "**********************************************************************"
    echo ""
else
    COMPANION_PLIST_PROGRAM="$(plist_program "$COMPANION_PLIST")"
    # The companion agent runs `open -a <app>`, so ProgramArguments[0] is
    # "open" and the app path is the third element. Compare that instead.
    COMPANION_PLIST_APP=""
    if [ -f "$COMPANION_PLIST" ]; then
        COMPANION_PLIST_APP="$(sed -n '/<key>ProgramArguments<\/key>/,/<\/array>/p' "$COMPANION_PLIST" \
            | grep -o '<string>[^<]*</string>' | sed -E 's#</?string>##g' | sed -n '3p')"
    fi
    if [ -f "$COMPANION_PLIST" ] && [ -n "$COMPANION_PLIST_PROGRAM" ] && [ "$COMPANION_PLIST_APP" = "$COMPANION_APP_PATH" ]; then
        skip "companion LaunchAgent already present and correct: $COMPANION_PLIST"
    else
        if [ -f "$COMPANION_PLIST" ]; then
            step "companion LaunchAgent points at '$COMPANION_PLIST_APP' but the app is at '$COMPANION_APP_PATH' -- rewriting it"
        fi
        if [ "$DRY_RUN" = 1 ]; then
            dry "would write LaunchAgent plist: $COMPANION_PLIST (runs open -a $COMPANION_APP_PATH)"
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
            # does nothing until the next logon, and a REWRITTEN one leaves
            # launchd running the old program until it is booted out first.
            if reload_agent "$COMPANION_PLIST"; then
                step "loaded companion LaunchAgent"
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

# rclone_path must be absolute (see the config below). Fall back to the bare
# name only when rclone genuinely isn't installed -- there is nothing better
# to write, and the companion's own error message is then accurate.
RCLONE_PATH_VALUE="$RCLONE_BIN"
if [ -z "$RCLONE_PATH_VALUE" ]; then
    RCLONE_PATH_VALUE="rclone"
    warn "rclone was not found, so config.toml gets rclone_path = \"rclone\" -- lanes A and B will not work until rclone is installed and this script re-run."
fi

if [ -f "$CCSYNC_CONFIG_PATH" ]; then
    skip "companion config already exists: $CCSYNC_CONFIG_PATH"
    if [ "$DRY_RUN" != 1 ]; then
        # Repair permissions on a config an older run wrote under the default
        # umask -- it holds the fleet dashboard_token (SEC-14).
        chmod 700 "$CCSYNC_CONFIG_DIR" 2>/dev/null || true
        chmod 600 "$CCSYNC_CONFIG_PATH" 2>/dev/null || true
    fi
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

# ABSOLUTE path, not the bare name "rclone". The companion is started by a
# LaunchAgent, and launchd gives it PATH=/usr/bin:/bin:/usr/sbin:/sbin --
# neither /opt/homebrew/bin nor ~/.local/ccsync/bin is on it, so
# rclone_available()'s shutil.which("rclone") fails and lanes A/B report
# "rclone not found on PATH" forever (INST-7).
rclone_path = "$RCLONE_PATH_VALUE"

log_path = "~/.ccsync/companion.log"
log_level = "INFO"

# Sync dashboard: reporting, managed one-at-a-time sync, and the tray's
# "Open dashboard" link. Tailnet address; token from the admin. Override
# at bootstrap time via DASHBOARD_URL / DASHBOARD_TOKEN env vars.
dashboard_url = "${DASHBOARD_URL:-http://100.71.216.3:8480}"
dashboard_token = "${DASHBOARD_TOKEN:-}"
TOML
    # SEC-14: this file carries the fleet dashboard_token, and `cat >` uses
    # the default umask (world-readable on a stock Mac). Lock down both the
    # file and the directory -- ~/.ccsync also holds identity.json.
    chmod 700 "$CCSYNC_CONFIG_DIR" 2>/dev/null || warn "could not chmod 700 $CCSYNC_CONFIG_DIR"
    chmod 600 "$CCSYNC_CONFIG_PATH" 2>/dev/null || warn "could not chmod 600 $CCSYNC_CONFIG_PATH"
    step "wrote seeded companion config: $CCSYNC_CONFIG_PATH (mode 600, dir 700 -- it holds the dashboard token)"
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
    DEVICE_ID=""
    if [ -n "$SYNCTHING_BIN" ]; then
        DEVICE_ID="$(device_id_from_generate)"
        if [ -z "$DEVICE_ID" ]; then
            DEVICE_ID="$(device_id_legacy)"
        fi
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
        echo " Send this device ID to Alex so he can approve this machine on"
        echo " the dashboard. There is no per-project sharing step for you to"
        echo " do -- once you're approved, ticking a project on the dashboard"
        echo " is what shares it."
    fi
    echo ""
    echo " Remaining manual steps (see docs/EDITOR_SETUP.md):"
    echo "   1. tailscale up   (join the tailnet, one-time interactive login)"
    echo "   2. generate an SSH keypair for rclone if you haven't already:"
    echo "        ssh-keygen -t ed25519 -f \"$KEY_FILE_PATH\""
    echo "      and send the .pub file to the admin"
    echo "   3. SIGN IN: right-click the CCSync menu-bar icon and choose"
    echo "      \"Sign in...\", using the SAME TrueNAS username and password"
    echo "      Alex gave you. NOTHING SYNCS UNTIL YOU DO THIS -- signing in"
    echo "      on the dashboard WEBSITE is not the same thing."
    echo "   4. connect DaVinci Resolve to the Project Server"
    echo "   5. Playback > Proxy Handling > Prefer Proxies"
    echo "   6. Preferences > Media Storage > add $CC_ROOT as a Mapped"
    echo "      Mount for P:\\  (manual, one-time -- see docs/EDITOR_SETUP.md)"
    echo "   7. do NOT mount any NAS share over SMB alongside this -- see the"
    echo "      drive-letter/mount warning in docs/EDITOR_SETUP.md"
    echo "=================================================================="

    # Last line seen, so the one thing that invalidates everything above
    # cannot scroll away (INST-6).
    if [ "$COMPANION_MISSING" = 1 ]; then
        echo ""
        warn "REMINDER: the sync app is NOT installed on this Mac (see the block"
        warn "above). Tailscale, rclone, Syncthing and the rclone remote are all"
        warn "configured -- but nothing will sync by itself, and step 3 above has"
        warn "no menu-bar icon to right-click yet. Do not report yourself ready."
        echo ""
    fi
fi
