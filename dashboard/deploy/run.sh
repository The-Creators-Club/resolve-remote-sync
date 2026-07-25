#!/bin/sh
# Container entrypoint for the ccsync-dashboard TrueNAS custom app.
# Runs inside python:3.12-slim as 3000:3001 with /app (code, READ-ONLY),
# /venv (the dependency venv, uid-3000-only) and /data (SQLite + packages,
# persistent) mounted from the host.
set -eu

# The venv is its OWN volume, NOT a directory inside /data (AUDIT C-2).
# /data used to be 3000:3001 mode 770 -- group `editors`, and every editor
# has a real shell account on the NAS -- while this line execs
# $VENV/bin/python out of it, guarded by nothing but an md5 stamp file
# sitting in the same writable directory. Any editor could replace
# /data/venv/bin/python (or any module under site-packages) and get
# arbitrary code execution as the dashboard user, in a container holding
# TRUENAS_PW. /data is now 3000:3000 770 and the venv lives at /venv,
# 3000:3000 mode 700: nothing but the dashboard's own uid can write either.
VENV=/venv
REQS=/app/deploy/requirements.txt
STAMP=$VENV/.requirements-hash

if [ ! -d "$VENV" ]; then
    echo "run.sh: FATAL: $VENV is not mounted. Re-run server/install_dashboard_app.py" >&2
    echo "run.sh: (--recreate) so the app gets the dedicated venv volume." >&2
    exit 1
fi

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

# Anything this process creates under /data (dashboard.db, the WAL, and
# packages/) stays owner-only: the process's effective GID is 3001
# (editors, needed for the setgid /projects tree), so a default umask would
# hand the editors group read -- and, with 664, write -- on the database.
umask 077

# The package runs straight off the read-only mount; templates/ and static/
# resolve relative to /app/src exactly as they did under the old editable
# install (which left a path entry pointing at the same directory).
export PYTHONPATH=/app/src

exec "$VENV/bin/python" -m uvicorn --factory ccsync_dashboard.app:create_app \
    --host 0.0.0.0 --port "${DASH_PORT:-8480}" --workers 1
