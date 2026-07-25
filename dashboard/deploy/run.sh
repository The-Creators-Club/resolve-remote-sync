#!/bin/sh
# Container entrypoint for the ccsync-dashboard TrueNAS custom app.
# Runs inside python:3.12-slim as 3000:3001 with /app (code, READ-ONLY)
# and /data (SQLite + venv, persistent) mounted from the host.
set -eu

VENV=/data/venv
REQS=/app/deploy/requirements.txt
STAMP=$VENV/.requirements-hash

if [ ! -x "$VENV/bin/python" ]; then
    echo "run.sh: creating venv at $VENV"
    python -m venv "$VENV"
fi

# Dependencies only, and only when requirements.txt changes. Two constraints
# drive this shape: /app is mounted read-only (a group-writable code mount
# was an editor->NAS-admin escalation, AUDIT C-1), which rules out
# `pip install -e /app` (it writes egg-info into the source tree); and a
# container boot must not depend on PyPI being reachable -- under `set -e`
# a pip network failure would crash-loop the app on every restart.
want="$(md5sum "$REQS" | cut -d' ' -f1)"
have="$(cat "$STAMP" 2>/dev/null || true)"
if [ "$want" != "$have" ]; then
    echo "run.sh: installing dependencies from $REQS"
    "$VENV/bin/pip" install --quiet --no-cache-dir -r "$REQS"
    printf '%s' "$want" > "$STAMP"
fi

# The package runs straight off the read-only mount; templates/ and static/
# resolve relative to /app/src exactly as they did under the old editable
# install (which left a path entry pointing at the same directory).
export PYTHONPATH=/app/src

exec "$VENV/bin/python" -m uvicorn --factory ccsync_dashboard.app:create_app \
    --host 0.0.0.0 --port "${DASH_PORT:-8480}" --workers 1
