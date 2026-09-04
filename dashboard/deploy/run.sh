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

# IMAGE MODE, decided ONCE (CR-84, 2026-08-26). The marker was tested inline in
# two places and is now needed in a third (the unblock install below), and the
# three had to agree: in image mode /venv is a read-only image layer owned by
# root and this container is uid 3000, so "can I pip into /venv?" is answered
# NO before pip is ever run. Marker rather than a writability probe: the answer
# to "is /venv writable?" is also no for a broken bind mount, which must still
# fail loudly (see the base install below).
IMAGE_MODE=""
if [ -f "$VENV/.image-baked" ]; then
    IMAGE_MODE=1
fi

# Appended to PYTHONPATH further down, empty unless the unblock block below
# fills it in. Declared here because `set -u` would abort on an unset one.
PYTHONPATH_EXTRA=""

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
if [ -n "$IMAGE_MODE" ]; then
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
# so image mode does NOT short-circuit this block the way it does the
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
    # WHERE IT LANDS, AND WHY IT IS NOT /venv IN IMAGE MODE (CR-84,
    # 2026-08-26). In image mode /venv is an image layer, `a+rX` on purpose
    # (AUDIT C-1: a writable code path in a process holding the NAS admin
    # password is remote code execution), and this container is uid 3000 -- so
    # this install could NEVER succeed there. It did not: the live NAS logged
    # `[Errno 13] Permission denied: '/venv/.../yt_dlp_plugins'` four times per
    # boot while the retry loop below called it a network blip, and the fix was
    # a `docker exec -u 0 ... pip install` that the next image update threw
    # away. So image mode installs into /data instead -- uid-3000-owned,
    # persistent across image updates, and exactly the shape /data/code already
    # uses for OTA code -- and puts it on PYTHONPATH. yt-dlp finds a plugin by
    # walking sys.path for a `yt_dlp_plugins` package (yt_dlp/plugins.py,
    # `default_plugin_paths`: "Load from PYTHONPATH directories"), so a path
    # entry is all it needs; it does not have to be inside the venv.
    #
    # --no-deps is a CONDITION of --target, not an optimisation: this lock is a
    # hash-pinned closure of exactly one package whose only dependency is
    # yt-dlp, which the venv already holds at the version requirements.lock
    # pins. Without it pip would try to install yt-dlp into the target too, and
    # --require-hashes would refuse (no hash for it in this lock).
    UNBLOCK_SITE=""
    STAMP_UNBLOCK=$VENV/.requirements-unblock-hash
    if [ -n "$IMAGE_MODE" ]; then
        UNBLOCK_SITE=/data/unblock-site
        STAMP_UNBLOCK=/data/.requirements-unblock-hash
        mkdir -p "$UNBLOCK_SITE" 2>/dev/null || true
        PYTHONPATH_EXTRA=":$UNBLOCK_SITE"
    fi
    unblock_install() {
        if [ -n "$IMAGE_MODE" ]; then
            "$VENV/bin/pip" install --quiet --no-cache-dir --no-deps \
                --target "$UNBLOCK_SITE" $PIP_HASH_FLAG_UNBLOCK -r "$REQS_UNBLOCK"
        else
            "$VENV/bin/pip" install --quiet --no-cache-dir \
                $PIP_HASH_FLAG_UNBLOCK -r "$REQS_UNBLOCK"
        fi
    }
    # WHAT HAPPENED HERE, WRITTEN DOWN (YTWEB-5, 2026-09-03). Until now the
    # entire evidence of this install was four `run.sh: WARNING:` lines in a
    # container log: CR-73 (DNS not up in the container's first seconds) and
    # CR-84 (`[Errno 13]` into a read-only /venv) each ran for days behind
    # them, with the symptom showing up as 1.8 MiB/s downloads and "the
    # downloaded file is empty" and the diagnosis reachable only by a
    # `docker logs`. The marker is written on SUCCESS as well as on failure --
    # a state file that only exists when things are broken cannot tell "fine"
    # from "this run.sh is too old to write one" -- and /ytdl's health route
    # reads it (ytdlweb.routes_api._plugin_install_state).
    #
    # It lives beside the plugin itself, so an image update carries the two
    # together, and the path is exported because only this script knows which
    # of the two layouts is in play.
    UNBLOCK_MARKER="${UNBLOCK_SITE:-$VENV}/plugin_install.json"
    export YTDL_PLUGIN_INSTALL_MARKER="$UNBLOCK_MARKER"
    UNBLOCK_VERSION="$(sed -n 's/^[Bb]gutil-ytdlp-pot-provider==\([^ ;\\]*\).*/\1/p' "$REQS_UNBLOCK" | head -1)"
    # Written through python, not printf: pip's last words are the whole point
    # of the `error` key and they arrive with quotes, backslashes and newlines
    # in them. A hand-rolled JSON string here would produce a marker the
    # health route cannot parse on exactly the boots that matter.
    write_unblock_marker() {
        "$VENV/bin/python" - "$UNBLOCK_MARKER" "$1" "$2" "$3" "$UNBLOCK_VERSION" <<'PYMARKER' 2>/dev/null || true
import json, os, sys, tempfile, time

path, ok, attempts, error, version = sys.argv[1:6]
payload = {
    "ok": ok == "1",
    "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    "attempts": int(attempts or 0),
    # Capped: pip can print a hundred lines and this file is read on a
    # request path. The first lines are the ones that name the cause.
    "error": (error or "")[:4000],
    "version": version or "",
}
try:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path) or ".", suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(payload, fh)
    os.replace(tmp, path)
except OSError:
    # A marker we cannot write is a diagnostic lost, never a boot stopped.
    pass
PYMARKER
    }
    want_unblock="$(md5sum "$REQS_UNBLOCK" | cut -d' ' -f1)"
    have_unblock="$(cat "$STAMP_UNBLOCK" 2>/dev/null || true)"
    if [ "$want_unblock" = "$have_unblock" ] && [ ! -f "$UNBLOCK_MARKER" ]; then
        # Nothing to install and no marker: this container was first booted by
        # a run.sh from before the marker existed. Record the state we are in
        # rather than leaving the health route to report NOT CHECKED forever.
        write_unblock_marker 1 0 ""
    fi
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
        unblock_err=""
        unblock_tries=0
        for unblock_delay in 5 15 30 0; do
            unblock_tries=$((unblock_tries + 1))
            if unblock_err="$(unblock_install 2>&1)"; then
                printf '%s' "$want_unblock" > "$STAMP_UNBLOCK"
                unblock_ok=1
                write_unblock_marker 1 "$unblock_tries" ""
                break
            fi
            if [ "$unblock_delay" != "0" ]; then
                echo "run.sh: unblock install failed -- retrying in ${unblock_delay}s" >&2
                sleep "$unblock_delay"
            fi
        done
        if [ -z "$unblock_ok" ]; then
            # PIP'S OWN LAST WORDS, NOT JUST OUR GUESS (CR-84, 2026-08-26).
            # The retry loop assumed the only possible cause was the boot-time
            # network gap CR-73 measured, so the log said "PyPI unreachable?"
            # four times while pip had actually said `[Errno 13] Permission
            # denied` -- a diagnosis nobody could reach from the log they had.
            echo "run.sh: WARNING: youtube_unblock dependency install FAILED." >&2
            echo "run.sh: WARNING: /ytdl's PO-token path will bot-check-fail" >&2
            echo "run.sh: WARNING: until this succeeds; everything else keeps" >&2
            echo "run.sh: WARNING: running. pip said:" >&2
            printf '%s\n' "$unblock_err" >&2
            # ...and, since YTWEB-5, somewhere an admin can reach without a
            # `docker logs`: /ytdl's health route and the dashboard's own
            # self-diagnosis read this file.
            write_unblock_marker 0 "$unblock_tries" "$unblock_err"
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
#
# PYTHONPATH_EXTRA is the youtube_unblock plugin's own site directory in image
# mode (CR-84) and empty everywhere else. APPENDED, never prepended: it holds
# one namespace package and must not get a vote on where `app`, `musicweb` or
# `ytdlweb` come from. It is a SUFFIX ON THE STRING rather than a fifth entry
# in the list above, so that when it is empty the exported path gains no empty
# entry -- an empty entry is how /music once came to report "absent" behind a
# green healthcheck.
# /cards-app IS DELIBERATELY NOT ON THAT LIST (Timeline Cards, phase 3,
# 2026-08-30). It is another repo's tree: it is never in this image and never
# in an over-the-air code bundle, so `select_code_root.py` -- which re-derives
# the four roots above on every image-mode boot -- has nothing to say about
# it, and a fifth entry here would be dropped on exactly the boots that
# matter. `ccsync_dashboard.cards` appends DASH_CARDS_SRC (=/cards-app) to
# sys.path itself when it mounts, so the path entry and the mount are one
# decision instead of two that can disagree.
IMAGE_PYTHONPATH="$PYTHONPATH$PYTHONPATH_EXTRA"
PYTHONPATH="$IMAGE_PYTHONPATH"
export PYTHONPATH

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
# ...and the same /opt/ffmpeg serves TIMELINE CARDS at /cards, which needs
# both binaries: ffmpeg for the lane's Opus copies, the .peaks and the audio
# it pulls out of a clip's own media, ffprobe to prove an extraction came out
# the length it went in. Its `media.ffmpeg_path()` / `ffprobe_path()` look on
# PATH FIRST and only then in two Windows install locations, so this line is
# all it needs -- and an empty /opt/ffmpeg mount is a state it reports rather
# than one it crashes on.
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
if [ -n "$IMAGE_MODE" ]; then
    while : ; do
        selected="$("$VENV/bin/python" /app/deploy/select_code_root.py || true)"
        if [ -n "$selected" ]; then
            # select_code_root.py prints the FOUR code roots and knows nothing
            # about the unblock site dir, so the suffix is re-attached here --
            # an OTA'd code tree must not lose the PO-token plugin (CR-84).
            PYTHONPATH="$selected$PYTHONPATH_EXTRA"
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
