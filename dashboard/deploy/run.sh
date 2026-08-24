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

# The uid:gid this container is SUPPOSED to run as, from site.toml via compose
# (APP_UID/APP_GID). Advisory only, and deliberately not fatal: an unprivileged
# container cannot setuid, so there is nothing to do about a mismatch except say
# so -- but saying so is worth a lot, because the symptom otherwise is silent
# and delayed. Everything this process writes into /projects, /broll-data and
# /music-share lands owned by whatever uid it actually has, and a wrong one
# means editors browsing those shares over SMB see files they cannot open. DSM
# assigns uids >= 1026 rather than letting you pick 3000, so this is exactly the
# knob a second site gets wrong (2026-08-17, COMMERCIAL_READINESS.md item 12).
if [ -n "${APP_UID:-}" ] && [ "$(id -u)" != "$APP_UID" ]; then
    echo "run.sh: WARNING: running as uid $(id -u), but APP_UID says $APP_UID." >&2
    echo "run.sh: WARNING: files written into the tree will have the WRONG owner." >&2
    echo "run.sh: WARNING: fix compose's \`user:\` line (site.toml [stack] uid/gid)." >&2
fi
if [ -n "${APP_GID:-}" ] && [ "$(id -g)" != "$APP_GID" ]; then
    echo "run.sh: WARNING: running as gid $(id -g), but APP_GID says $APP_GID." >&2
    echo "run.sh: WARNING: the setgid /projects tree needs the editors group." >&2
fi

# requirements.txt is the hand-maintained FLOOR list; requirements.lock is what
# `uv pip compile --universal --generate-hashes` resolved from it, and it is
# what dashboard/deploy/Dockerfile installs. Prefer the lock, and install it
# with --require-hashes so a compromised or typo-squatted mirror is an install
# failure rather than a shipped backdoor (2026-08-17, COMMERCIAL_READINESS.md
# item 13).
#
# The fallback is not vestigial: a site whose /app predates the lock -- a
# rollback to an older code tree, or a hand-assembled install -- still boots on
# the floors. Whichever file is chosen is also the one the md5 stamp below is
# taken from, so switching between them re-runs pip exactly once.
REQS=/app/deploy/requirements.txt
PIP_HASH_FLAG=""
if [ -f /app/deploy/requirements.lock ]; then
    REQS=/app/deploy/requirements.lock
    PIP_HASH_FLAG=--require-hashes
fi
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
#
# A pip failure is NOT fatal once the venv has been populated at least once.
# `set -e` plus an unconditional pip step meant a PyPI blip (or a DNS wobble on
# the NAS) crash-looped the whole fleet dashboard on every restart -- the one
# service that tells everyone whether their footage is syncing -- because two
# optional b-roll dependencies could not be re-fetched. The old deps are still
# installed and still work; run with them and shout. The FIRST boot still
# fails hard, because then there is genuinely nothing to run.
want="$(md5sum "$REQS" | cut -d' ' -f1)"
have="$(cat "$STAMP" 2>/dev/null || true)"
# IMAGE MODE (dashboard/deploy/Dockerfile, 2026-08-17): /venv is a layer, not a
# bind mount, and the Dockerfile already installed this exact lockfile with
# --require-hashes. The stamp file cannot be there -- it belongs to the host
# volume this mode does not have -- so without this the container would try to
# pip-install on every single boot, against a registry it may not be allowed to
# reach. Marker rather than "is /venv writable?": the answer to that question is
# also "no" for a broken mount, which must still fail loudly.
if [ -f "$VENV/.image-baked" ]; then
    have="$want"
fi
if [ "$want" != "$have" ]; then
    echo "run.sh: installing dependencies from $REQS"
    if "$VENV/bin/pip" install --quiet --no-cache-dir $PIP_HASH_FLAG -r "$REQS"; then
        printf '%s' "$want" > "$STAMP"
    elif [ -n "$have" ]; then
        echo "run.sh: WARNING: dependency install FAILED (PyPI unreachable?)." >&2
        echo "run.sh: WARNING: starting with the previously installed dependencies;" >&2
        echo "run.sh: WARNING: anything added to requirements.txt since is MISSING." >&2
    else
        echo "run.sh: FATAL: dependency install failed and this venv has never been" >&2
        echo "run.sh: populated -- there is nothing to run. Check network/PyPI access." >&2
        exit 1
    fi
fi

# The YouTube "unblock" plugin (bgutil-ytdlp-pot-provider, GPLv3), installed
# into this SAME /venv but ONLY when this site turned the feature on
# (2026-08-17, docs/COMMERCIAL_READINESS.md items 2/3, CI run 32041222871's
# licence gate). DASH_SITE_YOUTUBE_UNBLOCK is compose_config()'s existing,
# always-present "0"/"1" signal (published to every companion by
# GET /api/v1/site) -- reused here rather than inventing a second env var for
# the same fact. Moved OUT of the base requirements.lock/Dockerfile image for
# exactly this reason: a base lock that always carried a GPLv3
# anti-anti-automation package conveyed it to every customer whether or not
# they ever enabled `youtube_unblock`.
#
# UNLIKE the base install above, a failure here is NEVER fatal to the
# container, not even on a genuine first boot: this dependency serves one
# optional feature (docs/YTDL_LOCAL_DOWNLOAD.md's PO-token path), and the
# dashboard -- "the one service that tells everyone whether their footage is
# syncing" -- must keep booting either way. An unmet dependency degrades
# `/ytdl` exactly the way an unmounted /opt/deno already does: a clean
# bot-check failure, not a crash.
#
# NOTE for image mode (dashboard/deploy/Dockerfile): this lock is
# deliberately NOT baked into the image, for the same reason ffmpeg/deno/the
# Claude CLI are not (docs/DOCKER.md, "What image mode does NOT bake in") --
# so `.image-baked` does NOT short-circuit this block the way it does the
# base install above. A site that flips `youtube_unblock` on under image mode
# needs PyPI reachable from the container at the NEXT boot after the flag
# changes, same as bind-mount mode always has. (A dedicated `ccsync-unblock`
# image layer that bakes this in too is future work, not done here.)
if [ "${DASH_SITE_YOUTUBE_UNBLOCK:-0}" = "1" ]; then
    REQS_UNBLOCK=/app/deploy/requirements-unblock.txt
    PIP_HASH_FLAG_UNBLOCK=""
    if [ -f /app/deploy/requirements-unblock.lock ]; then
        REQS_UNBLOCK=/app/deploy/requirements-unblock.lock
        PIP_HASH_FLAG_UNBLOCK=--require-hashes
    fi
    STAMP_UNBLOCK=$VENV/.requirements-unblock-hash
    want_unblock="$(md5sum "$REQS_UNBLOCK" | cut -d' ' -f1)"
    have_unblock="$(cat "$STAMP_UNBLOCK" 2>/dev/null || true)"
    if [ "$want_unblock" != "$have_unblock" ]; then
        echo "run.sh: youtube_unblock is on -- installing $REQS_UNBLOCK"
        # RETRIED with short sleeps (CR-73, 2026-08-24): the only failure seen
        # in the field was this install running in the container's first
        # seconds, before its network/DNS was usable -- it failed once per
        # boot, on both recorded boots, and the worker then ran for DAYS with
        # no PO-token provider. YouTube withholds the https formats without
        # one, so every server download crawled through the throttled HLS
        # ladder (~1.8 MiB/s) or ended "The downloaded file is empty", while
        # nothing looked wrong but one boot-time WARNING nobody was watching.
        unblock_ok=""
        for unblock_delay in 5 15 30 0; do
            if "$VENV/bin/pip" install --quiet --no-cache-dir $PIP_HASH_FLAG_UNBLOCK -r "$REQS_UNBLOCK"; then
                printf '%s' "$want_unblock" > "$STAMP_UNBLOCK"
                unblock_ok=1
                break
            fi
            if [ "$unblock_delay" != "0" ]; then
                echo "run.sh: unblock install failed -- retrying in ${unblock_delay}s" >&2
                sleep "$unblock_delay"
            fi
        done
        if [ -z "$unblock_ok" ]; then
            echo "run.sh: WARNING: youtube_unblock dependency install FAILED" >&2
            echo "run.sh: WARNING: (PyPI unreachable?). /ytdl's PO-token path will" >&2
            echo "run.sh: WARNING: bot-check-fail until this succeeds; everything" >&2
            echo "run.sh: WARNING: else keeps running." >&2
        fi
    fi
fi

# Anything this process creates under /data (dashboard.db, the WAL, and
# packages/) stays owner-only: the process's effective GID is 3001
# (editors, needed for the setgid /projects tree), so a default umask would
# hand the editors group read -- and, with 664, write -- on the database.
#
# CAVEAT, /broll-data: this umask also applies to the b-roll data root, which
# unlike /data is the SHARED ARCHIVE editors browse over SMB as
# P:\Assets\B-roll Archive. Anything the b-roll app creates there lands 0700 /
# 0600 owned by uid 3000, i.e. invisible to editors. install_dashboard_app.py
# therefore pre-creates proxies/, sprites/, posters/ and sheets/ as
# broll:editors 2770 (setgid), and mkdir(exist_ok=True) leaves an existing
# directory's mode alone -- so the browsable tree keeps the same posture as
# Projects/. Only broll.db and files created below those dirs stay owner-only,
# which is correct for the database and UNVERIFIED for future subdirectories
# the app may add: NOT confirmed against the dataset's NFSv4 ACLs
# (aclmode=restricted can ignore chmod outright). Check on the NAS before
# relying on the mode bits above.
umask 077

# The package runs straight off the read-only mount; templates/ and static/
# resolve relative to /app/src exactly as they did under the old editable
# install (which left a path entry pointing at the same directory).
# /broll-app is the repo's broll/web tree, /music-app is its music/web tree and
# /ytdl-app is its ytdl/web tree, all mounted read-only. All are on the path
# unconditionally: the mounts are gated (DASH_BROLL_ENABLED, and for music and
# ytdl by whether the installer shipped the tree at all) and
# ccsync_dashboard.broll / .music / .ytdl each guard the import, so a path entry
# pointing at a volume that is not mounted costs nothing. Every root must be
# here -- an empty PYTHONPATH entry is how /music came to report "absent"
# behind a green healthcheck.
#
# The three trees are top-level packages `app` (b-roll), `musicweb` (music) and
# `ytdlweb` (ytdl). They are deliberately NOT all called `app`: two top-level
# packages of the same name on one PYTHONPATH collide in sys.modules and one
# wins silently.
export PYTHONPATH=/app/src:/broll-app:/music-app:/ytdl-app
# The image's own four roots, remembered for the restart loop at the bottom of
# this file: in image mode the path is re-decided on every boot by
# select_code_root.py, and this is what it falls back to (and what a
# bind-mount deployment keeps unconditionally). Assigned FROM the line above
# rather than repeated, so the list exists exactly once
# (server/tests/test_music_deploy.py reads that line and checks every entry is
# a real mount).
IMAGE_PYTHONPATH="$PYTHONPATH"

# Static ffmpeg/ffprobe, mounted read-only from the host at /opt/ffmpeg by
# compose and put there by server/install_dashboard_app.py. This image is a
# stock python:3.12.7-slim -- nothing builds it, and this container runs as
# 3000:3001, so it cannot install a distro package for itself.
#
# PATH rather than the FFMPEG/FFPROBE env vars musicweb reads first: those are
# absolute paths taken on trust, so pointing them at a mount that was never
# provisioned turns /api/ingest's clean 503 ("ingest needs ffmpeg: not on PATH
# here") into a FileNotFoundError partway through an upload. shutil.which()
# tells the truth about an empty mount. Prepended, so an image that ever does
# ship its own ffmpeg does not silently take precedence over the pinned build.
#
# /opt/deno rides along on the same reasoning, for /ytdl: the static deno the
# updated yt-dlp uses as a JS runtime for YouTube's "n challenge". Provisioned
# onto the host by server/install_dashboard_app.py and mounted read-only,
# exactly like ffmpeg -- but ONLY on a site whose site.toml sets
# `[features] youtube_unblock` (2026-08-17, docs/COMMERCIAL_READINESS.md
# item 3). An absent mount is the normal state, and a supported one: shutil.
# which() tells the truth about it and /ytdl/api/health says so.
#
# /opt/claude is GONE (item 1). The two AI calls use the anthropic SDK with
# the customer's ANTHROPIC_API_KEY, so there is no subprocess, no binary to
# put on PATH, and no need for a writable HOME -- which is why NOTHING sets
# HOME here and nothing should: exporting one process-wide would change the
# resolution of ~ for pip, uvicorn and every library in the dashboard. The
# entry is kept in the PATH below so an older host that still has the mount
# does not change behaviour mid-upgrade; it can go once no deployment has one.
export PATH="/opt/ffmpeg:/opt/claude:/opt/deno:$PATH"

# UVICORN'S ACCESS LOG, OFF BY DEFAULT (ops-efficiency-7, 2026-08-21).
#
# It logged one line per request, and the request rate here is set by polling
# rather than by people: every companion POSTs /api/v1/report every 5 s while
# a lane syncs, every open dashboard tab GETs /partials/* every 2 s, and the
# compose healthcheck hits /api/v1/health every 60 s. On a ten-machine fleet
# that is several lines a second, forever, and it says nothing -- 200s on
# three paths. It buried the lines that DO matter (tracebacks, the collector's
# warnings, "site identity not fully configured") and, with docker's json-file
# driver, it ate the disk; the compose files now cap that at 100 MB, which
# this keeps from rotating an incident away inside an hour.
#
# DASH_ACCESS_LOG=1 in the container environment puts it back for a debugging
# session. Deliberately NOT a key in the compose templates: an operator who
# needs it adds it, and a key in the file would have to be carried by
# compose_config() too (server/tests/test_safety.test_env_keys_match_compose).
#
# Referenced UNQUOTED below, on purpose: empty has to mean "pass no flag", and
# "$ACCESS_LOG_FLAG" would become an empty argv entry uvicorn rejects.
ACCESS_LOG_FLAG="--no-access-log"
if [ "${DASH_ACCESS_LOG:-0}" = "1" ]; then
    ACCESS_LOG_FLAG=""
    echo "run.sh: DASH_ACCESS_LOG=1 -- uvicorn's per-request access log is ON."
fi

# OVER-THE-AIR CODE UPDATES (ZERO_TOUCH_PLAN.md WP K, 2026-08-18), IMAGE MODE
# ONLY. The dashboard can install a newer, signed copy of its own CODE into
# /data/code/<version>/ and ask to be re-exec'd; the IMAGE stays the runtime.
# Two rules shape what follows:
#
#   * The choice of code root is made by the IMAGE's python running the
#     IMAGE's /app/deploy/select_code_root.py, which verifies the installed
#     tree's signed record against DASH_RELEASE_PUBKEYS before ever naming it.
#     The tree in /data is the thing being judged; it gets no vote. That is
#     also why the selection is re-run on every loop iteration rather than
#     once: a watchdog revert between two boots has to be honoured.
#   * Bind-mount mode is UNTOUCHED. /venv/.image-baked is absent there, /app
#     is the host's own tree, and there is no OTA path at all -- that
#     deployment updates from the base rig (server/install_dashboard_app.py).
#
# Exit 75 (EX_TEMPFAIL) is the app asking to be restarted; anything else exits
# as it always did, so `docker stop` and a real crash both behave exactly as
# before. uvicorn runs as a CHILD rather than an exec here, which means this
# shell keeps PID 1 and has to forward the stop signal itself -- without the
# trap, `docker stop` would kill the shell and leave uvicorn to be SIGKILLed
# ten seconds later, mid-request.
if [ -f "$VENV/.image-baked" ]; then
    while : ; do
        selected="$("$VENV/bin/python" /app/deploy/select_code_root.py || true)"
        if [ -n "$selected" ]; then
            PYTHONPATH="$selected"
        else
            echo "run.sh: WARNING: select_code_root.py printed nothing -- using the image's own code." >&2
            PYTHONPATH="$IMAGE_PYTHONPATH"
        fi
        export PYTHONPATH
        echo "run.sh: PYTHONPATH=$PYTHONPATH"
        "$VENV/bin/python" -m uvicorn --factory ccsync_dashboard.app:create_app \
            --host 0.0.0.0 --port "${DASH_PORT:-8480}" --workers 1 \
            $ACCESS_LOG_FLAG &
        app_pid=$!
        trap 'kill -TERM "$app_pid" 2>/dev/null' TERM INT
        rc=0
        wait "$app_pid" || rc=$?
        trap - TERM INT
        if [ "$rc" != "75" ]; then
            exit "$rc"
        fi
        echo "run.sh: the dashboard asked to restart (exit 75) -- re-selecting the code root"
    done
fi

exec "$VENV/bin/python" -m uvicorn --factory ccsync_dashboard.app:create_app \
    --host 0.0.0.0 --port "${DASH_PORT:-8480}" --workers 1 $ACCESS_LOG_FLAG
