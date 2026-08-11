#!/usr/bin/env python3
"""Deploy the ccsync-dashboard as a TrueNAS custom app.

    SYNCTHING_API_KEY=... DASH_REPORT_TOKEN=... TRUENAS_PW=... \\
        python install_dashboard_app.py [--port 8480] [--dry-run]

Steps (each idempotent, one line printed per action):

  1. Create the host dirs over SSH (sudo):
       <host-root>/app    -- the repo's dashboard/ tree (replaced on re-run);
                             root:root, world-readable, never group-writable
                             (mounted :ro in the container -- AUDIT C-1)
       <host-root>/venv   -- the container's dependency venv (NEVER touched
                             on re-run); 3000:3000, mode 700. Deliberately
                             NOT inside data/: run.sh execs an interpreter
                             out of it, and data/ used to be group-writable
                             by every editor (AUDIT C-2).
       <host-root>/data   -- SQLite DB + companion packages (NEVER touched on
                             re-run); 3000:3000 (broll:broll), mode 770 --
                             group 3000, NOT 3001/editors.
       <host-root>/broll-web -- this repo's broll/web tree (shipped in step
                             2b); root:root 755, mounted :ro like app/.
       <host-root>/ytdl-web, /claude-bin, /deno -- the ytdl code tree and the
                             two binaries it shells out to; root:root 755,
                             mounted :ro (steps 2f).
       <host-root>/ytdl-data -- ytdl.db + the pipeline worker's scratch;
                             3000:3000 mode 770, like data/ and music-data.
       <host-root>/claude-home -- where the one-time `claude /login` keeps its
                             OAuth credentials; 3000:3000 mode 700, because
                             that is a live credential.
       <host-root>/staging -- where the 1.4 GB music artefacts are staged, on
                             the same pool as their target instead of in a
                             possibly RAM-backed /tmp (OPS-8); owned by
                             TRUENAS_USER, mode 700. Optional: /tmp is still
                             the fallback, and the small code trees use it.
     ...and, when the b-roll UI is enabled, the b-roll DATA root -- which is
     the shared archive itself, /mnt/tank/.../Assets/B-roll Archive -- as
     broll:editors 2770 (setgid), the same posture setup_tree.py gives
     Projects/. Deliberately NOT 770/group-3000: editors browse that tree
     over SMB as P:\\Assets\\B-roll Archive and must not be locked out of it.
  2. Upload the local dashboard/ tree via SFTP to a fresh mktemp staging dir,
     verify the staged copy against the local manifest (file count AND total
     byte size), build <host-root>/app.new from it, verify that too, and only
     then swap it into place:
         mv app app.old.<ts> && mv app.new app
     Any failure before the swap leaves the live app/ untouched; a failed
     swap rolls back. The previous app.old.<ts> backups are pruned (most
     recent kept, and never one a container still has bind-mounted) only
     after a LATER install has succeeded, and a failure in any step AFTER
     the swap restarts the container first -- otherwise it keeps serving the
     inode that is now app.old.<ts>, which the next run would prune (OPS-2).
     Excludes .venv, __pycache__, *.pyc.
  2b. When DASH_BROLL_ENABLED=1 (the default): ship the b-roll web/ tree
     into <host-root>/broll-web by exactly the same staged-verify-swap
     route. The container mounts that dir read-only at /broll-app and puts it
     on PYTHONPATH; without this step it is EMPTY, the import fails, and the
     b-roll UI is silently absent behind a green healthcheck. The source is
     BROLL_WEB_SRC, defaulting to broll/web in this repo (the b-roll platform
     was folded in as broll/ on 2026-08-10); if it is missing this script
     FAILS rather than deploying a feature that cannot work. Set
     DASH_BROLL_ENABLED=0 to skip the b-roll UI entirely.
  2c. Ship the music web/ tree into <host-root>/music-web by the same route
     (mounted read-only at /music-app, on PYTHONPATH). Source is MUSIC_WEB_SRC,
     default music/web in this repo. Unlike b-roll this is a WARN-AND-SKIP if
     it is missing, not a refusal: there is no DASH_MUSIC_ENABLED asserting
     that the operator wanted it -- shipping the tree IS the switch, and a host
     without it reports the mount "absent" and hides the nav link.
  2d. Ship the music DATA artefacts, which are not code and are ~1.4 GB:
       music.db (~20 MB)         the index. WRITABLE: it lands in
                                 <host-root>/music-data (3000:3000 770,
                                 mounted rw at /music-data) because queued
                                 ingest writes `pending` rows into it. Shipped
                                 with its WAL sidecars moved aside, never
                                 deleted, previous kept as music.db.old.<ts>.
       text_encoder/ (~482 MB)   the exported CLAP text tower. WITHOUT IT
                                 /music/api/search 500s -- the fallback is the
                                 full CLAP model, which needs torch, which this
                                 container deliberately does not have.
       proxies/ (~906 MB)        128k preview mp3s. Without them /api/audio
                                 still works and streams 60 MB wavs instead.
     These do NOT ride along with every deploy: --music-data auto (the default)
     ships only what the NAS does not already have, so the first install is the
     1.4 GB one and a routine redeploy pushes nothing. --music-data all (or
     db/encoder/proxies) forces a re-push -- that is how a re-index is
     published. --music-data none skips them.
  2e. Provision static ffmpeg + ffprobe into <host-root>/ffmpeg (mounted
     read-only at /opt/ffmpeg, put on PATH by run.sh). /music's queued ingest
     needs them -- ffprobe to prove an upload is audio, ffmpeg to transcode
     .ogg -- and answers 503 without them. THERE IS NO IMAGE BUILD in this
     deployment (compose runs a stock pinned python:3.12.7-slim) and the
     container is unprivileged, so this is the only place it can come from.
     The 42 MB tarball is fetched HERE and pushed over the LAN (--ffmpeg-fetch
     local, the default), because the NAS pulls that host at ~28 kB/s and the
     download alone outlived the SSH timeout; --ffmpeg-fetch remote is the old
     "let the NAS curl it" path, for a workstation with no route out.
     Non-fatal and idempotent; --no-ffmpeg skips it.
  2f. Ship the ytdl web/ tree into <host-root>/ytdl-web (mounted read-only at
     /ytdl-app, on PYTHONPATH), source YTDL_WEB_SRC, default ytdl/web in this
     repo. WARN-AND-SKIP if missing, exactly like music: there is no
     DASH_YTDL_ENABLED asserting the operator wanted it, so shipping the tree
     IS the switch and a host without it hides the nav link. No data push goes
     with it -- ytdl.db is created by the container in /ytdl-data.
     Then provision the Claude CLI and a static deno into <host-root>/claude-bin
     and <host-root>/deno (mounted read-only at /opt/claude and /opt/deno, on
     PATH via run.sh), the same fetch-here-verify-push-install route as ffmpeg.
     Neither has a pinned URL in this repo: set YTDL_CLAUDE_URL /
     YTDL_CLAUDE_SHA256 and YTDL_DENO_URL / YTDL_DENO_SHA256 (or point
     YTDL_CLAUDE_FILE / YTDL_DENO_FILE at a local download). Every failure here
     -- including an unset URL -- is a NOTE, never a failed deploy: /ytdl then
     reports the CLI missing instead of hanging. --no-ytdl-bins skips the step.
  3. If the app is not yet installed: POST /api/v2.0/app with
       {"custom_app": true, "app_name": "ccsync-dashboard",
        "custom_compose_config": {...}}   (compose dict mirrors
     dashboard/deploy/compose.yaml -- keep them in sync; tests/test_safety.py
     asserts they have not drifted on image tag, bind defaults, env keys and
     healthcheck). The custom_app
     payload shape is ASSUMED from the TrueNAS 25.10 middleware; if the POST
     is rejected the script prints the manual fallback (paste
     dashboard/deploy/compose.yaml into Apps > Install via YAML) instead of
     guessing at other shapes.
     If the app IS installed: POST /api/v2.0/app/redeploy {"app_name": ...}
     so the freshly-uploaded code is picked up (also an assumed shape, same
     fallback: restart the app from the TrueNAS UI).

Env vars: TRUENAS_HOST (default 192.168.0.102), TRUENAS_USER (default
truenas_admin), TRUENAS_PW (required), SYNCTHING_API_KEY (required),
DASH_REPORT_TOKEN (required -- companions must present this to POST
status reports; generate one with e.g. `openssl rand -hex 24` and put the
same value in each editor's ~/.ccsync/config.toml as dashboard_token),
DASH_SESSION_SECRET (required -- signs editor/admin session cookies;
generate the same way. It must stay STABLE across deploys: a fresh value
logs every editor out, so store it alongside DASH_REPORT_TOKEN and pass
both again on --recreate).
Optional: DASH_ADMIN_USERS (default truenas_admin), SYNCTHING_GUI_URL,
CCSYNC_SSH_HOSTKEY (pin the NAS SSH host key; see --host-key),
DASH_BIND_LAN / DASH_BIND_TAILNET (the two addresses the dashboard is
published on, defaults 192.168.0.102 / 100.71.216.3 -- change these when the
NAS's DHCP lease or tailnet IP moves, or Docker refuses to start the app
with "cannot assign requested address"), DASH_IMAGE (pinned base image),
TRUENAS_VERIFY_SSL (default "0" = trust the NAS's self-signed cert),
DASH_BROLL_ENABLED (default "1"; "0" deploys without the b-roll UI),
BROLL_INGEST_TOKEN (REQUIRED when DASH_BROLL_ENABLED=1 -- it guards a write
path the indexer reaches with no session; `openssl rand -hex 24`),
BROLL_WEB_SRC (the b-roll web/ tree to ship, default broll/web in this repo),
MUSIC_WEB_SRC (the music web/ tree to ship, default music/web in this repo),
MUSIC_DATA_SRC (the music data/ dir, default <MUSIC_WEB_SRC>/data),
MUSIC_DATA_PUSH (same values as --music-data; default "auto"),
MUSIC_FFMPEG_URL / MUSIC_FFMPEG_SHA256 (the static ffmpeg build to install;
pinned defaults, and an empty URL skips the step like --no-ffmpeg),
MUSIC_FFMPEG_FETCH (same values as --ffmpeg-fetch: "local", the default, fetches
the tarball on this machine and pushes it over the LAN; "remote" makes the NAS
download it), MUSIC_FFMPEG_FILE (a tarball already on this machine -- skips the
download entirely, and is still checked against the pinned hash),
MUSIC_FFMPEG_CACHE (where locally-fetched tarballs are kept between deploys,
default <repo>/.cache/ffmpeg),
YTDL_WEB_SRC (the ytdl web/ tree to ship, default ytdl/web in this repo),
YTDL_CLAUDE_URL / YTDL_CLAUDE_SHA256 and YTDL_DENO_URL / YTDL_DENO_SHA256 (the
Claude CLI and static deno builds to install for /ytdl -- NO pinned defaults,
and an unset URL skips that binary with a NOTE), YTDL_CLAUDE_FILE /
YTDL_DENO_FILE (a download already on this machine, skipping the fetch),
YTDL_BINARY_CACHE (where those downloads are kept between deploys, default
<repo>/.cache/ytdl).

Compose-level settings are baked in at CREATE time: after changing any of
them, re-run with --recreate, otherwise the running app keeps the old ones.

TRUENAS_HOST/USER/PW are also forwarded into the deployed app's own
environment (same values this script already needs for its own SSH/API
calls) -- they back the admin "Users" section (create editor accounts,
approve pending Syncthing devices, set known passwords) added to the
dashboard. That section is a convenience layer over server/setup_editor_account.py
and server/accept_device.py, not a replacement -- the CLI scripts remain
the tools of record and work with or without the dashboard deployed.
"""
import argparse
import hashlib
import os
import posixpath
import re
import shutil
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

from common import (
    DEFAULT_BROLL_ARCHIVE_ROOT, DEFAULT_CC_ROOT, DEFAULT_PROJECTS_ROOT,
    add_host_key_arg, ok,
    require_env, run_ssh,
    set_host_key_pin, shell_quote, ssh_client, truenas_api,
    truenas_conn_params, wait_for_job,
)

APP_NAME = "ccsync-dashboard"
DEFAULT_HOST_ROOT = "/mnt/tank/apps/ccsync-dashboard"
# The install replaces everything under <host-root>/app, as root. Bound that
# to the one location this app is ever deployed to, so a mistyped --host-root
# cannot point the replace at a project tree (AUDIT DEL-9).
HOST_ROOT_RE = re.compile(r"^/mnt/[^/]+/apps/ccsync-dashboard(/[^/]+)*$")
DEFAULT_SYNCTHING_GUI_URL = "http://192.168.0.102:8384"
EXCLUDE_DIRS = {".venv", "__pycache__", ".pytest_cache"}
# How long a tree-sized remote step may run before run_ssh gives up on the
# channel (OPS-3). The floor covers the small code trees; the rate covers the
# 1.4 GB music artefacts, whose cp -a + chown -R + verify re-read say nothing
# until they are done. See tree_ssh_timeout.
MIN_TREE_SSH_TIMEOUT = 300
TREE_BYTES_PER_SECOND = 5 * 1024 * 1024
# Staging dirs this script creates on the NAS (make_staging_dir), and how old
# one has to be before it can only be the debris of a failed earlier run
# (prune_orphaned_staging -- OPS-8).
STAGING_GLOB = "ccsync-*-upload.*"
STAGING_ORPHAN_MINUTES = 120
LOCAL_DASHBOARD_DIR = Path(__file__).resolve().parents[1] / "dashboard"
# The b-roll app lives in this repo at broll/web (folded in from the standalone
# broll-platform repo on 2026-08-10); this script ships that tree into
# <host-root>/broll-web, which the container mounts read-only at /broll-app.
# BROLL_WEB_SRC still overrides, for deploying a checkout from elsewhere.
DEFAULT_BROLL_WEB_DIR = Path(__file__).resolve().parents[1] / "broll" / "web"
# Its tests/, git metadata and local venv have no business on the NAS -- the
# container only ever imports app/ and serves static/.
BROLL_EXCLUDE_DIRS = EXCLUDE_DIRS | {".git", ".github", "tests", "node_modules"}

# --------------------------------------------------------------------------
# The music app (music/web), mounted in-process at /music
# --------------------------------------------------------------------------
# Deployed exactly the way broll/web is: the CODE tree ships to
# <host-root>/music-web, which the container mounts read-only at /music-app and
# run.sh puts on PYTHONPATH. MUSIC_WEB_SRC overrides the source -- the same env
# var dashboard/tests/test_music_mount.py honours.
#
# There is deliberately NO DASH_MUSIC_ENABLED to go with DASH_BROLL_ENABLED.
# b-roll needs a flag because it has a credential (BROLL_INGEST_TOKEN) the
# dashboard refuses to start without; music has none -- nothing under /music is
# exempt from login_gate -- so SHIPPING THE TREE IS THE SWITCH, and a host that
# never received it reports the mount "absent" and simply hides the nav link.
# For the same reason a missing music tree is a WARNING here, not a refusal:
# nothing in the operator's command line asserted they wanted it.
DEFAULT_MUSIC_WEB_DIR = Path(__file__).resolve().parents[1] / "music" / "web"
# data/ is excluded from the CODE push and shipped separately (see
# MUSIC_DATA_COMPONENTS): it is ~1.4 GB whose update cadence has nothing to do
# with the dashboard's. Everything else -- tests/, .git, .venv, __pycache__ --
# is excluded for the same reasons broll/web excludes it (.venv was already in
# EXCLUDE_DIRS; music/web has one and broll/web does not).
MUSIC_EXCLUDE_DIRS = BROLL_EXCLUDE_DIRS | {"data"}
# The three data artefacts, none of which is code and none of which the app can
# be useful without. They are pushed INDEPENDENTLY of the code, because a
# dashboard deploy is a frequent, small, boring thing and this is 1.4 GB over
# paramiko's SFTP:
#
#   db       music.db, ~20 MB -- the entire index. Changes whenever the base
#            rig re-indexes. WRITABLE in the container: queued ingest writes
#            `pending` rows into it, so it lands in a data root owned by the
#            container's uid, NOT in a read-only code mount.
#   encoder  text_encoder/, ~482 MB -- the exported CLAP text tower. Without it
#            musicweb.search falls back to the full CLAP model, which needs
#            torch, which this container deliberately does not have, so
#            /music/api/search would 500. Immutable; mounted read-only.
#   proxies  proxies/, ~906 MB -- one 128k mp3 per track. Without them
#            /api/audio still works and serves the 60 MB originals over
#            Tailscale instead. Immutable HERE (they are generated on the base
#            rig; the container only ever checks existence), so read-only too.
MUSIC_DATA_COMPONENTS = ("db", "encoder", "proxies")
# component -> (subdirectory of the data source, <host-root> target name)
MUSIC_DATA_TREES = {
    "encoder": ("text_encoder", "music-encoder"),
    "proxies": ("proxies", "music-proxies"),
}
MUSIC_DB_FILENAME = "music.db"
# music.db is in WAL mode (write/read version 2 in its header), so its -wal and
# -shm siblings belong to THAT database file. Replacing the db and leaving a
# stale -wal beside it is how a working index becomes a corrupt one.
MUSIC_DB_SIDECARS = ("-wal", "-shm")
# Default for --music-data. "auto" = ship each component only if it is not on
# the NAS yet, which makes the first install a 1.4 GB one and every subsequent
# dashboard deploy a small one. `--music-data all` is how a re-index is
# published; `--music-data db` publishes just the index.
MUSIC_DATA_PUSH_DEFAULT = "auto"

# ffmpeg for the container. THERE IS NO IMAGE BUILD ANYWHERE IN THIS DEPLOYMENT
# -- compose runs a pinned, stock python:3.12.7-slim and execs /app/deploy/run.sh
# in it -- and the container runs as 3000:3001, so it cannot apt-get anything
# either. The remaining provisioning surface is this script, which has root over
# SSH: a static build is unpacked into <host-root>/ffmpeg, mounted read-only at
# /opt/ffmpeg, and put on PATH by run.sh.
#
# Only /api/ingest's queued path needs it (ffprobe to prove an upload is audio,
# ffmpeg to transcode .ogg), and musicweb answers 503 with a readable message
# when it is missing -- so this step is NON-FATAL and skippable. Deliberately
# NOT wired to the FFMPEG/FFPROBE env vars musicweb._tool() reads first: those
# are absolute paths taken on trust, and pointing them at a mount that was
# never provisioned turns a clean 503 into a FileNotFoundError mid-upload.
# PATH is checked with shutil.which(), which tells the truth.
DEFAULT_FFMPEG_URL = ("https://johnvansickle.com/ffmpeg/releases/"
                      "ffmpeg-7.0.2-amd64-static.tar.xz")
# sha256 of the tarball above, verified against the real download on 2026-08-10.
# The URL is the VERSIONED one on purpose: johnvansickle's
# ffmpeg-release-amd64-static.tar.xz is a rolling pointer whose bytes change
# under a pinned hash. Bump both together.
DEFAULT_FFMPEG_SHA256 = "abda8d77ce8309141f83ab8edf0596834087c52467f6badf376a6a2a4c87cf67"

# WHICH MACHINE DOES THE DOWNLOADING. "local" (the default) fetches the tarball
# here and pushes it to the NAS over the LAN; "remote" has the NAS curl it.
#
# It used to be remote-only, and that stranded the first deploy of this app: the
# NAS pulls johnvansickle.com at ~28 kB/s (42 MB ~= 25 minutes), run_ssh's
# timeout is 600s, and the step runs BEFORE any tree ships -- so a fresh host got
# a failed deploy out of a download this workstation does in seconds. Fetching
# here and pushing over gigabit LAN moves the slow, flaky half onto the machine
# that is fastest at it and can retry it cheaply, and turns the NAS's share of
# the work into a few seconds of SFTP + tar. "remote" is kept for the case this
# shape cannot serve: a workstation with no route out to the internet.
FFMPEG_FETCH_MODES = ("local", "remote")
DEFAULT_FFMPEG_FETCH = "local"
# Locally-fetched tarballs live here between deploys, so re-provisioning a host
# (or provisioning a second one) does not re-download 42 MB. Gitignored.
DEFAULT_FFMPEG_CACHE_DIR = Path(__file__).resolve().parents[1] / ".cache" / "ffmpeg"
# The local download's own timeout. Generous -- it is a 42 MB file from a host
# that is occasionally slow for everyone -- but not unbounded, because a hung
# socket here would stall a deploy exactly like the remote curl used to.
FFMPEG_FETCH_TIMEOUT = 300
# The name the tarball is staged under on the NAS. Fixed, not derived from the
# URL: it lands in a fresh mktemp dir that nothing else writes to.
FFMPEG_STAGED_NAME = "ffmpeg.tar.xz"

# The music library on the NAS: the SHARE ITSELF, beside Projects/ and the
# b-roll archive under Creators_Club, which is what makes it P:\Assets\Music on
# an editor's machine and W:\Creators_Club\Assets\Music on the base rig. Mounted
# READ-WRITE because queued ingest moves the accepted upload into it -- same
# posture as the b-roll archive, and for the same reason.
DEFAULT_MUSIC_LIBRARY_ROOT = DEFAULT_CC_ROOT + "/Assets/Music"

# --------------------------------------------------------------------------
# The YouTube downloader app (ytdl/web), mounted in-process at /ytdl
# --------------------------------------------------------------------------
# Deployed exactly the way music/web is, and warn-and-skip for the same reason:
# there is no DASH_YTDL_ENABLED, so nothing on the command line asserts that the
# operator wanted the feature. Shipping the tree IS the switch, and a host that
# never received it reports the mount "absent" and hides the nav link.
DEFAULT_YTDL_WEB_DIR = Path(__file__).resolve().parents[1] / "ytdl" / "web"
# Same exclusions as broll/web, PLUS data/ like music/web: in the container
# ytdl's database lives in its own writable /ytdl-data, but an env-less dev
# run defaults YTDL_DATA_ROOT to ytdl/web/data (ytdlweb.config), so a dev
# ytdl.db -- and any videos it downloaded -- would ride the next routine ship
# onto the NAS's read-only mount (YTDL-40, 2026-08-11).
YTDL_EXCLUDE_DIRS = BROLL_EXCLUDE_DIRS | {"data"}

# The two binaries the ytdl app shells out to, provisioned onto the host the
# same way ffmpeg is and for the same reason: NOTHING BUILDS THIS IMAGE (compose
# runs a stock pinned python:3.12.7-slim) and the container is unprivileged, so
# it can install neither for itself.
#
# The difference from ffmpeg is that neither has a pinned URL here. There is no
# stable, versioned, checksummable public tarball for the Claude CLI that this
# repo can name today, and the deno release the container wants depends on the
# yt-dlp version pinned in requirements.txt. So the URLs are OPERATOR-SUPPLIED
# (YTDL_CLAUDE_URL / YTDL_DENO_URL) and an unset one is a NOTE, not a failure:
# a fleet dashboard must not stop deploying because an optional download host
# was not configured yet. The feature degrades exactly as designed -- ytdlweb's
# api/health reports the CLI missing and the SPA says so before a job is
# submitted.
YTDL_BINARY_CACHE_DIR = Path(__file__).resolve().parents[1] / ".cache" / "ytdl"
# The staged name on the NAS is fixed rather than derived from the URL: it lands
# in a fresh mktemp dir that nothing else writes to. The EXTENSION still comes
# from the URL, because it is what says whether this is a tarball, a zip or a
# bare binary.
YTDL_BINARIES = (
    # (name, <host-root> dir, container mount, binary, url env, sha env,
    #  file env, what breaks without it)
    ("claude", "claude-bin", "/opt/claude", "claude",
     "YTDL_CLAUDE_URL", "YTDL_CLAUDE_SHA256", "YTDL_CLAUDE_FILE",
     "every /ytdl job fails immediately with the 'claude CLI missing' banner "
     "(term generation and relevance filtering both run through it)"),
    ("deno", "deno", "/opt/deno", "deno",
     "YTDL_DENO_URL", "YTDL_DENO_SHA256", "YTDL_DENO_FILE",
     "yt-dlp has no JS runtime for YouTube's challenges, so the high-quality "
     "formats fail and downloads fall back or error"),
)

# Minimum ingest-token strength, mirroring
# ccsync_dashboard.broll.check_ingest_token -- the dashboard refuses to START
# with a weaker one, and finding that out from a crash-looping container is a
# worse experience than finding it out here, before anything is uploaded.
MIN_INGEST_TOKEN_CHARS = 24
PLACEHOLDER_INGEST_TOKENS = {
    "replace_me", "replaceme", "replace-me", "change_me", "changeme", "change-me",
    "changethis", "todo", "tbd", "secret", "password", "token", "test", "example",
    "your-token-here", "xxx", "none", "null",
}
# Pinned, mirroring dashboard/deploy/compose.yaml: an unpinned python:3.12-slim
# silently changes underneath a redeploy. Bump deliberately, in both places.
DEFAULT_IMAGE = "python:3.12.7-slim"
# Host interfaces the dashboard binds to (mirrors dashboard/deploy/compose.yaml
# -- keep in sync): LAN for the base rig, tailnet for remote editors. Never
# 0.0.0.0 -- a new NAS interface must not silently expose the dashboard.
# These are DEFAULTS only: compose reads ${DASH_BIND_LAN}/${DASH_BIND_TAILNET}
# and this script takes --bind-lan/--bind-tailnet (same env names), because a
# NAS DHCP change or a tailnet IP rotation otherwise makes Docker fail with
# "cannot assign requested address" and the app never starts.
LAN_BIND_IP = "192.168.0.102"
TAILNET_BIND_IP = "100.71.216.3"


# yt-dlp's PO-token provider, run as a sidecar. The tag is pinned and MUST be
# bumped together with the `bgutil-ytdlp-pot-provider` pin in
# dashboard/deploy/requirements.txt -- the plugin and this server are one
# component in two processes, and the project ships them as a matched pair.
# server/tests/test_safety.py asserts the two versions agree.
POT_PROVIDER_SERVICE = "bgutil"
POT_PROVIDER_VERSION = "1.3.1"
POT_PROVIDER_IMAGE = f"brainicism/bgutil-ytdlp-pot-provider:{POT_PROVIDER_VERSION}-deno"
POT_PROVIDER_PORT = 4416


def healthcheck_config(port: int) -> dict:
    """Mirrors compose.yaml's healthcheck -- keep the two identical.

    `restart: unless-stopped` only covers a process that EXITS; a collector
    thread that died before entering its guarded loop leaves a container that
    answers nothing useful forever. /api/v1/health is unauthenticated by
    design for exactly this. urllib rather than curl: the python:*-slim image
    has no curl.
    """
    probe = (
        "python -c \"import urllib.request,sys; sys.exit(0 if "
        f"urllib.request.urlopen('http://127.0.0.1:{port}/api/v1/health', "
        "timeout=5).status == 200 else 1)\""
    )
    return {
        "test": ["CMD-SHELL", probe],
        "interval": "60s",
        "timeout": "10s",
        "retries": 3,
        "start_period": "120s",
    }


def compose_config(port: int, host_root: str, gui_url: str, api_key: str, token: str,
                   session_secret: str = "", admin_users: str = "truenas_admin",
                   truenas_host: str = "", truenas_user: str = "", truenas_pw: str = "",
                   truenas_verify_ssl: str = "0",
                   bind_lan: str = LAN_BIND_IP, bind_tailnet: str = TAILNET_BIND_IP,
                   image: str = DEFAULT_IMAGE,
                   broll_enabled: str = "1", broll_ingest_token: str = "",
                   broll_creators_shares: str = "mofa-disaster") -> dict:
    # Mirrors dashboard/deploy/compose.yaml -- keep the two in sync. The ${VAR}
    # substitutions there are resolved here in Python instead: the TrueNAS
    # middleware stores this dict verbatim, so an unresolved ${...} would end
    # up as a literal bind address.
    return {
        "services": {
            "dashboard": {
                "image": image,
                "user": "3000:3001",
                "command": ["/bin/sh", "/app/deploy/run.sh"],
                "environment": {
                    "SYNCTHING_GUI_URL": gui_url,
                    "SYNCTHING_API_KEY": api_key,
                    "DASH_REPORT_TOKEN": token,
                    "DASH_SESSION_SECRET": session_secret,
                    "DASH_ADMIN_USERS": admin_users,
                    "DASH_DB_PATH": "/data/dashboard.db",
                    "DASH_PORT": str(port),
                    "DASH_PROJECTS_DIR": "/projects",
                    # b-roll search UI, mounted in-process at /broll so
                    # editors reach it on this same host, port and login.
                    # Must stay in step with deploy/compose.yaml -- the two
                    # describe the same container and drift between them is
                    # only ever discovered in production.
                    "DASH_BROLL_ENABLED": broll_enabled,
                    "BROLL_DATA_ROOT": "/broll-data",
                    "BROLL_SHARES": "broll:Main b-roll archive",
                    "BROLL_CREATORS_SHARES": broll_creators_shares,
                    # Mandatory when the mount is on, and enforced twice: this
                    # script refuses to deploy without a strong one, and the
                    # dashboard refuses to start. Blank used to mean the b-roll
                    # app's own guard fell back to dev mode, where any
                    # logged-in editor could rewrite the archive index.
                    "BROLL_INGEST_TOKEN": broll_ingest_token,
                    # music search UI, mounted in-process at /music. No
                    # DASH_MUSIC_ENABLED and no token: shipping the tree is the
                    # switch, and nothing under /music is exempt from
                    # login_gate (see music/web/DEPLOY.md).
                    #
                    # Every one of these is MUSIC_-prefixed. musicweb still
                    # honours bare DATA_ROOT/MUSIC_ROOT as fallbacks, but this
                    # is one environment shared with the dashboard and with the
                    # b-roll mount (which namespaces everything BROLL_*), and a
                    # bare DATA_ROOT in it is a collision waiting to happen.
                    #
                    # MUSIC_DATA_ROOT is the one WRITABLE music path: music.db
                    # and the ingest staging/ dir live there. The other two are
                    # read-only artefacts shipped beside it.
                    "MUSIC_DATA_ROOT": "/music-data",
                    "MUSIC_SHARE_ROOT": "/music-share",
                    "MUSIC_PROXIES_DIR": "/music-proxies",
                    "MUSIC_TEXT_ENCODER_DIR": "/music-encoder",
                    # YouTube downloader UI, mounted in-process at /ytdl. No
                    # flag and no token, for music's reason: nothing under
                    # /ytdl is exempt from login_gate, so shipping the tree is
                    # the switch.
                    #
                    # YTDL_DATA_ROOT is the only writable one. The others are
                    # what it reaches through: the SHARED Projects tree that
                    # finished clips land in (sync distributes them from
                    # there), the dashboard's own SQLite opened READ-ONLY for
                    # the caller's ticked projects, and the home directory the
                    # one-time `claude /login` writes its credentials into --
                    # which ytdlweb.claude_cli puts in the SUBPROCESS env
                    # only, because run.sh deliberately exports no HOME.
                    "YTDL_DATA_ROOT": "/ytdl-data",
                    "YTDL_PROJECTS_ROOT": "/projects",
                    "YTDL_DASH_DB": "/data/dashboard.db",
                    "YTDL_CLAUDE_HOME": "/claude-home",
                    # The PO-token provider sidecar below, by compose service
                    # name. Without this yt-dlp finds no provider and every
                    # signed-in request comes back with no formats.
                    "YTDL_POT_BASE_URL": f"http://{POT_PROVIDER_SERVICE}:{POT_PROVIDER_PORT}",
                    # A signed-in cookies.txt is MANDATORY here, not the
                    # optional escape hatch it reads as elsewhere: this IP is
                    # bot-checked, so anonymous extraction fails outright.
                    # Operator-provisioned (it is a live Google session, so it
                    # is never in this repo) -- see ytdl/web/DEPLOY.md. An
                    # absent file is a supported state: yt-dlp ignores the
                    # option and the failure is the honest bot-check message.
                    "YTDL_COOKIES_FILE": "/ytdl-data/cookies.txt",
                    # yt-dlp DOWNLOADS the EJS challenge solver at first use
                    # and caches it. run.sh deliberately exports no HOME, so
                    # the default lands on /.cache -- which uid 3000 cannot
                    # create, making it re-fetch the solver on EVERY call.
                    "YTDL_CACHE_DIR": "/ytdl-data/cache",
                    # DASH_PACKAGES_DIR intentionally unset: defaults to a
                    # "packages" dir next to DASH_DB_PATH (/data/packages),
                    # which is already the persistent volume.
                    # AUDIT SEC-2 asked whether TRUENAS_PW can be dropped from
                    # the container env (it is readable via `docker inspect`).
                    # It cannot: the dashboard reads it at runtime
                    # (settings.py -> api.py/ui.py "Users" admin section, which
                    # creates editor accounts and approves devices) and returns
                    # a 503 "TRUENAS_PW is not configured" without it. Removing
                    # it here would break that section, so it stays -- the
                    # mitigation is that the container is root-only-readable and
                    # the dashboard is never exposed beyond LAN/tailnet.
                    "TRUENAS_HOST": truenas_host,
                    "TRUENAS_USER": truenas_user,
                    "TRUENAS_PW": truenas_pw,
                    # TLS verification for those TrueNAS API calls (they carry
                    # TRUENAS_PW). "0" = trust the NAS's self-signed cert, as
                    # before; "1" or a CA bundle path inside the container
                    # once the NAS has a trusted cert.
                    "TRUENAS_VERIFY_SSL": truenas_verify_ssl,
                },
                "ports": [
                    f"{bind_lan}:{port}:{port}",
                    f"{bind_tailnet}:{port}:{port}",
                ],
                "volumes": [
                    # ro: the command: line executes /app/deploy/run.sh, so a
                    # writable /app is code execution in a container holding
                    # TRUENAS_PW (AUDIT C-1).
                    f"{host_root}/app:/app:ro",
                    # The venv is its own volume, owned 3000:3000 mode 700.
                    # At /data/venv (group editors, mode 770) any editor
                    # could replace the interpreter run.sh execs and run code
                    # as the dashboard user with TRUENAS_PW in its env
                    # (AUDIT C-2). Keep it OUT of /data.
                    f"{host_root}/venv:/venv",
                    f"{host_root}/data:/data",
                    # rw for the /project-setup create flow; container runs
                    # as broll:editors, matching setup_tree.py's ownership.
                    f"{DEFAULT_PROJECTS_ROOT}:/projects:rw",
                    # b-roll: code read-only (same posture as /app), data rw.
                    f"{host_root}/broll-web:/broll-app:ro",
                    # DATA_ROOT is the shared archive itself (beside Projects/
                    # under Creators_Club), not a private copy -- one set of
                    # media serves both the search UI and editors' timelines.
                    f"{DEFAULT_BROLL_ARCHIVE_ROOT}:/broll-data:rw",
                    # music: code read-only (same posture as /app and
                    # /broll-app), and its data split by what has to be
                    # writable rather than by what happens to be big.
                    f"{host_root}/music-web:/music-app:ro",
                    # WRITABLE: music.db (queued ingest writes `pending` rows)
                    # and the ingest staging/ dir. A read-only data root here
                    # is the DEGRADED case the mount is built to report --
                    # "unable to open database file" on every request.
                    f"{host_root}/music-data:/music-data:rw",
                    # Read-only artefacts, shipped separately from the code
                    # because together they are ~1.4 GB: the exported CLAP text
                    # tower (without it /music/api/search 500s, since the
                    # fallback needs torch) and the 128k preview proxies
                    # (without them /api/audio serves 60 MB wavs over Tailscale).
                    f"{host_root}/music-encoder:/music-encoder:ro",
                    f"{host_root}/music-proxies:/music-proxies:ro",
                    # The music library itself, beside Projects/ and the b-roll
                    # archive. rw: queued ingest moves the accepted upload into
                    # the share.
                    f"{DEFAULT_MUSIC_LIBRARY_ROOT}:/music-share:rw",
                    # Static ffmpeg/ffprobe for /api/ingest. There is no image
                    # build in this deployment and the container is unprivileged,
                    # so the binaries are provisioned onto the host by this
                    # script and mounted in; run.sh puts them on PATH. An empty
                    # dir here is fine -- ingest answers 503 and says so.
                    f"{host_root}/ffmpeg:/opt/ffmpeg:ro",
                    # ytdl: code read-only (the /app posture again), data rw.
                    f"{host_root}/ytdl-web:/ytdl-app:ro",
                    # WRITABLE: ytdl.db -- jobs, manifests and the permanent
                    # cross-project dedupe ledger. The finished CLIPS are not
                    # here; they are written into /projects above, which is
                    # what makes sync distribute them to the editors.
                    f"{host_root}/ytdl-data:/ytdl-data:rw",
                    # The one-time `claude /login` credentials, so they survive
                    # a redeploy (once per NAS). 3000:3000 mode 700: a live
                    # OAuth credential for the user's own Claude account.
                    f"{host_root}/claude-home:/claude-home:rw",
                    # The Claude CLI and a static deno, provisioned onto the
                    # host like ffmpeg and mounted read-only for the same
                    # reason -- no image build, unprivileged container. deno
                    # is what answers YouTube's JS challenges for yt-dlp;
                    # without it the high-quality formats fail.
                    f"{host_root}/claude-bin:/opt/claude:ro",
                    f"{host_root}/deno:/opt/deno:ro",
                ],
                "restart": "unless-stopped",
                "healthcheck": healthcheck_config(port),
            },
            # yt-dlp's PO-token provider, the ONE piece that makes YouTube
            # extraction work from this NAS at all (2026-08-11). Measured
            # against the live container, all four states:
            #
            #   anonymous                 -> "Sign in to confirm you're not a bot"
            #   cookies alone             -> past the check, then NO FORMATS
            #   cookies + PO token + EJS  -> works
            #
            # A datacentre IP doing bulk extraction is bot-checked, so
            # authenticated is the only way in; and YouTube wants a GVS
            # proof-of-origin token for authenticated requests, which yt-dlp
            # has no provider for on its own. This runs one.
            #
            # A SIDECAR rather than a process inside the dashboard container:
            # the provider is a JS service, the dashboard image is a stock
            # python:slim that builds nothing, and the alternative (script
            # mode) spawns a JS runtime PER CALL against a pipeline that makes
            # hundreds. No ports published -- compose puts both services on one
            # network and the dashboard reaches it by service name, so nothing
            # on the LAN can ask this for tokens.
            #
            # The tag is pinned and MATCHED to the plugin pin in
            # dashboard/deploy/requirements.txt: one component, two processes.
            # The `-deno` flavour is deliberate (the `-node` one is the same
            # server on a different runtime; deno is what this fleet already
            # provisions for yt-dlp's JS challenges).
            POT_PROVIDER_SERVICE: {
                "image": POT_PROVIDER_IMAGE,
                "restart": "unless-stopped",
            },
        }
    }


# Every environment variable whose VALUE is a credential and which ends up in
# the compose body this script prints. --dry-run prints that body in full, on
# purpose (the admin needs to eyeball paths, ports, mounts and bind addresses
# before a real run) -- so the secrets, and only the secrets, are replaced with
# placeholders first. Keep this list in step with the secret-bearing keys in
# compose_config(); everything else in that body is configuration and stays
# readable, because a dry-run that hides the thing you are checking is useless.
SECRET_ENV_VARS = (
    "SYNCTHING_API_KEY",
    "DASH_REPORT_TOKEN",
    "DASH_SESSION_SECRET",
    "BROLL_INGEST_TOKEN",
    "TRUENAS_PW",
)


def dry_run_mask(name: str, value: str) -> str:
    """The placeholder a secret is printed as in --dry-run.

    Still distinguishes "configured" from "not configured": whether a secret is
    SET is not itself a secret, and it is the single most useful thing a dry-run
    can tell you about one (a blank DASH_SESSION_SECRET logs the whole fleet out
    on deploy). Its value is never printed.
    """
    return f"<{name}-not-shown-in-dry-run>" if value else f"<{name}-unset-dry-run>"


def resolve_compose_secrets(dry_run: bool, broll_ingest_token: str) -> dict:
    """The secret-bearing compose values: real ones for a real deploy, masked
    ones for --dry-run.

    ORDER MATTERS, and this function is why it is explicit. Everything that
    VALIDATES a secret (weak_ingest_token on BROLL_INGEST_TOKEN, require_env on
    the three mandatory ones) runs against the real value -- masking happens
    here, afterwards, on the way into the printed body only. A placeholder must
    never be able to satisfy or trip a check that the real value would not:
    `<BROLL_INGEST_TOKEN-unset-dry-run>` is 34 characters and would sail past a
    length check it was never meant to reach.

    TRUENAS_PW is masked here for the compose body alone; run_ssh and
    truenas_api each re-read it from the environment for their own use, so a
    real deploy is unaffected.
    """
    if dry_run:
        return {name: dry_run_mask(name, os.environ.get(name, "").strip())
                for name in SECRET_ENV_VARS}
    return {
        "SYNCTHING_API_KEY": require_env("SYNCTHING_API_KEY"),
        "DASH_REPORT_TOKEN": require_env("DASH_REPORT_TOKEN"),
        # Stable across deploys: rotating it logs every editor out.
        "DASH_SESSION_SECRET": require_env("DASH_SESSION_SECRET"),
        # Already validated by weak_ingest_token when the b-roll UI is on, and
        # legitimately blank when it is off.
        "BROLL_INGEST_TOKEN": broll_ingest_token,
        "TRUENAS_PW": require_env("TRUENAS_PW"),
    }


def broll_web_source() -> Path:
    """The b-roll web/ tree to ship -- broll/web in this repo, unless
    BROLL_WEB_SRC points somewhere else."""
    raw = os.environ.get("BROLL_WEB_SRC", "").strip()
    return Path(raw) if raw else DEFAULT_BROLL_WEB_DIR


def music_web_source() -> Path:
    """The music web/ tree to ship -- music/web in this repo, unless
    MUSIC_WEB_SRC points somewhere else."""
    raw = os.environ.get("MUSIC_WEB_SRC", "").strip()
    return Path(raw) if raw else DEFAULT_MUSIC_WEB_DIR


def music_data_source() -> Path:
    """The music data/ directory (music.db, text_encoder/, proxies/).

    Follows MUSIC_WEB_SRC by default -- a checkout elsewhere brings its own
    data with it -- and MUSIC_DATA_SRC overrides it on its own, for the case
    where the artefacts were built or fetched separately from the code.
    """
    raw = os.environ.get("MUSIC_DATA_SRC", "").strip()
    return Path(raw) if raw else music_web_source() / "data"


def parse_music_data_push(raw: str) -> tuple[set[str], str]:
    """--music-data -> (components to force-push, error).

    "auto" returns an EMPTY set and no error: nothing is forced, and what
    actually ships is decided per component by whether the NAS already has it
    (see music_components_to_push). "none" is the same empty set with
    force-only semantics, so the two are distinguished by the caller, not here.
    """
    value = (raw or "").strip().lower()
    if value in ("auto", "none", ""):
        return set(), ""
    if value == "all":
        return set(MUSIC_DATA_COMPONENTS), ""
    wanted = {p.strip() for p in value.split(",") if p.strip()}
    unknown = sorted(wanted - set(MUSIC_DATA_COMPONENTS))
    if unknown:
        return set(), (f"unknown --music-data component(s) {', '.join(unknown)}; "
                       f"expected auto, none, all, or a comma-separated subset of "
                       f"{', '.join(MUSIC_DATA_COMPONENTS)}")
    return wanted, ""


def music_component_paths(root: str) -> dict[str, str]:
    """component -> the path on the NAS whose existence means "already there"."""
    paths = {"db": f"{root}/music-data/{MUSIC_DB_FILENAME}"}
    for name, (_sub, target) in MUSIC_DATA_TREES.items():
        paths[name] = f"{root}/{target}"
    return paths


def music_components_present(root: str, dry_run: bool) -> dict[str, bool]:
    """Which music data components the NAS already holds.

    One SSH round trip printing "<component> yes|no" per line. A non-empty
    DIRECTORY is what counts for the two trees, not merely an existing one:
    install_dashboard_app creates them empty in step 1, and an empty
    music-proxies is exactly the state "auto" has to treat as missing.

    A dry run reports everything absent, so --dry-run shows the full first-run
    plan (which is the one worth eyeballing -- it is the 1.4 GB one).

    OPS-5 (2026-08-11): this probe used to run UNPRIVILEGED, unlike every other
    filesystem action in this script. `db` lives inside music-data, which is
    3000:3000 mode 770 and which TRUENAS_USER cannot traverse, so `[ -e ... ]`
    was false every time and routine `ship.cmd` (--music-data auto) re-uploaded
    the index on every deploy -- swapping the base rig's copy over the live one
    and discarding any container-written `pending` ingest rows. The `|| echo x`
    that used to paper over an unreadable directory went with it: an unreadable
    path must count as ABSENT (re-push, which is safe) rather than as present
    (skip a push that was needed).
    """
    paths = music_component_paths(root)
    if dry_run:
        run_ssh("true  # [dry-run] would check which music data components exist",
                dry_run=True)
        return {name: False for name in paths}
    probe = "; ".join(
        f'if [ -e {shell_quote(path)} ] && '
        f'[ -n "$(ls -A {shell_quote(path)} 2>/dev/null)" ]; '
        f'then echo "{name} yes"; else echo "{name} no"; fi'
        for name, path in paths.items()
    )
    rc, out, _err = run_ssh('echo "$SUDO_PW" | sudo -S sh -c ' + shell_quote(probe))
    present = {name: False for name in paths}
    if rc != 0:
        return present
    for line in out.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[0] in present:
            present[parts[0]] = parts[1] == "yes"
    return present


def music_components_to_push(root: str, mode: str, forced: set[str],
                             dry_run: bool) -> list[str]:
    """The components this run will actually ship, in a stable order.

    "none" ships nothing. An explicit list (or "all") ships exactly that, every
    time -- that is how a re-index is published. "auto" ships only what the NAS
    does not have, which is what keeps a routine dashboard deploy from pushing
    1.4 GB it already pushed last week.
    """
    if mode == "none":
        return []
    if forced:
        return [c for c in MUSIC_DATA_COMPONENTS if c in forced]
    present = music_components_present(root, dry_run)
    return [c for c in MUSIC_DATA_COMPONENTS if not present.get(c)]


def music_data_sizes(source: Path) -> dict[str, tuple[int, int]]:
    """component -> (file count, bytes) for whatever of it exists locally."""
    sizes: dict[str, tuple[int, int]] = {}
    db = source / MUSIC_DB_FILENAME
    if db.is_file():
        sizes["db"] = (1, db.stat().st_size)
    for name, (sub, _target) in MUSIC_DATA_TREES.items():
        if (source / sub).is_dir():
            sizes[name] = local_manifest(source / sub, MUSIC_EXCLUDE_DIRS)
    return sizes


def human_bytes(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024.0
    return f"{n:.1f} GB"


def build_db_swap_script(data_root: str, staging: str, target: str,
                         old: str, expected_bytes: int) -> str:
    """Install one shipped music.db, with install_tree's guarantees for a file.

    Everything in install_tree that stops a half-transfer from becoming the
    live thing applies here too -- verify the candidate, then swap it in with a
    rename, then roll the rename back if it fails -- but a single file cannot
    go through install_tree, for two reasons:

      - it must be OWNED BY THE CONTAINER (3000:3000, 660). install_tree
        chowns root:root and strips group write, which is right for code and
        would make every queued ingest fail to write its `pending` row.
      - music.db is in WAL MODE. Its -wal and -shm siblings belong to the
        database file they sit beside, and leaving a stale -wal next to a
        freshly replaced db is how a working index becomes a corrupt one. They
        are moved aside with it, never deleted.
    """
    root_q = shell_quote(data_root)
    db_q = shell_quote(target)
    new_q = shell_quote(target + ".new")
    old_q = shell_quote(old)
    staging_q = shell_quote(staging)
    staged_q = shell_quote(posixpath.join(staging, MUSIC_DB_FILENAME))
    sidecars = " ".join(
        f'if [ -e {shell_quote(target + s)} ]; then '
        f'mv {shell_quote(target + s)} {shell_quote(old + s)}; fi;'
        for s in MUSIC_DB_SIDECARS
    )
    return (
        f"set -e; "
        f"mkdir -p {root_q}; "
        f"rm -f {new_q}; "
        f"cp -a {staged_q} {new_q}; "
        f"chown 3000:3000 {new_q}; "
        f"chmod 660 {new_q}; "
        f"b=$(wc -c < {new_q}); "
        f'if [ "$b" -ne {expected_bytes} ]; then '
        f'echo "candidate index incomplete: $b bytes, expected {expected_bytes} '
        f'-- the installed index is untouched" >&2; exit 8; fi; '
        # Only now is anything live touched, and only by renames.
        f"if [ -e {db_q} ]; then mv {db_q} {old_q}; fi; "
        f"{sidecars} "
        f"mv {new_q} {db_q} || {{ if [ -e {old_q} ]; then mv {old_q} {db_q}; fi; "
        f'echo "swap failed, previous index restored" >&2; exit 9; }}; '
        f"rm -rf {staging_q}"
    )


def install_music_db(root: str, source: Path, dry_run: bool,
                     staging_parent: str = "/tmp") -> bool:
    """Ship music.db into <root>/music-data. True on success.

    The index is ~20 MB and is the only music artefact the container writes, so
    it goes to the writable data root rather than a read-only code mount. The
    previous index is kept as music.db.old.<ts> -- never deleted, and never
    pruned automatically: unlike code, a database that has been live has rows
    in it that the copy replacing it may not.
    """
    db = source / MUSIC_DB_FILENAME
    if not db.is_file():
        print(f"FAILED: no {MUSIC_DB_FILENAME} at {db} -- nothing to install",
              file=sys.stderr)
        return False
    # A -wal sitting beside the SOURCE means the base rig has committed writes
    # that are not in the .db file yet, and a plain file copy leaves them
    # behind. Not fatal (the copy is still a valid, if older, database) but the
    # operator has to know before they conclude the index is up to date.
    for sidecar in MUSIC_DB_SIDECARS:
        extra = source / (MUSIC_DB_FILENAME + sidecar)
        if extra.is_file() and extra.stat().st_size:
            print(f"WARNING: {extra.name} is non-empty -- the base rig has "
                  f"committed writes that are not in {MUSIC_DB_FILENAME} yet, "
                  f"and only the .db file is shipped. Close the indexer (or run "
                  f"`sqlite3 {db} 'PRAGMA wal_checkpoint(TRUNCATE)'`) and push "
                  f"again if the index looks stale on the NAS.", file=sys.stderr)

    expected_bytes = db.stat().st_size
    timeout = tree_ssh_timeout(expected_bytes)  # OPS-3, same reasoning as install_tree
    staging = make_staging_dir(dry_run, "ccsync-musicdb-upload", staging_parent)
    staged_db = posixpath.join(staging, MUSIC_DB_FILENAME)
    if dry_run:
        print(f"[dry-run] would SFTP {MUSIC_DB_FILENAME} "
              f"({human_bytes(expected_bytes)}) from {db} to {staging} on the NAS")
    else:
        host, user, pw = truenas_conn_params()
        client = ssh_client(host, user, pw)
        try:
            sftp = client.open_sftp()
            sftp.put(str(db), staged_db)
            sftp.close()
        finally:
            client.close()
        rc, out, err = run_ssh_guarded(f"wc -c < {shell_quote(staged_db)}",
                                       False, timeout)
        staged_bytes = int(out.strip()) if rc == 0 and out.strip().isdigit() else -1
        if staged_bytes != expected_bytes:
            print(f"FAILED: the staged index does not match what was sent "
                  f"({staged_bytes} bytes on the NAS vs {expected_bytes} locally) "
                  f"-- the installed index is untouched (staging left at "
                  f"{staging} for inspection): {err.strip()[:200]}", file=sys.stderr)
            return False
        print(f"staged index verified: {staged_bytes} bytes")

    data_root = f"{root}/music-data"
    target = f"{data_root}/{MUSIC_DB_FILENAME}"
    old = f"{target}.old.{time.strftime('%Y%m%d%H%M%S')}"
    swap = build_db_swap_script(data_root, staging, target, old, expected_bytes)
    rc, _out, err = run_ssh_guarded('echo "$SUDO_PW" | sudo -S sh -c ' + shell_quote(swap),
                                    dry_run, timeout)
    if rc != 0:
        print(f"FAILED to install the music index into {target}: "
              f"{err.strip()[:500]}\n"
              f"  The previously installed index is still in place (it is only "
              f"replaced by an atomic rename, and that rename rolls back).",
              file=sys.stderr)
        return False
    print(f"installed music index: {target} ({human_bytes(expected_bytes)}; "
          f"previous index kept at {old})")
    return True


def build_ffmpeg_install_script(target_dir: str, url: str, sha256: str) -> str:
    """Provision static ffmpeg + ffprobe into `target_dir` on the NAS.

    THIS IS NOT AN IMAGE BUILD, because this deployment has none: compose runs
    a pinned, stock python:3.12.7-slim and execs /app/deploy/run.sh inside it.
    The container is also unprivileged (3000:3001), so it cannot install
    packages itself. What is left is this: a root-run step that puts a
    self-contained static build on the host, which compose mounts read-only at
    /opt/ffmpeg and run.sh prepends to PATH.

    Shaped by what can go wrong:
      - Idempotent. Already-installed binaries are left alone, so a routine
        redeploy does not re-download 42 MB.
      - The download is checksummed against a PINNED hash before anything is
        unpacked, and the URL is a versioned one so the hash stays valid.
      - The candidate is EXECUTED (`-version`) before it is moved into place:
        an archive for the wrong architecture must not become the ffmpeg the
        app finds on PATH.
      - Nothing is deleted. A previous install is only ever overwritten by
        `mv`, and only after the new one has run.
    """
    d = shell_quote(target_dir)
    url_q = shell_quote(url)
    verify = (f"printf '%s  %s\\n' {shell_quote(sha256)} \"$t/ffmpeg.tar.xz\" "
              f"| sha256sum -c - >/dev/null; ") if sha256 else ""
    return (
        f"set -e; "
        f"if [ -x {d}/ffmpeg ] && [ -x {d}/ffprobe ]; then "
        f'echo "ffmpeg already provisioned at {target_dir}"; exit 0; fi; '
        f"mkdir -p {d}; "
        f"t=$(mktemp -d /tmp/ccsync-ffmpeg.XXXXXX); "
        f'trap "rm -rf $t" EXIT; '
        f'curl -fsSL --retry 3 -o "$t/ffmpeg.tar.xz" {url_q}; '
        f"{verify}"
        f'tar -xJf "$t/ffmpeg.tar.xz" -C "$t"; '
        f'b=$(find "$t" -type f -name ffmpeg | head -n 1); '
        f'p=$(find "$t" -type f -name ffprobe | head -n 1); '
        f'if [ -z "$b" ] || [ -z "$p" ]; then '
        f'echo "the archive holds no ffmpeg/ffprobe" >&2; exit 1; fi; '
        f'install -o root -g root -m 755 "$b" {d}/ffmpeg.new; '
        f'install -o root -g root -m 755 "$p" {d}/ffprobe.new; '
        # Runs it here rather than discovering in production that the binary is
        # for another architecture, or is not a binary at all.
        f"if ! {d}/ffmpeg.new -version >/dev/null 2>&1 || "
        f"! {d}/ffprobe.new -version >/dev/null 2>&1; then "
        f'echo "the downloaded ffmpeg/ffprobe does not run on this host" >&2; '
        f"rm -f {d}/ffmpeg.new {d}/ffprobe.new; exit 1; fi; "
        f"mv {d}/ffmpeg.new {d}/ffmpeg; mv {d}/ffprobe.new {d}/ffprobe; "
        f"chmod 755 {d}; "
        f'echo "ffmpeg provisioned: {target_dir}"'
    )


def build_ffmpeg_unpack_script(target_dir: str, tarball: str, staging: str,
                               sha256: str) -> str:
    """Install ffmpeg + ffprobe on the NAS from a tarball ALREADY STAGED there.

    The same script as build_ffmpeg_install_script minus its first line: the
    download. Everything that made that one safe still applies -- checksum
    before unpacking, execute the candidate before it goes live, replace only by
    `mv`, delete nothing -- and the checksum matters just as much here, because
    it is now verifying the SFTP transfer rather than the internet.

    The digest is not optional in practice: the caller always has one, either
    the pinned hash or the digest of the file it just fetched. An empty one is
    tolerated so an operator who overrode the URL with no hash still gets an
    install, and the transfer is then covered by nothing -- which is said out
    loud where the override happens.
    """
    d = shell_quote(target_dir)
    tb = shell_quote(tarball)
    # `printf | sha256sum -c` and NOT a bare pipeline under `set -e`: an explicit
    # `if !` says what failed. A pipeline's exit status is its LAST command, so
    # anything of the form `check | filter` silently reports the filter's
    # success -- that is how an unverified ffmpeg nearly shipped here on
    # 2026-08-10 (`ffmpeg -version | head -1` printed "Killed" and exited 0).
    verify = (
        f"if ! printf '%s  %s\\n' {shell_quote(sha256)} {tb} | sha256sum -c - "
        f">/dev/null 2>&1; then "
        f'echo "the staged tarball does not match the digest that was sent -- '
        f'the transfer was corrupted; nothing installed" >&2; exit 7; fi; '
    ) if sha256 else ""
    return (
        f"set -e; "
        f"if [ -x {d}/ffmpeg ] && [ -x {d}/ffprobe ]; then "
        f'echo "ffmpeg already provisioned at {target_dir}"; exit 0; fi; '
        # Before mkdir, before mktemp: a transfer that arrived wrong leaves no
        # trace of itself on the host at all.
        f"{verify}"
        f"mkdir -p {d}; "
        f"t=$(mktemp -d /tmp/ccsync-ffmpeg.XXXXXX); "
        f'trap "rm -rf $t" EXIT; '
        f'tar -xJf {tb} -C "$t"; '
        f'b=$(find "$t" -type f -name ffmpeg | head -n 1); '
        f'p=$(find "$t" -type f -name ffprobe | head -n 1); '
        f'if [ -z "$b" ] || [ -z "$p" ]; then '
        f'echo "the archive holds no ffmpeg/ffprobe" >&2; exit 1; fi; '
        f'install -o root -g root -m 755 "$b" {d}/ffmpeg.new; '
        f'install -o root -g root -m 755 "$p" {d}/ffprobe.new; '
        # Same reason as the download path: an archive for another architecture
        # must not become the ffmpeg the app finds on PATH.
        f"if ! {d}/ffmpeg.new -version >/dev/null 2>&1 || "
        f"! {d}/ffprobe.new -version >/dev/null 2>&1; then "
        f'echo "the downloaded ffmpeg/ffprobe does not run on this host" >&2; '
        f"rm -f {d}/ffmpeg.new {d}/ffprobe.new; exit 1; fi; "
        f"mv {d}/ffmpeg.new {d}/ffmpeg; mv {d}/ffprobe.new {d}/ffprobe; "
        f"chmod 755 {d}; "
        f"rm -rf {shell_quote(staging)}; "
        f'echo "ffmpeg provisioned: {target_dir}"'
    )


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def ffmpeg_cache_path(url: str) -> Path:
    """Where a locally-fetched tarball is kept between deploys.

    Namespaced by a digest of the URL, because every static-ffmpeg mirror names
    its tarball the same thing and a cache hit on somebody else's bytes is the
    one failure a cache must not have.
    """
    raw = os.environ.get("MUSIC_FFMPEG_CACHE", "").strip()
    cache = Path(raw) if raw else DEFAULT_FFMPEG_CACHE_DIR
    name = posixpath.basename(urllib.parse.urlparse(url).path) or FFMPEG_STAGED_NAME
    return cache / f"{hashlib.sha256(url.encode()).hexdigest()[:12]}-{name}"


def fetch_ffmpeg_tarball(url: str, sha256: str) -> tuple[Path | None, str]:
    """Get the tarball onto THIS machine. Returns (path, error).

    Three sources, in order: MUSIC_FFMPEG_FILE (one the operator already has),
    the local cache, then the network. A pinned hash is checked at every one of
    them -- including the cache, whose whole risk is serving bytes that were
    right once.

    A download that fails the pin is DELETED rather than cached: keeping it
    would make every later deploy fail the same way for a reason that reads like
    tampering, long after the truncated transfer that caused it.
    """
    override = os.environ.get("MUSIC_FFMPEG_FILE", "").strip()
    if override:
        path = Path(override)
        if not path.is_file():
            return None, f"MUSIC_FFMPEG_FILE={override} is not a file"
        if sha256:
            digest = sha256_file(path)
            if digest != sha256:
                return None, (f"{path} does not match the pinned sha256 "
                              f"(got {digest})")
        print(f"using the ffmpeg tarball at {path} "
              f"({human_bytes(path.stat().st_size)})")
        return path, ""

    cached = ffmpeg_cache_path(url)
    if cached.is_file():
        if not sha256 or sha256_file(cached) == sha256:
            print(f"using the cached ffmpeg tarball at {cached} "
                  f"({human_bytes(cached.stat().st_size)})")
            return cached, ""
        print(f"NOTE: the cached tarball at {cached} no longer matches the "
              f"pinned sha256 -- re-downloading", file=sys.stderr)

    cached.parent.mkdir(parents=True, exist_ok=True)
    part = cached.with_name(cached.name + ".part")
    print(f"fetching {url}")
    try:
        with urllib.request.urlopen(url, timeout=FFMPEG_FETCH_TIMEOUT) as resp:
            with part.open("wb") as out:
                shutil.copyfileobj(resp, out, 1 << 20)
    except Exception as exc:       # urllib raises URLError, socket.timeout, OSError...
        part.unlink(missing_ok=True)
        return None, f"{type(exc).__name__}: {exc}"
    if sha256:
        digest = sha256_file(part)
        if digest != sha256:
            part.unlink(missing_ok=True)
            return None, (f"the download does not match the pinned sha256 "
                          f"(got {digest}) -- nothing was sent to the NAS")
    part.replace(cached)
    print(f"fetched {human_bytes(cached.stat().st_size)} to {cached}")
    return cached, ""


def ffmpeg_present(root: str, dry_run: bool) -> bool:
    """Does the NAS already have both binaries?

    The remote scripts are idempotent on their own, so this exists for the LOCAL
    fetch path: without it, a routine redeploy of an already-provisioned host
    would download and push 42 MB to be told "already provisioned". A failed or
    unreadable probe counts as absent -- re-provisioning is idempotent and
    cheap, and skipping the step wrongly is how /music's ingest ends up 503.
    """
    if dry_run:
        run_ssh("true  # [dry-run] would check whether ffmpeg is already on the host",
                dry_run=True)
        return False
    d = shell_quote(f"{root}/ffmpeg")
    rc, out, _err = run_ssh(f'if [ -x {d}/ffmpeg ] && [ -x {d}/ffprobe ]; '
                            f'then echo yes; else echo no; fi')
    return rc == 0 and out.strip().splitlines()[-1:] == ["yes"]


def install_ffmpeg_over_lan(root: str, tarball: Path | None, sha256: str,
                            dry_run: bool) -> tuple[bool, str]:
    """Push a local ffmpeg tarball to the NAS and unpack it. (ok, error).

    Same staged-then-verified-then-swapped shape as every other thing this
    script ships: SFTP into a fresh mktemp dir, prove the staged bytes are the
    bytes that were sent, and only then let root touch anything.
    """
    target_dir = f"{root}/ffmpeg"
    staging = make_staging_dir(dry_run, "ccsync-ffmpeg-upload")
    staged = posixpath.join(staging, FFMPEG_STAGED_NAME)
    if dry_run:
        print(f"[dry-run] would SFTP the ffmpeg tarball to {staged} on the NAS "
              f"and unpack it into {target_dir}")
    else:
        expected_bytes = tarball.stat().st_size
        host, user, pw = truenas_conn_params()
        client = ssh_client(host, user, pw)
        try:
            sftp = client.open_sftp()
            sftp.put(str(tarball), staged)
            sftp.close()
        finally:
            client.close()
        rc, out, err = run_ssh(f"wc -c < {shell_quote(staged)}")
        staged_bytes = int(out.strip()) if rc == 0 and out.strip().isdigit() else -1
        if staged_bytes != expected_bytes:
            return False, (f"the staged tarball does not match what was sent "
                           f"({staged_bytes} bytes on the NAS vs {expected_bytes} "
                           f"locally; staging left at {staging}): "
                           f"{err.strip()[:200]}")
        print(f"pushed {human_bytes(staged_bytes)} to staging {staging}")

    script = build_ffmpeg_unpack_script(target_dir, staged, staging, sha256)
    rc, out, err = run_ssh('echo "$SUDO_PW" | sudo -S sh -c ' + shell_quote(script),
                           dry_run=dry_run, timeout=300)
    if rc != 0:
        return False, err.strip()[:300] or f"the unpack exited {rc}"
    if not dry_run:
        print(out.strip().splitlines()[-1] if out.strip()
              else f"ffmpeg provisioned: {target_dir}")
    return True, ""


def provision_ffmpeg(root: str, fetch: str, dry_run: bool) -> None:
    """Step 2e. NON-FATAL throughout: the only thing that needs ffmpeg is
    /music's queued ingest, which answers 503 with a readable message when it is
    absent, and a fleet dashboard must not fail to deploy because a download
    host was unreachable. Every failure below prints a NOTE and returns.
    """
    target_dir = f"{root}/ffmpeg"
    url = os.environ.get("MUSIC_FFMPEG_URL", DEFAULT_FFMPEG_URL).strip()
    sha = os.environ.get("MUSIC_FFMPEG_SHA256", DEFAULT_FFMPEG_SHA256).strip()
    local_file = os.environ.get("MUSIC_FFMPEG_FILE", "").strip()

    if not url and not (fetch == "local" and local_file):
        print("NOTE: MUSIC_FFMPEG_URL is empty -- skipping ffmpeg. /music's "
              "queued ingest will answer 503 until ffmpeg and ffprobe are on "
              f"PATH in the container (mount {target_dir} at /opt/ffmpeg).",
              file=sys.stderr)
        return
    if url and url != DEFAULT_FFMPEG_URL and sha == DEFAULT_FFMPEG_SHA256:
        # The pinned hash belongs to the pinned URL. Silently checking it
        # against somebody else's mirror would fail confusingly; not checking it
        # at all is the honest behaviour, said out loud.
        print("NOTE: MUSIC_FFMPEG_URL was overridden without "
              "MUSIC_FFMPEG_SHA256 -- the download will NOT be checksummed.",
              file=sys.stderr)
        sha = ""

    # Before the 42 MB moves anywhere. The remote scripts check this too; doing
    # it here is what stops a redeploy from fetching a tarball it cannot use.
    if ffmpeg_present(root, dry_run):
        print(f"ffmpeg already provisioned at {target_dir}")
        return

    if fetch == "remote":
        rc, out, err = run_ssh(
            'echo "$SUDO_PW" | sudo -S sh -c '
            + shell_quote(build_ffmpeg_install_script(target_dir, url, sha)),
            dry_run=dry_run,
            timeout=600,
        )
        if dry_run:
            print(f"[dry-run] would have the NAS download {url} and provision "
                  f"static ffmpeg/ffprobe into {target_dir}")
        elif rc == 0:
            print(out.strip().splitlines()[-1] if out.strip()
                  else f"ffmpeg provisioned: {target_dir}")
        else:
            print(f"NOTE: ffmpeg was NOT provisioned ({err.strip()[:200]}). "
                  f"Everything else deploys; /music's queued ingest will answer "
                  f"503 until ffmpeg and ffprobe exist in {target_dir}.\n"
                  f"  The NAS is slow to reach some download hosts (johnvansickle "
                  f"at ~28 kB/s = ~25 min for this file, past run_ssh's 600s "
                  f"timeout). --ffmpeg-fetch local fetches it here instead.",
                  file=sys.stderr)
        return

    tarball, err = (None, "")
    if dry_run:
        print(f"[dry-run] would fetch {url} to {ffmpeg_cache_path(url)} and push "
              f"it to the NAS over the LAN")
    else:
        tarball, err = fetch_ffmpeg_tarball(url, sha)
        if tarball is None:
            print(f"NOTE: ffmpeg was NOT provisioned -- the tarball could not be "
                  f"fetched here ({err}). Everything else deploys; /music's "
                  f"queued ingest will answer 503 until ffmpeg and ffprobe exist "
                  f"in {target_dir}.\n"
                  f"  Retry, or point MUSIC_FFMPEG_FILE at a downloaded tarball, "
                  f"or use --ffmpeg-fetch remote to have the NAS download it "
                  f"(slow: it pulls that host at ~28 kB/s).", file=sys.stderr)
            return
        # With no pinned hash there is still one worth sending: the digest of the
        # file actually fetched. It cannot speak for the download's provenance
        # (nothing can, once the URL was overridden) but it does prove the NAS
        # received what this machine holds, which is the half of the problem
        # that a 42 MB SFTP introduces.
        if not sha:
            sha = sha256_file(tarball)

    ok_, err = install_ffmpeg_over_lan(root, tarball, sha, dry_run)
    if not ok_:
        print(f"NOTE: ffmpeg was NOT provisioned ({err}). Everything else "
              f"deploys; /music's queued ingest will answer 503 until ffmpeg "
              f"and ffprobe exist in {target_dir}.", file=sys.stderr)


def ytdl_web_source() -> Path:
    """The ytdl web/ tree to ship -- ytdl/web in this repo, unless
    YTDL_WEB_SRC points somewhere else."""
    raw = os.environ.get("YTDL_WEB_SRC", "").strip()
    return Path(raw) if raw else DEFAULT_YTDL_WEB_DIR


def binary_cache_path(url: str) -> Path:
    """Where a locally-fetched ytdl binary archive is kept between deploys.

    Namespaced by a digest of the URL for ffmpeg_cache_path's reason: two
    releases of the same tool are named the same thing, and a cache hit on
    somebody else's bytes is the one failure a cache must not have.
    """
    raw = os.environ.get("YTDL_BINARY_CACHE", "").strip()
    cache = Path(raw) if raw else YTDL_BINARY_CACHE_DIR
    name = posixpath.basename(urllib.parse.urlparse(url).path) or "download"
    return cache / f"{hashlib.sha256(url.encode()).hexdigest()[:12]}-{name}"


def fetch_pinned_file(url: str, sha256: str, file_override: str,
                      label: str) -> tuple[Path | None, str]:
    """Get one archive/binary onto THIS machine. Returns (path, error).

    fetch_ffmpeg_tarball's shape, for the operator-supplied downloads: three
    sources in order -- a file the operator already has, the local cache, then
    the network -- with the digest checked at every one of them INCLUDING the
    cache, whose whole risk is serving bytes that were right once.

    The digest is optional here in a way it is not for ffmpeg (there is no
    pinned URL to pin a hash to), and that is said out loud at the call site.
    A download that fails a supplied pin is DELETED rather than cached: keeping
    it would make every later deploy fail the same way for a reason that reads
    like tampering, long after the truncated transfer that caused it.
    """
    if file_override:
        path = Path(file_override)
        if not path.is_file():
            return None, f"{path} is not a file"
        if sha256 and sha256_file(path) != sha256:
            return None, f"{path} does not match the supplied sha256"
        print(f"using the {label} download at {path} "
              f"({human_bytes(path.stat().st_size)})")
        return path, ""

    cached = binary_cache_path(url)
    if cached.is_file():
        if not sha256 or sha256_file(cached) == sha256:
            print(f"using the cached {label} download at {cached} "
                  f"({human_bytes(cached.stat().st_size)})")
            return cached, ""
        print(f"NOTE: the cached {label} download at {cached} no longer matches "
              f"the supplied sha256 -- re-downloading", file=sys.stderr)

    cached.parent.mkdir(parents=True, exist_ok=True)
    part = cached.with_name(cached.name + ".part")
    print(f"fetching {url}")
    try:
        with urllib.request.urlopen(url, timeout=FFMPEG_FETCH_TIMEOUT) as resp:
            with part.open("wb") as out:
                shutil.copyfileobj(resp, out, 1 << 20)
    except Exception as exc:       # urllib raises URLError, socket.timeout, OSError...
        part.unlink(missing_ok=True)
        return None, f"{type(exc).__name__}: {exc}"
    if sha256 and sha256_file(part) != sha256:
        part.unlink(missing_ok=True)
        return None, ("the download does not match the supplied sha256 "
                      "-- nothing was sent to the NAS")
    part.replace(cached)
    print(f"fetched {human_bytes(cached.stat().st_size)} to {cached}")
    return cached, ""


def build_binary_install_script(target_dir: str, binary: str, staged: str,
                                staging: str, sha256: str) -> str:
    """Install one ytdl binary on the NAS from a file ALREADY STAGED there.

    build_ffmpeg_unpack_script's guarantees, generalised over the three shapes
    an upstream release comes in:
      - idempotent (an already-installed binary is left alone, so a redeploy
        does not re-download it);
      - the digest is checked BEFORE anything is unpacked or created, so a
        transfer that arrived wrong leaves no trace on the host at all;
      - the candidate is EXECUTED (`--version`) before it is moved into place:
        a build for the wrong architecture must not become the `claude` or
        `deno` the app finds on PATH;
      - nothing is deleted -- a previous install is only ever replaced by `mv`.

    The archive kind is decided from the staged FILENAME, not sniffed: .zip
    (deno's release format), .tar.gz/.tgz/.tar.xz, or anything else, which is
    taken to be the bare binary itself. `unzip` is not guaranteed on a TrueNAS
    host, so the zip branch falls back to python3's zipfile -- which is, and
    which the middleware itself runs on.
    """
    d = shell_quote(target_dir)
    tb = shell_quote(staged)
    b = shell_quote(binary)
    lower = staged.lower()
    # Same explicit `if !` as the ffmpeg unpack script rather than a bare
    # pipeline under `set -e`: a pipeline's exit status is its LAST command, so
    # `check | filter` silently reports the filter's success.
    verify = (
        f"if ! printf '%s  %s\\n' {shell_quote(sha256)} {tb} | sha256sum -c - "
        f">/dev/null 2>&1; then "
        f'echo "the staged {binary} download does not match the digest that was '
        f'sent -- the transfer was corrupted; nothing installed" >&2; exit 7; fi; '
    ) if sha256 else ""
    if lower.endswith(".zip"):
        extract = (f'if command -v unzip >/dev/null 2>&1; then '
                   f'unzip -oq {tb} -d "$t"; else '
                   f'python3 -c "import sys,zipfile; '
                   f'zipfile.ZipFile(sys.argv[1]).extractall(sys.argv[2])" '
                   f'{tb} "$t"; fi; ')
    elif lower.endswith((".tar.gz", ".tgz")):
        extract = f'tar -xzf {tb} -C "$t"; '
    elif lower.endswith((".tar.xz", ".txz")):
        extract = f'tar -xJf {tb} -C "$t"; '
    else:
        # A bare binary: copy it into the scratch dir under the name we are
        # about to look for, so the find below has one job in every branch.
        extract = f'cp {tb} "$t"/{b}; '
    return (
        f"set -e; "
        f"if [ -x {d}/{b} ]; then "
        f'echo "{binary} already provisioned at {target_dir}"; exit 0; fi; '
        f"{verify}"
        f"mkdir -p {d}; "
        f"t=$(mktemp -d /tmp/ccsync-ytdlbin.XXXXXX); "
        f'trap "rm -rf $t" EXIT; '
        f"{extract}"
        f'f=$(find "$t" -type f -name {b} | head -n 1); '
        f'if [ -z "$f" ]; then '
        f'echo "the {binary} download holds no {binary} executable" >&2; exit 1; fi; '
        f'install -o root -g root -m 755 "$f" {d}/{b}.new; '
        f"if ! {d}/{b}.new --version >/dev/null 2>&1; then "
        f'echo "the downloaded {binary} does not run on this host" >&2; '
        f"rm -f {d}/{b}.new; exit 1; fi; "
        f"mv {d}/{b}.new {d}/{b}; "
        f"chmod 755 {d}; "
        f"rm -rf {shell_quote(staging)}; "
        f'echo "{binary} provisioned: {target_dir}"'
    )


def binary_present(root: str, host_dir: str, binary: str, dry_run: bool) -> bool:
    """Does the NAS already have this binary?

    The remote script is idempotent on its own; this exists so a routine
    redeploy of an already-provisioned host does not fetch and push the archive
    only to be told "already provisioned". A failed or unreadable probe counts
    as absent -- re-provisioning is idempotent and cheap.
    """
    if dry_run:
        run_ssh(f"true  # [dry-run] would check whether {binary} is already on the host",
                dry_run=True)
        return False
    d = shell_quote(f"{root}/{host_dir}")
    rc, out, _err = run_ssh(f'if [ -x {d}/{shell_quote(binary)} ]; '
                            f'then echo yes; else echo no; fi')
    return rc == 0 and out.strip().splitlines()[-1:] == ["yes"]


def install_binary_over_lan(root: str, host_dir: str, binary: str,
                            local_file: Path | None, url: str, sha256: str,
                            dry_run: bool) -> tuple[bool, str]:
    """Push one fetched binary/archive to the NAS and install it. (ok, error).

    The same staged-then-verified-then-swapped route as everything else this
    script ships: SFTP into a fresh mktemp dir, prove the staged bytes are the
    bytes that were sent, and only then let root touch anything.
    """
    target_dir = f"{root}/{host_dir}"
    staging = make_staging_dir(dry_run, f"ccsync-{binary}-upload")
    # The name on the NAS keeps the URL's extension, because that is what
    # build_binary_install_script reads to decide how to unpack it.
    name = posixpath.basename(urllib.parse.urlparse(url).path) or binary
    staged = posixpath.join(staging, name)
    if dry_run:
        print(f"[dry-run] would SFTP the {binary} download to {staged} on the NAS "
              f"and install it into {target_dir}")
    else:
        expected_bytes = local_file.stat().st_size
        host, user, pw = truenas_conn_params()
        client = ssh_client(host, user, pw)
        try:
            sftp = client.open_sftp()
            sftp.put(str(local_file), staged)
            sftp.close()
        finally:
            client.close()
        rc, out, err = run_ssh(f"wc -c < {shell_quote(staged)}")
        staged_bytes = int(out.strip()) if rc == 0 and out.strip().isdigit() else -1
        if staged_bytes != expected_bytes:
            return False, (f"the staged {binary} download does not match what was "
                           f"sent ({staged_bytes} bytes on the NAS vs "
                           f"{expected_bytes} locally; staging left at {staging}): "
                           f"{err.strip()[:200]}")
        print(f"pushed {human_bytes(staged_bytes)} to staging {staging}")

    script = build_binary_install_script(target_dir, binary, staged, staging, sha256)
    rc, out, err = run_ssh('echo "$SUDO_PW" | sudo -S sh -c ' + shell_quote(script),
                           dry_run=dry_run, timeout=300)
    if rc != 0:
        return False, err.strip()[:300] or f"the install exited {rc}"
    if not dry_run:
        print(out.strip().splitlines()[-1] if out.strip()
              else f"{binary} provisioned: {target_dir}")
    return True, ""


def provision_ytdl_binaries(root: str, dry_run: bool) -> None:
    """Step 2f. NON-FATAL throughout, like provision_ffmpeg -- and one step
    softer: an UNSET url is a NOTE too, not just a failed download.

    Neither binary has a pinned URL in this repo (see YTDL_BINARIES), so on a
    host where the operator has not configured them yet this step does nothing
    and says what that costs. The alternative -- refusing to deploy -- would
    take the fleet dashboard down over an optional feature's optional download,
    which is the opposite of every other rule here.
    """
    for (name, host_dir, mount, binary, url_env, sha_env, file_env,
         consequence) in YTDL_BINARIES:
        target_dir = f"{root}/{host_dir}"
        url = os.environ.get(url_env, "").strip()
        sha = os.environ.get(sha_env, "").strip()
        local_override = os.environ.get(file_env, "").strip()
        if not url and not local_override:
            print(f"NOTE: {url_env} is not set -- skipping {name}. Everything else "
                  f"deploys; until a {name} binary exists in {target_dir} (mounted "
                  f"{mount}), {consequence}.", file=sys.stderr)
            continue
        if not sha:
            # Said out loud rather than checked silently against nothing: with
            # no digest, the 40 MB SFTP that follows is covered by exactly
            # nothing, and that is a choice the operator is making.
            print(f"NOTE: {sha_env} is not set -- the {name} download will NOT be "
                  f"checksummed.", file=sys.stderr)

        if binary_present(root, host_dir, binary, dry_run):
            print(f"{name} already provisioned at {target_dir}")
            continue

        local_file = None
        if dry_run:
            print(f"[dry-run] would fetch {url or local_override} and push it to "
                  f"the NAS over the LAN, installing {binary} into {target_dir}")
        else:
            local_file, err = fetch_pinned_file(url, sha, local_override, name)
            if local_file is None:
                print(f"NOTE: {name} was NOT provisioned -- the download could not "
                      f"be fetched here ({err}). Everything else deploys; until it "
                      f"exists in {target_dir}, {consequence}.\n"
                      f"  Retry, or point {file_env} at a file already on this "
                      f"machine.", file=sys.stderr)
                continue
            # With no supplied hash there is still one worth sending: the digest
            # of the file actually fetched. It cannot speak for the download's
            # provenance, but it does prove the NAS received what this machine
            # holds -- the half of the problem the SFTP introduces.
            if not sha:
                sha = sha256_file(local_file)

        ok_, err = install_binary_over_lan(root, host_dir, binary, local_file,
                                           url or local_override, sha, dry_run)
        if not ok_:
            print(f"NOTE: {name} was NOT provisioned ({err}). Everything else "
                  f"deploys; until it exists in {target_dir}, {consequence}.",
                  file=sys.stderr)


def weak_ingest_token(token: str) -> str | None:
    """None if `token` may guard the b-roll ingest write path, else the reason.

    Mirrors ccsync_dashboard.broll.check_ingest_token; keep the two in step.
    """
    token = (token or "").strip()
    if not token:
        return "is not set"
    if token.lower() in PLACEHOLDER_INGEST_TOKENS:
        return f"is the placeholder {token!r} (a value that is in the public repo)"
    if len(token) < MIN_INGEST_TOKEN_CHARS:
        return f"is only {len(token)} characters; at least {MIN_INGEST_TOKEN_CHARS} are required"
    if len(set(token)) < 8:
        return "has too little variety to be a random secret"
    return None


def iter_local_files(base: Path = LOCAL_DASHBOARD_DIR, excludes: set = EXCLUDE_DIRS):
    for path in sorted(base.rglob("*")):
        rel = path.relative_to(base)
        if any(part in excludes for part in rel.parts) or path.suffix == ".pyc":
            continue
        if path.is_file():
            yield path, rel.as_posix()


def tree_ssh_timeout(total_bytes: int) -> int:
    """Channel timeout for a remote step whose runtime scales with tree size.

    OPS-3 (2026-08-11): install_tree was written for the ~1 MB dashboard tree
    and took run_ssh's 120 s default. Steps 2c/2d then pushed 906 MB of proxies
    and 482 MB of encoder through the same code: the verify re-reads the whole
    tree (`find -exec cat + | wc -c`), the swap `cp -a`s it and `chown -R`s it,
    and none of that prints anything until it is finished -- and paramiko's
    channel timeout is an INACTIVITY timeout, so silence for 120 s is a
    socket.timeout on a step that was working. The ffmpeg paths in this same
    file already pass 300/600 for a 42 MB job.

    The rate is deliberately pessimistic (5 MB/s, three full passes): this is a
    ceiling that only matters when something is genuinely wedged, and being
    generous costs nothing on a healthy run.
    """
    return int(MIN_TREE_SSH_TIMEOUT + (total_bytes / TREE_BYTES_PER_SECOND) * 3)


def run_ssh_guarded(cmd: str, dry_run: bool, timeout: int):
    """run_ssh, but a dropped transport is an ERROR RESULT, not a traceback.

    OPS-3 (2026-08-11): a socket.timeout out of the swap step used to escape
    main() as an unhandled exception, so the container was never restarted and
    the deploy stopped between `mv app app.old.<ts>` and step 3 -- which is
    also the precondition for OPS-2. Every transport failure means the same
    thing to every caller here ("assume it did not finish; the live tree is
    only ever replaced by a rename, so it is still there"), so they all get the
    same answer as a non-zero rc.
    """
    try:
        return run_ssh(cmd, dry_run=dry_run, timeout=timeout)
    except Exception as exc:  # noqa: BLE001 - any transport failure is the same answer
        return 255, "", (f"the SSH channel dropped after {timeout}s "
                         f"({type(exc).__name__}: {exc})")


def make_staging_dir(dry_run: bool, slug: str = "ccsync-dashboard-upload",
                     parent: str = "/tmp") -> str:
    """Fresh unpredictable staging dir on the NAS (mode 700, owned by the SSH
    user). A fixed path could be pre-created world-writable or symlinked
    by any local account and later cp -a'd into /app as root (AUDIT SEC-11).

    `parent` is /tmp for the small code trees and <host-root>/staging for the
    1.4 GB music artefacts (OPS-8): /tmp on the NAS may be RAM-backed, and the
    staging dir is deliberately LEFT BEHIND on failure so the operator can
    inspect it.
    """
    parent = parent.rstrip("/") or "/tmp"
    if dry_run:
        return f"{parent}/{slug}.dryrun"
    rc, out, err = run_ssh(f"mktemp -d {shell_quote(parent + '/' + slug + '.XXXXXX')}")
    staging = out.strip().splitlines()[-1].strip() if out.strip() else ""
    if rc != 0 or not staging.startswith(f"{parent}/{slug}."):
        print(f"FAILED to create staging dir: {err or out}", file=sys.stderr)
        sys.exit(1)
    return staging


def prune_orphaned_staging(dry_run: bool) -> None:
    """Reclaim the NAS's /tmp from staging dirs a FAILED earlier run left.

    OPS-8 (2026-08-11): a failed push leaves its staging behind on purpose (the
    operator has to be able to inspect it), and a DETERMINISTIC failure -- an
    OPS-3 timeout, say -- repeats that every run, at ~1.4 GB a go for the music
    artefacts. /tmp on that host may be RAM-backed, so the third attempt can
    ENOSPC services with nothing to do with this deploy. Anything older than two
    hours cannot belong to this run; the dirs are mode 700 owned by the SSH
    user, so no sudo is involved. Entirely non-fatal -- this is housekeeping,
    not a deploy step.
    """
    cmd = (f"find /tmp -maxdepth 1 -name {shell_quote(STAGING_GLOB)} "
           f"-mmin +{STAGING_ORPHAN_MINUTES} -print -exec rm -rf {{}} + 2>/dev/null")
    rc, out, _err = run_ssh(cmd, dry_run=dry_run)
    if dry_run:
        return
    removed = [ln.strip() for ln in out.splitlines() if ln.strip()]
    if rc == 0 and removed:
        print(f"reclaimed {len(removed)} orphaned staging dir(s) from the NAS's "
              f"/tmp (left by an earlier FAILED run): {', '.join(removed[:4])}"
              + (" ..." if len(removed) > 4 else ""))


def local_manifest(base: Path = LOCAL_DASHBOARD_DIR,
                   excludes: set = EXCLUDE_DIRS) -> tuple[int, int]:
    """(file count, total bytes) of the tree we are about to ship.

    Both halves matter: a partial transfer that wrote every file but
    truncated the last one passes a count-only check (AUDIT INST-31).
    """
    files = list(iter_local_files(base, excludes))
    return len(files), sum(p.stat().st_size for p, _ in files)


def upload_tree(staging_dir: str, dry_run: bool, base: Path = LOCAL_DASHBOARD_DIR,
                excludes: set = EXCLUDE_DIRS) -> int:
    files = list(iter_local_files(base, excludes))
    if dry_run:
        print(f"[dry-run] would SFTP {len(files)} files from {base} "
              f"to {staging_dir} on the NAS")
        return len(files)

    host, user, pw = truenas_conn_params()
    client = ssh_client(host, user, pw)
    try:
        sftp = client.open_sftp()
        made: set[str] = set()
        for local, rel in files:
            remote = posixpath.join(staging_dir, rel)
            parent = posixpath.dirname(remote)
            parts = parent.split("/")
            for i in range(2, len(parts) + 1):
                d = "/".join(parts[:i])
                if d and d not in made:
                    try:
                        sftp.stat(d)
                    except FileNotFoundError:
                        sftp.mkdir(d)
                    made.add(d)
            sftp.put(str(local), remote)
        sftp.close()
    finally:
        client.close()
    print(f"uploaded {len(files)} files to staging {staging_dir}")
    return len(files)


def count_and_size_cmd(path: str) -> str:
    """Shell printing two lines for `path`: file count, then total bytes.

    `cat | wc -c` rather than `find -printf '%s'` so the check does not
    depend on GNU find; the tree is well under a megabyte.
    """
    q = shell_quote(path)
    return f"find {q} -type f | wc -l; find {q} -type f -exec cat {{}} + | wc -c"


def build_swap_script(root: str, staging: str, new_dir: str, old_dir: str,
                      expected_count: int, expected_bytes: int,
                      target_dir: str | None = None) -> str:
    """The install itself: build <root>/app.new from staging, verify it
    (count AND bytes), then swap it in with renames only.

    `target_dir` defaults to <root>/app; the b-roll code ships to
    <root>/broll-web through this same script, so both trees get the same
    never-gut-the-live-directory guarantees.

    Failure modes and what they leave behind:
      - cp/chown/chmod fails  -> app/ untouched, app.new left for inspection
      - verification fails    -> app/ untouched, exit 8
      - the swap-in mv fails  -> the previous app/ is renamed back, exit 9
    Nothing here ever deletes the running code: it is moved to app.old.<ts>
    and only pruned by a LATER successful install (most recent kept).
    """
    app_q = shell_quote(target_dir if target_dir is not None else root + "/app")
    new_q = shell_quote(new_dir)
    old_q = shell_quote(old_dir)
    staged_q = shell_quote(staging)
    return (
        f"set -e; "
        f"rm -rf {new_q}; mkdir -p {new_q}; "
        f"cp -a {staged_q}/. {new_q}/; "
        f"chown -R root:root {new_q}; "
        f"chmod -R u+rwX,go+rX,go-w {new_q}; "
        f"n=$(find {new_q} -type f | wc -l); "
        f"b=$(find {new_q} -type f -exec cat {{}} + | wc -c); "
        f'if [ "$n" -ne {expected_count} ] || [ "$b" -ne {expected_bytes} ]; then '
        f'echo "candidate tree incomplete: $n files/$b bytes, expected '
        f'{expected_count}/{expected_bytes} -- app left untouched" >&2; exit 8; fi; '
        f"mkdir -p {app_q}; "
        # The only step that touches the live dir, and it is a rename.
        f"mv {app_q} {old_q}; "
        f"mv {new_q} {app_q} || {{ mv {old_q} {app_q}; "
        f'echo "swap failed, previous code restored" >&2; exit 9; }}; '
        f"rm -rf {staged_q}"
    )


def build_prune_script(target: str, mountinfo_glob: str = "/proc/*/mountinfo") -> str:
    """Delete every <target>.old.* backup except the most recent one.

    Two things shape this:
      - `IFS= read -r` (and, before it, `xargs -d '\\n'`): the shell's default
        splitting breaks on any whitespace, so a space anywhere in the root
        (HOST_ROOT_RE permits one) would hand `rm -rf` path fragments.
      - OPS-2 (2026-08-11): the container bind-mounts <target> and keeps
        serving the INODE it mounted, so after a swap the LIVE code is the
        previous run's <target>.old.<ts>. A deploy that failed after the swap
        (and so never restarted the container) leaves it that way, and this
        prune would then rm -rf the directory the live dashboard is reading its
        templates and static files out of. A still-mounted dir shows up by name
        in some process's mountinfo, so skip those. The immediate restart in
        main() is the primary fix; this is the belt to its braces, and it fails
        SAFE in both directions -- no /proc, or no match, prunes exactly as
        before.
    """
    t_q = shell_quote(target)
    return (
        f"ls -1d {t_q}.old.* 2>/dev/null | sort | head -n -1 | "
        f"while IFS= read -r d; do "
        f'b=$(basename "$d"); '
        f'if grep -qsF -- "$b" {mountinfo_glob}; then '
        f'echo "keeping $d -- still bind-mounted by a running container" >&2; '
        f"continue; fi; "
        f'rm -rf "$d"; '
        f"done"
    )


def install_tree(root: str, target_name: str, source: Path, dry_run: bool,
                 excludes: set = EXCLUDE_DIRS,
                 staging_slug: str = "ccsync-dashboard-upload",
                 staging_parent: str = "/tmp") -> bool:
    """Ship `source` into <root>/<target_name>. True on success.

    Upload to a fresh staging dir, verify the staged copy is COMPLETE, build
    <target>.new from it, verify THAT, and only then swap it in. Constraints
    shaping this (AUDIT INST-31 / D-7):
      - No step may leave the live tree gutted. The old sequence was
        `find app -mindepth 1 -delete && cp -a staged/. app/`, so a cp failure
        half-way (full dataset, I/O error) left /app empty with nothing to roll
        back to. Now the only destructive-looking step is `mv app app.old.<ts>`,
        which is a rename: the previous code is still there, and the swap rolls
        back if the second mv fails.
      - Verification is count AND total bytes against the local manifest: a
        transfer that wrote every file but truncated the last one passes a
        count-only check.
      - Staging comes from mktemp (see make_staging_dir) so no other local
        account can pre-plant content that ends up root-copied into /app.
      - The swap changes the directory's inode, and the container bind-mounts
        it, so the running container keeps serving the OLD inode until it is
        restarted. Step 3 always restarts it (docker restart re-resolves bind
        mounts) -- a redeploy alone was observed not to, 2026-07-24.

    Used for both the dashboard tree and the b-roll app's tree: two mounts with
    the same posture (root-owned, world-readable, :ro in the container) deserve
    the same install guarantees, and the b-roll one is the mount whose silent
    emptiness made /broll disappear without a single error.
    """
    target = f"{root}/{target_name}"
    staging = make_staging_dir(dry_run, staging_slug, staging_parent)
    expected = upload_tree(staging, dry_run, source, excludes)
    expected_count, expected_bytes = local_manifest(source, excludes)
    if expected_count == 0:
        print(f"FAILED: {source} contains no files to ship -- refusing to install an "
              f"empty {target}", file=sys.stderr)
        return False
    new_dir_raw = f"{target}.new"
    old_dir_raw = f"{target}.old.{time.strftime('%Y%m%d%H%M%S')}"
    # Every remote step below re-reads or copies the whole tree, so its ceiling
    # has to scale with the tree (OPS-3): 120 s is right for the 1 MB dashboard
    # and wrong for 906 MB of proxies.
    timeout = tree_ssh_timeout(expected_bytes)

    # Verify the staged upload before anything on the NAS is moved.
    rc, out, err = run_ssh_guarded(count_and_size_cmd(staging), dry_run, timeout)
    if not dry_run:
        nums = [ln.strip() for ln in out.strip().splitlines() if ln.strip().isdigit()]
        staged_count = int(nums[0]) if rc == 0 and len(nums) >= 2 else -1
        staged_bytes = int(nums[1]) if rc == 0 and len(nums) >= 2 else -1
        if staged_count != expected_count or staged_bytes != expected_bytes:
            print(f"FAILED: staged tree does not match what was sent "
                  f"({staged_count} files/{staged_bytes} bytes on the NAS vs "
                  f"{expected_count}/{expected_bytes} locally) -- {target} is "
                  f"untouched (staging left at {staging} for inspection)"
                  + (f": {err.strip()[:200]}" if err.strip() else ""),
                  file=sys.stderr)
            return False
        print(f"staged tree verified: {staged_count} files, {staged_bytes} bytes")
    if expected != expected_count:  # upload_tree and the manifest must agree
        print(f"FAILED: internal manifest mismatch ({expected} vs {expected_count})",
              file=sys.stderr)
        return False

    swap = build_swap_script(root, staging, new_dir_raw, old_dir_raw,
                             expected_count, expected_bytes, target_dir=target)
    rc, _, err = run_ssh_guarded(
        'echo "$SUDO_PW" | sudo -S sh -c ' + shell_quote(swap),
        dry_run, timeout,
    )
    if rc != 0:
        print(f"FAILED to install code into {target}: {err.strip()[:500]}\n"
              f"  The previously installed code is still in place ({target} was only "
              f"replaced by an atomic rename, and that rename rolls back).\n"
              f"  Staging is left at {staging} and the candidate tree at {new_dir_raw} "
              f"for inspection.",
              file=sys.stderr)
        return False
    print(f"installed code: {target} (previous code kept at {old_dir_raw})")

    # Prune earlier backups now that THIS install has succeeded -- always
    # keeping the most recent one, i.e. the copy of the code we just
    # replaced, and never one a container is still reading (build_prune_script).
    # Non-fatal: a failure here changes nothing about the deploy.
    run_ssh_guarded('echo "$SUDO_PW" | sudo -S sh -c '
                    + shell_quote(build_prune_script(target)), dry_run, timeout)
    return True


def restart_dashboard_container(dry_run: bool) -> tuple[bool, str]:
    """`docker restart` the dashboard container. Returns (ok, stderr).

    /app/redeploy was observed NOT restarting the container on TrueNAS 25.10
    (2026-07-24: a stale process kept serving old in-memory code), so the
    restart is done directly. Compose name convention: ix-<app_name>-<service>-1.
    """
    container = f"ix-{APP_NAME}-dashboard-1"
    rc, _out, err = run_ssh(
        f'echo "$SUDO_PW" | sudo -S docker restart {shell_quote(container)}',
        dry_run=dry_run,
    )
    return (dry_run or rc == 0), err


def fail_after_app_swap(dry_run: bool) -> int:
    """Return 1 -- but restart the container onto the new code first.

    OPS-2 (2026-08-11): once `mv app app.old.<ts> && mv app.new app` has run,
    the container is serving an INODE that is now app.old.<ts> (a bind mount
    follows the directory it was given, not the name). Every step after the
    swap -- b-roll, music code, the 1.4 GB music data, ytdl -- used to `return
    1` straight out of main(), leaving it that way; the NEXT deploy's prune
    then keeps only the newest backup and `rm -rf`s the very directory the live
    dashboard was reading its templates and static files out of, so the fleet
    dashboard 500s on every page two runs later. The app tree that was just
    installed is complete and verified -- it is the later, less-proven steps
    that failed -- so restarting onto it is both safe and the thing that ends
    the exposure.
    """
    ok_restart, err = restart_dashboard_container(dry_run)
    if ok_restart:
        print("restarted the container onto the freshly installed code before "
              "failing -- it was still serving the previous code directory, "
              "which the next deploy would prune (OPS-2).")
    else:
        print(f"NOTE: could not restart the container after the app swap "
              f"({err.strip()[:200]}) -- harmless if the app is not installed "
              f"yet; otherwise restart {APP_NAME!r} from the TrueNAS UI before "
              f"the next deploy, because it is still serving the PREVIOUS code "
              f"directory.", file=sys.stderr)
    return 1


def app_installed(dry_run: bool) -> bool:
    # No query-filters param: the 25.10 middleware was observed returning []
    # for a filtered GET /app even when the app exists (2026-07-24 live run),
    # so fetch the full list and filter client-side.
    resp = truenas_api("GET", "/app", dry_run=dry_run)
    if dry_run:
        return False
    if not ok(resp):
        print(f"FAILED to query installed apps: HTTP {resp.status_code} {resp.text}",
              file=sys.stderr)
        sys.exit(1)
    return any(a.get("name") == APP_NAME for a in resp.json())


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=8480,
                    help="dashboard HTTP port, default 8480 (avoid 5432/8384/22000)")
    ap.add_argument("--host-root", default=DEFAULT_HOST_ROOT,
                    help=f"host dir for app+data, default {DEFAULT_HOST_ROOT}")
    ap.add_argument("--syncthing-gui-url",
                    default=os.environ.get("SYNCTHING_GUI_URL", DEFAULT_SYNCTHING_GUI_URL),
                    help="Syncthing GUI URL as seen FROM THE CONTAINER (host LAN IP works)")
    ap.add_argument("--bind-lan", default=os.environ.get("DASH_BIND_LAN", LAN_BIND_IP),
                    help=f"LAN address to publish the dashboard on, default {LAN_BIND_IP} "
                         f"(or DASH_BIND_LAN). It must be an address the NAS actually has, "
                         f"or Docker refuses to start the app.")
    ap.add_argument("--bind-tailnet",
                    default=os.environ.get("DASH_BIND_TAILNET", TAILNET_BIND_IP),
                    help=f"tailnet address to publish on, default {TAILNET_BIND_IP} "
                         f"(or DASH_BIND_TAILNET)")
    ap.add_argument("--image", default=os.environ.get("DASH_IMAGE", DEFAULT_IMAGE),
                    help=f"container base image, default {DEFAULT_IMAGE} (pinned on "
                         f"purpose; keep it in step with dashboard/deploy/compose.yaml)")
    ap.add_argument("--music-data",
                    default=os.environ.get("MUSIC_DATA_PUSH", MUSIC_DATA_PUSH_DEFAULT),
                    help="which of the music DATA artefacts to ship: 'auto' (default; "
                         "only the ones the NAS does not have yet), 'none', 'all', or a "
                         "comma-separated subset of "
                         f"{'/'.join(MUSIC_DATA_COMPONENTS)}. They total ~1.4 GB, so "
                         "they are deliberately not part of every dashboard deploy; "
                         "'all' is how you publish a re-index (or MUSIC_DATA_PUSH).")
    ap.add_argument("--no-ffmpeg", action="store_true",
                    help="skip provisioning static ffmpeg/ffprobe onto the host. "
                         "Only /music's queued ingest uses them, and it answers 503 "
                         "with a readable message when they are missing.")
    ap.add_argument("--no-ytdl-bins", action="store_true",
                    help="skip provisioning the Claude CLI and deno onto the host "
                         "for /ytdl. They are skipped anyway when YTDL_CLAUDE_URL / "
                         "YTDL_DENO_URL are unset -- this is for re-running a deploy "
                         "without re-probing the NAS for them.")
    ap.add_argument("--ffmpeg-fetch", choices=FFMPEG_FETCH_MODES,
                    default=os.environ.get("MUSIC_FFMPEG_FETCH",
                                           DEFAULT_FFMPEG_FETCH).strip()
                            or DEFAULT_FFMPEG_FETCH,
                    help="which machine downloads the 42 MB ffmpeg tarball: "
                         "'local' (default) fetches it here, checksums it and "
                         "pushes it over the LAN; 'remote' has the NAS curl it, "
                         "which is what the first deploy of this app timed out "
                         "on (the NAS pulls that host at ~28 kB/s).")
    ap.add_argument("--recreate", action="store_true",
                    help="delete and re-create the app so compose changes (env vars, "
                         "mounts, ports) take effect; host app/ and data/ dirs survive")
    ap.add_argument("--allow-any-host-root", action="store_true",
                    help="allow a --host-root outside /mnt/<pool>/apps/ccsync-dashboard. "
                         "The install REPLACES everything under <host-root>/app as root; "
                         "this flag exists so that can never happen by typo.")
    add_host_key_arg(ap)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    set_host_key_pin(args.host_key)

    if not LOCAL_DASHBOARD_DIR.is_dir():
        print(f"FAILED: {LOCAL_DASHBOARD_DIR} not found -- run from the repo", file=sys.stderr)
        return 1

    # b-roll pre-flight, BEFORE anything is uploaded or created. Two ways this
    # feature used to ship broken and silent, and neither is detectable from a
    # healthcheck: an empty broll-web (nothing ever copied the app in), and an
    # ingest token that was blank or the literal "REPLACE_ME" from the repo.
    # Both are refusals now, and both are refusals HERE, where the operator is
    # still looking at a terminal.
    broll_enabled = os.environ.get("DASH_BROLL_ENABLED", "1").strip() or "1"
    broll_src = broll_web_source()
    broll_ingest_token = os.environ.get("BROLL_INGEST_TOKEN", "").strip()
    # A --dry-run reports both problems instead of returning 1: it touches
    # nothing, and it must stay runnable on a machine that has neither the
    # b-roll checkout nor the production secrets (the same "only works on one
    # workstation" trap the b-roll tests fell into). A real run refuses.
    ship_broll = broll_enabled == "1"
    if broll_enabled == "1":
        if not (broll_src / "app" / "main.py").is_file():
            print(
                f"{'[dry-run] would FAIL' if args.dry_run else 'FAILED'}: "
                f"DASH_BROLL_ENABLED=1 but no b-roll app at {broll_src}\n"
                f"  (looked for {broll_src / 'app' / 'main.py'}).\n"
                f"  The container mounts <host-root>/broll-web read-only at /broll-app "
                f"and imports app.main from it; deploying without shipping that tree "
                f"gives a dashboard whose /broll silently does not exist.\n"
                f"  broll/web is part of THIS repo, so a missing one means a "
                f"broken or partial checkout -- fix the checkout, point "
                f"BROLL_WEB_SRC at a web/ tree elsewhere, or set "
                f"DASH_BROLL_ENABLED=0 to deploy without the b-roll UI.",
                file=sys.stderr)
            if not args.dry_run:
                return 1
            ship_broll = False
        problem = weak_ingest_token(broll_ingest_token)
        if problem:
            print(
                f"{'[dry-run] would FAIL' if args.dry_run else 'FAILED'}: "
                f"DASH_BROLL_ENABLED=1 but BROLL_INGEST_TOKEN {problem}.\n"
                f"  /broll/api/ingest/* is a WRITE path the indexer reaches with no "
                f"session at all -- this token is the only thing guarding it, and the "
                f"dashboard refuses to start without a strong one.\n"
                f"  Generate one with `openssl rand -hex 24`, or set "
                f"DASH_BROLL_ENABLED=0.",
                file=sys.stderr)
            if not args.dry_run:
                return 1

    # Music pre-flight. Deliberately a WARNING and a skip rather than a refusal,
    # unlike b-roll's: DASH_BROLL_ENABLED=1 is an operator saying "I want this
    # feature", so a missing tree contradicts them and is an error. Nothing on
    # this command line asserts anything about music -- shipping the tree IS the
    # switch -- so a checkout without it deploys a dashboard whose /music mount
    # reports "absent" and whose nav link is simply not there, which is the
    # documented, supported state.
    music_src = music_web_source()
    music_data_src = music_data_source()
    ship_music = (music_src / "musicweb" / "main.py").is_file()
    if not ship_music:
        print(f"NOTE: no music app at {music_src} "
              f"(looked for {music_src / 'musicweb' / 'main.py'}) -- deploying "
              f"WITHOUT the /music UI; the dashboard will report the mount "
              f"'absent' and hide the nav link. music/web is part of THIS repo, "
              f"so a missing one means a partial checkout; MUSIC_WEB_SRC points "
              f"at a web/ tree elsewhere.", file=sys.stderr)
    # ytdl pre-flight: the music rule, verbatim. Nothing on this command line
    # asserts that the operator wants the YouTube downloader -- shipping the
    # tree IS the switch -- so a checkout without it deploys a dashboard whose
    # /ytdl mount reports "absent" and whose nav link is simply not there.
    ytdl_src = ytdl_web_source()
    ship_ytdl = (ytdl_src / "ytdlweb" / "main.py").is_file()
    if not ship_ytdl:
        print(f"NOTE: no ytdl app at {ytdl_src} "
              f"(looked for {ytdl_src / 'ytdlweb' / 'main.py'}) -- deploying "
              f"WITHOUT the /ytdl UI; the dashboard will report the mount "
              f"'absent' and hide the nav link. ytdl/web is part of THIS repo, "
              f"so a missing one means a partial checkout; YTDL_WEB_SRC points "
              f"at a web/ tree elsewhere.", file=sys.stderr)
    music_data_mode = (args.music_data or "").strip().lower() or MUSIC_DATA_PUSH_DEFAULT
    music_forced, music_data_err = parse_music_data_push(music_data_mode)
    if music_data_err:
        print(f"FAILED: {music_data_err}", file=sys.stderr)
        return 1

    # Secrets, resolved in one place and AFTER every check that needs the real
    # value (the b-roll pre-flight above). --dry-run prints the entire compose
    # body, which is the point of it -- but a token pasted into a bug report or
    # left in terminal scrollback is a live credential, and four of the five
    # here used to be printed in the clear while only TRUENAS_PW was masked.
    secrets = resolve_compose_secrets(args.dry_run, broll_ingest_token)
    api_key = secrets["SYNCTHING_API_KEY"]
    token = secrets["DASH_REPORT_TOKEN"]
    session_secret = secrets["DASH_SESSION_SECRET"]
    broll_ingest_token = secrets["BROLL_INGEST_TOKEN"]
    truenas_pw = secrets["TRUENAS_PW"]
    admin_users = os.environ.get("DASH_ADMIN_USERS", "truenas_admin")
    # "0" keeps today's behaviour (self-signed NAS cert trusted); the dashboard
    # reads the same var (truenas_client._verify_setting).
    truenas_verify_ssl = os.environ.get("TRUENAS_VERIFY_SSL", "0").strip() or "0"
    # Host and user only -- neither is a secret, and both appear in the printed
    # ssh lines anyway. The password for the compose body comes from `secrets`;
    # run_ssh and truenas_api re-read TRUENAS_PW themselves for their own calls.
    truenas_host, truenas_user, _ = truenas_conn_params(dry_run=args.dry_run)

    root = args.host_root.rstrip("/")
    if not HOST_ROOT_RE.match(root):
        if not args.allow_any_host_root:
            print(
                f"REFUSING --host-root {root!r}: it is not under "
                f"/mnt/<pool>/apps/ccsync-dashboard.\n"
                f"  This install replaces EVERYTHING under {root}/app as root, so a "
                f"mistyped root (a project tree, a share) would take its contents with "
                f"it.\n"
                f"  Use {DEFAULT_HOST_ROOT} (the default), or pass --allow-any-host-root "
                f"if this really is a deliberate alternate deployment.",
                file=sys.stderr)
            return 1
        print(f"WARNING: --allow-any-host-root given. {root}/app will be REPLACED "
              f"wholesale (its current contents are moved aside to {root}/app.old.<ts>, "
              f"not deleted); {root}/data is left untouched.", file=sys.stderr)

    # Step 1: host dirs. app/ is root-owned and world-readable but NOT
    # group-writable -- editors have shell accounts in group 3001, and a
    # group-writable code dir behind the container's `command: run.sh` was an
    # editor->NAS-admin escalation (AUDIT C-1). The container only ever READS
    # /app (mounted :ro).
    #
    # data/ and venv/ are create-only (contents never touched on re-run) and
    # are owned 3000:3000, NOT 3000:3001. AUDIT C-2: with group `editors` and
    # mode 770, every editor could write into /data -- where run.sh kept the
    # venv it execs `bin/python` from, guarded only by an md5 stamp file in
    # the same directory. Swapping that interpreter was arbitrary code
    # execution as the dashboard user, in a container holding TRUENAS_PW.
    # The venv now has its own volume at 700, and dashboard.db + packages/
    # sit under a /data no editor can traverse.
    rc, _, err = run_ssh(
        'echo "$SUDO_PW" | sudo -S sh -c '
        + shell_quote(
            f"mkdir -p {shell_quote(root + '/app')} {shell_quote(root + '/data')} "
            f"{shell_quote(root + '/venv')} {shell_quote(root + '/broll-web')} && "
            f"chown root:root {shell_quote(root)} {shell_quote(root + '/app')} && "
            f"chmod 755 {shell_quote(root)} {shell_quote(root + '/app')} && "
            f"chown -R 3000:3000 {shell_quote(root + '/data')} && "
            f"chmod 770 {shell_quote(root + '/data')} && "
            f"chown -R 3000:3000 {shell_quote(root + '/venv')} && "
            f"chmod 700 {shell_quote(root + '/venv')} && "
            # b-roll CODE: root-owned and world-readable, mounted :ro -- same
            # posture as app/, so the process running it cannot rewrite it.
            # (There is deliberately no <root>/broll-data any more: nothing
            # ever mounted it. The b-roll DATA root is the shared archive,
            # prepared separately below.)
            f"chown root:root {shell_quote(root + '/broll-web')} && "
            f"chmod 755 {shell_quote(root + '/broll-web')} && "
            # music CODE and the two read-only data artefacts: root-owned,
            # world-readable, mounted :ro -- the /app posture, because none of
            # the three is ever written by the container. Same for the ffmpeg
            # binaries, which are executed by it and must not be replaceable
            # from inside it.
            f"mkdir -p {shell_quote(root + '/music-web')} "
            f"{shell_quote(root + '/music-encoder')} "
            f"{shell_quote(root + '/music-proxies')} "
            f"{shell_quote(root + '/ffmpeg')} && "
            f"chown root:root {shell_quote(root + '/music-web')} "
            f"{shell_quote(root + '/music-encoder')} "
            f"{shell_quote(root + '/music-proxies')} "
            f"{shell_quote(root + '/ffmpeg')} && "
            f"chmod 755 {shell_quote(root + '/music-web')} "
            f"{shell_quote(root + '/music-encoder')} "
            f"{shell_quote(root + '/music-proxies')} "
            f"{shell_quote(root + '/ffmpeg')} && "
            # music DATA root: the one music path the container writes
            # (music.db + the ingest staging/ dir), so it gets data/'s posture
            # -- 3000:3000 mode 770, group 3000 and NOT 3001/editors, for the
            # same C-2 reason. Create-only: an existing one is left alone, and
            # in particular the live music.db is never touched from here.
            f"mkdir -p {shell_quote(root + '/music-data')} && "
            f"chown 3000:3000 {shell_quote(root + '/music-data')} && "
            f"chmod 770 {shell_quote(root + '/music-data')} && "
            # ytdl CODE and the two binary dirs: the /app posture again --
            # root-owned, world-readable, mounted :ro. The binaries in
            # particular are EXECUTED by the container and must not be
            # replaceable from inside it.
            f"mkdir -p {shell_quote(root + '/ytdl-web')} "
            f"{shell_quote(root + '/claude-bin')} "
            f"{shell_quote(root + '/deno')} && "
            f"chown root:root {shell_quote(root + '/ytdl-web')} "
            f"{shell_quote(root + '/claude-bin')} "
            f"{shell_quote(root + '/deno')} && "
            f"chmod 755 {shell_quote(root + '/ytdl-web')} "
            f"{shell_quote(root + '/claude-bin')} "
            f"{shell_quote(root + '/deno')} && "
            # ytdl DATA root: ytdl.db and the worker's scratch, so data/'s
            # posture -- 3000:3000 mode 770, group 3000 and NOT 3001/editors,
            # for the same C-2 reason. Create-only; an existing one (with a
            # live job ledger in it) is left alone.
            f"mkdir -p {shell_quote(root + '/ytdl-data')} && "
            f"chown 3000:3000 {shell_quote(root + '/ytdl-data')} && "
            f"chmod 770 {shell_quote(root + '/ytdl-data')} && "
            # The Claude home: 700, tighter than everything else here, because
            # it holds a live OAuth credential for the user's own Claude
            # account after the one-time `claude /login`. Same posture as the
            # venv volume, and for the same class of reason.
            f"mkdir -p {shell_quote(root + '/claude-home')} && "
            f"chown 3000:3000 {shell_quote(root + '/claude-home')} && "
            f"chmod 700 {shell_quote(root + '/claude-home')}"
        ),
        dry_run=args.dry_run,
    )
    if rc != 0:
        print(f"FAILED to create host dirs: {err}", file=sys.stderr)
        return 1
    print(f"host dirs ready: {root}/app, {root}/venv, {root}/data, {root}/broll-web, "
          f"{root}/music-web, {root}/music-data, {root}/music-encoder, "
          f"{root}/music-proxies, {root}/ffmpeg, {root}/ytdl-web, {root}/ytdl-data, "
          f"{root}/claude-home, {root}/claude-bin, {root}/deno")

    # Debris from a previous FAILED run, before this one adds its own (OPS-8).
    prune_orphaned_staging(args.dry_run)

    # Where the 1.4 GB music artefacts are staged (OPS-8). /tmp on the NAS may
    # be RAM-backed and holds the whole component until the swap `cp -a`s it
    # into place; <host-root>/staging is on the same pool as the target, so the
    # push costs the pool what it is about to cost it anyway. Owned by the SSH
    # user at 700 because mktemp runs unprivileged (AUDIT SEC-11 still applies).
    # ENTIRELY OPTIONAL: this is its own non-fatal call rather than another
    # `&&` in the chain above, and /tmp remains the fallback -- a deploy must
    # not fail over where it puts a temporary directory.
    music_staging_parent = "/tmp"
    if ship_music and music_data_mode != "none":
        staging_root = f"{root}/staging"
        rc_stage, _, stage_err = run_ssh(
            'echo "$SUDO_PW" | sudo -S sh -c '
            + shell_quote(
                f"mkdir -p {shell_quote(staging_root)} && "
                f"chown {shell_quote(truenas_user)} {shell_quote(staging_root)} && "
                f"chmod 700 {shell_quote(staging_root)}"
            ),
            dry_run=args.dry_run,
        )
        if args.dry_run or rc_stage == 0:
            music_staging_parent = staging_root
        else:
            print(f"NOTE: could not prepare {staging_root} "
                  f"({stage_err.strip()[:200]}) -- staging the music data in "
                  f"/tmp instead", file=sys.stderr)

    # The b-roll DATA root: the one the compose file actually bind-mounts at
    # /broll-data. It is NOT under <host-root> -- it is the shared archive
    # itself, beside Projects/ under Creators_Club, which is what makes it
    # P:\Assets\B-roll Archive on an editor's machine. Two things follow:
    #
    #   - It must exist and be writable by the container's uid BEFORE the app
    #     starts. Left to Docker, the bind source is auto-created root:root
    #     0755, the container (3000:3001) cannot create broll.db in it, and
    #     every /broll request answers "unable to open database file".
    #   - Its posture is Projects', not /data's: broll:editors 2770 setgid,
    #     exactly what setup_tree.py applies. It is emphatically NOT chmod 770
    #     group-3000 -- that is the mode for a private app directory, and this
    #     tree is browsed over SMB by the same editors whose proxies live in
    #     it. That change would have locked them out of their own archive.
    #
    # Only the archive root and the four directories the app itself creates are
    # touched, non-recursively: the tree is tens of gigabytes and an existing
    # archive's contents are none of this script's business. Pre-creating those
    # four also side-steps run.sh's `umask 077`, under which the app would make
    # them 0700/uid-3000 and invisible over SMB.
    #
    # chmod is non-fatal: TrueNAS datasets with aclmode=restricted (NFSv4 ACLs)
    # refuse chmod outright, even for root -- setup_tree.py handles it the same
    # way. Ownership still applies. NOTE FOR THE NAS: whether these mode bits
    # survive on THIS dataset is unverified from here; check with `ls -ld` (and
    # `getfacl`) after the first install.
    if broll_enabled == "1":
        archive_dirs = [DEFAULT_BROLL_ARCHIVE_ROOT] + [
            f"{DEFAULT_BROLL_ARCHIVE_ROOT}/{d}"
            for d in ("proxies", "sprites", "posters", "sheets")
        ]
        quoted = " ".join(shell_quote(d) for d in archive_dirs)
        rc, _, err = run_ssh(
            'echo "$SUDO_PW" | sudo -S sh -c '
            + shell_quote(
                f"mkdir -p {quoted} && chown 3000:3001 {quoted} && "
                f"{{ chmod 2770 {quoted} || "
                f'echo "NOTE: chmod blocked on this dataset (likely ZFS '
                f'aclmode=restricted) -- ownership above still applied"; }}'
            ),
            dry_run=args.dry_run,
        )
        if rc != 0:
            print(f"FAILED to prepare the b-roll archive root "
                  f"{DEFAULT_BROLL_ARCHIVE_ROOT}: {err}", file=sys.stderr)
            return 1
        print(f"b-roll data root ready: {DEFAULT_BROLL_ARCHIVE_ROOT} "
              f"(broll:editors 2770, same as Projects/)")

    # The music library: the same shape of thing as the b-roll archive, and
    # prepared the same way. It is the SHARE ITSELF (P:\Assets\Music to an
    # editor, W:\Creators_Club\Assets\Music to the base rig), not a private
    # copy, and it is mounted READ-WRITE because queued ingest moves each
    # accepted upload into it. broll:editors 2770 setgid, exactly like
    # Projects/ and the b-roll archive -- emphatically not 770/group-3000,
    # which would lock the editors who browse this library out of it.
    #
    # Left to Docker, an absent bind source is auto-created root:root 0755 and
    # every ingest fails to write into it. Only the root itself is touched,
    # non-recursively: the library is ~9.5 GB and its contents are none of this
    # script's business. chmod is non-fatal for the same reason as above (ZFS
    # aclmode=restricted refuses chmod outright, even for root).
    if ship_music:
        lib_q = shell_quote(DEFAULT_MUSIC_LIBRARY_ROOT)
        rc, _, err = run_ssh(
            'echo "$SUDO_PW" | sudo -S sh -c '
            + shell_quote(
                f"mkdir -p {lib_q} && chown 3000:3001 {lib_q} && "
                f"{{ chmod 2770 {lib_q} || "
                f'echo "NOTE: chmod blocked on this dataset (likely ZFS '
                f'aclmode=restricted) -- ownership above still applied"; }}'
            ),
            dry_run=args.dry_run,
        )
        if rc != 0:
            print(f"FAILED to prepare the music library root "
                  f"{DEFAULT_MUSIC_LIBRARY_ROOT}: {err}", file=sys.stderr)
            return 1
        print(f"music library root ready: {DEFAULT_MUSIC_LIBRARY_ROOT} "
              f"(broll:editors 2770, same as Projects/)")

    # ffmpeg/ffprobe for /music's queued ingest. NON-FATAL by design, and by
    # default fetched HERE and pushed over the LAN rather than downloaded by the
    # NAS -- see provision_ffmpeg.
    # ...and for /ytdl, which re-encodes to the edit-ready H.264/AAC/CFR
    # profile with the same binaries off the same mount. Either mount being
    # shipped is reason enough to provision them; the step is idempotent.
    if (ship_music or ship_ytdl) and not args.no_ffmpeg:
        provision_ffmpeg(root, args.ffmpeg_fetch, args.dry_run)

    # The Claude CLI and deno for /ytdl. Non-fatal in every direction,
    # including an unset URL: see provision_ytdl_binaries. ffmpeg is not
    # repeated here -- the step above covers both mounts.
    if ship_ytdl and not args.no_ytdl_bins:
        provision_ytdl_binaries(root, args.dry_run)

    # A pre-C-2 deployment has an editor-writable venv sitting inside data/.
    # Move it aside (never delete: no-deletion rule) so run.sh rebuilds a
    # clean one at /venv and nothing keeps executing the old interpreter.
    quarantine = f"{root}/data/venv.quarantined.{time.strftime('%Y%m%d%H%M%S')}"
    retire_old_venv = (
        f"if [ -d {shell_quote(root + '/data/venv')} ]; then "
        f"mv {shell_quote(root + '/data/venv')} {shell_quote(quarantine)} && "
        f"chmod 700 {shell_quote(quarantine)} && "
        f'echo "retired the old editor-writable venv to {quarantine}"; fi'
    )
    rc, _, err = run_ssh('echo "$SUDO_PW" | sudo -S sh -c ' + shell_quote(retire_old_venv),
                         dry_run=args.dry_run)
    if not args.dry_run and rc != 0:
        # A failed mv leaves the editor-writable venv (the C-2 hazard) in
        # place; reporting success here would defeat the quarantine's point.
        print(f"FAILED to retire the old editor-writable venv at "
              f"{root}/data/venv: {err.strip() or 'mv/chmod failed'}",
              file=sys.stderr)
        return 1

    # Step 2: ship the dashboard code (see install_tree for the guarantees).
    if not install_tree(root, "app", LOCAL_DASHBOARD_DIR, args.dry_run):
        return 1

    # Step 2b: ship the b-roll web/ tree into broll-web. Without this the
    # directory the container mounts at /broll-app is EMPTY, `from app.main
    # import app` raises ModuleNotFoundError, the mount is skipped, and the
    # operator gets a green healthcheck with a missing feature.
    if ship_broll:
        if not install_tree(root, "broll-web", broll_src, args.dry_run,
                            excludes=BROLL_EXCLUDE_DIRS,
                            staging_slug="ccsync-brollweb-upload"):
            return fail_after_app_swap(args.dry_run)

    # Step 2c: ship the music web/ tree into music-web, the same staged-verify-
    # swap route, for the same reason -- the container mounts it read-only at
    # /music-app and imports musicweb.main off PYTHONPATH, so an empty dir there
    # is a silently absent feature behind a green healthcheck. data/ is excluded
    # (MUSIC_EXCLUDE_DIRS) and shipped by step 2d instead.
    if ship_music:
        if not install_tree(root, "music-web", music_src, args.dry_run,
                            excludes=MUSIC_EXCLUDE_DIRS,
                            staging_slug="ccsync-musicweb-upload"):
            return fail_after_app_swap(args.dry_run)

    # Step 2d: the music DATA artefacts -- the index, the text-encoder model and
    # the preview proxies. Unlike b-roll, whose data root is a shared archive
    # the container writes into itself, none of this can be generated on the
    # NAS: the index and the proxies come off the base rig, and the encoder is
    # an exported artefact. They are also ~1.4 GB, so they do NOT ride along
    # with every dashboard deploy: --music-data auto ships only what the NAS
    # does not have, and --music-data all/db/encoder/proxies force a re-push.
    if ship_music and music_data_mode != "none":
        if not music_data_src.is_dir():
            print(f"NOTE: no music data at {music_data_src} -- shipping the code "
                  f"only. /music will mount and be EMPTY (and /music/api/search "
                  f"will 500 without text_encoder/). Point MUSIC_DATA_SRC at the "
                  f"base rig's music/web/data, or re-run once it exists.",
                  file=sys.stderr)
        else:
            wanted = music_components_to_push(root, music_data_mode, music_forced,
                                              args.dry_run)
            sizes = music_data_sizes(music_data_src)
            missing_locally = [c for c in wanted if c not in sizes]
            if missing_locally:
                print(f"NOTE: not shipping {', '.join(missing_locally)} -- absent "
                      f"from {music_data_src}. (text_encoder/ is exported by "
                      f"music/indexer/export_text_encoder.py and proxies/ are "
                      f"generated on the base rig.)", file=sys.stderr)
                wanted = [c for c in wanted if c in sizes]
            if not wanted:
                print(f"music data: nothing to ship (--music-data {music_data_mode})")
            else:
                total = sum(sizes[c][1] for c in wanted)
                why = "forced" if music_forced else "not on the NAS yet"
                breakdown = ", ".join(f"{c} {human_bytes(sizes[c][1])}"
                                      for c in wanted)
                print(f"music data to ship ({why}): {breakdown} "
                      f"-- {human_bytes(total)} total")
            for component in wanted:
                if component == "db":
                    if not install_music_db(root, music_data_src, args.dry_run,
                                            staging_parent=music_staging_parent):
                        return fail_after_app_swap(args.dry_run)
                    continue
                sub, target = MUSIC_DATA_TREES[component]
                if not install_tree(root, target, music_data_src / sub, args.dry_run,
                                    excludes=MUSIC_EXCLUDE_DIRS,
                                    staging_slug=f"ccsync-music{component}-upload",
                                    staging_parent=music_staging_parent):
                    return fail_after_app_swap(args.dry_run)

    # Step 2f: ship the ytdl web/ tree into ytdl-web, the same staged-verify-
    # swap route as broll-web and music-web -- the container mounts it
    # read-only at /ytdl-app and imports ytdlweb.main off PYTHONPATH, so an
    # empty dir there is a silently absent feature behind a green healthcheck.
    # There is no data push to go with it: ytdl.db is created by the container
    # in its own writable /ytdl-data on first request.
    if ship_ytdl:
        if not install_tree(root, "ytdl-web", ytdl_src, args.dry_run,
                            excludes=YTDL_EXCLUDE_DIRS,
                            staging_slug="ccsync-ytdlweb-upload"):
            return fail_after_app_swap(args.dry_run)

    # Step 3: create or redeploy the custom app.
    if args.recreate and app_installed(args.dry_run):
        resp = truenas_api("DELETE", f"/app/id/{APP_NAME}",
                           json_body={"remove_ix_volumes": False}, dry_run=args.dry_run)
        if args.dry_run:
            print(f"[dry-run] would delete app {APP_NAME} and re-create it")
        elif not ok(resp):
            print(f"FAILED to delete app for --recreate: HTTP {resp.status_code} {resp.text}",
                  file=sys.stderr)
            return 1
        else:
            try:
                job_id = resp.json()
            except ValueError:
                job_id = None
            if isinstance(job_id, int):
                state, job_err = wait_for_job(job_id, timeout=180)
                if state != "SUCCESS":
                    print(f"FAILED: app delete job ended {state}: {job_err}", file=sys.stderr)
                    return 1
            print(f"deleted app for re-create: {APP_NAME}")

    if app_installed(args.dry_run):
        container = f"ix-{APP_NAME}-dashboard-1"
        restarted, err = restart_dashboard_container(args.dry_run)
        if restarted:
            print(f"restarted container: {container}")
            print("NOTE: only the CODE was updated. Compose-level changes -- bind "
                  "addresses (--bind-lan/--bind-tailnet), image tag, healthcheck, env "
                  "vars -- need --recreate to take effect (pass DASH_REPORT_TOKEN and "
                  "DASH_SESSION_SECRET again when you do).")
        else:
            print(f"NOTE: docker restart failed ({err.strip()[:200]}); restart the "
                  f"{APP_NAME!r} app from the TrueNAS UI to pick up the new code.")
        return 0

    body = {
        "custom_app": True,
        "app_name": APP_NAME,
        "custom_compose_config": compose_config(
            args.port, root, args.syncthing_gui_url, api_key, token,
            session_secret, admin_users, truenas_host, truenas_user, truenas_pw,
            truenas_verify_ssl=truenas_verify_ssl,
            bind_lan=args.bind_lan, bind_tailnet=args.bind_tailnet,
            image=args.image,
            broll_enabled=broll_enabled,
            # Validated in the pre-flight above (weak_ingest_token) against the
            # REAL value, and masked afterwards for --dry-run only: the
            # dashboard refuses to START with a blank, placeholder or short
            # one, because this guards a write path no session protects.
            broll_ingest_token=broll_ingest_token,
            broll_creators_shares=os.environ.get(
                "BROLL_CREATORS_SHARES", "mofa-disaster"),
        ),
    }
    resp = truenas_api("POST", "/app", json_body=body, dry_run=args.dry_run)
    if args.dry_run:
        print(f"[dry-run] would create custom app {APP_NAME} on port {args.port}")
        return 0
    if not ok(resp):
        print(f"FAILED to create custom app: HTTP {resp.status_code} {resp.text}",
              file=sys.stderr)
        print("Manual fallback: TrueNAS UI > Apps > Discover Apps > (...) > Install via "
              "YAML, paste dashboard/deploy/compose.yaml and fill in SYNCTHING_API_KEY "
              "and DASH_REPORT_TOKEN.", file=sys.stderr)
        return 1
    print(f"installed custom app: {APP_NAME} on port {args.port}")
    print(f"Next: open http://<tailnet-ip>:{args.port}/ and check /api/v1/health; then set "
          f"dashboard_url/dashboard_token in each editor's ~/.ccsync/config.toml.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
