# DOCKER.md — the two ways the dashboard container gets its code and its deps

Written 2026-08-17 for `docs/COMMERCIAL_READINESS.md` item 12 ("ship a real
Dockerfile so the container is self-contained"). Section F of that document
recorded the state this replaces: *"No Dockerfile for the dashboard (pip-installs
into a bind-mounted venv at boot)"*.

There are now two modes. **Bind-mount mode is the default and every live site
uses it.** Nothing in this document changes a running deployment until an
operator deliberately switches.

| | bind-mount mode (default) | image mode (opt-in) |
|---|---|---|
| compose file | `dashboard/deploy/compose.yaml` | `dashboard/deploy/compose.image.yaml` |
| base image | stock `python:3.12.7-slim` | `ccsync-dashboard:<version>`, built here |
| code | bind-mounted `:ro` from the host | image layers |
| dependencies | `pip install` into a `/venv` volume on first boot | baked, `--require-hashes` |
| needs PyPI at boot | on the first boot, and after any requirements change | never |
| what a deploy ships | the code trees, over SFTP | an image, plus the code trees are unused |
| rollback | re-ship the previous tree | re-tag / re-pull the previous image |

Both run the **same entrypoint** (`/app/deploy/run.sh`), put the same four
trees on the same `PYTHONPATH` (`/app/src:/broll-app:/music-app:/ytdl-app`),
mount the same data volumes and expose the same healthcheck. That is
deliberate: one entrypoint means the two modes cannot drift, and every
`DEPLOY.md` in the repo stays true in both.

---

## Bind-mount mode (what runs today)

`server/install_dashboard_app.py` creates the host directories, SFTPs the
`dashboard/`, `broll/web`, `music/web` and `ytdl/web` trees into them, renders
`compose.yaml` from `site.toml`, and starts the stack. On boot, `run.sh`:

1. checks `/venv` is mounted (it is a *dedicated* volume, mode 700 — not a
   directory inside `/data`; a group-writable venv beside a group-writable
   `/data` was an editor→NAS-admin escalation, AUDIT C-2);
2. installs the dependency file **when its md5 changes** — preferring
   `requirements.lock` with `--require-hashes` and falling back to
   `requirements.txt` if no lock has been shipped;
3. execs uvicorn.

A pip failure after the venv has been populated once is a **warning, not a
crash**: a PyPI blip once crash-looped the whole fleet dashboard on every
restart, and the dashboard is the one service that tells everyone whether their
footage is syncing.

This mode is the right default while a deployment is being iterated on: a code
fix is an SFTP push and a restart, with no registry in the loop.

## Image mode (opt-in)

### Build

From **the repo root** — the image carries four trees from four directories,
and `.dockerignore` keeps the ~2 GB repo down to ~10 MB of context:

```bash
docker build -f dashboard/deploy/Dockerfile -t ccsync-dashboard:0.4.1 .
```

Two stages. The first creates `/venv` and runs
`pip install --require-hashes -r dashboard/deploy/requirements.lock`; the second
copies that venv plus the four trees, drops to a non-root user, and sets
`CMD ["/bin/sh", "/app/deploy/run.sh"]`. The base image is pinned **by digest**
(`python:3.12.7-slim@sha256:60d9996b…`), not only by tag.

`--require-hashes` is the point of the exercise: it makes a compromised or
typo-squatted mirror a build failure instead of a shipped backdoor, and it
forbids any unpinned transitive dependency. Regenerate the lock with the recipe
in `docs/RELEASE.md` ("Refreshing the lockfiles"), never by hand.

### Get it onto the NAS

There is no registry in this product. Either push to one you control, or move
the image directly:

```bash
docker save ccsync-dashboard:0.4.1 | gzip > ccsync-dashboard-0.4.1.tar.gz
scp ccsync-dashboard-0.4.1.tar.gz <nas>:/tmp/
ssh <nas> 'gunzip -c /tmp/ccsync-dashboard-0.4.1.tar.gz | docker load'
```

On TrueNAS SCALE the app is installed through the middleware and the image must
exist on the host before the app is (re)deployed; on Synology `docker load`
then `docker compose up -d` is the whole story.

### Run it

`compose.image.yaml` is a template in the same grammar as `compose.yaml`
(`{{NAME}}` placeholders filled from `site.toml`). Render it:

```bash
python -c "import sys; sys.path.insert(0,'server'); \
  import install_dashboard_app as i, pathlib; \
  print(i.render_compose_yaml(template=pathlib.Path('dashboard/deploy/compose.image.yaml')))" \
  > /tmp/compose.yaml
```

Fill in the five `REPLACE_ME` values (`SYNCTHING_API_KEY`, `DASH_REPORT_TOKEN`,
`DASH_SESSION_SECRET`, `BROLL_INGEST_TOKEN`, and the NAS password in both
`TRUENAS_PW` and `DASH_NAS_PW`), set `CCSYNC_IMAGE` to the tag you loaded, and
`docker compose up -d`.

### What image mode does NOT bake in, and why

- **ffmpeg / ffprobe** stay a read-only mount at `/opt/ffmpeg`. The static build
  is GPLv3 and putting it inside a vendor image is *conveying* it, with all the
  source-offer obligations that implies (item 3, `docs/legal/THIRD_PARTY_NOTICES.md`).
- **The Claude Code CLI** at `/opt/claude` stays a mount because it must not be
  redistributed at all (item 1).
- **deno** at `/opt/deno` rides along with those two.
- **Every data volume.** `/data`, `/projects`, `/broll-data`, `/music-data`,
  `/music-encoder`, `/music-proxies`, `/music-share`, `/ytdl-data`,
  `/claude-home` are unchanged, byte for byte, from `compose.yaml`. The data is
  the half that cannot be rebuilt.

### uid and gid

The image defaults to `3000:3000` so a bare `docker run` is still unprivileged,
but compose overrides it with the site's own `user: "<APP_UID>:<APP_GID>"` —
DSM assigns uids ≥ 1026 and will not let you pick 3000, so it must be read off
the live account, never assumed.

An unprivileged container **cannot setuid**, so there is no entrypoint that
reads `APP_UID` and switches to it. What `run.sh` does instead is *shout*: set
`APP_UID`/`APP_GID` in the environment (compose.image.yaml does) and it warns
loudly when the uid it actually got disagrees. That matters because the symptom
otherwise is silent and delayed — files written into `/projects` and
`/music-share` land owned by the wrong uid, and the editors browsing those
shares over SMB find files they cannot open.

---

## Migrating between the modes

Both directions are a compose-file swap. **No data moves and nothing is
deleted.**

Bind-mount → image:

1. Build and load the image (above).
2. `docker compose down` (or stop the app in the TrueNAS UI).
3. Bring the stack up with the rendered `compose.image.yaml`.
4. Check `/api/v1/health` returns `{"ok": true}` and that `/broll`, `/music`
   and `/ytdl` are present on the dashboard's nav.

The host's `app/`, `venv/`, `broll-web/`, `music-web/` and `ytdl-web/`
directories are simply unused afterwards. **Leave them there.** They are the
rollback: swapping back to `compose.yaml` uses them exactly as before, and
`/venv` still holds a populated venv, so the first boot back does not even need
PyPI.

Image → bind-mount: re-run `server/install_dashboard_app.py` to refresh the
code trees (they may be older than the image), then start with `compose.yaml`.

## What to check after either switch

```
docker compose ps                        # dashboard healthy, bgutil up
docker compose logs dashboard | head -40 # run.sh's own lines
curl -s localhost:8480/api/v1/health     # {"ok": true, ...}
```

`run.sh` announces which dependency file it chose and whether it skipped pip
because the venv came from the image. If it says it is *installing* in image
mode, the `/venv/.image-baked` marker is missing and something rebuilt the venv
volume over the layer — check that `compose.image.yaml` has no `/venv` mount.

---

## Not done here

- **Not built on this machine.** Docker Desktop is not installed on the base
  rig (checked 2026-08-17), so `dashboard/deploy/Dockerfile` has never been
  through `docker build`. Treat the first build as part of the migration.
  In particular, confirm that every wheel in `dashboard/deploy/requirements.lock`
  has a manylinux build — `--require-hashes` forbids the fallback to an
  unpinned source build, so a package that ships no wheel for the platform is a
  hard, early failure rather than a slow one.
- **No image signing or SBOM.** Both belong with item 4 (code signing).
- **The GPU indexers are a different image** — `tools/Dockerfile.indexer-gpu`
  and `tools/compose.indexer-gpu.yaml` (item 14). Nothing here builds them, and
  `music/indexer/requirements.lock` is deliberately the CPU / default-PyPI wheel
  set: the CUDA-index build belongs to that image, and CI does not install it.
- **`server/install_dashboard_app.py` does not deploy image mode.** Its
  `--image`/`DASH_IMAGE` switch changes the *tag* only; the mounts and the
  compose body it POSTs to the TrueNAS middleware are bind-mount mode's. Image
  mode is a rendered-compose deployment today. Wiring the install script to
  render `compose.image.yaml` on a flag is a small, separate change.
- **`broll/web/Dockerfile`** predates all of this and builds the *standalone*
  b-roll app on its own port. It is not part of the dashboard image and is not
  used by any deployment here.
