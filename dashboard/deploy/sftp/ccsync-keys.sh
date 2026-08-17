#!/bin/sh
# ccsync-keys -- sshd_config's `AuthorizedKeysCommand /usr/local/bin/ccsync-keys %u`.
#
# Runs as `AuthorizedKeysCommandUser nobody`, once PER CONNECTION ATTEMPT,
# with an environment sshd itself sanitizes (it does NOT inherit this
# container's own env vars -- see entrypoint.sh's comment on why the token
# lives in a file instead). Deliberately has NO `set -e`: every failure mode
# here must fall through to "print nothing, exit 0" rather than abort,
# because sshd treats a nonzero exit or noisy stderr as a LOGGED WARNING on
# every single connection attempt, and a flaky dashboard must not turn into
# a log flood or (worse) a hung sshd waiting on this script.
#
# Contract (owned by the dashboard side, ZERO_TOUCH_PLAN.md WP C):
#   GET /internal/sftp/keys/<username>   text/plain authorized_keys lines
#   Authorization: Bearer <CCSYNC_INTERNAL_TOKEN>
#   404 for an unknown user; EMPTY BODY (200) for a user with no keys yet.
# Both "unknown" and "no keys" end up printing nothing here, which is
# correct -- either way, this login has no valid public key and openssh's
# own pubkey verification (not this script) is what actually refuses it.

user="${1:-}"
if [ -z "$user" ]; then
    exit 0
fi

token=""
if [ -f /etc/ccsync/internal-token ]; then
    token="$(cat /etc/ccsync/internal-token 2>/dev/null)"
fi

dashboard_url="${CCSYNC_DASHBOARD_INTERNAL_URL:-http://dashboard:8480}"

# -f: a non-2xx response (404 unknown user, 5xx a dashboard blip) becomes a
# curl failure with NO stdout, which is exactly "print nothing" -- never a
# half-written authorized_keys line. --max-time: a wedged dashboard must not
# hang this editor's login forever; sshd itself has no timeout on this
# command.
curl -fsS --max-time 5 \
    -H "Authorization: Bearer ${token}" \
    "${dashboard_url}/internal/sftp/keys/${user}" 2>/dev/null

exit 0
