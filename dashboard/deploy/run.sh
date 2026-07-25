#!/bin/sh
# Container entrypoint for the ccsync-dashboard TrueNAS custom app.
# Runs inside python:3.12-slim as 3000:3001 with /app (code, read-mostly)
# and /data (SQLite + venv, persistent) mounted from the host.
set -eu

VENV=/data/venv
if [ ! -x "$VENV/bin/python" ]; then
    echo "run.sh: creating venv at $VENV"
    python -m venv "$VENV"
fi
# Editable install: templates/ and static/ resolve relative to /app/src, so
# the package must run from the mount, not a site-packages copy. Cheap no-op
# when already satisfied; picks up dependency changes on redeploy.
"$VENV/bin/pip" install --quiet --no-cache-dir -e /app

exec "$VENV/bin/python" -m uvicorn --factory ccsync_dashboard.app:create_app \
    --host 0.0.0.0 --port "${DASH_PORT:-8480}" --workers 1
