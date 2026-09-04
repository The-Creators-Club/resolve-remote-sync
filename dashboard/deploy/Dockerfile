# A self-contained image for ccsync-dashboard -- COMMERCIAL_READINESS.md item
# 12, added 2026-08-17.
#
# WHAT THIS REPLACES, AND WHAT IT DOES NOT
#
# Until now this deployment had NO image build at all: compose ran a stock
# pinned python:3.12.7-slim, bind-mounted the code read-only at /app and a
# host directory at /venv, and run.sh pip-installed the dependencies into that
# bind mount on the first boot after requirements.txt changed. That mode still
# works and is still the DEFAULT -- the live sites use it (docs/DOCKER.md,
# "bind-mount mode"). Nothing here changes compose.yaml.
#
# What that mode costs, and what this image buys:
#   - a container boot could depend on PyPI being reachable from the NAS;
#   - the deployed dependency set was whatever pip resolved on the day of the
#     first boot, per site, with no record of it anywhere;
#   - and "what is actually installed in the container" was on
#     COMMERCIAL_READINESS.md's "not verified from the repo" list.
# Here the dependency set is `requirements.lock` installed with
# `--require-hashes`, resolved once on a developer machine and identical on
# every site, and the image is a build artefact that can be scanned, signed and
# rolled back as one thing.
#
# BUILD FROM THE REPO ROOT -- the image carries four trees from four
# directories, and .dockerignore keeps the 2 GB repo down to ~10 MB of context:
#
#   docker build -f dashboard/deploy/Dockerfile -t ccsync-dashboard:0.4.1 .
#
# NOT BUILT ON THIS MACHINE. Docker Desktop is not installed on the base rig
# (checked 2026-08-17), so this file has never been through `docker build`.
# Treat the first build as part of the migration, not as a formality.

# Pinned BY DIGEST, not just by tag. compose.yaml pins python:3.12.7-slim
# because an unpinned 3.12-slim silently changes underneath a redeploy; a tag
# is still mutable in principle, and this image is the thing a customer's
# security review asks about. The digest is the multi-arch index for
# python:3.12.7-slim (registry-1.docker.io, fetched 2026-08-17), so it resolves
# on both amd64 (TrueNAS, the DS423+ is x86_64) and arm64.
#
# Bump it deliberately, together with compose.yaml's tag, and re-run the tests.
ARG BASE_IMAGE=python:3.12.7-slim@sha256:60d9996b6a8a3689d36db740b49f4327be3be09a21122bd02fb8895abb38b50d

# --- stage 1: the dependency venv ------------------------------------------
#
# A separate stage so the runtime image carries the venv but not pip's caches,
# and so a lockfile change rebuilds only this layer.
FROM ${BASE_IMAGE} AS deps

# The container-side dependency set, hash-pinned. This is the SAME file
# deploy/run.sh prefers in bind-mount mode, so the two modes install the
# identical closure -- there is exactly one answer to "what is in the venv".
#
# --require-hashes is not decoration: it is what makes a compromised or
# typo-squatted PyPI mirror a build failure instead of a shipped backdoor. It
# also forbids any unpinned transitive dependency, which is why the lock is
# generated with `uv pip compile --universal --generate-hashes` (docs/RELEASE.md).
COPY dashboard/deploy/requirements.lock /tmp/requirements.lock

# --no-cache-dir: the cache is dead weight in a layer that is copied wholesale
# into the next stage anyway. `python -m venv` rather than installing into the
# system site-packages, so the runtime path is byte-for-byte the one run.sh
# already execs (/venv/bin/python) in both modes.
RUN python -m venv /venv \
    && /venv/bin/pip install --no-cache-dir --require-hashes \
        -r /tmp/requirements.lock

# --- stage 2: the runtime image ---------------------------------------------
FROM ${BASE_IMAGE}

LABEL org.opencontainers.image.title="ccsync-dashboard" \
      org.opencontainers.image.description="Creators Club Sync fleet dashboard, with the b-roll, music and ytdl sub-apps mounted in-process" \
      org.opencontainers.image.source="https://example.invalid/ccsync" \
      org.opencontainers.image.licenses="NOASSERTION"

COPY --from=deps /venv /venv

# The four trees, at exactly the paths deploy/run.sh puts on PYTHONPATH
# (/app/src:/broll-app:/music-app:/ytdl-app) and compose bind-mounts in the
# other mode. Same paths in both modes is the whole point: run.sh, the sub-app
# guards and every DEPLOY.md stay true.
#
# The three sub-apps are deliberately NOT all called `app`: b-roll's package IS
# top-level `app`, music's is `musicweb` and ytdl's is `ytdlweb`. Two top-level
# packages of the same name on one PYTHONPATH collide in sys.modules and one
# wins silently (CLAUDE.md). That is why they get three separate roots here
# rather than one shared /opt/ccsync directory.
COPY dashboard/src /app/src
COPY dashboard/deploy /app/deploy
# templates/ and static/ resolve as parents[2] of the package directory --
# /app/templates and /app/static -- because ui.py and app.py compute them from
# their own __file__ (they were beside the package under the old editable
# install and still are in bind-mount mode, where the whole dashboard/ tree is
# mounted at /app). WITHOUT THESE TWO LINES an image-mode container answers
# /api/v1/health perfectly and 500s on every page (2026-08-18, found while
# building WP K's bundle, which has to carry the same two directories for the
# same reason).
COPY dashboard/templates /app/templates
COPY dashboard/static /app/static
# The documents the RUNNING dashboard serves (REL-5, usability sweep
# 2026-09-04; widened to the whole tree the same day at the owner's request).
# `docs/` is excluded wholesale by .dockerignore, which re-includes the
# MARKDOWN under it and nothing else: without these lines setup_engine's EULA
# task falls back to "no licence agreement is included in this build" and
# /help says it is not installed. ~4 MB of text against a ~10 MB context, and
# no screenshot, no PDF, no binary -- the .dockerignore rule is what keeps
# docs/mobile's PNGs out.
#
# /app/docs, because every reader resolves it from its own __file__ the way
# ui.py resolves /app/templates (help.document_root, setup_engine._find_eula).
COPY docs /app/docs
# The top-level documents (KNOWN_BUGS.md, SPEC.md, CLAUDE.md, and a
# README.md if one is ever added), under the name help.py browses them by
# (help.ROOT_DIR_NAME). They are not in docs/, and /app is the application
# root here, so they get a directory of their own rather than being dropped
# beside the code. A glob rather than four names because a COPY that names a
# file the checkout does not have fails the BUILD, and the browser
# allow-lists what it will serve anyway (help.ROOT_FILES).
COPY *.md /app/docs/_root/
COPY broll/web /broll-app
COPY music/web /music-app
COPY ytdl/web /ytdl-app

# Tells run.sh the venv came from the image, so it never runs pip. Without it
# run.sh would compare requirements.lock's md5 against a stamp that does not
# exist, try to install, and -- in a container with no PyPI egress -- either
# stall the boot or (on a first boot) exit 1.
#
# a+rX, not a+rwX: /app and the three sub-app trees are the code this container
# EXECUTES, and a writable code path in a process holding the NAS admin
# password is remote code execution (AUDIT C-1, the reason compose mounts them
# :ro). The image keeps that posture without needing a mount option, and
# read-for-everyone is what lets the container run as ANY uid (see below).
RUN : > /venv/.image-baked \
    && chmod -R a+rX /venv /app /broll-app /music-app /ytdl-app

# WHICH RUNTIME THIS IMAGE IS (ZERO_TOUCH_PLAN.md WP K, 2026-08-18). The
# dashboard can install a newer copy of its own CODE from the signed vendor
# feed and re-exec into it, but it can never bring a dependency: the venv
# above is the image's and this container has no Docker socket. So every code
# bundle is stamped with the runtime it was built against, and
# `dashboard_update.py` / `select_code_root.py` refuse anything whose stamp is
# not this file's content -- those updates need the NAS's own image-update
# click instead.
#
# BASE_IMAGE is re-declared here so the value used is this build's ACTUAL one,
# including a `--build-arg` override: an override changes what `import` can
# find, so it must change the id. The recipe itself lives in exactly one place
# (dashboard/src/ccsync_dashboard/runtime_id.py), imported here and by
# tools/build_dashboard_bundle.py, because two implementations would be two
# answers to "may this update be applied".
ARG BASE_IMAGE
RUN PYTHONPATH=/app/src /venv/bin/python -c \
    "import os, pathlib; from ccsync_dashboard.runtime_id import runtime_id_from_paths; \
     pathlib.Path('/venv/.runtime-id').write_text(runtime_id_from_paths( \
        '/app/deploy/requirements.lock', '/app/deploy/Dockerfile', \
        base_image=os.environ.get('BASE_IMAGE', '')))" \
    && chmod a+r /venv/.runtime-id \
    && echo "runtime id: $(cat /venv/.runtime-id)"

# A non-root default so `docker run` with no `user:` is still unprivileged.
# 3000:3000 matches this fleet's service account (setup_tree.py's broll:broll),
# but it is only a DEFAULT: compose passes `user: "${APP_UID}:${APP_GID}"` from
# site.toml, and DSM assigns uids >= 1026 rather than letting you pick 3000. The
# image therefore owns nothing the runtime uid needs to write -- every writable
# path (/data, /projects, /broll-data, /music-data, /music-share, /ytdl-data,
# /claude-home) is a mount, chowned on the host by the install script.
#
# An unprivileged container cannot setuid, so there is no entrypoint here that
# reads APP_UID and switches to it; run.sh instead SHOUTS if APP_UID/APP_GID are
# set and disagree with the uid it is actually running as, which is the only
# honest thing a process without CAP_SETUID can do about it.
RUN groupadd --gid 3000 ccsync \
    && useradd --uid 3000 --gid 3000 --no-create-home --shell /usr/sbin/nologin ccsync
USER 3000:3000

# Documentation only (compose publishes the real bind addresses); DASH_PORT
# overrides it and run.sh defaults to 8480.
EXPOSE 8480

# NOTHING sets HOME, PYTHONPATH or PATH here on purpose -- run.sh owns all
# three, and it is the entrypoint in both modes so the two cannot drift.
# /opt/ffmpeg, /opt/claude and /opt/deno stay MOUNTS rather than image content:
# the ffmpeg build is GPL and shipping it inside a vendor image is conveying
# (COMMERCIAL_READINESS.md item 3), and the Claude Code CLI must not be
# redistributed at all (item 1).
CMD ["/bin/sh", "/app/deploy/run.sh"]
