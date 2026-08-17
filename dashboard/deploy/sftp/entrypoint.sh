#!/bin/sh
# Entrypoint for the ccsync-sftp sidecar (dashboard/deploy/sftp/Dockerfile).
# Runs as root inside Alpine -- this container OWNS the tree mount and the
# accounts it creates, so account/tree ownership is its own business
# (ZERO_TOUCH_PLAN.md 3.1). See README.md in this directory for the chroot
# layout, the uid model and why host keys persist.
set -eu

# The internal API's bearer token. Two sources so this works both with a
# plain compose `environment:` (dev, or a customer who typed it into a
# .env) and with a mounted docker/swarm secret file
# (CCSYNC_INTERNAL_TOKEN_FILE=/run/secrets/ccsync_internal_token) --
# compose.appliance.yaml uses the file form via the dashboard-written
# secrets env_file (dashboard/deploy/compose.appliance.yaml's own comment
# explains why env_file rather than a literal value).
#
# Written to a FILE under /etc/ccsync rather than left in this process's own
# environment: `AuthorizedKeysCommand` runs with an environment sshd itself
# sanitizes -- it does NOT inherit this process's env vars -- so
# ccsync-keys.sh (run as `AuthorizedKeysCommandUser sftpkeys`) has to read
# the token from somewhere that survives that sanitisation.
#
# `0440 root:sftpkeys`, NOT world-readable: an earlier draft of this file
# made the token file `644` and ran the command as `nobody`, which means
# EVERY unprivileged process in the container -- not just this one script --
# could read it. `sftpkeys` (created in the Dockerfile) is a dedicated
# account that exists for nothing else, matching the spike's own verdict
# (docs/spikes/zero-touch-spikes-2026-08-17.md S2: "give the sidecar a
# dedicated `sftpkeys` user rather than `nobody`, and mount the token
# `0440 root:sftpkeys`").
TOKEN=""
if [ -n "${CCSYNC_INTERNAL_TOKEN_FILE:-}" ] && [ -f "$CCSYNC_INTERNAL_TOKEN_FILE" ]; then
    TOKEN="$(cat "$CCSYNC_INTERNAL_TOKEN_FILE")"
elif [ -n "${CCSYNC_INTERNAL_TOKEN:-}" ]; then
    TOKEN="$CCSYNC_INTERNAL_TOKEN"
fi
if [ -z "$TOKEN" ]; then
    echo "entrypoint: WARNING: no CCSYNC_INTERNAL_TOKEN(_FILE) set." >&2
    echo "entrypoint: WARNING: every call to the dashboard's internal API will 401/403," >&2
    echo "entrypoint: WARNING: so no editor can authenticate and no account will be created." >&2
    echo "entrypoint: WARNING: this is the FAIL-CLOSED default, not a crash -- fix the token and restart." >&2
fi
mkdir -p /etc/ccsync
printf '%s' "$TOKEN" > /etc/ccsync/internal-token
chown root:sftpkeys /etc/ccsync/internal-token
chmod 440 /etc/ccsync/internal-token

# --- host keys: generate once, persist forever ------------------------
# /etc/ssh/keys is the volume (compose:
# ${CCSYNC_DATA}/sftp-hostkeys:/etc/ssh/keys). A regenerated host key makes
# every editor's rclone refuse the NAS on its next connection (known_hosts
# mismatch) -- checking for an EXISTING key before generating one is the
# whole point of this being first in the script, ahead of anything that
# could plausibly fail and restart the container mid-boot.
mkdir -p /etc/ssh/keys
if [ ! -f /etc/ssh/keys/ssh_host_ed25519_key ]; then
    echo "entrypoint: generating ed25519 host key (first boot for this data volume)"
    ssh-keygen -q -t ed25519 -f /etc/ssh/keys/ssh_host_ed25519_key -N "" -C "ccsync-sftp"
fi
if [ ! -f /etc/ssh/keys/ssh_host_rsa_key ]; then
    echo "entrypoint: generating rsa host key (first boot for this data volume)"
    ssh-keygen -q -t rsa -b 4096 -f /etc/ssh/keys/ssh_host_rsa_key -N "" -C "ccsync-sftp"
fi
chmod 700 /etc/ssh/keys
chmod 600 /etc/ssh/keys/ssh_host_ed25519_key /etc/ssh/keys/ssh_host_rsa_key

# sshd itself needs /run for its pid file / privsep dir; Alpine's package
# does not pre-create it.
mkdir -p /run/sshd

# --- the jail --------------------------------------------------------
# ChrootDirectory's StrictModes check requires /jail itself (and every
# directory above it) to be root:root, not group/other-writable. The
# Dockerfile already sets this once; re-asserting it here is cheap
# insurance against a bind mount or a base-image change silently altering
# it -- an editor whose login fails StrictModes just sees "Connection
# reset", with nothing sshd logs pointing at the actual cause.
chown root:root /jail
chmod 755 /jail

# --- the `editors` group -----------------------------------------------
# Every OS account ccsync-users.sh creates is a member of ONE group so
# sshd_config's `Match Group editors` block applies to all of them --
# ZERO_TOUCH_PLAN.md section 5's "single service uid" decision, and the
# reason ccsync-users.sh does not trust the API's own per-user `gid` field
# for group membership (see that script's own comment).
APP_GID="${APP_GID:-3001}"
if ! getent group editors >/dev/null 2>&1; then
    addgroup -g "$APP_GID" editors
fi

# One synchronous pass before sshd opens its listener, so the very first
# connection an editor makes after this container starts already has an
# account to land in -- not just from the second 30s tick.
/usr/local/bin/ccsync-users || echo "entrypoint: WARNING: initial ccsync-users pass failed; retrying on the 30s loop" >&2

# Background poll: sshd needs the OS account to EXIST for a session to open
# at all (AuthorizedKeysCommand only supplies the KEY, not the account --
# see README.md "uid model"), and nothing else in this container is told
# when the dashboard's editor list changes. `kill -HUP <container>` runs it
# immediately instead of waiting out the tick, for an admin who just
# invited someone and does not want to explain a 30-second wait.
( while true; do
    sleep 30
    /usr/local/bin/ccsync-users || true
done ) &
LOOP_PID=$!

trap '/usr/local/bin/ccsync-users || true' HUP
trap 'kill "$SSHD_PID" "$LOOP_PID" 2>/dev/null || true; exit 0' TERM INT

/usr/sbin/sshd -D -e &
SSHD_PID=$!

# Loop rather than a bare `wait`: a delivered HUP interrupts `wait` in
# BusyBox ash (same as dash/bash) before the child has actually exited, so a
# single `wait $SSHD_PID` would return early on the FIRST admin-triggered
# refresh and the script -- PID 1 -- would exit under it, taking sshd down
# with it. Checking `kill -0` re-enters `wait` until sshd itself is
# actually gone.
while kill -0 "$SSHD_PID" 2>/dev/null; do
    wait "$SSHD_PID" 2>/dev/null || true
done
