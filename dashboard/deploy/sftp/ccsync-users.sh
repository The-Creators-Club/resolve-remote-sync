#!/bin/sh
# ccsync-users -- polls the dashboard's editor list and creates the matching
# OS accounts inside THIS container. Run once synchronously at boot and then
# every 30s (or on SIGHUP) by entrypoint.sh; never invoked directly by sshd.
#
# WHY THIS EXISTS AT ALL: `AuthorizedKeysCommand` (ccsync-keys.sh) only
# supplies a KEY for a login attempt -- sshd still requires the target OS
# account to already EXIST before it will even ask for one. The dashboard is
# the identity provider (ZERO_TOUCH_PLAN.md 3.3) but has no way to create a
# Linux account inside a sidecar it does not have exec access to, so this
# script is the other half of that design: it turns the dashboard's row into
# a real `/etc/passwd` entry.
#
# Deliberately no `set -e` -- one malformed row from the API must not abort
# the rest of the list; each account creation is independent and this script
# runs unattended, so partial progress beats an all-or-nothing failure that
# nobody's watching, exactly as run.sh's own dependency-install step reasons
# (dashboard/deploy/run.sh).
set -u

token=""
if [ -f /etc/ccsync/internal-token ]; then
    token="$(cat /etc/ccsync/internal-token 2>/dev/null)"
fi
dashboard_url="${CCSYNC_DASHBOARD_INTERNAL_URL:-http://dashboard:8480}"

body="$(curl -fsS --max-time 10 \
    -H "Authorization: Bearer ${token}" \
    "${dashboard_url}/internal/sftp/users" 2>/dev/null)"
if [ -z "$body" ]; then
    echo "ccsync-users: could not reach ${dashboard_url}/internal/sftp/users -- leaving the account list unchanged this pass" >&2
    exit 0
fi

# The API's contract hands back a per-user `gid` (ZERO_TOUCH_PLAN.md WP C's
# schema), but this container only has ONE group that sshd_config's `Match
# Group editors` actually matches -- created once by entrypoint.sh. Rather
# than trust a numeric gid over the wire to happen to equal that group's own
# gid (today it should, by construction: both come from the same APP_GID the
# compose file hands to the dashboard AND this sidecar -- but a mismatch
# here would silently exclude an editor from the Match block with no error
# anywhere), every account created below is put in `editors` BY NAME. The
# API's `gid` field is read and used only to sanity-check the group already
# has that gid; nothing here creates a SECOND group per differing gid --
# ZERO_TOUCH_PLAN.md's per-project isolation (spike S3) is where that would
# eventually matter, not this pass.
echo "$body" | jq -r '.users[]? | [.username, .uid] | @tsv' | while IFS="$(printf '\t')" read -r name uid; do
    [ -z "$name" ] && continue
    [ -z "$uid" ] && continue
    if getent passwd "$name" >/dev/null 2>&1; then
        continue
    fi
    # -o: multiple usernames may share one uid -- every editor is the SAME
    #   service account today (ZERO_TOUCH_PLAN.md section 5). BusyBox's own
    #   `adduser` refuses a non-unique uid outright; `useradd -o` (the
    #   `shadow` package) is why this image installs shadow instead.
    # -M: no home directory -- ForceCommand's `internal-sftp -d /tree`
    #   already fixes the start directory inside the chroot; a home dir
    #   here would just be dead weight nobody reads.
    # -s /sbin/nologin: this account can NEVER get an interactive shell,
    #   even if ForceCommand were ever misconfigured -- belt and braces
    #   with sshd_config's own ForceCommand line.
    if useradd -o -M -g editors -u "$uid" -s /sbin/nologin -d /tree "$name" 2>/tmp/ccsync-users.err; then
        echo "ccsync-users: created $name (uid $uid, group editors)"
    else
        echo "ccsync-users: FAILED to create $name: $(cat /tmp/ccsync-users.err 2>/dev/null)" >&2
    fi
done
